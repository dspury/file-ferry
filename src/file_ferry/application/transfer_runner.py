"""Durable verified transfer runner (destination-presets spec §7.2/§7.3).

This is the P5 execution engine. It does not copy bytes itself —
:mod:`file_ferry.application.transfer_safety` owns that, and there is
deliberately no second copier here. What this module owns is everything
*around* the copy that makes it a durable, recoverable, audited
transfer:

- **``transfer.start``** takes an approved plan id plus the fingerprint
  it was approved under, creates the durable execution + job, and
  returns promptly (spec §8). Callers never supply paths; the plan is
  the only source of what gets written.
- **Publication-time validation.** At every (re)start the sources and
  destination are revalidated against the plan's snapshots, and before
  every publication the binding is rechecked cheaply — same resolved
  root, same ``st_dev`` — which is what catches a share that unmounted
  while its mount directory stayed on the local disk (A12). Approval's
  preflight bounded the review-to-execution window; this closes it.
- **Crash-window reconciliation (§7.3).** Three windows exist between
  "bytes moving" and "receipt exported": a temporary written but
  unpublished (discard *this job's* recorded partial and redo — never a
  foreign ``.ferry-part``), published but not committed (verify with a
  full checksum and commit, or fail — never re-copy over the name), and
  committed with the receipt not yet exported (the database receipt
  exists; re-export is retriable).
- **Checksum-proven reuse.** An existing file at a planned path is
  adopted only with full content equality *and* provenance: a
  reviewer's ``skip_identical`` decision, this execution's own prior
  attempt, or a prior committed mapping for the same source, root, and
  relative path. Anything else stops for review — an external writer is
  never overwritten and never silently renamed around (A09, E06, §6.4).
- **Cross-job path reservation (§6.4/A21).** Every planned path is
  reserved in the database for the execution's lifetime; a second job
  targeting the same paths stops with ``needs_attention`` naming the
  holder. Exclusive publication still guards against external writers.
- **Receipts (§7.3).** The database receipt is written *first*, in the
  same transaction as the execution's final state and the reservation
  release; the JSON file export is attempted after and its failure is
  recorded, visible, and retriable. A receipt-persistence failure makes
  the job ``needs_attention`` rather than a clean completion (A22).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import stat as stat_module
import sys
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from file_ferry import APP_VERSION
from file_ferry.application.destinations import DestinationService
from file_ferry.application.inventory import manifest_hash_of_walk
from file_ferry.application.jobs import InvalidTransitionError, JobService
from file_ferry.application.replicas import compute_checksum
from file_ferry.application.scheduler import JobScheduler
from file_ferry.application.transfer_safety import (
    TEMP_SUFFIX,
    copy_file_verified,
    render_destination,
)
from file_ferry.application.transfer_safety import (
    _Cancelled as _CopyCancelled,
)
from file_ferry.persistence.connection import transaction
from file_ferry.persistence.repositories import transfer_executions as exec_repo
from file_ferry.persistence.repositories import transfer_plans as plan_repo
from file_ferry.persistence.repositories.transfer_executions import (
    TransferExecutionItemRow,
    TransferExecutionRow,
    TransferReceiptRow,
)
from file_ferry.persistence.repositories.transfer_plans import (
    TransferPlanEntryRow,
    TransferPlanRow,
)
from file_ferry.service.protocol import (
    PROTOCOL_VERSION,
    CreateJobParams,
    JobDetail,
    JobTransitionParams,
    TransferReceiptParams,
    TransferReceiptStatus,
    TransferStartParams,
    TransferStartResult,
)

_log = logging.getLogger(__name__)

#: The scheduler command this runner serves.
TRANSFER_COMMAND = "transfer"

#: Job states in which an execution may still do work. Anything else at
#: bootstrap means a crash left reservations or execution rows behind.
_ALIVE_JOB_STATES = frozenset({"queued", "running", "verifying", "needs_attention", "resumable"})

#: Actions whose entries get execution items. ``needs_review`` never
#: reaches execution (approval refuses it); anything else does.
_EXECUTABLE_ACTIONS = frozenset({"copy", "skip_identical", "dir", "exclude"})

#: How much has to be written before byte progress is flushed to the
#: job row and an event is published — one SQLite write and one IPC
#: frame per 16 MiB, not per chunk.
_PROGRESS_FLUSH_BYTES = 16 * 1024 * 1024


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO-8601 stamp, returning None rather than raising."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def sidecar_peak_rss_bytes() -> int | None:
    """Peak RSS of this (the sidecar) process **since it started**, or None.

    ``ru_maxrss`` is a high-water mark over the process lifetime, and the
    sidecar is long-lived across jobs — so on the second and later runs in a
    session this is the peak of *some* run, possibly an earlier, larger one,
    not necessarily this transfer. It is therefore named for what it is and
    must not be read as this run's memory. macOS reports bytes, Linux
    kibibytes, Windows has no ``resource`` and gets None.

    The D-2 collector samples the real per-run curve from outside, which is
    where a run's own peak belongs; restarting the sidecar before a timed
    gate makes this number mean what a reader will assume.
    """
    if sys.platform == "win32":
        return None
    import resource

    usage = resource.getrusage(resource.RUSAGE_SELF)
    factor = 1 if sys.platform == "darwin" else 1024
    return int(usage.ru_maxrss) * factor


def _performance_block(execution: Any, committed: list[Any]) -> dict[str, Any]:
    """The §12.2 performance fields a receipt can honestly carry.

    Duration and sustained (average) throughput come from the run's own
    start/finish. Peak memory is the sidecar's high-water mark *since sidecar
    start*, not a per-run figure — see ``sidecar_peak_rss_bytes``. The
    *timeline* — throughput and DB state over time, and the per-run peak
    across both processes — cannot be reconstructed by a receipt written at
    the end; the D-2 collector records it alongside the run.
    """
    started = _parse_iso(execution.started_at)
    finished = datetime.now(UTC)
    duration = None
    if started is not None:
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        duration = (finished - started).total_seconds()
    bytes_committed = sum(i.bytes_copied for i in committed)
    rate = bytes_committed / duration if duration and duration > 0 else None
    return {
        "durationSeconds": duration,
        "bytesCommitted": bytes_committed,
        "bytesPerSecond": rate,
        # Named for what it is: since sidecar start, not this run alone.
        "sidecarPeakRssBytes": sidecar_peak_rss_bytes(),
    }


class TransferRunnerError(ValueError):
    """A transfer could not be started, reconciled, or read back."""


class NeedsAttentionError(Exception):
    """An operator must look at this; the transfer stops cleanly."""


class TransferCancelledError(BaseException):
    """Cancellation observed inside a copy (re-raised as control flow)."""


class TransferRunner:
    """Executes approved plans as durable, verified, receipted transfers."""

    def __init__(
        self,
        db_path: Path,
        jobs: JobService,
        destinations: DestinationService,
        observations: Callable[[], list[Any]],
        *,
        app_data_dir: Path,
    ) -> None:
        self._db_path = Path(db_path)
        self._jobs = jobs
        self._destinations = destinations
        self._observations = observations
        self._receipts_dir = Path(app_data_dir) / "receipts"

    # ------------------------------------------------------------------
    # transfer.start
    # ------------------------------------------------------------------

    def start(self, params: TransferStartParams) -> TransferStartResult:
        """Start (or return the existing durable job for) an approved plan.

        Never waits for the copy: the job is queued and the dispatcher
        picks it up. Idempotent per ``(plan, fingerprint)`` — a second
        start while a job is alive returns that job, not a duplicate.
        """
        with transaction(self._db_path) as conn:
            row = plan_repo.get_plan(conn, params.id)
            if row is None:
                raise TransferRunnerError(f"plan {params.id} does not exist")
            plan_project_id = row.project_id
            existing = exec_repo.latest_execution_for_plan(conn, params.id)
            if existing is not None and existing.fingerprint == params.fingerprint:
                job = self._jobs.get(existing.job_id)
                if job is not None and job.state in _ALIVE_JOB_STATES:
                    return TransferStartResult(job=job, executionId=existing.id)
            if row.status != "approved" or row.approved_fingerprint != params.fingerprint:
                raise TransferRunnerError(
                    f"plan {params.id} is {row.status} (approved fingerprint "
                    f"{row.approved_fingerprint!r}), not approved exactly under "
                    f"{params.fingerprint!r}"
                )
            if existing is not None:
                raise TransferRunnerError(
                    f"plan {params.id} already started under fingerprint "
                    f"{existing.fingerprint!r}; that execution is the live one"
                )

        job = self._jobs.create(
            CreateJobParams(
                # A general transfer need not belong to a project, and the
                # empty string is not a project id -- it fails the foreign
                # key. The plan carries the association if there is one.
                projectId=plan_project_id,
                command=TRANSFER_COMMAND,
                argsFingerprint=params.fingerprint,
                totalSteps=3,
                reviewed=True,
            )
        )
        try:
            self._jobs.transition(
                JobTransitionParams(id=job.id, fromState="planned", toState="awaiting_review")
            )
            self._jobs.transition(
                JobTransitionParams(id=job.id, fromState="awaiting_review", toState="queued")
            )
        except InvalidTransitionError as exc:  # pragma: no cover - defensive
            raise TransferRunnerError(f"could not queue the transfer job: {exc}") from exc

        execution_id = uuid.uuid4().hex
        started = _now_iso()
        with transaction(self._db_path) as conn:
            claimed = conn.execute(
                "UPDATE transfer_plans SET status = 'executing' "
                "WHERE id = ? AND status = 'approved' AND approved_fingerprint = ?",
                (params.id, params.fingerprint),
            ).rowcount
            if claimed != 1:
                raise TransferRunnerError(
                    f"plan {params.id} changed state while its job was created; "
                    "start again against its current approval"
                )
            exec_repo.insert_execution(
                conn,
                TransferExecutionRow(
                    id=execution_id,
                    job_id=job.id,
                    plan_id=params.id,
                    fingerprint=params.fingerprint,
                    dest_root="",
                    dest_st_dev=None,
                    binding_json="{}",
                    state="running",
                    started_at=started,
                    updated_at=started,
                ),
            )
        return TransferStartResult(job=self._jobs.get(job.id), executionId=execution_id)

    # ------------------------------------------------------------------
    # the scheduler runner
    # ------------------------------------------------------------------

    def __call__(self, job: JobDetail, scheduler: JobScheduler) -> str:
        """Run one dispatch of the transfer job; returns the outcome."""
        try:
            execution = self._execution_for(job)
        except TransferRunnerError as exc:
            _log.error("transfer job %s has no execution: %s", job.id, exc)
            return "failed"
        try:
            outcome, _final_state = self._run(job, scheduler, execution)
        except Exception:
            _log.exception("transfer job %s crashed", job.id)
            self._finish_without_receipt(execution.id, "failed")
            return "failed"
        return outcome

    def _execution_for(self, job: JobDetail) -> TransferExecutionRow:
        with transaction(self._db_path) as conn:
            execution = exec_repo.get_execution_by_job(conn, job.id)
            if execution is not None:
                return execution
            # A retry creates a new job for the same fingerprint: adopt
            # the prior execution so the crash-window ledger and the
            # provenance of earlier attempts survive (§7.3 lineage).
            if job.command != TRANSFER_COMMAND:
                raise TransferRunnerError(f"job {job.id} is not a transfer job")
            prior = exec_repo.latest_execution_for_fingerprint(conn, job.args_fingerprint or "")
            if prior is None:
                raise TransferRunnerError(
                    f"no execution exists for job {job.id}; transfer.start creates it"
                )
            conn.execute(
                "UPDATE transfer_executions SET job_id = ?, updated_at = ? WHERE id = ?",
                (job.id, _now_iso(), prior.id),
            )
            adopted = exec_repo.get_execution(conn, prior.id)
            assert adopted is not None
            return adopted

    def _revalidate(self, plan: TransferPlanRow) -> list[str]:
        """Fresh source + destination validation against the plan (§7.2).

        Runs at every (re)start of the execution — resume revalidates
        original identity rather than trusting recorded rows (§7.3).
        """
        findings: list[str] = []
        for snap in _snapshots(plan):
            root = Path(snap["rootPath"])
            try:
                live = manifest_hash_of_walk(root)
            except OSError as exc:
                findings.append(f"source {root} cannot be walked: {exc}")
                continue
            if live != snap.get("manifestHash"):
                findings.append(
                    f"the files under {root} changed since they were scanned; rescan "
                    "and replan (resume refuses to guess)"
                )
        if findings:
            return findings
        resolution = self._resolve_destination(plan)
        if resolution is None:
            return ["the saved destination no longer exists"]
        status, binding_path, reason = resolution
        if status != "available":
            return [f"the destination is {status} right now: {reason}"]
        if binding_path != plan.destination_binding_path:
            return [
                f"the destination now resolves to {binding_path}, but this plan was "
                f"built for {plan.destination_binding_path}; rebuild and review"
            ]
        return []

    def _resolve_destination(self, plan: TransferPlanRow) -> tuple[str, str | None, str] | None:
        if plan.destination_id is None:
            return ("available", plan.destination_binding_path, "explicit path binding")
        try:
            observations = self._observations()
        except Exception as exc:
            return ("unavailable", None, f"storage discovery failed: {exc}")
        resolutions = self._destinations.resolve(
            destination_id=plan.destination_id, observations=observations
        ).resolutions
        if not resolutions:
            return None
        r = resolutions[0]
        return (r.status, r.binding_path, r.reason)

    def _run(
        self, job: JobDetail, scheduler: JobScheduler, execution: TransferExecutionRow
    ) -> tuple[str, str]:
        """One dispatch: validate, reconcile, execute, receipt.

        Returns ``(scheduler outcome, execution final state)``.
        """
        with transaction(self._db_path) as conn:
            plan = plan_repo.get_plan(conn, execution.plan_id)
        if plan is None:  # pragma: no cover - plans are immutable
            _log.error("execution %s references a missing plan", execution.id)
            return "failed", "failed"
        if plan.fingerprint != execution.fingerprint:  # pragma: no cover
            return "failed", "failed"

        if not self._has_items(execution.id):
            findings = self._revalidate(plan)
            if findings:
                self._fail_boot(execution.id, findings)
                self._write_receipt(plan, execution, "needs_attention", findings=findings)
                return "needs_attention", "needs_attention"
            dest_root, st_dev, binding_json = self._binding_evidence(plan)
            conflicts = self._initialize_items(execution, plan, dest_root, st_dev, binding_json)
            if conflicts:
                self._fail_boot(execution.id, conflicts)
                self._write_receipt(plan, execution, "needs_attention", findings=conflicts)
                return "needs_attention", "needs_attention"
            refreshed = self._read_execution(execution.id)
            assert refreshed is not None
            execution = refreshed
        else:
            findings = self._revalidate(plan)
            if findings:
                self._fail_boot(execution.id, findings)
                self._write_receipt(plan, execution, "needs_attention", findings=findings)
                return "needs_attention", "needs_attention"
            problems = self._reconcile_crash_windows(execution, plan)
            if problems:
                self._write_receipt(plan, execution, "needs_attention", findings=problems)
                return "needs_attention", "needs_attention"

        dest_root = Path(execution.dest_root)
        for item in self._pending_items(execution.id):
            if scheduler.should_cancel(job.id):
                self._write_receipt(plan, execution, "cancelled")
                return "cancelled", "cancelled"
            try:
                self._execute_item(job, scheduler, execution, plan, item, dest_root)
            except NeedsAttentionError as attention:
                self._fail_item(execution.id, item.plan_entry_id, str(attention))
                self._write_receipt(plan, execution, "needs_attention")
                return "needs_attention", "needs_attention"
            except TransferCancelledError:
                self._write_receipt(plan, execution, "cancelled")
                return "cancelled", "cancelled"

        # Every item should now be committed, skipped-proven, reused,
        # excluded, or a created directory. That is asserted against the
        # ledger rather than inferred from having reached this line: the
        # loop above only walks *pending* items, so anything left in a
        # failed or unfinished state would otherwise be reported as a
        # clean success (§7.3: no green success over an unpublished file).
        unfinished = self._unfinished_items(execution.id)
        if unfinished:
            _log.error(
                "execution %s reached the end of its item loop with %d unfinished "
                "item(s); refusing to report success: %s",
                execution.id,
                len(unfinished),
                unfinished[:10],
            )
            self._write_receipt(
                plan,
                execution,
                "needs_attention",
                findings=[f"item did not finish: {u}" for u in unfinished],
            )
            return "needs_attention", "needs_attention"

        self._write_receipt(plan, execution, "succeeded")
        with transaction(self._db_path) as conn:
            plan_repo.set_plan_status(conn, execution.plan_id, status="executed")
        return "succeeded", "succeeded"

    # ------------------------------------------------------------------
    # initialization and crash-window reconciliation
    # ------------------------------------------------------------------

    def _has_items(self, execution_id: str) -> bool:
        with transaction(self._db_path) as conn:
            return bool(exec_repo.get_execution_items(conn, execution_id))

    def _read_execution(self, execution_id: str) -> TransferExecutionRow | None:
        with transaction(self._db_path) as conn:
            return exec_repo.get_execution(conn, execution_id)

    def _binding_evidence(self, plan: TransferPlanRow) -> tuple[Path, int, str]:
        """Resolved root, device id, and the resolver's binding snapshot."""
        resolution = self._resolve_destination(plan)
        assert resolution is not None and resolution[1] is not None
        binding_path = Path(resolution[1])
        st = os.stat(binding_path)
        snapshot: dict[str, Any] = {
            "status": resolution[0],
            "bindingPath": str(binding_path),
            "reason": resolution[2],
            "destinationId": plan.destination_id,
            "identity": json.loads(plan.destination_identity_json or "null"),
        }
        return binding_path, st.st_dev, json.dumps(snapshot, sort_keys=True)

    def _initialize_items(
        self,
        execution: TransferExecutionRow,
        plan: TransferPlanRow,
        dest_root: Path,
        st_dev: int,
        binding_json: str,
    ) -> list[str]:
        """Create the item ledger and reserve every planned path (A21).

        Returns reservation-conflict messages (empty means success).
        Reservations are acquired in one transaction together with the
        item rows, so a job can never observe a half-reserved plan.
        """
        now = _now_iso()
        entries = self._all_entries(plan.id)
        items = [
            TransferExecutionItemRow(
                execution_id=execution.id,
                plan_entry_id=e.id,
                dest_rel_path=e.dest_rel_path,
                source_path=e.source_path,
                size=e.size,
                state="excluded" if e.action == "exclude" else "pending",
                temp_path=None,
                source_checksum=None,
                dest_checksum=None,
                checksum_algo=None,
                bytes_copied=0,
                error=None,
                warning=None,
                updated_at=now,
            )
            for e in entries
            if e.action in _EXECUTABLE_ACTIONS
        ]
        reservable = [i.dest_rel_path for i in items if i.state == "pending"]
        with transaction(self._db_path) as conn:
            conflicts = exec_repo.active_reservation_conflicts(conn, str(dest_root), reservable)
            if conflicts:
                return [
                    f"{rel} is reserved by transfer job {holder}; wait for that job "
                    "to finish, cancel it, or replan around it"
                    for rel, holder in sorted(conflicts.items())
                ]
            exec_repo.insert_execution_items(conn, items)
            exec_repo.insert_reservations(
                conn,
                dest_root=str(dest_root),
                rel_paths=reservable,
                execution_id=execution.id,
                acquired_at=now,
            )
            exec_repo.update_execution_state(
                conn,
                execution.id,
                state="running",
                updated_at=now,
                dest_st_dev=st_dev,
            )
            conn.execute(
                "UPDATE transfer_executions SET dest_root = ?, binding_json = ? WHERE id = ?",
                (str(dest_root), binding_json, execution.id),
            )
        # Job items drive the Activity view's byte/file progress; they
        # are progress, never load-bearing (the execution items are).
        for item in items:
            if item.state == "pending":
                self._safely(
                    self._jobs.add_item,
                    execution.job_id,
                    step="transfer",
                    asset_id=str(item.plan_entry_id),
                    source_path=item.source_path,
                    dest_path=item.dest_rel_path,
                    total_bytes=item.size,
                )
        return []

    def _reconcile_crash_windows(
        self, execution: TransferExecutionRow, plan: TransferPlanRow
    ) -> list[str]:
        """Reconcile the three §7.3 windows before writing anything.

        Window 1 — temporary written, unpublished: discard *this job's*
        recorded partial (and only that; a foreign ``.ferry-part`` is
        never touched) and mark the item pending again.

        Window 2 — published, not committed: a full checksum decides.
        Equal commits the item as verified reuse; unequal fails it and
        the job, because neither re-copying over the name nor guessing
        is acceptable.

        Window 3 — committed, receipt not exported: nothing to do at
        item level; the database receipt is the record and the JSON
        export is retriable via ``transfer.receiptExport``.

        An item left ``failed`` by an earlier attempt is re-armed to
        pending. Resuming *is* the operator saying the cause is gone, and
        the revalidation above has already refused the run if the source
        or the binding moved. Leaving it failed made the resume skip it
        silently -- ``_pending_items`` only sees pending -- and then claim
        success for a transfer that never published the file.
        """
        problems: list[str] = []
        now = _now_iso()
        with transaction(self._db_path) as conn:
            items = exec_repo.get_execution_items(conn, execution.id)
        for item in items:
            if item.state == "copying":
                if item.temp_path:
                    tmp = Path(item.temp_path)
                    try:
                        if tmp.name.endswith(TEMP_SUFFIX) and tmp.exists():
                            tmp.unlink()
                    except OSError as exc:
                        problems.append(f"this job's partial {tmp} could not be removed: {exc}")
                        continue
                with transaction(self._db_path) as conn:
                    exec_repo.update_execution_item(
                        conn,
                        execution.id,
                        item.plan_entry_id,
                        state="pending",
                        clear_temp=True,
                        updated_at=now,
                    )
            elif item.state == "failed":
                with transaction(self._db_path) as conn:
                    exec_repo.update_execution_item(
                        conn,
                        execution.id,
                        item.plan_entry_id,
                        state="pending",
                        clear_temp=True,
                        clear_error=True,
                        updated_at=now,
                    )
            elif item.state == "published":
                entry = self._entry(execution.plan_id, item.plan_entry_id)
                if entry is None:  # pragma: no cover - immutable plans
                    problems.append(f"plan entry {item.plan_entry_id} vanished")
                    continue
                source = Path(entry.source_path)
                dest = Path(execution.dest_root).joinpath(*PurePosixPath(item.dest_rel_path).parts)
                try:
                    source_sum = compute_checksum(source, plan.checksum_algo)
                    dest_sum = compute_checksum(dest, plan.checksum_algo)
                except OSError as exc:
                    problems.append(
                        f"published-but-uncommitted {item.dest_rel_path} could not "
                        f"be verified: {exc}"
                    )
                    self._fail_item(execution.id, item.plan_entry_id, str(exc))
                    continue
                if source_sum == dest_sum:
                    with transaction(self._db_path) as conn:
                        exec_repo.update_execution_item(
                            conn,
                            execution.id,
                            item.plan_entry_id,
                            state="committed",
                            source_checksum=source_sum,
                            dest_checksum=dest_sum,
                            checksum_algo=plan.checksum_algo,
                            warning="verified after an interruption; not re-copied",
                            updated_at=now,
                        )
                else:
                    reason = (
                        "published output no longer matches its source after an "
                        "interruption; refusing to overwrite — replan"
                    )
                    self._fail_item(execution.id, item.plan_entry_id, reason)
                    problems.append(f"{item.dest_rel_path}: {reason}")
        return problems

    # ------------------------------------------------------------------
    # per-item execution
    # ------------------------------------------------------------------

    #: Item states that represent a finished, accounted-for outcome. Any
    #: other state at the end of a run means the run is not a success.
    #: A planned directory settles as ``committed`` like a file does.
    _SETTLED_ITEM_STATES = frozenset({"committed", "skipped_identical", "reused", "excluded"})

    def _pending_items(self, execution_id: str) -> list[TransferExecutionItemRow]:
        with transaction(self._db_path) as conn:
            items = exec_repo.get_execution_items(conn, execution_id)
        return [i for i in items if i.state == "pending"]

    def _unfinished_items(self, execution_id: str) -> list[str]:
        """``dest_rel_path (state)`` for every item that did not settle."""
        with transaction(self._db_path) as conn:
            items = exec_repo.get_execution_items(conn, execution_id)
        return [
            f"{i.dest_rel_path} ({i.state})"
            for i in items
            if i.state not in self._SETTLED_ITEM_STATES
        ]

    def _entry(self, plan_id: str, entry_id: int) -> TransferPlanEntryRow | None:
        with transaction(self._db_path) as conn:
            return plan_repo.get_plan_entry(conn, plan_id, entry_id)

    def _execute_item(
        self,
        job: JobDetail,
        scheduler: JobScheduler,
        execution: TransferExecutionRow,
        plan: TransferPlanRow,
        item: TransferExecutionItemRow,
        dest_root: Path,
    ) -> None:
        entry = self._entry(execution.plan_id, item.plan_entry_id)
        if entry is None:  # pragma: no cover - immutable plans
            raise NeedsAttentionError(f"plan entry {item.plan_entry_id} vanished; replan")
        if entry.action == "exclude":
            self._finish_item(execution.id, item.plan_entry_id, "excluded")
            return
        if entry.action == "dir":
            self._execute_dir_item(execution, entry, dest_root)
            return

        source = Path(entry.source_path)
        dest = render_destination(dest_root, entry.dest_rel_path)
        self._check_binding_still_true(execution, dest_root)

        if entry.action == "skip_identical":
            self._execute_skip_decision(execution, plan, entry, source, dest)
            return

        existing = _lstat(dest)
        if existing is not None:
            self._execute_existing_target(execution, plan, entry, source, dest, existing)
            return

        tmp = dest.parent / f".{dest.name}.{execution.id}{TEMP_SUFFIX}"
        if tmp.exists():
            # Our own recorded name; only this execution writes here.
            tmp.unlink()
        with transaction(self._db_path) as conn:
            exec_repo.update_execution_item(
                conn,
                execution.id,
                item.plan_entry_id,
                state="copying",
                temp_path=str(tmp),
                updated_at=_now_iso(),
            )
        try:
            verification = copy_file_verified(
                source,
                dest,
                algo=plan.checksum_algo,
                on_progress=self._progress_reporter(scheduler, job, execution, item),
                cancel_check=lambda: scheduler.should_cancel(job.id),
                tmp_path=tmp,
            )
        except _CopyCancelled as exc:
            # Cancellation is not a failure: the item returns to pending
            # (its temp is already gone; the copier cleans it) and the
            # receipt reads as a deliberate stop.
            with transaction(self._db_path) as conn:
                exec_repo.update_execution_item(
                    conn,
                    execution.id,
                    item.plan_entry_id,
                    state="pending",
                    clear_temp=True,
                    updated_at=_now_iso(),
                )
            raise TransferCancelledError(str(exc) or "cancelled during copy") from exc
        except Exception as exc:
            with transaction(self._db_path) as conn:
                exec_repo.update_execution_item(
                    conn,
                    execution.id,
                    item.plan_entry_id,
                    state="failed",
                    clear_temp=True,
                    error=f"copy failed: {exc}"[:2000],
                    updated_at=_now_iso(),
                )
            raise NeedsAttentionError(
                f"copy of {entry.rel_path} failed: {exc}; source untouched, nothing "
                "published at the destination"
            ) from exc
        # Window 2 lives between these two statements.
        with transaction(self._db_path) as conn:
            exec_repo.update_execution_item(
                conn,
                execution.id,
                item.plan_entry_id,
                state="published",
                updated_at=_now_iso(),
            )
        with transaction(self._db_path) as conn:
            exec_repo.update_execution_item(
                conn,
                execution.id,
                item.plan_entry_id,
                state="committed",
                clear_temp=True,
                source_checksum=verification.source_checksum,
                dest_checksum=verification.dest_checksum,
                checksum_algo=verification.checksum_algo,
                bytes_copied=verification.bytes_copied,
                warning=None
                if verification.mtime_preserved
                else "basic mtime could not be preserved on the target filesystem",
                updated_at=_now_iso(),
            )
        self._safely(
            self._jobs.update_item_progress,
            execution.job_id,
            str(item.plan_entry_id),
            byte_progress=verification.bytes_copied,
            state="succeeded",
        )
        scheduler.notify_progress(job.id)

    def _execute_dir_item(
        self, execution: TransferExecutionRow, entry: TransferPlanEntryRow, dest_root: Path
    ) -> None:
        dest = render_destination(dest_root, entry.dest_rel_path)
        try:
            st = os.lstat(dest)
        except OSError:
            st = None
        note: str | None = None
        if st is not None:
            if stat_module.S_ISDIR(st.st_mode) and not stat_module.S_ISLNK(st.st_mode):
                # Idempotent on resume; anything else is occupied.
                note = "directory already present"
            else:
                raise NeedsAttentionError(
                    f"planned directory {entry.dest_rel_path} is occupied by a "
                    "non-directory; exclude it or replan"
                )
        else:
            try:
                dest.mkdir(parents=True, exist_ok=False)
            except FileExistsError:  # pragma: no cover - raced with lstat
                raise NeedsAttentionError(
                    f"planned directory {entry.dest_rel_path} appeared while the plan ran"
                ) from None
            except OSError as exc:
                raise NeedsAttentionError(
                    f"could not create directory {entry.dest_rel_path}: {exc}"
                ) from exc
        self._finish_item(execution.id, entry.id, "committed", warning=note)

    def _execute_skip_decision(
        self,
        execution: TransferExecutionRow,
        plan: TransferPlanRow,
        entry: TransferPlanEntryRow,
        source: Path,
        dest: Path,
    ) -> None:
        """Prove or refute a reviewed skip-identical decision (§6.4, A03)."""
        try:
            source_sum = compute_checksum(source, plan.checksum_algo)
            dest_sum = compute_checksum(dest, plan.checksum_algo)
        except OSError as exc:
            raise NeedsAttentionError(
                f"skip-identical proof for {entry.rel_path} could not be computed: {exc}"
            ) from exc
        if source_sum != dest_sum:
            raise NeedsAttentionError(
                f"{entry.rel_path} and its existing destination file are NOT identical "
                "(full checksums disagree); the skip decision does not apply — replan "
                "and decide again"
            )
        self._finish_item(
            execution.id,
            entry.id,
            "skipped_identical",
            source_checksum=source_sum,
            dest_checksum=dest_sum,
            checksum_algo=plan.checksum_algo,
            warning="skipped after full checksum equality (reviewed decision)",
        )

    def _execute_existing_target(
        self,
        execution: TransferExecutionRow,
        plan: TransferPlanRow,
        entry: TransferPlanEntryRow,
        source: Path,
        dest: Path,
        st: os.stat_result,
    ) -> None:
        """An existing file occupies a planned copy path (A09/E06/§6.4).

        Overwriting is never an option and silently renaming around it
        is not either. Adoption requires full checksum equality *plus*
        provenance — a prior committed mapping for exactly this source,
        destination root, and relative path (§6.4/A23). Without
        provenance this stops for review, whatever the bytes say.
        """
        if stat_module.S_ISLNK(st.st_mode) or not stat_module.S_ISREG(st.st_mode):
            raise NeedsAttentionError(
                f"{entry.dest_rel_path} is occupied by something that is not an "
                "ordinary file; exclude it or replan"
            )
        with transaction(self._db_path) as conn:
            provenance = exec_repo.prior_committed_mapping(
                conn,
                source_path=entry.source_path,
                dest_rel_path=entry.dest_rel_path,
                dest_root=execution.dest_root,
                exclude_execution_id=execution.id,
            )
        if provenance is None:
            raise NeedsAttentionError(
                f"{entry.dest_rel_path} already exists and no prior Ferry transfer "
                "verifiably put it there; refusing to overwrite or rename around it "
                "— review the conflict and replan (skip-identical is available as "
                "an explicit decision)"
            )
        try:
            source_sum = compute_checksum(source, plan.checksum_algo)
            dest_sum = compute_checksum(dest, plan.checksum_algo)
        except OSError as exc:
            raise NeedsAttentionError(
                f"existing destination {entry.dest_rel_path} could not be verified: {exc}"
            ) from exc
        if (source_sum, dest_sum) != tuple(provenance) or source_sum != dest_sum:
            raise NeedsAttentionError(
                f"{entry.dest_rel_path} exists and no longer matches the verified "
                "prior mapping; refusing to overwrite — replan"
            )
        self._finish_item(
            execution.id,
            entry.id,
            "reused",
            source_checksum=source_sum,
            dest_checksum=dest_sum,
            checksum_algo=plan.checksum_algo,
            warning="existing output matched the prior verified mapping",
        )

    def _check_binding_still_true(self, execution: TransferExecutionRow, dest_root: Path) -> None:
        """Cheap per-publication binding revalidation (§5.2, A12).

        A full identity probe per file would put a platform subprocess
        in the inner loop of a 100,000-entry copy. What the per-file
        check must catch is the storage under the resolved root being
        swapped — an unmounted share whose mount directory remains now
        sits on the boot volume, and ``st_dev`` says so. The full
        resolver runs at every (re)start and after failures.
        """
        try:
            st = os.stat(dest_root)
        except OSError as exc:
            raise NeedsAttentionError(
                f"the destination root {dest_root} stopped being usable mid-transfer: {exc}"
            ) from exc
        if execution.dest_st_dev is not None and st.st_dev != execution.dest_st_dev:
            raise NeedsAttentionError(
                f"the storage under {dest_root} changed identity mid-transfer "
                f"(device {execution.dest_st_dev} -> {st.st_dev}); a share that "
                "unmounted behind its mount directory must never be written into"
            )

    # ------------------------------------------------------------------
    # item state helpers
    # ------------------------------------------------------------------

    def _finish_item(
        self,
        execution_id: str,
        plan_entry_id: int,
        state: str,
        *,
        source_checksum: str | None = None,
        dest_checksum: str | None = None,
        checksum_algo: str | None = None,
        warning: str | None = None,
    ) -> None:
        with transaction(self._db_path) as conn:
            exec_repo.update_execution_item(
                conn,
                execution_id,
                plan_entry_id,
                state=state,
                source_checksum=source_checksum,
                dest_checksum=dest_checksum,
                checksum_algo=checksum_algo,
                warning=warning,
                updated_at=_now_iso(),
            )

    def _fail_item(self, execution_id: str, plan_entry_id: int, error: str) -> None:
        with transaction(self._db_path) as conn:
            exec_repo.update_execution_item(
                conn,
                execution_id,
                plan_entry_id,
                state="failed",
                clear_temp=True,
                error=error[:2000],
                updated_at=_now_iso(),
            )

    def _fail_boot(self, execution_id: str, findings: list[str]) -> None:
        """A validation/reservation failure before any item ran."""
        text = "; ".join(findings)[:2000]
        now = _now_iso()
        with transaction(self._db_path) as conn:
            for item in exec_repo.get_execution_items(conn, execution_id):
                if item.state in ("pending", "copying"):
                    exec_repo.update_execution_item(
                        conn,
                        execution_id,
                        item.plan_entry_id,
                        state="failed",
                        clear_temp=True,
                        error=text,
                        updated_at=now,
                    )

    def _progress_reporter(
        self,
        scheduler: JobScheduler,
        job: JobDetail,
        execution: TransferExecutionRow,
        item: TransferExecutionItemRow,
    ) -> Callable[[int], None]:
        state = {"flushed": 0}

        def report(copied: int) -> None:
            if copied - state["flushed"] < _PROGRESS_FLUSH_BYTES:
                return
            state["flushed"] = copied
            with transaction(self._db_path) as conn:
                exec_repo.update_execution_item(
                    conn,
                    execution.id,
                    item.plan_entry_id,
                    bytes_copied=copied,
                    updated_at=_now_iso(),
                )
            self._safely(
                self._jobs.update_item_progress,
                execution.job_id,
                str(item.plan_entry_id),
                byte_progress=copied,
            )
            scheduler.notify_progress(job.id)

        return report

    @staticmethod
    def _safely(fn: Callable[..., object], *args: object, **kwargs: object) -> None:
        """Progress is never load-bearing (same policy as offload)."""
        try:
            fn(*args, **kwargs)
        except Exception:  # pragma: no cover - defensive
            _log.debug("transfer progress recording failed", exc_info=True)

    def _all_entries(self, plan_id: str) -> list[TransferPlanEntryRow]:
        entries: list[TransferPlanEntryRow] = []
        after = 0
        while True:
            with transaction(self._db_path) as conn:
                batch = plan_repo.page_plan_entries(conn, plan_id, limit=1000, after_id=after)
            if not batch:
                return entries
            entries.extend(batch)
            after = batch[-1].id

    # ------------------------------------------------------------------
    # receipts (§7.3)
    # ------------------------------------------------------------------

    def _write_receipt(
        self,
        plan: TransferPlanRow,
        execution: TransferExecutionRow,
        final_state: str,
        *,
        findings: list[str] | None = None,
    ) -> None:
        """Persist the database receipt first, then attempt the export.

        ``findings`` are execution-level reasons the run stopped —
        revalidation, binding, and crash-reconciliation failures, which
        belong to no single item. Without them a resume refused because
        the source changed would receipt only the *previous* attempt's
        per-item error, naming the wrong cause (A16).

        The execution state and the reservation release commit with the
        receipt in one transaction, so a receipt can never name a state
        the execution is not in. A persistence failure escalates to the
        caller as ``needs_attention``; an export failure is recorded
        and retriable (A22).
        """
        receipt = self._build_receipt(plan, execution, final_state, findings or [])
        receipt_json = json.dumps(receipt, sort_keys=True, indent=2)
        receipt_hash = hashlib.sha256(receipt_json.encode("utf-8")).hexdigest()
        try:
            with transaction(self._db_path) as conn:
                exec_repo.upsert_receipt(
                    conn,
                    execution_id=execution.id,
                    plan_id=plan.id,
                    fingerprint=plan.fingerprint,
                    receipt_json=receipt_json,
                    receipt_hash=receipt_hash,
                    final_state=final_state,
                    written_at=_now_iso(),
                )
                exec_repo.update_execution_state(
                    conn, execution.id, state=final_state, updated_at=_now_iso()
                )
                exec_repo.release_reservations(conn, execution.id, released_at=_now_iso())
        except Exception:
            _log.exception(
                "execution %s finished %s but its database receipt could not be "
                "written; marking needs_attention",
                execution.id,
                final_state,
            )
            try:
                with transaction(self._db_path) as conn:
                    exec_repo.update_execution_state(
                        conn,
                        execution.id,
                        state="needs_attention",
                        updated_at=_now_iso(),
                    )
                    exec_repo.release_reservations(conn, execution.id, released_at=_now_iso())
            except Exception:  # pragma: no cover - already failing
                _log.exception("execution %s could not be marked needs_attention", execution.id)
        self._export_receipt_file(execution.id)

    def _build_receipt(
        self,
        plan: TransferPlanRow,
        execution: TransferExecutionRow,
        final_state: str,
        findings: list[str],
    ) -> dict[str, Any]:
        with transaction(self._db_path) as conn:
            items = exec_repo.get_execution_items(conn, execution.id)
        committed = [i for i in items if i.state == "committed"]
        committed_directories = [
            i for i in committed if i.source_checksum is None and i.dest_checksum is None
        ]
        return {
            "schema": 1,
            "kind": "transfer",
            "executionId": execution.id,
            "jobId": execution.job_id,
            "planId": plan.id,
            "fingerprint": plan.fingerprint,
            "appVersion": APP_VERSION,
            "protocolVersion": PROTOCOL_VERSION,
            "destination": json.loads(execution.binding_json or "{}")
            | {"destRoot": execution.dest_root, "destStDev": execution.dest_st_dev},
            "preset": {
                "id": plan.preset_id,
                "revision": plan.preset_revision,
                "contentHash": plan.preset_content_hash,
            },
            "projectId": plan.project_id,
            "conflictPolicy": plan.conflict_policy,
            "checksumAlgo": plan.checksum_algo,
            "expected": {
                "totalFiles": plan.total_files,
                "totalBytes": plan.total_bytes,
                "exclusions": plan.exclusion_count,
                "ruleExclusions": plan.rule_exclusion_count,
                "reviewerExclusions": plan.exclusion_count - plan.rule_exclusion_count,
                "conflictFindings": plan.conflict_count,
                "ledgerEntries": len(items),
            },
            "actual": {
                "committed": len(committed),
                # A committed file always carries the checksum that proved it;
                # a committed directory has nothing to checksum and carries
                # none. Splitting them stops `committed` (16) reading as a
                # discrepancy against the file count (15) — #207.
                "files": len(committed) - len(committed_directories),
                "directories": len(committed_directories),
                "skippedIdentical": sum(1 for i in items if i.state == "skipped_identical"),
                "reused": sum(1 for i in items if i.state == "reused"),
                "excluded": sum(1 for i in items if i.state == "excluded"),
                "failed": sum(1 for i in items if i.state == "failed"),
                "bytesCommitted": sum(i.bytes_copied for i in committed),
            },
            "entries": [
                {
                    "planEntryId": i.plan_entry_id,
                    "sourcePath": i.source_path,
                    "destRelPath": i.dest_rel_path,
                    "state": i.state,
                    "size": i.size,
                    "bytesCopied": i.bytes_copied,
                    "checksumAlgo": i.checksum_algo,
                    "sourceChecksum": i.source_checksum,
                    "destChecksum": i.dest_checksum,
                    "warning": i.warning,
                    "error": i.error,
                }
                for i in items
            ],
            "warnings": [i.warning for i in items if i.warning],
            # Execution-level reasons first: they are why this run stopped,
            # where a per-item error may be left over from an earlier attempt.
            "errors": findings + [i.error for i in items if i.error],
            "blockingFindings": findings,
            "interruptionLineage": self._lineage(execution.id),
            "finalState": final_state,
            "startedAt": execution.started_at,
            "finishedAt": _now_iso(),
            # §12.2: duration, sustained (average) throughput, peak RSS.
            "performance": _performance_block(execution, committed),
        }

    def _lineage(self, execution_id: str) -> list[dict[str, str]]:
        with transaction(self._db_path) as conn:
            rows = conn.execute(
                "SELECT id, job_id, state, started_at, updated_at FROM transfer_executions "
                "WHERE plan_id = (SELECT plan_id FROM transfer_executions WHERE id = ?) "
                "ORDER BY started_at ASC",
                (execution_id,),
            ).fetchall()
        return [
            {
                "executionId": r["id"],
                "jobId": r["job_id"],
                "state": r["state"],
                "startedAt": r["started_at"],
                "updatedAt": r["updated_at"],
            }
            for r in rows
        ]

    def _export_receipt_file(self, execution_id: str) -> None:
        """Best-effort JSON export; failures are recorded, retriable (A22)."""
        try:
            with transaction(self._db_path) as conn:
                row = exec_repo.get_receipt(conn, execution_id)
                if row is None:
                    return
            self._receipts_dir.mkdir(parents=True, exist_ok=True)
            target = self._receipts_dir / f"transfer-{execution_id}.json"
            tmp = target.with_name(target.name + ".tmp")
            tmp.write_text(row.receipt_json, encoding="utf-8")
            os.replace(tmp, target)
            with transaction(self._db_path) as conn:
                exec_repo.mark_receipt_exported(conn, execution_id, exported_path=str(target))
        except Exception as exc:
            _log.warning("receipt export failed for %s: %s", execution_id, exc)
            try:
                with transaction(self._db_path) as conn:
                    exec_repo.mark_receipt_export_failed(conn, execution_id, error=str(exc))
            except Exception:  # pragma: no cover - best effort
                _log.exception("could not even record the export failure")

    def _finish_without_receipt(self, execution_id: str, state: str) -> None:
        """Terminal bookkeeping for a path that bypassed the receipt flow."""
        try:
            with transaction(self._db_path) as conn:
                exec_repo.update_execution_state(
                    conn, execution_id, state=state, updated_at=_now_iso()
                )
                exec_repo.release_reservations(conn, execution_id, released_at=_now_iso())
        except Exception:  # pragma: no cover - already a failure path
            _log.exception("failed to finalize execution %s", execution_id)

    # ------------------------------------------------------------------
    # receipt reads (transfer.receipt / transfer.receiptExport)
    # ------------------------------------------------------------------

    def receipt(self, params: TransferReceiptParams) -> TransferReceiptStatus:
        with transaction(self._db_path) as conn:
            row = exec_repo.latest_receipt_for_plan(conn, params.plan_id)
            execution = exec_repo.latest_execution_for_plan(conn, params.plan_id)
        if row is None:
            if execution is None:
                raise TransferRunnerError(
                    f"plan {params.plan_id} has no execution; transfer.start creates one"
                )
            raise TransferRunnerError(
                f"plan {params.plan_id} has an execution but no receipt yet "
                f"(execution state {execution.state})"
            )
        return self._receipt_status(row)

    def export_receipt(self, params: TransferReceiptParams) -> TransferReceiptStatus:
        status = self.receipt(params)  # raises the actionable reason if none
        self._export_receipt_file(status.execution_id)
        with transaction(self._db_path) as conn:
            row = exec_repo.get_receipt(conn, status.execution_id)
        assert row is not None
        return self._receipt_status(row)

    @staticmethod
    def _receipt_status(row: TransferReceiptRow) -> TransferReceiptStatus:
        return TransferReceiptStatus(
            executionId=row.execution_id,
            planId=row.plan_id,
            fingerprint=row.fingerprint,
            finalState=row.final_state,
            writtenAt=row.written_at,
            exportedPath=row.exported_path,
            exportError=row.export_error,
            receipt=json.loads(row.receipt_json),
        )

    # ------------------------------------------------------------------
    # bootstrap recovery (§7.3)
    # ------------------------------------------------------------------

    def recover_executions(self) -> list[str]:
        """Reconcile executions with dead jobs at startup.

        The scheduler already moved crashed jobs to ``needs_attention``;
        this mirrors that for execution rows and releases path
        reservations no live job will ever use again (a crash otherwise
        leaves them held forever, A21).
        """
        recovered: list[str] = []
        with transaction(self._db_path) as conn:
            released = exec_repo.release_reservations_for_dead_executions(
                conn, alive_job_states=set(_ALIVE_JOB_STATES), released_at=_now_iso()
            )
            recovered.extend(released)
            rows = conn.execute(
                "SELECT e.id, j.state FROM transfer_executions e "
                "JOIN jobs j ON j.id = e.job_id WHERE e.state = 'running'"
            ).fetchall()
            for row in rows:
                if row["state"] not in _ALIVE_JOB_STATES:
                    exec_repo.update_execution_state(
                        conn, row["id"], state="needs_attention", updated_at=_now_iso()
                    )
                    recovered.append(row["id"])
        return recovered

    def volume_of(self, job: JobDetail) -> str:
        """Volume key for per-destination serialization (scheduler)."""
        with transaction(self._db_path) as conn:
            execution = exec_repo.get_execution_by_job(conn, job.id)
            if execution is not None and execution.dest_root:
                return execution.dest_root
            prior = exec_repo.latest_execution_for_fingerprint(conn, job.args_fingerprint or "")
            if prior is not None and prior.dest_root:
                return prior.dest_root
        return "default"


def _snapshots(plan: TransferPlanRow) -> list[dict[str, Any]]:
    try:
        value = json.loads(plan.inventory_snapshot_json or "[]")
    except (TypeError, ValueError):
        return []
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def _lstat(path: Path) -> os.stat_result | None:
    try:
        return os.lstat(path)
    except OSError:
        return None


__all__ = [
    "TRANSFER_COMMAND",
    "TransferRunner",
    "TransferRunnerError",
]
