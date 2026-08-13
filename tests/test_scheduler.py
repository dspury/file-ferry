"""Job scheduler — concurrency, cancellation, recovery, events."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from media_mate.application.jobs import JobService
from media_mate.application.scheduler import JobScheduler, VolumeLimiter
from media_mate.service.protocol import CreateJobParams, JobTransitionParams


@pytest.fixture
def db(tmp_path: Path) -> Path:
    from media_mate.application.service import ApplicationService

    db = tmp_path / "media-mate.db"
    boot = ApplicationService(db_path=db, app_data_dir=tmp_path / "app")
    boot.bootstrap()
    boot.close()
    with sqlite3.connect(db) as conn:
        for pid in ("proj-1", "proj-2"):
            conn.execute(
                "INSERT INTO projects (id, name, status, working_root, storage_policy, "
                "created_at, updated_at) VALUES (?, ?, 'active', '/tmp', '{}', 'now', 'now')",
                (pid, pid),
            )
        conn.commit()
    return db


def _queued_job(jobs: JobService, *, command: str = "copy", pid: str = "proj-1") -> str:
    job = jobs.create(CreateJobParams(projectId=pid, command=command))
    jobs.transition(JobTransitionParams(id=job.id, fromState="planned", toState="awaiting_review"))
    jobs.transition(JobTransitionParams(id=job.id, fromState="awaiting_review", toState="queued"))
    return job.id


# ---- VolumeLimiter ---------------------------------------------------


def test_limiter_enforces_cap() -> None:
    lim = VolumeLimiter(max_per_volume=1)
    assert lim.can_start("vol-a")
    assert lim.acquire("vol-a") is True
    assert lim.can_start("vol-a") is False
    assert lim.acquire("vol-a") is False  # second acquire rejected
    assert lim.active("vol-a") == 1
    lim.release("vol-a")
    assert lim.active("vol-a") == 0
    assert lim.can_start("vol-a") is True


def test_limiter_tracks_separate_volumes() -> None:
    lim = VolumeLimiter(max_per_volume=1)
    assert lim.acquire("vol-a")
    assert lim.acquire("vol-b")  # different volume, still allowed
    assert lim.active("vol-a") == 1
    assert lim.active("vol-b") == 1


def test_limiter_release_is_safe_when_empty() -> None:
    lim = VolumeLimiter(max_per_volume=1)
    lim.release("vol-a")  # must not raise
    assert lim.active("vol-a") == 0


# ---- dispatch --------------------------------------------------------


def test_dispatch_success(db: Path) -> None:
    jobs = JobService(db)
    sched = JobScheduler(db, jobs)
    sched.register_runner("copy", lambda job, s: "succeeded")
    jid = _queued_job(jobs)
    result = sched.dispatch(jid)
    assert result.state == "succeeded"


def test_dispatch_holds_volume_slot_during_run(db: Path) -> None:
    jobs = JobService(db)
    sched = JobScheduler(db, jobs, max_per_volume=1)
    sched.register_volume("copy", lambda job: "vol-A")
    observed: dict[str, int] = {}

    def runner(job, s):
        observed["active"] = s._limiter.active("vol-A")
        return "succeeded"

    sched.register_runner("copy", runner)
    jid = _queued_job(jobs)
    sched.dispatch(jid)
    assert observed["active"] == 1  # slot held while the runner executed


def test_dispatch_failure(db: Path) -> None:
    jobs = JobService(db)
    sched = JobScheduler(db, jobs)
    sched.register_runner("copy", lambda job, s: "failed")
    jid = _queued_job(jobs)
    assert sched.dispatch(jid).state == "failed"


def test_dispatch_runner_exception_becomes_failed(db: Path) -> None:
    jobs = JobService(db)
    sched = JobScheduler(db, jobs)

    def runner(job, s):
        raise RuntimeError("boom")

    sched.register_runner("copy", runner)
    jid = _queued_job(jobs)
    assert sched.dispatch(jid).state == "failed"


def test_dispatch_no_runner_becomes_needs_attention(db: Path) -> None:
    jobs = JobService(db)
    sched = JobScheduler(db, jobs)  # no runner registered
    jid = _queued_job(jobs, command="unknown")
    assert sched.dispatch(jid).state == "needs_attention"


def test_dispatch_non_queued_is_noop(db: Path) -> None:
    jobs = JobService(db)
    sched = JobScheduler(db, jobs)
    sched.register_runner("copy", lambda job, s: "succeeded")
    job = jobs.create(CreateJobParams(projectId="proj-1", command="copy"))  # still planned
    assert sched.dispatch(job.id).state == "planned"


# ---- cooperative cancellation ----------------------------------------


def test_cancel_runner_checks_flag(db: Path) -> None:
    jobs = JobService(db)
    sched = JobScheduler(db, jobs)

    def runner(job, s):
        return "cancelled" if s.should_cancel(job.id) else "succeeded"

    sched.register_runner("copy", runner)
    jid = _queued_job(jobs)
    sched.request_cancel(jid)
    assert sched.dispatch(jid).state == "cancelled"


# ---- event publishing ------------------------------------------------


def test_dispatch_publishes_events(db: Path) -> None:
    jobs = JobService(db)
    sched = JobScheduler(db, jobs)
    sched.register_runner("copy", lambda job, s: "succeeded")
    seen: list[str] = []
    sched.subscribe(lambda job: seen.append(job.state))
    jid = _queued_job(jobs)
    sched.dispatch(jid)
    assert "running" in seen
    assert "verifying" in seen
    assert seen[-1] == "succeeded"


# ---- restart recovery ------------------------------------------------


def test_recover_marks_interrupted_as_needs_attention(db: Path) -> None:
    jobs = JobService(db)
    sched = JobScheduler(db, jobs)
    running = _queued_job(jobs)
    jobs.transition(JobTransitionParams(id=running, fromState="queued", toState="running"))
    verifying = _queued_job(jobs, pid="proj-2")
    jobs.transition(JobTransitionParams(id=verifying, fromState="queued", toState="running"))
    jobs.transition(JobTransitionParams(id=verifying, fromState="running", toState="verifying"))
    # A terminal job must be left alone.
    done = _queued_job(jobs)
    jobs.transition(JobTransitionParams(id=done, fromState="queued", toState="running"))
    jobs.transition(JobTransitionParams(id=done, fromState="running", toState="verifying"))
    jobs.transition(JobTransitionParams(id=done, fromState="verifying", toState="succeeded"))

    recovered = sched.recover()
    assert set(recovered) == {running, verifying}
    assert jobs.get(running).state == "needs_attention"
    assert jobs.get(verifying).state == "needs_attention"
    assert jobs.get(done).state == "succeeded"
