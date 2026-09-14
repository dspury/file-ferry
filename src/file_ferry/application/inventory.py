"""Server-side full source inventories (destination-presets spec §4.3).

The desktop needs to inspect arbitrarily large sources. Bounding the
inspection payload to fit a UI page (the baseline's silent 5,000-entry
cap) truncates the plan silently, so a UI page size must never limit
planning or execution. This service persists the full inventory
server-side and returns it in stable paginated slices; the renderer
fetches status + pages without ever holding the whole list.

Scans run in a background thread so ``inventory.create`` returns
immediately with the inventory id; ``inventory.status`` reports
``scanning | complete | failed``; ``inventory.entries`` reads the
persisted set.

Every finding the walker produces is persisted: ordinary directories
(so empty directories can be preserved), files, symlinks, unsupported
objects, and read failures. An entry's ``entry_type`` is the kind of
filesystem object; a read failure is ``scan_status='error'`` carrying
the diagnostic, with ``entry_type='unknown'`` when the object could not
be stat'd at all. A scan that fails keeps the counts and entries it
genuinely reached, and records why it stopped.
"""

from __future__ import annotations

import contextlib
import os
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from file_ferry.application.sources import ScanItem, _walk
from file_ferry.persistence.connection import transaction
from file_ferry.persistence.repositories import inventories as inv_repo
from file_ferry.persistence.repositories.inventories import (
    InventoryEntryRow,
    InventoryRow,
)
from file_ferry.service.protocol import (
    InventoryEntriesPage,
    InventoryEntry,
    InventoryStatus,
)

DEFAULT_PAGE_SIZE = 200
MAX_PAGE_SIZE = 1000
_SCAN_ERROR_LIMIT = 50
_HEARTBEAT_SECONDS = 5.0


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class InventoryService:
    """Background full-scan service over the shared filesystem walker."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._lock = threading.Lock()
        self._scans: dict[int, threading.Event] = {}
        self._cancel_flags: dict[int, threading.Event] = {}
        self._threads: dict[int, threading.Thread] = {}

    # ---- lifecycle ---------------------------------------------------

    def create(
        self,
        root_path: str,
        label: str | None,
        *,
        on_complete: Callable[[int], object] | None = None,
    ) -> InventoryStatus:
        """Record the inventory header and kick off a background scan.

        Returns immediately. The actual walk happens on a daemon thread;
        callers poll :meth:`get` for status. ``on_complete`` (optional)
        is invoked once the scan reaches ``complete`` or ``failed`` —
        useful for tests, ignored by the renderer.
        """
        root = Path(root_path).expanduser()
        if not root.exists() or not root.is_dir():
            raise FileNotFoundError(f"inventory source does not exist: {root}")
        now = _now_iso()
        with transaction(self._db_path) as conn:
            inventory_id = inv_repo.insert_inventory(
                conn,
                InventoryRow(
                    id=0,
                    root_path=str(root),
                    label=label,
                    status="scanning",
                    error=None,
                    owner_pid=os.getpid(),
                    heartbeat_at=now,
                    file_count=0,
                    dir_count=0,
                    total_bytes=0,
                    error_count=0,
                    excluded_count=0,
                    manifest_hash=None,
                    started_at=now,
                    finished_at=None,
                ),
            )
        cancel_event = threading.Event()
        thread = threading.Thread(
            target=self._run_scan,
            args=(inventory_id, root, cancel_event, on_complete),
            name=f"inventory-scan-{inventory_id}",
            daemon=True,
        )
        with self._lock:
            self._scans[inventory_id] = cancel_event
            self._cancel_flags[inventory_id] = cancel_event
            self._threads[inventory_id] = thread
        thread.start()
        return self.get(inventory_id)

    def shutdown(self, *, timeout: float = 5.0) -> None:
        """Cancel in-flight scans and wait briefly for them to stop.

        A scan thread keeps opening connections to the database, so one
        that outlives the service it belongs to is still writing to a
        database its owner believes it has released — against a
        directory that may be removed, or alongside a later migration's
        backup of the same file. Daemon threads make that invisible
        until it is a flaky failure somewhere else entirely.

        Cancellation is cooperative and bounded: a walk blocked in the
        kernel on an unresponsive mount cannot be interrupted, so this
        waits ``timeout`` and returns rather than hanging shutdown.
        """
        with self._lock:
            events = list(self._cancel_flags.values())
            threads = list(self._threads.values())
        for event in events:
            event.set()
        deadline = time.monotonic() + timeout
        for thread in threads:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            thread.join(remaining)

    def cancel(self, inventory_id: int) -> bool:
        """Request cooperative cancellation of an in-progress scan."""
        with self._lock:
            event = self._cancel_flags.get(inventory_id)
        if event is None:
            return False
        event.set()
        return True

    # ---- reads -------------------------------------------------------

    def get(self, inventory_id: int) -> InventoryStatus:
        with transaction(self._db_path) as conn:
            row = inv_repo.get_inventory(conn, inventory_id)
        if row is None:
            raise KeyError(f"no inventory {inventory_id}")
        return _to_status(row)

    def entries(
        self, inventory_id: int, *, limit: int = DEFAULT_PAGE_SIZE, after: int = 0
    ) -> InventoryEntriesPage:
        """One page of inventory entries, ordered by insertion id.

        ``after`` is the last id seen; the returned page starts strictly
        after it. ``limit`` is clamped to :data:`MAX_PAGE_SIZE` and the
        page reports ``nextCursor`` so callers can keep paging without
        guessing offsets. Stable ordering (by id) means cursoring is
        monotonic and gaps never appear.
        """
        effective_limit = max(1, min(int(limit), MAX_PAGE_SIZE))
        with transaction(self._db_path) as conn:
            rows = inv_repo.page_entries(
                conn, inventory_id, limit=effective_limit + 1, after_id=after
            )
            total = inv_repo.count_entries(conn, inventory_id)
        next_cursor: int | None = None
        if len(rows) > effective_limit:
            next_cursor = rows[effective_limit - 1].id
            rows = rows[:effective_limit]
        return InventoryEntriesPage(
            entries=[_to_entry(r) for r in rows],
            total=total,
            nextCursor=next_cursor,
        )

    # ---- scan worker -------------------------------------------------

    def _run_scan(
        self,
        inventory_id: int,
        root: Path,
        cancel_event: threading.Event,
        on_complete: Callable[[int], object] | None,
    ) -> None:
        """Walk the source in batches and persist incrementally.

        Writing per-row commits keep memory bounded for very large
        trees; the test suite uses a fresh-finding batch of 500 to keep
        per-inventory write traffic manageable. The walker classifies
        every entry — files, symlinks, unsupported objects, walk
        failures — so the inventory's ``file_count``, ``error_count``,
        and ``excluded_count`` are exact.
        """
        counts = _Counts()
        try:
            batch: list[InventoryEntryRow] = []
            file_paths_for_hash: list[tuple[str, int, float]] = []
            last_beat = time.monotonic()

            def _flush() -> None:
                if not batch:
                    return
                with transaction(self._db_path) as conn:
                    inv_repo.insert_entries(conn, inventory_id, batch)
                batch.clear()

            for item in self._items(root):
                if cancel_event.is_set():
                    _flush()
                    self._finalize(
                        inventory_id,
                        "failed",
                        counts=counts,
                        manifest_hash=None,
                        error="scan cancelled by request",
                    )
                    return
                kind = item.entry_type
                failed = item.scan_status == "error"
                batch.append(
                    InventoryEntryRow(
                        id=0,
                        inventory_id=inventory_id,
                        rel_path=item.rel,
                        entry_type=kind,
                        size=item.size,
                        mtime=item.mtime,
                        scan_status="error" if failed else "ok",
                        error=item.error,
                    )
                )
                if failed:
                    # A read failure is counted as an error whatever
                    # object type the walker managed to determine, and
                    # never also counted as a readable file/dir.
                    counts.errors += 1
                    if len(counts.error_samples) < _SCAN_ERROR_LIMIT:
                        counts.error_samples.append(f"{item.rel}: {item.error}")
                elif kind == "file":
                    counts.files += 1
                    counts.total_bytes += item.size
                    file_paths_for_hash.append((item.rel, item.size, item.mtime))
                elif kind == "dir":
                    counts.dirs += 1
                else:
                    # symlink / other — surfaced so the user can exclude.
                    counts.excluded += 1
                if len(batch) >= 500:
                    _flush()
                now = time.monotonic()
                if now - last_beat >= _HEARTBEAT_SECONDS:
                    last_beat = now
                    self._beat(inventory_id)

            _flush()
            self._finalize(
                inventory_id,
                "complete",
                counts=counts,
                manifest_hash=_manifest_hash(file_paths_for_hash),
                error=None,
            )
        except Exception as exc:
            # The walker surfaces entry-level errors as ScanItem
            # findings; an exception here is an infrastructure fault
            # (disk disappeared, transaction conflict, …). Mark the
            # inventory failed — but keep the counts and entries the
            # scan genuinely reached. Reporting zeros would claim the
            # scan saw nothing when it saw something, and the diagnostic
            # is what tells the user why approval is blocked (spec §4.3,
            # §7.1). ``status='failed'`` already stops the planner.
            self._finalize(
                inventory_id,
                "failed",
                counts=counts,
                manifest_hash=None,
                error=f"{type(exc).__name__}: {exc}",
            )
        finally:
            with self._lock:
                self._scans.pop(inventory_id, None)
                self._cancel_flags.pop(inventory_id, None)
                self._threads.pop(inventory_id, None)
            if on_complete is not None:
                with contextlib.suppress(Exception):
                    on_complete(inventory_id)

    def _items(self, root: Path) -> Iterator[ScanItem]:
        """Adapter that lets the test suite swap the walker."""
        return _walk(root)

    def _finalize(
        self,
        inventory_id: int,
        status: str,
        *,
        counts: _Counts,
        manifest_hash: str | None,
        error: str | None,
    ) -> None:
        """Write the terminal state, retrying once on a write failure.

        The diagnostic actually reaches the row: an inventory that
        failed without saying why cannot be acted on, and the spec
        requires approval to block on *explained* scan errors.
        """
        try:
            self._write_final(inventory_id, status, counts, manifest_hash, error)
        except Exception as exc:  # pragma: no cover - second write attempt
            with contextlib.suppress(Exception):
                self._write_final(
                    inventory_id,
                    "failed",
                    counts,
                    None,
                    f"{error or 'scan failed'}; finalize failed: {exc}",
                )

    def _write_final(
        self,
        inventory_id: int,
        status: str,
        counts: _Counts,
        manifest_hash: str | None,
        error: str | None,
    ) -> None:
        detail = error
        if status == "failed" and counts.error_samples:
            sample = "; ".join(counts.error_samples[:5])
            detail = f"{error}; first findings: {sample}" if error else f"scan findings: {sample}"
        with transaction(self._db_path) as conn:
            inv_repo.finalize_inventory(
                conn,
                inventory_id,
                status=status,
                file_count=counts.files,
                dir_count=counts.dirs,
                total_bytes=counts.total_bytes,
                error_count=counts.errors,
                excluded_count=counts.excluded,
                manifest_hash=manifest_hash,
                finished_at=_now_iso(),
                error=detail,
            )

    def _beat(self, inventory_id: int) -> None:
        with contextlib.suppress(Exception), transaction(self._db_path) as conn:
            inv_repo.heartbeat(conn, inventory_id, _now_iso())


@dataclass
class _Counts:
    """Running totals for one scan, reported truthfully even on failure."""

    files: int = 0
    dirs: int = 0
    total_bytes: int = 0
    errors: int = 0
    excluded: int = 0
    error_samples: list[str] = field(default_factory=list)


def manifest_hash_of_walk(root: Path) -> str:
    """Recompute a source root's manifest hash straight from the filesystem.

    Deliberately the same canonicalization the scan used, so a preflight
    comparing live state against a stored inventory is comparing like
    with like. Files only — directories and findings do not participate,
    exactly as when the inventory recorded it.
    """
    entries = [
        (item.rel, item.size, item.mtime)
        for item in _walk(root)
        if item.entry_type == "file" and item.scan_status != "error"
    ]
    return _manifest_hash(entries)


def recover_abandoned_scans(db_path: Path) -> list[int]:
    """Fail inventories left ``scanning`` by a previous process.

    Scans run on daemon threads, so a process that exits mid-walk
    leaves its inventory ``scanning`` forever; a later planner would
    then read a silently partial entry set as if it were the source.
    Startup recovery marks those failed with a reason, preserving the
    partial entries as evidence (spec §7.3 — unfinished work becomes
    attention-needing, never silent success). Returns the ids moved.

    Only scans whose owning process is **gone** are failed. A CLI run
    and the desktop sidecar can be live at the same time, and a second
    process starting up must not terminate a scan the first one is still
    running — that would turn a concurrent session into a corrupted one.
    """
    with transaction(db_path) as conn:
        return inv_repo.fail_abandoned_scans(
            conn,
            finished_at=_now_iso(),
            reason=(
                "scan was abandoned when its process exited; "
                "the entries recorded so far are partial — rescan before planning"
            ),
            is_live=process_is_live,
        )


def process_is_live(pid: int) -> bool:
    """Whether a process id is still running and could own a scan.

    ``signal 0`` is the portable "does this exist" probe. ``PermissionError``
    means it exists under another user — still alive, still not ours to
    fail. Anything we cannot determine is treated as alive, because
    wrongly failing a live scan is worse than leaving a dead one for the
    next startup to catch.
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def _to_status(row: InventoryRow) -> InventoryStatus:
    return InventoryStatus(
        id=row.id,
        rootPath=row.root_path,
        label=row.label,
        status=row.status,  # type: ignore[arg-type]
        error=row.error,
        fileCount=row.file_count,
        dirCount=row.dir_count,
        totalBytes=row.total_bytes,
        errorCount=row.error_count,
        excludedCount=row.excluded_count,
        manifestHash=row.manifest_hash,
        startedAt=row.started_at,
        finishedAt=row.finished_at,
    )


def _to_entry(row: InventoryEntryRow) -> InventoryEntry:
    return InventoryEntry(
        id=row.id,
        relPath=row.rel_path,
        entryType=row.entry_type,  # type: ignore[arg-type]
        size=row.size,
        mtime=row.mtime,
        scanStatus=row.scan_status,  # type: ignore[arg-type]
        error=row.error,
    )


def _manifest_hash(entries: list[tuple[str, int, float]]) -> str:
    """Deterministic manifest hash over the sorted (rel, size, mtime).

    Uses the same canonicalization as :func:`file_ferry.application.sources._manifest_hash`
    so an inventory's manifest hash is comparable to the scan-on-the-fly
    hash returned by ``source.inspect``. Spec §4.3: the manifest hash
    is the durable identity of "what was scanned"; rescan-comparison
    depends on it being stable across code paths.
    """
    import hashlib
    import json

    sorted_entries = sorted(entries)
    canonical = json.dumps(
        [[path, size, round(mtime, 3)] for path, size, mtime in sorted_entries],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def wait_until_complete(
    service: InventoryService, inventory_id: int, *, timeout: float = 30.0
) -> InventoryStatus:
    """Test helper: poll ``get`` until the inventory leaves ``scanning``.

    Production code uses the ``job.updated`` event and the inventory
    status page; this is a synchronous waiting helper that keeps the
    test suite readable.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = service.get(inventory_id)
        if status.status != "scanning":
            return status
        time.sleep(0.01)
    raise TimeoutError(f"inventory {inventory_id} did not complete in {timeout}s")


__all__ = [
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "InventoryService",
    "manifest_hash_of_walk",
    "process_is_live",
    "recover_abandoned_scans",
    "wait_until_complete",
]
