"""Tests for ``job.updated`` publishing.

The sidecar declared this event, the desktop's replay store recorded it,
the preload exposed a listener for it, and nothing ever emitted it: the
scheduler published every transition to its listener list and no one had
ever subscribed. These tests pin the whole edge — real snapshots, the
subscription filter, and the event actually reaching a wired server's
stdout.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from file_ferry.application.jobs import JobNotFoundError, JobService
from file_ferry.application.service import ApplicationService
from file_ferry.service.protocol import (
    PROTOCOL_VERSION,
    CreateJobParams,
    CreateProjectParams,
    JobTransitionParams,
)
from file_ferry.service.server import SidecarServer
from file_ferry.service.wiring import wire_server


@pytest.fixture
def service(tmp_path: Path) -> ApplicationService:
    svc = ApplicationService(
        db_path=tmp_path / "events.db",
        app_data_dir=tmp_path / "app",
        config_path=tmp_path / "config.toml",
    )
    svc.bootstrap()
    # Stop the background dispatcher `bootstrap` starts (#146).
    #
    # These tests drive the §6.4 state machine by hand, and reaching
    # `queued` is the dispatcher's entire trigger condition -- deliberately,
    # since #84 fixed the opposite bug. So the dispatcher could claim a job
    # the moment a test queued it, run it, and fail it before the test's
    # next transition, which then failed with
    # "job ... is 'failed', not 'queued'". Roughly 3% of isolated runs, and
    # it red-lit an unrelated PR on CI.
    #
    # Nothing in this file exercises dispatch -- it is all subscription and
    # event publishing -- so the dispatcher is ambient interference here,
    # not the thing under test. Tests that DO want it live should keep it
    # and settle it instead; see `_settle_dispatcher` in test_job_start.py.
    #
    # The dispatcher's own `stop()` rather than `svc.shutdown()`: shutdown
    # also clears the reference, and `job_create` goes through
    # `_dispatcher_service()`, which reads a missing dispatcher as
    # "bootstrap() was never called" and raises. Stopping the loop leaves the
    # object in place, so `kick()` still sets an event -- there is simply no
    # thread waiting on it.
    assert svc._dispatcher is not None
    svc._dispatcher.stop()
    yield svc
    svc.close()


def _project(service: ApplicationService, tmp_path: Path) -> str:
    working = tmp_path / "working"
    working.mkdir(exist_ok=True)
    return service.create_project(CreateProjectParams(name="events", workingRoot=str(working)))


def _job(service: ApplicationService, tmp_path: Path, *, total_steps: int = 3) -> str:
    project_id = _project(service, tmp_path)
    job = service.job_create(
        CreateJobParams(projectId=project_id, command="offload", totalSteps=total_steps)
    )
    return job.id


class TestJobSnapshot:
    def test_reports_completed_steps(self, service: ApplicationService, tmp_path: Path) -> None:
        """The progress bar divides completedSteps by totalSteps, so the
        snapshot has to count real step rows rather than the job row alone."""
        job_id = _job(service, tmp_path)
        jobs: JobService = service._job_service()
        for step in ("copy", "checksum", "verify"):
            jobs.add_step(job_id, step)
        jobs.mark_step(job_id, "copy", "succeeded")
        jobs.mark_step(job_id, "checksum", "succeeded")
        jobs.mark_step(job_id, "verify", "running")

        snapshot = service.job_snapshot(job_id)
        assert snapshot.completed_steps == ["copy", "checksum"]
        assert snapshot.current_step == "verify"
        assert snapshot.total_steps == 3

    def test_unknown_job_raises(self, service: ApplicationService) -> None:
        # The old stub answered for any id at all, so a bad id looked like a
        # real job stuck at 0%.
        with pytest.raises(JobNotFoundError):
            service.job_snapshot("no-such-job")

    def test_no_steps_recorded_is_not_an_error(
        self, service: ApplicationService, tmp_path: Path
    ) -> None:
        job_id = _job(service, tmp_path)
        snapshot = service.job_snapshot(job_id)
        assert snapshot.completed_steps == []
        assert snapshot.current_step == ""
        assert snapshot.state == "planned"


class TestSubscriptionFilter:
    def test_creation_is_announced_even_though_nobody_can_be_subscribed(
        self, service: ApplicationService, tmp_path: Path
    ) -> None:
        """A subscription is per job id, so a client watching the job list
        cannot ask for a job that does not exist yet. Without this one
        unsolicited event, a job created while the Activity screen is open
        stays invisible until something else reloads the list.
        """
        seen: list[str] = []
        service.set_event_sink(lambda _m, params: seen.append(params["jobId"]))
        job_id = _job(service, tmp_path)
        assert seen == [job_id]
        # And it really is unsolicited -- no subscription was created by it,
        # so the stream does not continue on its own.
        assert job_id not in service._job_subscriptions

    def test_subscribe_returns_current_state(
        self, service: ApplicationService, tmp_path: Path
    ) -> None:
        job_id = _job(service, tmp_path)
        assert service.job_subscribe(job_id).id == job_id

    def test_nothing_is_published_without_a_subscription(
        self, service: ApplicationService, tmp_path: Path
    ) -> None:
        job_id = _job(service, tmp_path)
        seen: list[tuple[str, dict]] = []
        service.set_event_sink(lambda method, params: seen.append((method, params)))
        service.job_transition(
            JobTransitionParams(id=job_id, fromState="planned", toState="awaiting_review")
        )
        assert seen == []

    def test_transition_publishes_to_a_subscriber(
        self, service: ApplicationService, tmp_path: Path
    ) -> None:
        job_id = _job(service, tmp_path)
        seen: list[tuple[str, dict]] = []
        service.set_event_sink(lambda method, params: seen.append((method, params)))
        service.job_subscribe(job_id)
        service.job_transition(
            JobTransitionParams(id=job_id, fromState="planned", toState="awaiting_review")
        )
        assert len(seen) == 1
        method, params = seen[0]
        assert method == "job.updated"
        assert params["jobId"] == job_id
        # camelCase on the wire: the renderer reads `snapshot.currentStep`.
        assert params["snapshot"]["state"] == "awaiting_review"
        assert "currentStep" in params["snapshot"]
        assert "completedSteps" in params["snapshot"]

    def test_unsubscribe_stops_the_stream(
        self, service: ApplicationService, tmp_path: Path
    ) -> None:
        job_id = _job(service, tmp_path)
        seen: list[str] = []
        service.set_event_sink(lambda method, _params: seen.append(method))
        service.job_subscribe(job_id)
        service.job_unsubscribe(job_id)
        service.job_transition(
            JobTransitionParams(id=job_id, fromState="planned", toState="awaiting_review")
        )
        assert seen == []

    def test_unsubscribe_is_idempotent(self, service: ApplicationService) -> None:
        service.job_unsubscribe("never-subscribed")

    def test_a_terminal_job_drops_its_own_subscription(
        self, service: ApplicationService, tmp_path: Path
    ) -> None:
        """A finished job can never emit again, so holding its subscription
        would leak one entry per completed job for the process lifetime."""
        job_id = _job(service, tmp_path)
        seen: list[str] = []
        service.set_event_sink(lambda _method, params: seen.append(params["snapshot"]["state"]))
        service.job_subscribe(job_id)
        for src, dst in (
            ("planned", "awaiting_review"),
            ("awaiting_review", "cancelled"),
        ):
            service.job_transition(JobTransitionParams(id=job_id, fromState=src, toState=dst))
        assert seen == ["awaiting_review", "cancelled"]
        assert job_id not in service._job_subscriptions

    def test_a_failing_sink_does_not_break_the_transition(
        self, service: ApplicationService, tmp_path: Path
    ) -> None:
        """An event is a courtesy to the UI. A closed pipe must not fail the
        operation that happened to trigger it."""

        def explode(_method: str, _params: dict) -> None:
            raise BrokenPipeError("renderer went away")

        service.set_event_sink(explode)
        job_id = _job(service, tmp_path)
        service.job_subscribe(job_id)
        updated = service.job_transition(
            JobTransitionParams(id=job_id, fromState="planned", toState="awaiting_review")
        )
        assert updated.state == "awaiting_review"


class TestSchedulerDrivenTransitions:
    def test_a_scheduler_transition_publishes(
        self, service: ApplicationService, tmp_path: Path
    ) -> None:
        """The path a real running job takes.

        The scheduler owns every transition during a run and publishes each
        one to its listeners; this is the subscription that was missing, so
        without it a job could go from running to needs_attention with the
        UI none the wiser.
        """
        seen: list[str] = []
        service.set_event_sink(lambda _m, params: seen.append(params["snapshot"]["state"]))
        job_id = _job(service, tmp_path)
        for src, dst in (
            ("planned", "awaiting_review"),
            ("awaiting_review", "queued"),
            ("queued", "running"),
        ):
            service.job_transition(JobTransitionParams(id=job_id, fromState=src, toState=dst))
        service.job_subscribe(job_id)
        seen.clear()

        # `recover` runs inside the scheduler, not through job_transition.
        assert job_id in service.job_recover()
        assert seen == ["needs_attention"]


class TestWiredServerEmitsFrames:
    def test_subscribe_then_transition_writes_an_event_frame(self, tmp_path: Path) -> None:
        """End to end over stdio: the wiring installs the sink, so a
        transition lands on stdout as a well-formed event frame."""
        service = ApplicationService(
            db_path=tmp_path / "wired.db",
            app_data_dir=tmp_path / "app",
            config_path=tmp_path / "config.toml",
        )
        service.bootstrap()
        try:
            job_id = _job(service, tmp_path)
            server = SidecarServer(db_path=Path(":memory:"))
            wire_server(server, service)

            def request(method: str, params: dict) -> str:
                return (
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "v": PROTOCOL_VERSION,
                            "kind": "request",
                            "id": "e-test",
                            "method": method,
                            "params": params,
                        }
                    )
                    + "\n"
                )

            out = io.StringIO()
            lines = request("job.subscribe", {"jobId": job_id}) + request(
                "job.transition",
                {"id": job_id, "fromState": "planned", "toState": "awaiting_review"},
            )
            # `run` emits sidecar.ready first, then processes both requests.
            server.run(io.StringIO(lines), out)

            frames = [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]
            events = [f for f in frames if f.get("kind") == "event"]
            job_events = [f for f in events if f["method"] == "job.updated"]
            assert len(job_events) == 1
            frame = job_events[0]
            assert frame["v"] == PROTOCOL_VERSION
            assert frame["params"]["jobId"] == job_id
            assert frame["params"]["snapshot"]["state"] == "awaiting_review"
        finally:
            service.close()

    def test_close_clears_subscriptions(self, tmp_path: Path) -> None:
        service = ApplicationService(
            db_path=tmp_path / "closed.db",
            app_data_dir=tmp_path / "app",
            config_path=tmp_path / "config.toml",
        )
        service.bootstrap()
        job_id = _job(service, tmp_path)
        service.job_subscribe(job_id)
        service.close()
        assert service._job_subscriptions == set()
