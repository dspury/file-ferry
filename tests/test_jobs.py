"""Job service + §6.4 state machine."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ferry.application.jobs import InvalidTransitionError, JobNotFoundError, JobService
from ferry.service.protocol import CreateJobParams, JobTransitionParams


@pytest.fixture
def service(tmp_path: Path) -> JobService:
    import sqlite3 as _s

    from ferry.application.service import ApplicationService

    db = tmp_path / "ferry.db"
    boot = ApplicationService(db_path=db, app_data_dir=tmp_path / "app")
    boot.bootstrap()
    boot.close()
    with _s.connect(db) as conn:
        for pid in ("proj-1", "p1", "p2"):
            _insert_project(conn, pid)
        conn.commit()
    return JobService(db_path=db)


def _insert_project(conn: sqlite3.Connection, pid: str) -> None:
    conn.execute(
        """
        INSERT INTO projects (id, name, status, working_root, storage_policy, created_at, updated_at)
        VALUES (?, ?, 'active', '/tmp', '{}', 'now', 'now')
        """,
        (pid, pid),
    )


def test_create_job(service: JobService) -> None:
    job = service.create(CreateJobParams(projectId="proj-1", command="offload", totalSteps=3))
    assert job.state == "planned"
    assert job.total_steps == 3
    fetched = service.get(job.id)
    assert fetched.id == job.id
    assert fetched.project_id == "proj-1"


def test_list_jobs_by_project(service: JobService) -> None:
    service.create(CreateJobParams(projectId="p1", command="a"))
    service.create(CreateJobParams(projectId="p2", command="b"))
    assert len(service.list("p1")) == 1
    assert len(service.list()) == 2


def test_valid_full_path(service: JobService) -> None:
    job = service.create(CreateJobParams(projectId="p1", command="offload"))
    steps = [
        ("planned", "awaiting_review"),
        ("awaiting_review", "queued"),
        ("queued", "running"),
        ("running", "verifying"),
        ("verifying", "succeeded"),
    ]
    for from_state, to_state in steps:
        job = service.transition(
            JobTransitionParams(id=job.id, fromState=from_state, toState=to_state)
        )
    assert job.state == "succeeded"
    assert job.finished_at is not None
    assert job.started_at is not None


def test_needs_attention_to_resumable(service: JobService) -> None:
    job = service.create(CreateJobParams(projectId="p1", command="offload"))
    service.transition(
        JobTransitionParams(id=job.id, fromState="planned", toState="awaiting_review")
    )
    service.transition(
        JobTransitionParams(id=job.id, fromState="awaiting_review", toState="queued")
    )
    service.transition(JobTransitionParams(id=job.id, fromState="queued", toState="running"))
    service.transition(
        JobTransitionParams(id=job.id, fromState="running", toState="needs_attention")
    )
    resumable = service.transition(
        JobTransitionParams(id=job.id, fromState="needs_attention", toState="resumable")
    )
    assert resumable.state == "resumable"
    assert resumable.resumable is True
    # And it can resume.
    running = service.transition(
        JobTransitionParams(id=job.id, fromState="resumable", toState="running")
    )
    assert running.state == "running"


def test_illegal_transition_rejected(service: JobService) -> None:
    job = service.create(CreateJobParams(projectId="p1", command="offload"))
    # planned -> running is not legal (must go through awaiting_review -> queued).
    with pytest.raises(InvalidTransitionError):
        service.transition(JobTransitionParams(id=job.id, fromState="planned", toState="running"))


def test_transition_from_wrong_state_rejected(service: JobService) -> None:
    job = service.create(CreateJobParams(projectId="p1", command="offload"))
    # Job is 'planned', claiming from_state 'queued' must fail.
    with pytest.raises(InvalidTransitionError):
        service.transition(JobTransitionParams(id=job.id, fromState="queued", toState="running"))


def test_terminal_state_is_frozen(service: JobService) -> None:
    job = service.create(CreateJobParams(projectId="p1", command="offload"))
    service.transition(
        JobTransitionParams(id=job.id, fromState="planned", toState="awaiting_review")
    )
    service.transition(
        JobTransitionParams(id=job.id, fromState="awaiting_review", toState="cancelled")
    )
    with pytest.raises(InvalidTransitionError):
        service.transition(JobTransitionParams(id=job.id, fromState="cancelled", toState="running"))


def test_get_missing_raises(service: JobService) -> None:
    with pytest.raises(JobNotFoundError):
        service.get("no-such-job")


def test_add_and_mark_step(service: JobService) -> None:
    job = service.create(CreateJobParams(projectId="p1", command="offload"))
    service.add_step(job.id, "copy")
    service.mark_step(job.id, "copy", "running")
    service.mark_step(job.id, "copy", "succeeded")
    # mark_step is idempotent-ish and must not raise.
    service.mark_step(job.id, "copy", "succeeded")
