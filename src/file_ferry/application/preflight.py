"""Preflight — does the world still match the plan? (spec §7.1)

A plan is an immutable record of what was reviewed. Checking it against
*itself* proves only that nobody edited the record, which is exactly the
thing an attacker or an accident would not do. The source files change
on disk, the drive is unplugged, the share unmounts, the free space
disappears — and none of that moves a row in the database.

So approval does not read stored rows and call it validation. It
requires a preflight: a run that goes back to the filesystem and the
storage observations and compares what is there now against what the
plan recorded.

What it checks, and why each one exists:

- **Source manifest per inventory.** Re-walks each source root and
  recomputes the same manifest hash the inventory stored. Catches files
  added, removed, resized, or re-timestamped since the scan. It does not
  catch a same-size, same-mtime content change — only checksums can, and
  those belong to the P5 runner; that limitation is reported rather than
  papered over.
- **Every planned source still present.** A file deleted between scan
  and approval must force a replan, not a failed item mid-transfer.
- **Destination resolution, from fresh observations.** The destination
  must resolve ``available`` *now*, at the binding the plan recorded. An
  unplugged drive, a swapped drive, a share that unmounted and left its
  directory behind — all of them refuse here.
- **The publish primitive, probed at the destination.** Ferry publishes
  every file with a hard link so it can never replace existing content.
  A filesystem that cannot link — macOS SMB, for one — has no publish
  path at all, so it is refused here rather than at the first item
  mid-transfer (#211). The *operation* is probed, never guessed from the
  filesystem type.
- **No new content at a planned target.** A file that appeared at a
  reserved path after planning invalidates that entry (§6.4); it must be
  replanned, never quietly replaced or renamed around.
- **Capacity, recomputed.** Free space is a live number, and the reserve
  is part of what the plan needs.

Preflight runs in the background with progress, because on a large plan
it is hundreds of thousands of stat calls and must not block the IPC
handler (spec §12: job creation returns without waiting).

This is **not** a substitute for the publication-time checks the P5
runner owes. Anything validated here can change again a second later;
preflight bounds the window, it does not close it.
"""

from __future__ import annotations

import contextlib
import errno
import json
import os
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from file_ferry.application.destinations import (
    DestinationObservation,
    DestinationService,
)
from file_ferry.application.inventory import manifest_hash_of_walk
from file_ferry.persistence.connection import transaction
from file_ferry.persistence.repositories import inventories as inv_repo
from file_ferry.persistence.repositories import preflights as preflight_repo
from file_ferry.persistence.repositories import transfer_plans as plan_repo
from file_ferry.persistence.repositories.preflights import PreflightRow
from file_ferry.service.protocol import PreflightStatus

#: A pass older than this is not current evidence any more. Approval
#: re-runs rather than trusting it: storage can disappear in a second,
#: and a stale pass reads exactly like a fresh one.
PREFLIGHT_TTL_SECONDS = 300.0

#: How often the running row's progress counter is written.
_PROGRESS_EVERY = 500

#: How many offending paths a finding names before summarizing.
_SAMPLE_LIMIT = 20

ObservationProvider = Callable[[], list[DestinationObservation]]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class PreflightError(ValueError):
    """Raised when a preflight cannot be started or found."""


@dataclass
class _Findings:
    """Reasons this plan may not be approved, in the order discovered."""

    items: list[str] = field(default_factory=list)

    def add(self, item: str) -> None:
        self.items.append(item)

    @property
    def ok(self) -> bool:
        return not self.items


class PreflightService:
    """Run and read plan preflights."""

    def __init__(
        self,
        db_path: Path,
        *,
        destinations: DestinationService,
        observations: ObservationProvider,
    ) -> None:
        self._db_path = Path(db_path)
        self._destinations = destinations
        self._observations = observations
        self._lock = threading.Lock()
        self._threads: list[threading.Thread] = []

    # ---- lifecycle ---------------------------------------------------

    def start(
        self, plan_id: str, *, on_complete: Callable[[int], object] | None = None
    ) -> PreflightStatus:
        """Begin a preflight and return immediately with its id."""
        with transaction(self._db_path) as conn:
            plan = plan_repo.get_plan(conn, plan_id)
            if plan is None:
                raise PreflightError(f"plan {plan_id} not found")
            if plan.status in {"executing", "executed"}:
                raise PreflightError(f"plan {plan_id} is {plan.status}; nothing to preflight")
            total = plan_repo.count_plan_entries(conn, plan_id)
            preflight_id = preflight_repo.insert_preflight(
                conn,
                PreflightRow(
                    id=0,
                    plan_id=plan_id,
                    fingerprint=plan.fingerprint,
                    status="running",
                    findings_json="[]",
                    checked_entries=0,
                    total_entries=total,
                    resolved_binding_path=None,
                    destination_status=None,
                    free_bytes=None,
                    started_at=_now_iso(),
                    finished_at=None,
                ),
            )
        thread = threading.Thread(
            target=self._run,
            args=(preflight_id, plan_id, on_complete),
            name=f"preflight-{preflight_id}",
            daemon=True,
        )
        with self._lock:
            self._threads = [t for t in self._threads if t.is_alive()]
            self._threads.append(thread)
        thread.start()
        return self.get(preflight_id)

    def shutdown(self, *, timeout: float = 5.0) -> None:
        """Wait briefly for in-flight preflights before releasing the service.

        Same reason as the inventory scanner: a background thread still
        writing to a database its owner has released is a defect that
        only ever shows up as flakiness somewhere unrelated. A preflight
        is read-mostly and short, so waiting is usually instant.
        """
        with self._lock:
            threads = list(self._threads)
        deadline = time.monotonic() + timeout
        for thread in threads:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            thread.join(remaining)

    def get(self, preflight_id: int) -> PreflightStatus:
        with transaction(self._db_path) as conn:
            row = preflight_repo.get_preflight(conn, preflight_id)
        if row is None:
            raise PreflightError(f"no preflight {preflight_id}")
        return _to_status(row)

    def latest(self, plan_id: str) -> PreflightStatus | None:
        with transaction(self._db_path) as conn:
            row = preflight_repo.latest_for_plan(conn, plan_id)
        return _to_status(row) if row is not None else None

    def run_blocking(self, plan_id: str, *, timeout: float = 60.0) -> PreflightStatus:
        """Start a preflight and wait for it — for CLI and tests.

        The RPC surface deliberately does not expose this: a caller that
        blocks the IPC handler on a 100,000-entry plan is the behavior
        §12 forbids.
        """
        done = threading.Event()
        status = self.start(plan_id, on_complete=lambda _id: done.set())
        if not done.wait(timeout):
            raise PreflightError(f"preflight {status.id} did not finish in {timeout}s")
        return self.get(status.id)

    # ---- the run -----------------------------------------------------

    def _run(
        self, preflight_id: int, plan_id: str, on_complete: Callable[[int], object] | None
    ) -> None:
        findings = _Findings()
        checked = 0
        binding: str | None = None
        dest_status: str | None = None
        free: int | None = None
        try:
            with transaction(self._db_path) as conn:
                plan = plan_repo.get_plan(conn, plan_id)
            if plan is None:  # pragma: no cover - start() already checked
                findings.add(f"plan {plan_id} disappeared while preflighting")
            else:
                if plan.status == "invalidated":
                    findings.add(
                        "the plan was invalidated by a configuration change; rebuild and review"
                    )
                self._check_sources(plan, findings)
                binding, dest_status, free = self._check_destination(plan, findings)
                checked = self._check_entries(preflight_id, plan, findings)
        except Exception as exc:
            findings.add(f"preflight could not complete: {type(exc).__name__}: {exc}")
        finally:
            with contextlib.suppress(Exception):
                self._finish(
                    preflight_id,
                    findings=findings,
                    checked=checked,
                    binding=binding,
                    dest_status=dest_status,
                    free=free,
                )
            if on_complete is not None:
                with contextlib.suppress(Exception):
                    on_complete(preflight_id)

    def _check_sources(self, plan: plan_repo.TransferPlanRow, findings: _Findings) -> None:
        """Re-walk every source root and compare it to what was scanned."""
        try:
            snapshots = json.loads(plan.inventory_snapshot_json or "[]")
        except (TypeError, ValueError):
            findings.add("the plan's source snapshot is unreadable; rebuild the plan")
            return
        for snap in snapshots:
            if not isinstance(snap, dict):
                continue
            inventory_id = snap.get("inventoryId")
            root = Path(str(snap.get("rootPath", "")))
            with transaction(self._db_path) as conn:
                current = (
                    inv_repo.get_inventory(conn, int(inventory_id))
                    if inventory_id is not None
                    else None
                )
            if current is None:
                findings.add(f"inventory {inventory_id} no longer exists; rescan and replan")
                continue
            if current.status != "complete":
                findings.add(
                    f"inventory {current.id} is {current.status!r}; only a complete source "
                    "scan may be approved"
                )
                continue
            if current.manifest_hash != snap.get("manifestHash"):
                findings.add(
                    f"the inventory record for {root} changed since this plan was built; "
                    "rebuild the plan"
                )
                continue
            if not root.is_dir():
                findings.add(
                    f"source {root} is no longer a readable directory; reconnect it or replan"
                )
                continue
            live = manifest_hash_of_walk(root)
            if live != snap.get("manifestHash"):
                findings.add(
                    f"the files under {root} have changed since they were scanned "
                    "(added, removed, resized, or re-saved); rescan and replan before "
                    "transferring"
                )

    def _check_destination(
        self, plan: plan_repo.TransferPlanRow, findings: _Findings
    ) -> tuple[str | None, str | None, int | None]:
        """Resolve the destination from *current* observations."""
        if plan.destination_id is None:
            return plan.destination_binding_path, None, None
        try:
            observations = self._observations()
        except Exception as exc:
            findings.add(f"storage discovery failed, so the destination cannot be verified: {exc}")
            return None, None, None
        resolutions = self._destinations.resolve(
            destination_id=plan.destination_id, observations=observations
        ).resolutions
        if not resolutions:
            findings.add("the saved destination no longer exists")
            return None, None, None
        resolution = resolutions[0]
        if resolution.status != "available":
            findings.add(f"the destination is {resolution.status} right now: {resolution.reason}")
            return resolution.binding_path, resolution.status, None
        if resolution.binding_path != plan.destination_binding_path:
            findings.add(
                f"the destination now resolves to {resolution.binding_path}, but this plan "
                f"was built for {plan.destination_binding_path}; rebuild and review"
            )
            return resolution.binding_path, resolution.status, None
        binding = Path(plan.destination_binding_path)
        try:
            if not _supports_exclusive_publish(binding):
                findings.add(
                    f"the destination {binding} cannot support ferry's non-overwriting "
                    "publish: this filesystem does not allow hard links, which ferry uses "
                    "so it can never replace an existing file. No files will be written "
                    "there; choose a different destination"
                )
        except OSError as exc:
            # Fail closed. Not being able to test the publish primitive is
            # not evidence that it works, and #211 was exactly a publish
            # that only failed once files were already moving.
            findings.add(
                f"ferry could not check whether {binding} supports its non-overwriting "
                f"publish ({exc.strerror or exc}); a destination that is read-only or "
                "not writable cannot be approved"
            )
        free = _free_bytes(binding)
        if free is None:
            if not (plan.capacity_override_reason or "").strip():
                findings.add(
                    "free space at the destination cannot be determined and no override "
                    "reason was recorded"
                )
        elif free < plan.needed_bytes:
            findings.add(
                f"the destination now has {free} bytes free but the plan needs "
                f"{plan.needed_bytes} (including a {plan.free_space_reserve}-byte reserve)"
            )
        return resolution.binding_path, resolution.status, free

    def _check_entries(
        self, preflight_id: int, plan: plan_repo.TransferPlanRow, findings: _Findings
    ) -> int:
        """Every planned source still there; nothing new at a planned target."""
        root = Path(plan.destination_binding_path)
        checked = 0
        # Counts and samples are tracked separately: capping the sample
        # list would otherwise cap the reported total, so a plan missing
        # five hundred files would report twenty.
        missing_count = 0
        occupied_count = 0
        linked_count = 0
        missing: list[str] = []
        occupied: list[str] = []
        linked: list[str] = []
        # Symlink answers are cached per directory. Every entry under one
        # tree shares its ancestors, so a plan with a hundred thousand
        # files costs the depth of the tree rather than its size.
        link_cache: dict[str, str | None] = {}
        after_id = 0
        while True:
            with transaction(self._db_path) as conn:
                batch = plan_repo.page_plan_entries(conn, plan.id, limit=1000, after_id=after_id)
            if not batch:
                break
            for entry in batch:
                checked += 1
                if entry.action in ("copy", "dir"):
                    # A symbolic link anywhere on the destination path
                    # sends the write outside the root while the plan and
                    # the receipt both name a path inside it. ``is_dir()``
                    # follows links and reports such a component as an
                    # ordinary directory, so it has to be tested with
                    # ``lstat`` and it has to be tested at every level —
                    # the planner emits no directory entry for a parent
                    # its own children imply (R16).
                    link = _symlinked_component(root, entry.dest_rel_path, link_cache)
                    if link is not None:
                        linked_count += 1
                        if len(linked) < _SAMPLE_LIMIT:
                            linked.append(link)
                if entry.action == "copy":
                    if not _exists_including_broken_links(Path(entry.source_path)):
                        missing_count += 1
                        if len(missing) < _SAMPLE_LIMIT:
                            missing.append(entry.source_path)
                    target = root / entry.dest_rel_path
                    if _exists_including_broken_links(target):
                        occupied_count += 1
                        if len(occupied) < _SAMPLE_LIMIT:
                            occupied.append(str(target))
                if checked % _PROGRESS_EVERY == 0:
                    with contextlib.suppress(Exception), transaction(self._db_path) as conn:
                        preflight_repo.update_progress(conn, preflight_id, checked_entries=checked)
            after_id = batch[-1].id
        if missing_count:
            findings.add(
                f"{missing_count} planned source file(s) are gone: {_sample(missing)}. "
                "Rescan the source and rebuild the plan"
            )
        if occupied_count:
            findings.add(
                f"{occupied_count} planned destination path(s) now hold content that did "
                f"not exist at planning time: {_sample(occupied)}. Rebuild the plan so the "
                "conflict is reviewed"
            )
        if linked_count:
            findings.add(
                f"{linked_count} planned destination path(s) would be written through a "
                f"symbolic link at the destination: {_sample(linked)}. Ferry does not write "
                "through links — their targets are not inspected and may be outside the "
                "destination root. Remove or rename them, or rebuild the plan"
            )
        return checked

    def _finish(
        self,
        preflight_id: int,
        *,
        findings: _Findings,
        checked: int,
        binding: str | None,
        dest_status: str | None,
        free: int | None,
    ) -> None:
        with transaction(self._db_path) as conn:
            preflight_repo.finish_preflight(
                conn,
                preflight_id,
                status="passed" if findings.ok else "failed",
                findings_json=json.dumps(findings.items),
                checked_entries=checked,
                resolved_binding_path=binding,
                destination_status=dest_status,
                free_bytes=free,
                finished_at=_now_iso(),
            )


def preflight_is_current(row: PreflightRow, *, fingerprint: str, now: float | None = None) -> bool:
    """Whether this run still counts as evidence for ``fingerprint``.

    A pass expires: storage can disappear a second after it was checked,
    and an hour-old pass reads exactly like a fresh one to anyone
    downstream. Expiry does not make approval impossible, only
    re-checked.
    """
    if row.status != "passed" or row.fingerprint != fingerprint or not row.finished_at:
        return False
    age = _age_seconds(row.finished_at, now=now)
    return age is not None and age <= PREFLIGHT_TTL_SECONDS


def _age_seconds(iso: str, *, now: float | None = None) -> float | None:
    try:
        stamp = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    current = datetime.now(UTC).timestamp() if now is None else now
    return max(0.0, current - stamp.timestamp())


def recover_abandoned_preflights(db_path: Path) -> list[int]:
    """Fail preflights orphaned by a process exit (startup recovery)."""
    with transaction(db_path) as conn:
        return preflight_repo.fail_abandoned(
            conn,
            finished_at=_now_iso(),
            reason="the preflight was abandoned when the previous process exited; run it again",
        )


def _sample(paths: list[str]) -> str:
    shown = ", ".join(paths[:5])
    return f"{shown} …" if len(paths) > 5 else shown


def _symlinked_component(root: Path, dest_rel: str, cache: dict[str, str | None]) -> str | None:
    """The first symlink on a planned destination path, or ``None`` (R16).

    Includes the leaf: a planned directory that is already a symlink is
    just as unwritable-through as a symlinked parent, and ``is_dir()``
    cannot tell the two apart from an ordinary directory.
    """
    parts = PurePosixPath(dest_rel).parts
    for depth in range(1, len(parts) + 1):
        component = "/".join(parts[:depth])
        if component in cache:
            found = cache[component]
        else:
            found = component if os.path.islink(root / component) else None
            cache[component] = found
        if found is not None:
            return str(root / found)
    return None


def _exists_including_broken_links(path: Path) -> bool:
    """``exists()`` misses a broken symlink, which still occupies the name."""
    try:
        os.lstat(path)
    except OSError:
        return False
    return True


#: ``os.link`` errnos that mean the destination filesystem cannot publish
#: exclusively — as opposed to a transient fault worth another attempt.
#: ``ENOTSUP`` and ``EOPNOTSUPP`` are one value on Linux and differ on
#: macOS, where the network filesystem most likely to lack hard links —
#: SMB — returns ``ENOTSUP``.
_UNSUPPORTED_LINK_ERRNOS = frozenset(
    {
        errno.ENOTSUP,
        errno.EOPNOTSUPP,
        errno.EPERM,
        errno.EACCES,
        errno.ENOSYS,
        errno.EMLINK,
    }
)


def _supports_exclusive_publish(root: Path) -> bool:
    """Whether ``os.link`` — the primitive every publish uses — works at ``root``.

    Hard links are a property of the *mounted filesystem*, so this probes
    inside ``root`` rather than a system temp directory, and it probes the
    operation rather than the filesystem type: branching on ``smbfs``
    would be wrong for NFS, some FUSE mounts, and the SMB servers that do
    support links. The cost is one file create and one link attempt; it
    never walks.

    The probe leaves nothing behind on either outcome. It raises
    ``OSError`` when it cannot run at all — a read-only or unsearchable
    root — so the caller reports that frankly instead of reading silence
    as a pass.
    """
    source: Path | None = None
    linked: Path | None = None
    try:
        fd, name = tempfile.mkstemp(prefix=".ferry-publish-probe.", dir=root)
        source = Path(name)
        os.close(fd)
        linked = source.with_name(f"{source.name}.link")
        try:
            os.link(source, linked)
        except OSError as exc:
            if exc.errno in _UNSUPPORTED_LINK_ERRNOS:
                return False
            raise
        return True
    finally:
        for path in (linked, source):
            if path is not None:
                with contextlib.suppress(OSError):
                    path.unlink()


def _free_bytes(path: Path) -> int | None:
    import shutil

    try:
        return int(shutil.disk_usage(path).free)
    except OSError:
        return None


def _to_status(row: PreflightRow) -> PreflightStatus:
    try:
        findings = json.loads(row.findings_json or "[]")
    except (TypeError, ValueError):
        findings = ["the stored findings are unreadable"]
    return PreflightStatus(
        id=row.id,
        planId=row.plan_id,
        fingerprint=row.fingerprint,
        status=row.status,  # type: ignore[arg-type]
        findings=[str(f) for f in findings],
        checkedEntries=row.checked_entries,
        totalEntries=row.total_entries,
        resolvedBindingPath=row.resolved_binding_path,
        destinationStatus=row.destination_status,
        freeBytes=row.free_bytes,
        startedAt=row.started_at,
        finishedAt=row.finished_at,
    )


def wait_for_preflight(
    service: PreflightService, preflight_id: int, *, timeout: float = 30.0
) -> PreflightStatus:
    """Test helper: poll until the run leaves ``running``."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = service.get(preflight_id)
        if status.status != "running":
            return status
        time.sleep(0.01)
    raise PreflightError(f"preflight {preflight_id} did not finish in {timeout}s")


__all__ = [
    "PREFLIGHT_TTL_SECONDS",
    "PreflightError",
    "PreflightService",
    "preflight_is_current",
    "recover_abandoned_preflights",
    "wait_for_preflight",
]
