"""Durable job scheduler — concurrency, cancellation, recovery, events.

Implements plan §6.4/§7.2 scheduling concerns:

- Per-volume concurrency: :class:`VolumeLimiter` tracks active jobs per
  volume so a single drive is not saturated (plan §7.2).
- Cooperative cancellation: a runner polls :meth:`JobScheduler.should_cancel`
  at safe boundaries and stops; incomplete work is marked, never declared
  succeeded.
- Event publishing: listeners receive a :class:`JobDetail` on every state
  change (the renderer subscribes via ``job.subscribe``).
- Restart recovery: :meth:`recover` marks any job stuck in ``running`` /
  ``verifying`` after a crash as ``needs_attention`` — never succeeded.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from file_ferry.application.jobs import InvalidTransitionError, JobService
from file_ferry.service.protocol import CreateJobParams, JobDetail

Runner = Callable[[JobDetail, "JobScheduler"], str]
VolumeResolver = Callable[[JobDetail], str]

_log = logging.getLogger(__name__)

_DEFAULT_VOLUME = "default"


class VolumeLimiter:
    """Tracks active jobs per volume and enforces a per-volume cap."""

    def __init__(self, max_per_volume: int = 1) -> None:
        if max_per_volume < 1:
            raise ValueError("max_per_volume must be >= 1")
        self._max = max_per_volume
        self._active: dict[str, int] = {}

    def can_start(self, volume: str) -> bool:
        return self._active.get(volume, 0) < self._max

    def acquire(self, volume: str) -> bool:
        if not self.can_start(volume):
            return False
        self._active[volume] = self._active.get(volume, 0) + 1
        return True

    def release(self, volume: str) -> None:
        current = self._active.get(volume, 0)
        if current <= 0:
            return
        if current == 1:
            del self._active[volume]
        else:
            self._active[volume] = current - 1

    def active(self, volume: str) -> int:
        return self._active.get(volume, 0)


class JobScheduler:
    """Dispatches queued jobs through registered runners."""

    def __init__(self, db_path: Path, jobs: JobService, *, max_per_volume: int = 1) -> None:
        self._db_path = Path(db_path)
        self._jobs = jobs
        self._limiter = VolumeLimiter(max_per_volume)
        self._runners: dict[str, Runner] = {}
        self._volumes: dict[str, VolumeResolver] = {}
        self._cancelled: set[str] = set()
        self._listeners: list[Callable[[JobDetail], None]] = []

    # ---- registration ------------------------------------------------

    def register_runner(self, command: str, runner: Runner) -> None:
        self._runners[command] = runner

    def register_volume(self, command: str, resolver: VolumeResolver) -> None:
        self._volumes[command] = resolver

    def subscribe(self, listener: Callable[[JobDetail], None]) -> None:
        self._listeners.append(listener)

    # ---- cancellation ------------------------------------------------

    def request_cancel(self, job_id: str) -> None:
        """Ask a running job to stop at its next safe boundary."""
        self._cancelled.add(job_id)

    def should_cancel(self, job_id: str) -> bool:
        return job_id in self._cancelled

    # ---- dispatch ----------------------------------------------------

    def dispatch(self, job_id: str) -> JobDetail:
        """Run one queued job through its runner (respecting volume limits)."""
        job = self._jobs.get(job_id)
        if job.state != "queued":
            return job
        runner = self._runners.get(job.command)
        volume = self._volume_of(job)
        if not self._limiter.acquire(volume):
            return job  # no slot yet; stays queued

        try:
            try:
                job = self._transition(job_id, "queued", "running")
            except InvalidTransitionError:
                # Another caller claimed it between the state check above and
                # here -- the background dispatcher and the `job.dispatch` IPC
                # method both land in this method. The transition is the real
                # lock (it re-checks the state inside its transaction), so the
                # loser simply reports what the winner has made of the job
                # instead of raising at the renderer.
                return self._jobs.get(job_id)
            return self._execute(job, runner)
        finally:
            self._limiter.release(volume)

    def _execute(self, job: JobDetail, runner: Runner | None) -> JobDetail:
        """Run an already-"running" job through its runner and finish it."""
        if runner is None:
            self._cancelled.discard(job.id)
            return self._transition(job.id, "running", "needs_attention")
        try:
            outcome = runner(job, self)
        except Exception:  # runner must not crash the scheduler
            outcome = "failed"
        return self._finish(job.id, job, outcome)

    def _finish(self, job_id: str, job: JobDetail, outcome: str) -> JobDetail:
        # ``failed`` is only reachable from ``verifying`` in the §6.4 machine,
        # so a hard runner failure passes through verifying (no success claim).
        if outcome == "succeeded":
            result = self._transition(job_id, "running", "verifying")
            result = self._transition(job_id, "verifying", "succeeded")
        elif outcome == "cancelled":
            result = self._transition(job_id, "running", "cancelled")
        else:
            self._transition(job_id, "running", "verifying")
            result = self._transition(job_id, "verifying", "failed")
        self._cancelled.discard(job_id)
        return result

    def _transition(self, job_id: str, from_state: str, to_state: str) -> JobDetail:
        from file_ferry.service.protocol import JobTransitionParams

        updated = self._jobs.transition(
            JobTransitionParams(id=job_id, fromState=from_state, toState=to_state)
        )
        self._publish(updated)
        return updated

    # ---- recovery ----------------------------------------------------

    def recover(self) -> list[str]:
        """Mark jobs stuck in running/verifying as needs_attention (restart)."""
        recovered: list[str] = []
        for job in self._jobs.list():
            if job.state in {"running", "verifying"}:
                try:
                    self._transition(job.id, job.state, "needs_attention")
                    recovered.append(job.id)
                except InvalidTransitionError:  # pragma: no cover - defensive
                    continue
        return recovered

    def resume(self, job_id: str) -> JobDetail:
        """Resume an attention/partial job at a safe boundary.

        Per plan §6.4, ``needs_attention -> resumable -> running``. The
        runner is responsible for validating source/destination state and
        the original plan fingerprint before it reuses partial output; the
        scheduler only advances the legal transitions and executes.
        """
        job = self._jobs.get(job_id)
        if job.state != "needs_attention":
            raise InvalidTransitionError(
                f"cannot resume job {job_id} in state {job.state!r}; expected needs_attention"
            )
        runner = self._runners.get(job.command)
        volume = self._volume_of(job)
        if not self._limiter.acquire(volume):
            return job  # no slot yet; stays needs_attention
        try:
            self._transition(job_id, "needs_attention", "resumable")
            job = self._transition(job_id, "resumable", "running")
            return self._execute(job, runner)
        finally:
            self._limiter.release(volume)

    def retry(self, job_id: str) -> JobDetail:
        """Retry a failed job with a fresh attempt.

        ``failed`` is a terminal state in the §6.4 machine, so a retry
        creates a NEW job (a fresh attempt) rather than mutating the
        failed record. The prior failure is preserved in history.
        """
        prior = self._jobs.get(job_id)
        if prior.state != "failed":
            raise InvalidTransitionError(
                f"cannot retry job {job_id} in state {prior.state!r}; expected failed"
            )
        created = self._jobs.create(
            CreateJobParams(
                projectId=prior.project_id,
                command=prior.command,
                sessionId=prior.session_id,
                totalSteps=prior.total_steps,
            )
        )
        self._transition(created.id, "planned", "awaiting_review")
        self._transition(created.id, "awaiting_review", "queued")
        return self.dispatch(created.id)

    # ---- events ------------------------------------------------------

    def notify_progress(self, job_id: str) -> None:
        """Publish a job's current state without changing it.

        A runner calls this as it works. Without it the only events a job
        ever produced were its state transitions, so a two-hour copy sat
        between `running` and `verifying` with nothing to show for it.
        Best-effort: a job that vanished mid-run must not fail the transfer.
        """
        try:
            self._publish(self._jobs.get(job_id))
        except Exception:  # pragma: no cover - progress is never load-bearing
            _log.debug("progress notification failed for job %s", job_id, exc_info=True)

    def _publish(self, job: JobDetail) -> None:
        for listener in self._listeners:
            listener(job)

    # ---- helpers -----------------------------------------------------

    def _volume_of(self, job: JobDetail) -> str:
        resolver = self._volumes.get(job.command)
        return resolver(job) if resolver is not None else _DEFAULT_VOLUME
