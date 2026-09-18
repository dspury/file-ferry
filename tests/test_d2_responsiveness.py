"""D-2 §12.2 — the responsiveness assertions that are automatable locally.

The physical gates need drives, a network share and cable-pulling, and are
NOT RUN here. What §12.2 says must stay responsive can be checked on a local
disk, and is:

- job creation returns without waiting for the copy;
- a cancel request is acknowledged within two seconds under normal local
  conditions;
- large plan pages are bounded, so the whole plan never reaches the renderer;
- 100,000-entry synthetic planning, which is opt-in (``pytest -m slow``) and
  reports time and peak memory rather than asserting a hardware bound.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from file_ferry.application.service import ApplicationService
from file_ferry.application.transfer_runner import peak_rss_bytes
from file_ferry.service.protocol import (
    CancelJobParams,
    CreateJobParams,
    InventoryCreateParams,
    InventoryEntriesParams,
    InventoryStatusParams,
    PlanCreateParams,
    PlanEntriesParams,
    SaveDestinationParams,
)


def _service(tmp_path: Path) -> ApplicationService:
    svc = ApplicationService(db_path=tmp_path / "ferry.db", app_data_dir=tmp_path / "app")
    svc.bootstrap()
    return svc


def _wait_inventory(svc: ApplicationService, inventory_id: int, timeout: float = 300.0) -> None:
    deadline = time.monotonic() + timeout
    while True:
        status = svc.inventory_status(InventoryStatusParams(id=inventory_id))
        if status.status != "scanning":
            assert status.status == "complete", status.error
            return
        assert time.monotonic() < deadline, "inventory scan did not finish in time"
        time.sleep(0.05)


def test_job_creation_returns_without_waiting_for_the_copy(tmp_path: Path) -> None:
    """`job.create` queues and returns; the dispatcher does the copying."""
    svc = _service(tmp_path)
    entered = threading.Event()
    release = threading.Event()

    def slow_runner(job: object, scheduler: object) -> str:
        entered.set()
        assert release.wait(timeout=10), "the test never released the runner"
        return "succeeded"

    try:
        svc.scheduler().register_runner("copy", slow_runner)
        started = time.monotonic()
        job = svc.job_create(CreateJobParams(command="copy", reviewed=True))
        elapsed = time.monotonic() - started
        assert elapsed < 1.0, f"job.create blocked for {elapsed:.3f}s"
        # The copy is genuinely in flight, not skipped: the dispatcher entered
        # the runner, and create had already returned while it was blocked.
        assert entered.wait(timeout=5), "the background dispatcher never started the copy"
        assert svc.job_get(job.id).state in {"queued", "running"}
    finally:
        release.set()
        svc.shutdown()


def test_cancel_request_is_acknowledged_within_two_seconds(tmp_path: Path) -> None:
    """Cancel is acknowledged immediately; the runner stops at a safe boundary."""
    svc = _service(tmp_path)
    entered = threading.Event()
    release = threading.Event()

    def slow_runner(job: object, scheduler: object) -> str:
        entered.set()
        assert release.wait(timeout=10), "the test never released the runner"
        return "succeeded"

    try:
        svc.scheduler().register_runner("copy", slow_runner)
        job = svc.job_create(CreateJobParams(command="copy", reviewed=True))
        assert entered.wait(timeout=5), "the job never started"
        started = time.monotonic()
        svc.job_cancel(CancelJobParams(id=job.id))
        elapsed = time.monotonic() - started
        assert elapsed < 2.0, f"cancel acknowledged after {elapsed:.3f}s"
        assert svc.scheduler().should_cancel(job.id)
    finally:
        release.set()
        svc.shutdown()


def test_plan_and_inventory_pages_are_hard_capped() -> None:
    """A caller cannot ask for the whole plan in one response."""
    with pytest.raises(ValidationError):
        PlanEntriesParams(id="p", limit=100_000)
    with pytest.raises(ValidationError):
        InventoryEntriesParams(id=1, limit=100_000)
    assert PlanEntriesParams(id="p").limit <= 1000
    assert InventoryEntriesParams(id=1).limit <= 1000


@pytest.mark.slow
def test_100k_entry_planning_is_bounded(tmp_path: Path) -> None:
    """100,000 synthetic entries: bounded pages, measured time and peak RSS.

    §12.2 asks for this to expose memory/IPC growth, not to hit a throughput
    number. The assertion is the bound — no response carries the whole plan —
    and the measurements are printed for the D-2 record.
    """
    dirs, per_dir = 100, 1000
    root = tmp_path / "source"
    for d in range(dirs):
        sub = root / f"d{d:03d}"
        sub.mkdir(parents=True)
        for f in range(per_dir):
            (sub / f"f{f:04d}.bin").touch()

    svc = _service(tmp_path)
    try:
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        dest = svc.destination_save(SaveDestinationParams(name="D2 synthetic", path=str(dest_dir)))
        inv = svc.inventory_create(InventoryCreateParams(path=str(root), label="D2 synthetic"))
        _wait_inventory(svc, inv.inventory_id)
        scanned = svc.inventory_status(InventoryStatusParams(id=inv.inventory_id))
        assert scanned.file_count == dirs * per_dir

        rss_before = peak_rss_bytes()
        started = time.monotonic()
        plan = svc.transfer_plan_create(
            PlanCreateParams.model_validate(
                {"destinationId": dest.id, "inventoryIds": [inv.inventory_id]}
            )
        )
        plan_seconds = time.monotonic() - started
        rss_after = peak_rss_bytes()

        first = svc.transfer_plan_entries(PlanEntriesParams(id=plan.id, limit=1000))
        assert len(first.entries) <= 1000
        assert first.total == dirs * per_dir
        second = svc.transfer_plan_entries(
            PlanEntriesParams(id=plan.id, limit=1000, after=first.entries[-1].id)
        )
        assert len(second.entries) == 1000
        assert second.entries[0].id > first.entries[-1].id

        rss_delta = None if rss_before is None or rss_after is None else rss_after - rss_before
        print(
            f"\n[d2] 100k-entry planning: files={scanned.file_count} "
            f"plan_seconds={plan_seconds:.2f} "
            f"peak_rss_before={rss_before} peak_rss_after={rss_after} delta={rss_delta} "
            f"page_cap={len(first.entries)}"
        )
        assert plan_seconds < 300.0, f"planning took {plan_seconds:.1f}s"
    finally:
        svc.shutdown()
