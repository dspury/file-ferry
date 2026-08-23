"""Progress reporting for the offload and proxy runners.

Both runners had the same shape of defect. The offload runner recorded
per-file *items* but never any *steps*, and wrote a hardcoded
``byte_progress=1`` on success while discarding the byte count
``copy_file_atomic`` returns — so a snapshot reported one byte copied per
file regardless of size. The proxy runner called ``update_item_progress``
for items it had never inserted, so every update matched zero rows and was
swallowed by a bare ``suppress(Exception)``.

These tests read the snapshot the desktop actually consumes.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import NamedTuple

import pytest

from file_ferry.application.offload import copy_file_atomic
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

# Two destinations are configured throughout, because the interesting
# arithmetic is that one source file is copied twice.
DESTINATIONS = 2


class Fixture(NamedTuple):
    service: ApplicationService
    job_id: str
    project_id: str
    session_id: str
    backup: Path


def _setup(tmp_path: Path, files: dict[str, bytes]) -> Fixture:
    """Build a project, card, session, and a queued offload job."""
    svc = ApplicationService(db_path=tmp_path / "ferry.db", app_data_dir=tmp_path / "app")
    svc.bootstrap()
    working = tmp_path / "proj" / "working"
    backup = tmp_path / "proj" / "backup"
    working.mkdir(parents=True)
    backup.mkdir(parents=True)
    pid = svc.create_project(
        CreateProjectParams(
            name="Progress",
            workingRoot=str(working),
            backupRoot=str(backup),
            storagePolicy=SAME_VOLUME_POLICY,
            acknowledgeWeaker=True,
        )
    )
    src = tmp_path / "card" / "DCIM"
    src.mkdir(parents=True)
    for name, content in files.items():
        (src / name).write_bytes(content)
    inspected = svc.source_inspect(SourceInspectParams(path=str(tmp_path / "card"), kind="card"))
    session = svc.intake_create_session(
        CreateIntakeSessionParams(projectId=pid, sourceId=inspected.source_id, kind="offload")
    )
    for kind, root in (("working", working), ("backup", backup)):
        svc.intake_add_destination(
            AddDestinationParams(intakeSessionId=session.id, kind=kind, rootPath=str(root))
        )
    svc.intake_adopt_source(session.id, inspected.source_id, inspected.entries, str(working))
    # Park the background dispatcher thread before queueing anything. It
    # wakes on `job.create` and drains whatever is queued, so a job left
    # queued races the test: the run can finish before the test has installed
    # its event sink, and these tests assert on the events. Only the thread is
    # stopped -- `shutdown()` would tear down the whole service -- so
    # dispatch here is explicit and ordered.
    assert svc._dispatcher is not None
    svc._dispatcher.stop()
    job = svc.job_create(
        CreateJobParams(
            projectId=pid, command="offload", sessionId=session.id, totalSteps=len(files)
        )
    )
    for src_state, dst_state in (("planned", "awaiting_review"), ("awaiting_review", "queued")):
        svc.job_transition(JobTransitionParams(id=job.id, fromState=src_state, toState=dst_state))
    return Fixture(svc, job.id, pid, session.id, backup)


class TestCopyProgressCallback:
    def test_reports_the_running_total(self, tmp_path: Path) -> None:
        src = tmp_path / "src.bin"
        src.write_bytes(b"x" * (3 * 1024 * 1024))
        seen: list[int] = []
        copied = copy_file_atomic(src, tmp_path / "out.bin", on_progress=seen.append)
        assert copied == 3 * 1024 * 1024
        # One call per 1 MiB chunk, monotonically increasing, ending at the
        # full size -- the caller can trust the last value as the total.
        assert seen == [1024 * 1024, 2 * 1024 * 1024, 3 * 1024 * 1024]

    def test_is_optional(self, tmp_path: Path) -> None:
        src = tmp_path / "src.bin"
        src.write_bytes(b"hello")
        assert copy_file_atomic(src, tmp_path / "out.bin") == 5


class TestOffloadRecordsSteps:
    def test_a_finished_offload_reports_its_steps(self, tmp_path: Path) -> None:
        fixture = _setup(tmp_path, {"A001.mov": b"media-content"})
        svc, job_id = fixture.service, fixture.job_id
        try:
            assert svc.job_dispatch(job_id).state == "succeeded"
            snapshot = svc.job_snapshot(job_id)
            assert snapshot.completed_steps == ["plan", "transfer"]
            # `totalSteps` counts steps, so it stays commensurable with
            # `completedSteps` rather than being the job's file count.
            assert snapshot.total_steps == 2
        finally:
            svc.close()

    @pytest.mark.skipif(
        hasattr(os, "geteuid") and os.geteuid() == 0,
        reason="root ignores file permissions, so the copy would not fail",
    )
    def test_a_failed_transfer_names_the_step_that_failed(self, tmp_path: Path) -> None:
        """Without this the scheduler records only that the job failed, and
        neither the receipt nor the UI can say which phase gave up."""
        svc, job_id, _pid, _sid, _backup = _setup(tmp_path, {"A001.mov": b"media-content"})
        try:
            # An unreadable source still plans fine -- the planner needs the
            # directory and the file size, not the contents -- so the failure
            # lands in `transfer`, which is the case under test. (An
            # unwritable *destination* fails earlier, during planning.)
            source = tmp_path / "card" / "DCIM" / "A001.mov"
            source.chmod(0o000)
            try:
                assert svc.job_dispatch(job_id).state == "failed"
            finally:
                source.chmod(0o600)
            snapshot = svc.job_snapshot(job_id)
            assert snapshot.completed_steps == ["plan"]
        finally:
            svc.close()


class TestOffloadRecordsBytes:
    def test_totals_account_for_every_destination(self, tmp_path: Path) -> None:
        """One source file written to a working root *and* a backup is two
        copies of work, so it is only complete when both are done."""
        content = b"x" * 4096
        fixture = _setup(tmp_path, {"A001.mov": content})
        svc, job_id = fixture.service, fixture.job_id
        try:
            svc.job_dispatch(job_id)
            snapshot = svc.job_snapshot(job_id)
            assert snapshot.total_items == 1
            assert snapshot.completed_items == 1
            assert snapshot.total_bytes == len(content) * DESTINATIONS
            assert snapshot.bytes_copied == len(content) * DESTINATIONS
        finally:
            svc.close()

    def test_byte_counts_are_real_not_a_placeholder(self, tmp_path: Path) -> None:
        # The old code wrote byte_progress=1 on success, so any card of any
        # size reported one byte per file.
        fixture = _setup(tmp_path, {"A.mov": b"a" * 1000, "B.mov": b"b" * 3000})
        svc, job_id = fixture.service, fixture.job_id
        try:
            svc.job_dispatch(job_id)
            snapshot = svc.job_snapshot(job_id)
            assert snapshot.total_items == 2
            assert snapshot.bytes_copied == (1000 + 3000) * DESTINATIONS
        finally:
            svc.close()

    def test_progress_is_published_during_the_run(self, tmp_path: Path) -> None:
        """The point of the whole change: a long copy has to emit while it
        runs, not only when it changes state."""
        fixture = _setup(tmp_path, {"A.mov": b"a" * 512, "B.mov": b"b" * 512})
        svc, job_id = fixture.service, fixture.job_id
        try:
            svc.job_subscribe(job_id)
            seen: list[tuple[int, int]] = []
            svc.set_event_sink(
                lambda _m, params: seen.append(
                    (params["snapshot"]["completedItems"], params["snapshot"]["bytesCopied"])
                )
            )
            svc.job_dispatch(job_id)
            # Transitions alone would give running/verifying/succeeded with a
            # flat 0 items; the per-item notifications are what make the
            # count climb.
            assert [items for items, _ in seen] == sorted(items for items, _ in seen)
            assert max(items for items, _ in seen) == 2
            assert max(byte_count for _, byte_count in seen) == 512 * 2 * DESTINATIONS
        finally:
            svc.close()

    def test_a_large_file_reports_progress_before_it_finishes(self, tmp_path: Path) -> None:
        """A single 60 GB clip must not sit at 0% for its whole copy, so
        progress is flushed mid-file once enough bytes have been written."""
        # Comfortably over the 16 MiB flush threshold.
        fixture = _setup(tmp_path, {"BIG.mov": b"x" * (40 * 1024 * 1024)})
        svc, job_id = fixture.service, fixture.job_id
        try:
            svc.job_subscribe(job_id)
            seen: list[int] = []
            svc.set_event_sink(lambda _m, params: seen.append(params["snapshot"]["bytesCopied"]))
            svc.job_dispatch(job_id)
            total = 40 * 1024 * 1024 * DESTINATIONS
            partials = [b for b in seen if 0 < b < total]
            assert partials, "expected at least one mid-file progress event"
        finally:
            svc.close()


class TestProxyRunnerRecordsItems:
    def test_items_exist_so_updates_are_not_no_ops(self, tmp_path: Path) -> None:
        """`update_item_progress` on a row that was never inserted matches
        nothing and raises nothing, so this went unnoticed."""
        svc, _job, project_id, session_id, _backup = _setup(
            tmp_path, {"A001.mov": b"media-content"}
        )
        try:
            proxy_job = svc.job_create(
                CreateJobParams(
                    projectId=project_id, command="proxy", sessionId=session_id, totalSteps=1
                )
            )
            for src_state, dst_state in (
                ("planned", "awaiting_review"),
                ("awaiting_review", "queued"),
            ):
                svc.job_transition(
                    JobTransitionParams(id=proxy_job.id, fromState=src_state, toState=dst_state)
                )
            svc.job_dispatch(proxy_job.id)
            snapshot = svc.job_snapshot(proxy_job.id)
            assert snapshot.total_items == 1
        finally:
            svc.close()
