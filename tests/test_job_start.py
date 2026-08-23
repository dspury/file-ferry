"""Creating a job is not the same as starting one.

Two defects, found by driving the desktop app rather than the suite:

- ``ApplicationService.job_transition`` never woke the background
  dispatcher, and reaching ``queued`` is the dispatcher's entire trigger
  condition. ``job.create`` kicks, but a job is never queued at creation,
  so a job queued by transition sat until some unrelated event happened to
  wake the loop.
- The Offload screen called ``job.create`` and stopped. A new job is
  ``planned``, held at the plan §6.4 review gate, so every offload run
  from the desktop waited forever for an approval the UI never offered.

Both are invisible to a test that dispatches explicitly, which is what
every existing job test does.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import NamedTuple

from file_ferry.application.service import ApplicationService
from file_ferry.service.protocol import (
    AddDestinationParams,
    CreateIntakeSessionParams,
    CreateJobParams,
    CreateProjectParams,
    JobTransitionParams,
    SourceInspectParams,
    StoragePolicy,
)

SAME_VOLUME_POLICY = StoragePolicy(
    requiredReplicas=2,
    backupOnDifferentVolume=False,
    checksumAlgo="xxhash64",
    safetyReserveBytes=0,
    requireSourceFingerprint=True,
)


class Fixture(NamedTuple):
    service: ApplicationService
    project_id: str
    session_id: str


def _setup(tmp_path: Path) -> Fixture:
    svc = ApplicationService(db_path=tmp_path / "ferry.db", app_data_dir=tmp_path / "app")
    svc.bootstrap()
    working = tmp_path / "proj" / "working"
    backup = tmp_path / "proj" / "backup"
    working.mkdir(parents=True)
    backup.mkdir(parents=True)
    pid = svc.create_project(
        CreateProjectParams(
            name="Start",
            workingRoot=str(working),
            backupRoot=str(backup),
            storagePolicy=SAME_VOLUME_POLICY,
            acknowledgeWeaker=True,
        )
    )
    src = tmp_path / "card" / "DCIM"
    src.mkdir(parents=True)
    (src / "A001.mov").write_bytes(b"media-content")
    inspected = svc.source_inspect(SourceInspectParams(path=str(tmp_path / "card"), kind="card"))
    session = svc.intake_create_session(
        CreateIntakeSessionParams(projectId=pid, sourceId=inspected.source_id, kind="offload")
    )
    for kind, root in (("working", working), ("backup", backup)):
        svc.intake_add_destination(
            AddDestinationParams(intakeSessionId=session.id, kind=kind, rootPath=str(root))
        )
    svc.intake_adopt_source(session.id, inspected.source_id, inspected.entries, str(working))
    return Fixture(svc, pid, session.id)


def _settle_dispatcher(svc: ApplicationService, timeout: float = 5.0) -> None:
    """Wait until the dispatcher loop is parked on its wake event.

    Without this the test races: `job.create` sets the wake, and if the
    loop has not consumed it yet then a transition made microseconds later
    is picked up by that *earlier* wake. The job then runs whether or not
    queueing wakes the dispatcher, and the test passes for the wrong
    reason. A clear event means the loop is blocked in ``_wake.wait()`` and
    only a fresh kick can move it.
    """
    dispatcher = svc._dispatcher
    assert dispatcher is not None
    waiter = threading.Event()
    for _ in range(int(timeout / 0.02)):
        if not dispatcher._wake.is_set():
            return
        waiter.wait(0.02)
    raise AssertionError("dispatcher never parked on its wake event")


def _await_state(svc: ApplicationService, job_id: str, state: str, timeout: float = 10.0) -> str:
    """Poll until the background dispatcher has taken the job somewhere.

    The dispatcher is a real thread here on purpose -- that it never woke
    is the defect -- so the test waits on the outcome rather than driving
    dispatch itself, which is what hid this.
    """
    deadline = threading.Event()
    for _ in range(int(timeout / 0.05)):
        current = svc.job_get(job_id).state
        if current == state:
            return current
        deadline.wait(0.05)
    return svc.job_get(job_id).state


class TestAReviewedJobRuns:
    def test_creating_a_reviewed_job_starts_it(self, tmp_path: Path) -> None:
        """The Offload screen's Execute button, end to end: nothing calls
        dispatch, and the job still finishes."""
        fixture = _setup(tmp_path)
        svc = fixture.service
        try:
            job = svc.job_create(
                CreateJobParams(
                    projectId=fixture.project_id,
                    command="offload",
                    sessionId=fixture.session_id,
                    reviewed=True,
                )
            )
            assert _await_state(svc, job.id, "succeeded") == "succeeded"
        finally:
            svc.close()

    def test_an_unreviewed_job_waits_at_the_gate(self, tmp_path: Path) -> None:
        """The gate still exists. A job created without review must not run
        itself -- that is the whole point of plan §6.4's review step."""
        fixture = _setup(tmp_path)
        svc = fixture.service
        try:
            job = svc.job_create(
                CreateJobParams(
                    projectId=fixture.project_id,
                    command="offload",
                    sessionId=fixture.session_id,
                )
            )
            # Give the dispatcher every chance to run it wrongly.
            assert _await_state(svc, job.id, "succeeded", timeout=1.0) == "planned"
        finally:
            svc.close()

    def test_reviewing_reports_the_queued_or_later_state(self, tmp_path: Path) -> None:
        """`job.create` returns the job as it stands after the gate, not the
        `planned` row it briefly was -- a caller that renders the result
        should not show a state the job has already left."""
        fixture = _setup(tmp_path)
        svc = fixture.service
        try:
            job = svc.job_create(
                CreateJobParams(
                    projectId=fixture.project_id,
                    command="offload",
                    sessionId=fixture.session_id,
                    reviewed=True,
                )
            )
            assert job.state != "planned"
        finally:
            svc.close()


class TestQueueingWakesTheDispatcher:
    def test_a_job_queued_by_transition_is_picked_up(self, tmp_path: Path) -> None:
        """The transition path, driven the way the CLI and a manual approval
        would drive it. Nothing here calls dispatch or kick."""
        fixture = _setup(tmp_path)
        svc = fixture.service
        try:
            job = svc.job_create(
                CreateJobParams(
                    projectId=fixture.project_id,
                    command="offload",
                    sessionId=fixture.session_id,
                )
            )
            _settle_dispatcher(svc)
            svc.job_transition(
                JobTransitionParams(id=job.id, fromState="planned", toState="awaiting_review")
            )
            svc.job_transition(
                JobTransitionParams(id=job.id, fromState="awaiting_review", toState="queued")
            )
            assert _await_state(svc, job.id, "succeeded") == "succeeded"
        finally:
            svc.close()
