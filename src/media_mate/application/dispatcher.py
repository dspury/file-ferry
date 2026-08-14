"""Background job dispatcher for the sidecar.

Plan §5.1 / §6.4 require that queued jobs are picked up as soon as
their dependencies (a free volume slot, in particular) are
available. The :class:`JobScheduler` is a fire-once method; the
:class:`JobDispatcher` is the daemon thread that repeatedly calls it
on jobs that have moved into the ``queued`` state.

Why a thread
------------

The IPC handler thread must not block on long-running runners. A
daemon thread that wakes on ``job.create`` and on volume-slot frees
gives us ``job.dispatch`` semantics for every code path without
coupling dispatch to the renderer (CLI / TUI / plan-build / future
clients all benefit).

Lifecycle
---------

- Started by :meth:`ApplicationService.bootstrap`.
- Stopped by :meth:`ApplicationService.shutdown` (or on
  interpreter shutdown). The thread joins on ``stop()``.

Public surface
--------------

- :meth:`kick` -- wake the loop to re-scan the queue. Idempotent.
- :meth:`stop` -- request a clean shutdown and join.

The class is intentionally tiny: it owns a single Event, a Thread,
and one call to ``JobScheduler.dispatch`` per iteration.
"""

from __future__ import annotations

import logging
import threading

from media_mate.application.scheduler import JobScheduler
from media_mate.service.protocol import JobDetail

LOGGER = logging.getLogger(__name__)


class JobDispatcher:
    """Background loop that drains the queued jobs through the scheduler."""

    def __init__(self, scheduler: JobScheduler) -> None:
        self._scheduler = scheduler
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    # ---- lifecycle -------------------------------------------------

    def start(self) -> None:
        """Spawn the daemon thread. Safe to call multiple times."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._wake.set()
            self._thread = threading.Thread(
                target=self._run,
                name="media-mate-job-dispatcher",
                daemon=True,
            )
            self._thread.start()

    def stop(self, *, timeout: float = 5.0) -> None:
        """Request the loop to exit and join the thread."""
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
        self._thread = None

    def kick(self) -> None:
        """Wake the loop. Idempotent; cheap.

        Call this from anywhere a job might have become runnable --
        ``job.create``, ``job.recover``, ``job.resume``, or from the
        renderer's ``job.dispatch`` IPC method.
        """
        self._wake.set()

    # ---- loop -------------------------------------------------------

    def _run(self) -> None:
        LOGGER.debug("job dispatcher loop started")
        try:
            while not self._stop.is_set():
                # Block until kicked, then drain the queue. Each
                # dispatch is a single JobScheduler.dispatch call --
                # it runs one job synchronously and returns. A job
                # that needs a busy volume will come back unchanged,
                # and the next wakeup will retry it.
                self._wake.wait()
                self._wake.clear()
                if self._stop.is_set():
                    break
                self._dispatch_pending()
        except Exception:  # pragma: no cover - defensive
            LOGGER.exception("job dispatcher loop crashed")
        finally:
            LOGGER.debug("job dispatcher loop stopped")

    def _dispatch_pending(self) -> None:
        """Pull queued jobs through the scheduler until none remain."""
        # Snapshot queued jobs once per pass; dispatch attempts will
        # mutate rows, so do not iterate a live cursor.
        queued: list[JobDetail] = []
        for job in self._scheduler._jobs.list():
            if job.state == "queued":
                queued.append(job)
        for job in queued:
            if self._stop.is_set():
                return
            self._safe_dispatch(job.id)

    def _safe_dispatch(self, job_id: str) -> None:
        """Dispatch a single job, logging and swallowing any exception.

        Runners must handle their own state cleanly, but a misbehaving
        runner must not kill the dispatcher loop.
        """
        try:
            self._scheduler.dispatch(job_id)
        except Exception:  # pragma: no cover - defensive
            LOGGER.exception("dispatch failed for job %s", job_id)
