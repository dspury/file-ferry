"""Verified offload engine (plan §4.2, §7.2).

Implements the source-preserving offload core:

- Each copy is written to an application-owned temporary name in the
  final parent directory, flushed, then atomically renamed only after the
  transfer succeeds (plan §7.2). A failed copy leaves no partial file at
  the destination.
- Each replica is checksum-verified against its source after copy; a
  mismatch fails that replica and keeps the card unsafe (ADR-0004).
- Completed verified copies are preserved when a later destination
  fails, and the receipt explains the partial state: every run writes
  one, on success, failure, and cancellation alike (plan §4.2).
- :class:`OffloadRunner` is a scheduler runner that drives a plan for an
  intake session, recording replicas and per-file progress.
"""

from __future__ import annotations

import contextlib
import logging
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

from file_ferry import APP_VERSION
from file_ferry.application.assets import AssetService
from file_ferry.application.intake import IntakeService
from file_ferry.application.jobs import JobService
from file_ferry.application.plan import IntakePlanner
from file_ferry.application.policies import StoragePolicy
from file_ferry.application.receipts import ReceiptWriter, build_receipt
from file_ferry.application.replicas import ReplicaService, compute_checksum
from file_ferry.application.scheduler import JobScheduler
from file_ferry.service.protocol import (
    PROTOCOL_VERSION,
    BuildPlanParams,
    JobDetail,
    PlanDestination,
    PlanEntry,
)

PolicyResolver = Callable[[str], StoragePolicy | None]

_log = logging.getLogger(__name__)

_CHUNK_BYTES = 1024 * 1024

# How much has to be written before progress is flushed to the database and
# an event is published. Every chunk would mean a SQLite write and an IPC
# frame per megabyte; this keeps a large copy to a few updates per second on
# fast media while still moving visibly.
_PROGRESS_FLUSH_BYTES = 16 * 1024 * 1024

# The phases an offload moves through. Steps say *where* the job is; the
# per-item counters say how far. Copy and verify are interleaved per entry
# in this implementation, so they are one honest `transfer` step rather than
# two that would both sit "running" for the whole job.
_STEPS = ("plan", "transfer")

# The receipt `kind` for an offload. It is half of the receipts table's
# UNIQUE key, so it also decides what a re-run supersedes.
_RECEIPT_KIND = "offload"


def copy_file_atomic(
    source: Path,
    dest: Path,
    *,
    on_progress: Callable[[int], None] | None = None,
) -> int:
    """Copy ``source`` to ``dest`` atomically.

    Writes to a temporary sibling, fsyncs, then renames over ``dest``.
    On any failure the temporary file is removed and ``dest`` is left
    untouched. Returns the number of bytes copied.

    ``on_progress`` is called with the running byte total after each chunk.
    Media files are large enough that per-file progress is not granular
    enough on its own -- a single 60 GB card clip would otherwise show
    nothing at all until it finished. The callback is invoked on every
    chunk and is expected to do its own throttling; it must not raise.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{dest.name}.", suffix=".part", dir=dest.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as out:
            with open(source, "rb") as src:
                total = 0
                while True:
                    chunk = src.read(_CHUNK_BYTES)
                    if not chunk:
                        break
                    out.write(chunk)
                    total += len(chunk)
                    if on_progress is not None:
                        on_progress(total)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, dest)
        return total
    except Exception:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def verify_copy(source: Path, dest: Path, algo: str) -> tuple[str, str, bool]:
    """Verify ``dest`` against ``source``.

    Returns ``(source_checksum, replica_checksum, match)`` under the
    configured algorithm.
    """
    source_checksum = compute_checksum(source, algo)
    replica_checksum = compute_checksum(dest, algo)
    return source_checksum, replica_checksum, source_checksum == replica_checksum


@dataclass
class _Attempt:
    """What one run of the runner has done, accumulated for the receipt.

    Built as the copy proceeds rather than assembled at the end, because
    the receipt that matters most is the one for a run that did *not*
    finish: it is the only record of which replicas verified before the
    job stopped, which is exactly what decides whether the card can be
    released. A run that ends at the first destination still leaves a
    receipt naming what landed.
    """

    project_id: str | None = None
    planned: list[dict[str, Any]] = field(default_factory=list)
    actual: list[dict[str, Any]] = field(default_factory=list)
    checksums: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class OffloadRunner:
    """A scheduler runner that executes a verified offload for a session."""

    def __init__(
        self,
        planner: IntakePlanner,
        intake: IntakeService,
        replicas: ReplicaService,
        assets: AssetService,
        jobs: JobService,
        *,
        algo: str = "xxhash64",
        receipt_writer: ReceiptWriter | None = None,
        policy_resolver: PolicyResolver | None = None,
    ) -> None:
        """``receipt_writer`` persists the operation receipt; ``policy_resolver``
        supplies the project's storage policy to stamp into it.

        Both are injected rather than built here because both need a
        database connection and this runner is constructed with services,
        not a ``db_path`` -- and because a runner that reaches into the
        receipts table itself is a runner that cannot be tested without
        one. Both default to ``None``: a runner assembled without them
        transfers exactly as before and simply records nothing.
        """
        self._planner = planner
        self._intake = intake
        self._replicas = replicas
        self._assets = assets
        self._jobs = jobs
        self._algo = algo
        self._receipt_writer = receipt_writer
        self._policy_resolver = policy_resolver

    def __call__(self, job: JobDetail, scheduler: JobScheduler) -> str:
        """Run the offload and write its receipt, whatever the outcome."""
        attempt = _Attempt()
        try:
            outcome = self._run(job, scheduler, attempt)
        except Exception as exc:
            # The scheduler turns a runner exception into `failed` without
            # asking the runner what happened, so without this the one run
            # most in need of a record -- the one that crashed -- is the
            # only one that leaves none. The exception is re-raised so the
            # scheduler still sees it; this only adds the paperwork.
            attempt.errors.append(f"unexpected error: {exc}")
            self._write_receipt(job.id, attempt, "failed")
            raise
        self._write_receipt(job.id, attempt, outcome)
        return outcome

    def _run(self, job: JobDetail, scheduler: JobScheduler, attempt: _Attempt) -> str:
        # Steps are declared up front so `totalSteps` is known from the first
        # event, rather than the denominator growing as the job runs.
        self._declare_steps(job.id)
        self._begin_step(job.id, "plan")
        if job.session_id is None:
            return self._fail(attempt, job.id, "plan", "job has no intake session")
        session = self._intake.get_session(job.session_id)
        attempt.project_id = session.project_id
        if session.source_id is None:
            return self._fail(attempt, job.id, "plan", "intake session has no source")
        dests = self._intake.get_destinations(job.session_id)
        if not dests:
            return self._fail(attempt, job.id, "plan", "intake session has no destinations")

        plan = self._planner.build(
            BuildPlanParams(
                projectId=session.project_id,
                sourceId=session.source_id,
                destinations=[
                    PlanDestination(
                        kind=cast(Literal["working", "backup", "organization"], d.kind),
                        rootPath=d.root_path,
                        required=d.required,
                    )
                    for d in dests
                ],
            )
        )
        if plan.collisions or not plan.capacity_ok:
            return self._fail(
                attempt, job.id, "plan", "plan has collisions or insufficient capacity"
            )

        source_root = Path(plan.source_root)
        project_id = session.project_id
        source_id = session.source_id

        # `plan.entries` is the cross product of files and destinations --
        # one entry per planned *write*, each carrying its own `destPath`.
        # Grouping by source file both restores the file as the unit of
        # progress and fixes a real defect: the old loop iterated the
        # destinations *again* inside the entry loop, so every file was
        # copied `len(destinations) ** 2` times. With a working root and a
        # backup that is twice the writes for the same result, and it
        # ignored the destination the planner had already computed.
        #
        # Grouping also makes the order file-major rather than
        # destination-major, so a file is fully replicated before the next
        # one starts. A card interrupted halfway then leaves complete,
        # verified files behind instead of a partial copy at every root.
        writes: dict[str, list[PlanEntry]] = {}
        for entry in plan.entries:
            writes.setdefault(entry.rel_path, []).append(entry)

        # The receipt's `planned` is the plan itself -- one row per intended
        # write. Recorded here, before a byte moves, so that comparing it
        # against `actual` is what tells an operator which replicas of a
        # partial run are missing.
        attempt.planned = [
            {"relPath": e.rel_path, "destPath": e.dest_path, "bytes": e.size} for e in plan.entries
        ]

        # Enumerate every item before copying starts. The denominator has to
        # be known up front or the bar walks backwards as work is discovered,
        # which reads as the job going in reverse.
        for rel_path, planned in writes.items():
            asset = self._assets.get_by_path(source_id, rel_path)
            if asset is None:
                return self._fail(attempt, job.id, "plan", f"no adopted asset for {rel_path}")
            # Sized for the total work: a file written to a working root
            # *and* a backup is copied twice, so it is only complete when
            # both copies are verified.
            self._add_item(job.id, asset.id, rel_path, sum(e.size for e in planned))
        self._finish_step(job.id, "plan")
        self._begin_step(job.id, "transfer")
        scheduler.notify_progress(job.id)

        for rel_path, planned in writes.items():
            if scheduler.should_cancel(job.id):
                return self._cancel(attempt, job.id, "transfer")
            asset = self._assets.get_by_path(source_id, rel_path)
            if asset is None:
                return self._fail(attempt, job.id, "transfer", f"asset vanished: {rel_path}")
            src = source_root / rel_path
            # Bytes already durably written for this file, across the
            # destinations finished so far.
            item_base = 0
            for entry in planned:
                if scheduler.should_cancel(job.id):
                    return self._cancel(attempt, job.id, "transfer")
                dest_file = Path(entry.dest_path)
                report = self._byte_reporter(scheduler, job.id, asset.id, item_base)
                try:
                    copied = copy_file_atomic(src, dest_file, on_progress=report)
                except OSError as exc:
                    self._mark_item_failed(job.id, asset.id, f"copy failed: {exc}")
                    return self._fail(attempt, job.id, "transfer", f"copy failed: {rel_path}")
                try:
                    scs, rcs, match = verify_copy(src, dest_file, self._algo)
                except OSError as exc:
                    self._mark_item_failed(job.id, asset.id, f"verify failed: {exc}")
                    return self._fail(attempt, job.id, "transfer", f"verify failed: {rel_path}")
                if not match:
                    # Keep the replica recorded but unverified; card stays unsafe.
                    self._replicas.record(
                        asset.id,
                        project_id,
                        str(dest_file),
                        checksum=rcs,
                        algo=self._algo,
                        source_checksum=scs,
                        verified=False,
                    )
                    self._record_replica(
                        attempt, rel_path, dest_file, scs=scs, rcs=rcs, verified=False
                    )
                    self._mark_item_failed(job.id, asset.id, "checksum mismatch")
                    return self._fail(attempt, job.id, "transfer", f"checksum mismatch: {rel_path}")
                self._replicas.record_verified(
                    asset.id,
                    project_id,
                    str(dest_file),
                    checksum=rcs,
                    algo=self._algo,
                    source_checksum=scs,
                )
                self._record_replica(
                    attempt, rel_path, dest_file, scs=scs, rcs=rcs, verified=True, copied=copied
                )
                item_base += copied
                self._set_item_bytes(job.id, asset.id, item_base)
            self._mark_item_done(job.id, asset.id, item_base)
            scheduler.notify_progress(job.id)

        self._finish_step(job.id, "transfer")
        scheduler.notify_progress(job.id)
        return "succeeded"

    # ---- progress helpers -------------------------------------------
    #
    # Progress is never load-bearing: a failure to record it must not fail
    # the transfer. It is logged at debug rather than swallowed silently,
    # though -- a bare `suppress(Exception)` is exactly how the proxy runner
    # spent its life updating rows it had never inserted.

    def _byte_reporter(
        self, scheduler: JobScheduler, job_id: str, asset_id: str, base: int
    ) -> Callable[[int], None]:
        """A throttled ``on_progress`` callback for one destination copy.

        Called once per chunk, so the throttle is what keeps this from
        putting a SQLite write and an IPC frame on every megabyte.
        """
        state = {"flushed": 0}

        def report(copied: int) -> None:
            if copied - state["flushed"] < _PROGRESS_FLUSH_BYTES:
                return
            state["flushed"] = copied
            self._set_item_bytes(job_id, asset_id, base + copied)
            scheduler.notify_progress(job_id)

        return report

    def _declare_steps(self, job_id: str) -> None:
        for step in _STEPS:
            self._safely("declare step", self._jobs.add_step, job_id, step)

    def _begin_step(self, job_id: str, step: str) -> None:
        self._safely("begin step", self._jobs.mark_step, job_id, step, "running")

    def _finish_step(self, job_id: str, step: str) -> None:
        self._safely("finish step", self._jobs.mark_step, job_id, step, "succeeded")

    def _fail(self, attempt: _Attempt, job_id: str, step: str, reason: str) -> str:
        """Mark the step that failed and return the runner's outcome.

        The scheduler only records that the *job* failed; without this the
        receipt and the UI could not say which phase gave up or why.
        """
        _log.info("offload job %s failed during %s: %s", job_id, step, reason)
        attempt.errors.append(f"{step}: {reason}")
        self._safely("fail step", self._jobs.mark_step, job_id, step, "failed", error=reason)
        return "failed"

    def _cancel(self, attempt: _Attempt, job_id: str, step: str) -> str:
        # Not an error: a cancelled run is a deliberate stop, and the
        # receipt should read as one. It goes in `warnings` so the replicas
        # that did verify are not filed under a failure.
        attempt.warnings.append(f"cancelled during {step}")
        self._safely("cancel step", self._jobs.mark_step, job_id, step, "cancelled")
        return "cancelled"

    # ---- receipt -----------------------------------------------------

    def _record_replica(
        self,
        attempt: _Attempt,
        rel_path: str,
        dest: Path,
        *,
        scs: str,
        rcs: str,
        verified: bool,
        copied: int = 0,
    ) -> None:
        """Note one written replica in the receipt under construction."""
        attempt.actual.append(
            {
                "relPath": rel_path,
                "destPath": str(dest),
                "bytes": copied,
                "verified": verified,
            }
        )
        attempt.checksums.append(
            {
                "relPath": rel_path,
                "destPath": str(dest),
                "algo": self._algo,
                "sourceChecksum": scs,
                "replicaChecksum": rcs,
                "verified": verified,
            }
        )

    def _write_receipt(self, job_id: str, attempt: _Attempt, final_state: str) -> None:
        """Persist the operation receipt for this run.

        Plan §4.2 ends the offload flow here: the receipt is the durable
        record of what was copied and verified, and it is what makes a
        card safe to format.

        Best-effort, like progress recording -- a verified transfer must
        not be undone by a failure to write the paperwork about it. Unlike
        progress it logs at warning rather than debug: a missing receipt
        is a real gap in the audit trail, not a cosmetic one.
        """
        writer = self._receipt_writer
        if writer is None:
            return
        try:
            writer(
                build_receipt(
                    operation_id=job_id,
                    kind=_RECEIPT_KIND,
                    app_version=APP_VERSION,
                    protocol_version=PROTOCOL_VERSION,
                    policy=self._policy_of(attempt.project_id),
                    planned=attempt.planned,
                    actual=attempt.actual,
                    checksums=attempt.checksums,
                    warnings=attempt.warnings,
                    errors=attempt.errors,
                    final_state=final_state,
                )
            )
        except Exception:
            _log.warning(
                "offload job %s finished %s but its receipt could not be written",
                job_id,
                final_state,
                exc_info=True,
            )

    def _policy_of(self, project_id: str | None) -> StoragePolicy | None:
        """The project's storage policy, or None if it cannot be read.

        The policy is what a receipt is checked *against* -- how many
        replicas were required, under which checksum algorithm -- so it is
        worth stamping, but not worth failing a receipt over.
        """
        if project_id is None or self._policy_resolver is None:
            return None
        try:
            return self._policy_resolver(project_id)
        except Exception:
            _log.debug("offload could not resolve policy for %s", project_id, exc_info=True)
            return None

    def _add_item(self, job_id: str, asset_id: str, rel_path: str, total_bytes: int) -> None:
        self._safely(
            "add item",
            self._jobs.add_item,
            job_id,
            step="copy",
            asset_id=asset_id,
            source_path=rel_path,
            dest_path=rel_path,
            total_bytes=total_bytes,
        )

    def _set_item_bytes(self, job_id: str, asset_id: str, copied: int) -> None:
        self._safely(
            "item bytes", self._jobs.update_item_progress, job_id, asset_id, byte_progress=copied
        )

    def _mark_item_done(self, job_id: str, asset_id: str, copied: int) -> None:
        self._safely(
            "item done",
            self._jobs.update_item_progress,
            job_id,
            asset_id,
            byte_progress=copied,
            state="succeeded",
        )

    def _mark_item_failed(self, job_id: str, asset_id: str, error: str) -> None:
        self._safely(
            "item failed",
            self._jobs.update_item_progress,
            job_id,
            asset_id,
            state="failed",
            error=error,
        )

    @staticmethod
    def _safely(what: str, fn: Callable[..., object], *args: object, **kwargs: object) -> None:
        try:
            fn(*args, **kwargs)
        except Exception:  # pragma: no cover - progress is never load-bearing
            _log.debug("offload could not record %s", what, exc_info=True)
