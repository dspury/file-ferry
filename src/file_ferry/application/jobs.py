"""Job service — durable jobs and the §6.4 state machine.

A job is a durable operation command with a plan fingerprint, an owner
session, timing, and resumability. ``succeeded`` is allowed only after
all mandatory steps and verification steps complete; ``needs_attention``
marks recoverable conditions; ``resumable`` records that a resume
boundary exists.

Legal transitions (plan §6.4):

    planned -> awaiting_review -> queued -> running -> verifying -> succeeded
                                    |         |          |
                                    v         v          v
                              cancelled  needs_attention  failed
                                            |
                                            v
                                        resumable
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from file_ferry.persistence.connection import transaction
from file_ferry.persistence.repositories import jobs as job_repo
from file_ferry.service.protocol import CreateJobParams, JobDetail, JobTransitionParams

# Terminal states cannot transition out of.
_TERMINAL = {"succeeded", "failed", "cancelled"}

LEGAL_TRANSITIONS: dict[str, set[str]] = {
    "planned": {"awaiting_review"},
    "awaiting_review": {"queued", "cancelled"},
    "queued": {"running", "cancelled"},
    "running": {"verifying", "needs_attention", "cancelled"},
    "verifying": {"succeeded", "failed", "needs_attention"},
    "needs_attention": {"resumable", "running", "cancelled"},
    "resumable": {"running"},
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class JobNotFoundError(KeyError):
    """Raised when a named job does not exist."""


class InvalidTransitionError(ValueError):
    """Raised when a job state transition is not legal."""


class JobService:
    """Durable jobs with an enforced state machine."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)

    def create(self, params: CreateJobParams) -> JobDetail:
        job_id = str(uuid.uuid4())
        now = _now_iso()
        row = job_repo.JobRow(
            id=job_id,
            project_id=params.project_id,
            session_id=params.session_id,
            command=params.command,
            args_fingerprint=params.args_fingerprint,
            state="planned",
            owner=None,
            current_step=None,
            total_steps=params.total_steps,
            started_at=None,
            updated_at=now,
            finished_at=None,
            error=None,
            resumable=0,
        )
        with transaction(self._db_path) as conn:
            job_repo.insert_job(conn, row)
        return self._to_detail(row)

    def get(self, job_id: str) -> JobDetail:
        with transaction(self._db_path) as conn:
            row = job_repo.get_job(conn, job_id)
        if row is None:
            raise JobNotFoundError(job_id)
        return self._to_detail(row)

    def list(self, project_id: str | None = None) -> list[JobDetail]:
        with transaction(self._db_path) as conn:
            rows = job_repo.list_jobs(conn, project_id)
        return [self._to_detail(r) for r in rows]

    def transition(self, params: JobTransitionParams) -> JobDetail:
        """Validate and apply a single state transition.

        ``from_state`` must match the job's current state and
        ``to_state`` must be a legal successor (plan §6.4).
        """
        with transaction(self._db_path) as conn:
            row = job_repo.get_job(conn, params.id)
            if row is None:
                raise JobNotFoundError(params.id)
            if row.state != params.from_state:
                raise InvalidTransitionError(
                    f"job {params.id} is {row.state!r}, not {params.from_state!r}"
                )
            legal = LEGAL_TRANSITIONS.get(params.from_state, set())
            if params.to_state not in legal:
                raise InvalidTransitionError(
                    f"illegal transition {params.from_state!r} -> {params.to_state!r} "
                    f"for job {params.id}"
                )
            now = _now_iso()
            job_repo.update_job(
                conn,
                params.id,
                state=params.to_state,
                started_at=now if params.to_state == "running" else None,
                finished_at=now if params.to_state in _TERMINAL else None,
                resumable=1 if params.to_state == "resumable" else None,
                updated_at=now,
            )
            updated = job_repo.get_job(conn, params.id)
        assert updated is not None
        return self._to_detail(updated)

    # ---- step / item helpers (consumed by later packages) ------------

    def add_step(self, job_id: str, step: str) -> None:
        with transaction(self._db_path) as conn:
            job_repo.insert_step(
                conn,
                job_repo.JobStepRow(
                    id=0,
                    job_id=job_id,
                    step=step,
                    state="pending",
                    started_at=None,
                    finished_at=None,
                    error=None,
                ),
            )

    def mark_step(self, job_id: str, step: str, state: str, *, error: str | None = None) -> None:
        now = _now_iso()
        with transaction(self._db_path) as conn:
            job_repo.update_step(
                conn,
                job_id,
                step,
                state=state,
                started_at=now if state == "running" else None,
                finished_at=now if state in {"succeeded", "failed", "cancelled"} else None,
                error=error,
            )

    def add_item(
        self,
        job_id: str,
        *,
        step: str,
        asset_id: str | None,
        source_path: str,
        dest_path: str,
        total_bytes: int,
        temp_path: str | None = None,
    ) -> None:
        with transaction(self._db_path) as conn:
            job_repo.insert_item(
                conn,
                job_repo.JobItemRow(
                    id=0,
                    job_id=job_id,
                    step=step,
                    asset_id=asset_id,
                    source_path=source_path,
                    dest_path=dest_path,
                    temp_path=temp_path,
                    byte_progress=0,
                    total_bytes=total_bytes,
                    state="pending",
                    error=None,
                ),
            )

    def update_item_progress(
        self,
        job_id: str,
        asset_id: str,
        *,
        byte_progress: int | None = None,
        state: str | None = None,
        error: str | None = None,
    ) -> None:
        with transaction(self._db_path) as conn:
            job_repo.update_item_progress(
                conn,
                job_id,
                asset_id,
                byte_progress=byte_progress,
                state=state,
                error=error,
            )

    @staticmethod
    def _to_detail(row: job_repo.JobRow) -> JobDetail:
        return JobDetail(
            id=row.id,
            projectId=row.project_id,
            sessionId=row.session_id,
            command=row.command,
            state=row.state,
            currentStep=row.current_step,
            totalSteps=row.total_steps,
            startedAt=row.started_at,
            updatedAt=row.updated_at,
            finishedAt=row.finished_at,
            error=row.error,
            resumable=bool(row.resumable),
        )
