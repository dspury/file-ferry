"""Background job dispatcher — wake/sleep, drain, shutdown semantics."""

from __future__ import annotations

import threading
import time

from media_mate.application.dispatcher import JobDispatcher


class _StubJob:
    """Minimal object that looks like a queued ``JobDetail`` to the dispatcher."""

    def __init__(self, job_id: str) -> None:
        self.id = job_id
        self.state = "queued"


class _JobsServiceStub:
    """Stands in for :class:`media_mate.application.jobs.JobService`.

    The dispatcher reads ``scheduler._jobs.list()`` to find queued
    jobs and never calls any other method on it, so a one-method
    surface is enough.
    """

    def __init__(self) -> None:
        self._items: list[_StubJob] = []

    def queue(self, job_id: str) -> None:
        self._items.append(_StubJob(job_id))

    def list(self) -> list[_StubJob]:
        return list(self._items)


class _SchedulerStub:
    """Stands in for :class:`media_mate.application.scheduler.JobScheduler`.

    Exposes ``_jobs`` (the queue) and ``dispatch`` (the action).
    """

    def __init__(self) -> None:
        self._jobs = _JobsServiceStub()
        self.dispatched: list[str] = []

    def dispatch(self, job_id: str) -> object:
        self.dispatched.append(job_id)
        # Mark the dispatched job as "running" so a re-drain skips it.
        for obj in self._jobs._items:
            if obj.id == job_id:
                obj.state = "running"
        return None  # JobDetail would normally be returned


def _make_dispatcher(scheduler: _SchedulerStub) -> JobDispatcher:
    """Build a dispatcher without spinning the daemon thread.

    Useful for unit-testing the drain logic. The daemon thread is
    covered separately by ``test_dispatcher_is_a_daemon_thread``.
    """
    disp = JobDispatcher.__new__(JobDispatcher)
    disp._scheduler = scheduler  # type: ignore[attr-defined]
    disp._wake = threading.Event()  # type: ignore[attr-defined]
    disp._stop = threading.Event()  # type: ignore[attr-defined]
    disp._lock = threading.Lock()  # type: ignore[attr-defined]
    disp._thread = None  # type: ignore[attr-defined]
    return disp  # type: ignore[return-value]


def test_dispatcher_drains_queued_jobs() -> None:
    """A dispatch pass runs every queued job once."""
    scheduler = _SchedulerStub()
    scheduler._jobs.queue("j-1")
    scheduler._jobs.queue("j-2")
    disp = _make_dispatcher(scheduler)

    disp._dispatch_pending()  # type: ignore[attr-defined]
    assert sorted(scheduler.dispatched) == ["j-1", "j-2"], scheduler.dispatched


def test_dispatcher_skips_non_queued_jobs() -> None:
    """A job in any state other than ``queued`` is left alone."""
    scheduler = _SchedulerStub()
    queued = _StubJob("q-1")
    queued.state = "queued"
    running = _StubJob("r-1")
    running.state = "running"
    succeeded = _StubJob("s-1")
    succeeded.state = "succeeded"
    scheduler._jobs._items.extend([queued, running, succeeded])

    disp = _make_dispatcher(scheduler)
    disp._dispatch_pending()  # type: ignore[attr-defined]
    assert scheduler.dispatched == ["q-1"]


def test_dispatcher_kick_is_idempotent() -> None:
    """``kick`` is a cheap wake; calling it many times costs nothing."""
    scheduler = _SchedulerStub()
    disp = _make_dispatcher(scheduler)
    for _ in range(100):
        disp.kick()
    assert disp._wake.is_set()  # type: ignore[attr-defined]


def test_dispatcher_stop_breaks_the_loop() -> None:
    """The daemon thread exits cleanly when ``stop`` is called."""
    scheduler = _SchedulerStub()
    disp = JobDispatcher(scheduler=scheduler)  # type: ignore[arg-type]

    disp.start()
    time.sleep(0.05)
    disp.stop(timeout=1.0)
    assert disp._thread is None  # type: ignore[attr-defined]


def test_dispatcher_thread_is_daemon() -> None:
    """A daemon thread means a crashed process won't hang on the loop."""
    scheduler = _SchedulerStub()
    disp = JobDispatcher(scheduler=scheduler)  # type: ignore[arg-type]
    disp.start()
    try:
        thread = disp._thread  # type: ignore[attr-defined]
        assert thread is not None
        assert thread.daemon is True
    finally:
        disp.stop(timeout=1.0)


def test_application_service_starts_dispatcher_on_bootstrap(tmp_path) -> None:
    """``bootstrap`` wires the dispatcher and the shutdown path stops it."""
    from media_mate.application.service import ApplicationService

    svc = ApplicationService(
        db_path=tmp_path / "media-mate.db",
        app_data_dir=tmp_path / "app",
    )
    svc.bootstrap()
    try:
        dispatcher = svc.dispatcher()
        assert dispatcher is not None
        # The thread must be alive immediately after bootstrap -- the
        # loop is blocked on the wake event, so we just confirm start.
        assert dispatcher._thread is not None  # type: ignore[attr-defined]
    finally:
        svc.shutdown()

    # After shutdown, the dispatcher is gone and a follow-up kick
    # would be a clear no-op (but we won't invoke it -- the dispatcher
    # has been garbage-collected).
    assert svc._dispatcher is None  # type: ignore[attr-defined]
