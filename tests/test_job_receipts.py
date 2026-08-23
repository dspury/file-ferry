"""Offload and proxy runs write an operation receipt (issue #81).

The receipt machinery worked and was proven -- the project service has
written one on every create/update/archive since Package 2 -- but no job
runner ever called it. Nothing landed in ``operation_receipts`` keyed by
a job id, so ``receipt.export({operationId: job.id})``, which is what the
Activity screen's Receipt button calls, failed for every job ever run.

Plan §4.2 ends the offload flow at the receipt: it is the durable record
of what was copied and verified, and it is what makes a card safe to
format. These tests read it back the way the desktop does.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import NamedTuple

import pytest

from file_ferry.application.receipts import OperationReceipt, ReceiptStore, build_receipt
from file_ferry.application.service import ApplicationService
from file_ferry.service.protocol import (
    AddDestinationParams,
    CancelJobParams,
    CreateIntakeSessionParams,
    CreateJobParams,
    CreateProjectParams,
    ExportReceiptParams,
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

DESTINATIONS = 2


class Fixture(NamedTuple):
    service: ApplicationService
    job_id: str
    project_id: str
    session_id: str
    source: Path


def _setup(tmp_path: Path, files: dict[str, bytes], *, command: str = "offload") -> Fixture:
    """A project, a card, a session, and one queued job."""
    svc = ApplicationService(db_path=tmp_path / "ferry.db", app_data_dir=tmp_path / "app")
    svc.bootstrap()
    working = tmp_path / "proj" / "working"
    backup = tmp_path / "proj" / "backup"
    working.mkdir(parents=True)
    backup.mkdir(parents=True)
    pid = svc.create_project(
        CreateProjectParams(
            name="Receipts",
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
    # The background dispatcher drains the queue as soon as a job is
    # created; parking it keeps dispatch explicit and ordered here.
    assert svc._dispatcher is not None
    svc._dispatcher.stop()
    job = svc.job_create(CreateJobParams(projectId=pid, command=command, sessionId=session.id))
    for from_state, to_state in (("planned", "awaiting_review"), ("awaiting_review", "queued")):
        svc.job_transition(JobTransitionParams(id=job.id, fromState=from_state, toState=to_state))
    return Fixture(svc, job.id, pid, session.id, src)


def _receipt(svc: ApplicationService, job_id: str) -> dict[str, object]:
    return svc.receipt_get(job_id)


class TestASucceededOffload:
    def test_the_receipt_button_resolves(self, tmp_path: Path) -> None:
        """The reported symptom: `receipt.export` raised KeyError for every
        job, so the button in Activity failed 100% of the time."""
        fixture = _setup(tmp_path, {"A001.mov": b"media-content"})
        svc = fixture.service
        try:
            assert svc.job_dispatch(fixture.job_id).state == "succeeded"
            result = svc.receipt_export(
                ExportReceiptParams(operationId=fixture.job_id, format="markdown")
            )
            assert fixture.job_id in result.content
            assert result.content.strip()
        finally:
            svc.close()

    def test_it_records_every_planned_and_verified_replica(self, tmp_path: Path) -> None:
        fixture = _setup(tmp_path, {"A001.mov": b"a" * 512, "B002.mov": b"b" * 512})
        svc = fixture.service
        try:
            svc.job_dispatch(fixture.job_id)
            receipt = _receipt(svc, fixture.job_id)
            assert receipt["finalState"] == "succeeded"
            assert receipt["kind"] == "offload"
            # Two files to two destinations: four planned writes, four
            # verified replicas. `planned` against `actual` is what says
            # which replicas a partial run is missing.
            assert len(receipt["planned"]) == 2 * DESTINATIONS
            assert len(receipt["actual"]) == 2 * DESTINATIONS
            assert all(row["verified"] for row in receipt["actual"])
            assert not receipt["errors"]
        finally:
            svc.close()

    def test_it_carries_the_checksums_and_the_policy(self, tmp_path: Path) -> None:
        """A receipt is the evidence the copy was verified; without the
        checksums and the policy it was judged against, it is only a claim."""
        fixture = _setup(tmp_path, {"A001.mov": b"media-content"})
        svc = fixture.service
        try:
            svc.job_dispatch(fixture.job_id)
            receipt = _receipt(svc, fixture.job_id)
            checksums = receipt["checksums"]
            assert len(checksums) == DESTINATIONS
            for row in checksums:
                assert row["algo"] == "xxhash64"
                # Verified means the replica matched its source.
                assert row["sourceChecksum"] == row["replicaChecksum"]
            policy = receipt["policy"]
            assert policy is not None
            assert policy["requiredReplicas"] == 2
        finally:
            svc.close()


class TestAnInterruptedOffload:
    @pytest.mark.skipif(
        hasattr(os, "geteuid") and os.geteuid() == 0,
        reason="root ignores file permissions, so the copy would not fail",
    )
    def test_a_failure_still_writes_one_and_says_why(self, tmp_path: Path) -> None:
        """The docstring on the offload module has always promised that
        "the receipt explains the partial state". Nothing wrote it."""
        fixture = _setup(tmp_path, {"A001.mov": b"media-content"})
        svc = fixture.service
        try:
            source = fixture.source / "A001.mov"
            source.chmod(0o000)
            try:
                assert svc.job_dispatch(fixture.job_id).state == "failed"
            finally:
                source.chmod(0o600)
            receipt = _receipt(svc, fixture.job_id)
            assert receipt["finalState"] == "failed"
            errors = receipt["errors"]
            assert errors, "a failed run must record why it stopped"
            assert any("transfer" in e for e in errors)
        finally:
            svc.close()

    @pytest.mark.skipif(
        hasattr(os, "geteuid") and os.geteuid() == 0,
        reason="root ignores file permissions, so the copy would not fail",
    )
    def test_it_names_the_replicas_that_did_verify(self, tmp_path: Path) -> None:
        """The point of a partial receipt. The first file replicates to both
        destinations, then the second is unreadable -- and the operator needs
        to know the first one is safely down before formatting anything."""
        fixture = _setup(tmp_path, {"A001.mov": b"a" * 512, "B002.mov": b"b" * 512})
        svc = fixture.service
        try:
            # Files are processed in plan order; make the *second* one fail so
            # there is completed work to report.
            entries = sorted(p.name for p in fixture.source.iterdir())
            doomed = fixture.source / entries[-1]
            doomed.chmod(0o000)
            try:
                assert svc.job_dispatch(fixture.job_id).state == "failed"
            finally:
                doomed.chmod(0o600)
            receipt = _receipt(svc, fixture.job_id)
            assert receipt["finalState"] == "failed"
            # Everything was planned; only the readable file landed.
            assert len(receipt["planned"]) == 2 * DESTINATIONS
            verified = [row for row in receipt["actual"] if row["verified"]]
            assert len(verified) == DESTINATIONS
            assert all(entries[0] in row["relPath"] for row in verified)
        finally:
            svc.close()

    def test_a_cancelled_run_writes_one_too(self, tmp_path: Path) -> None:
        fixture = _setup(tmp_path, {"A001.mov": b"media-content"})
        svc = fixture.service
        try:
            svc.job_cancel(CancelJobParams(id=fixture.job_id))
            assert svc.job_dispatch(fixture.job_id).state == "cancelled"
            receipt = _receipt(svc, fixture.job_id)
            assert receipt["finalState"] == "cancelled"
            # A deliberate stop is not a failure, so it is filed as a warning
            # and the replicas that did land are not tainted by an error.
            assert not receipt["errors"]
            assert any("cancelled" in w for w in receipt["warnings"])
        finally:
            svc.close()


class TestResumeSupersedesTheEarlierReceipt:
    """`operation_receipts` is UNIQUE(operation_id, kind), and job receipts
    are keyed by the job id -- which `resume` puts through the runner a
    second time. A plain INSERT raises IntegrityError on that second run.

    The sequence is the one `recover` exists for: the runner finishes and
    writes its receipt, the process dies before the job can be transitioned
    out of `running`, and on restart the job is recovered to
    `needs_attention` for the operator to resume. Running the runner
    directly is how that crash is reproduced without killing the process.
    """

    def _crash_after_one_run(self, fixture: Fixture) -> None:
        svc = fixture.service
        svc.job_transition(
            JobTransitionParams(id=fixture.job_id, fromState="queued", toState="running")
        )
        runner = svc._scheduler_service()._runners["offload"]
        assert runner(svc.job_get(fixture.job_id), svc._scheduler_service()) == "succeeded"
        # The job is still `running`: nothing recorded the outcome, which is
        # exactly what a crash at this moment looks like from the database.
        assert svc.job_recover() == [fixture.job_id]
        assert svc.job_get(fixture.job_id).state == "needs_attention"

    def test_a_second_run_of_one_job_id_does_not_collide(self, tmp_path: Path) -> None:
        fixture = _setup(tmp_path, {"A001.mov": b"media-content"})
        svc = fixture.service
        try:
            self._crash_after_one_run(fixture)
            assert svc.job_resume(fixture.job_id).state == "succeeded"
            receipt = _receipt(svc, fixture.job_id)
            assert receipt["finalState"] == "succeeded"
            # The superseded attempt is not silently forgotten.
            assert any("supersedes receipt" in w for w in receipt["warnings"])
        finally:
            svc.close()

    def test_only_one_row_survives_per_kind(self, tmp_path: Path) -> None:
        fixture = _setup(tmp_path, {"A001.mov": b"media-content"})
        svc = fixture.service
        try:
            self._crash_after_one_run(fixture)
            svc.job_resume(fixture.job_id)
            with sqlite3.connect(tmp_path / "ferry.db") as conn:
                rows = conn.execute(
                    "SELECT receipt_json FROM operation_receipts WHERE operation_id = ?",
                    (fixture.job_id,),
                ).fetchall()
            assert len(rows) == 1
            # And it is the *later* attempt that survived. Asserting only the
            # count would also pass if the second write had been dropped --
            # which is exactly what a failed INSERT looks like from here,
            # since a receipt failure is deliberately not allowed to raise.
            assert any("supersedes receipt" in w for w in json.loads(rows[0][0])["warnings"])
        finally:
            svc.close()


class TestTheReceiptIsNeverLoadBearing:
    def test_a_writer_that_raises_does_not_fail_the_transfer(self, tmp_path: Path) -> None:
        """A verified copy must not be undone by a failure to write the
        paperwork about it."""
        fixture = _setup(tmp_path, {"A001.mov": b"media-content"})
        svc = fixture.service
        try:

            def explode(_receipt: OperationReceipt) -> None:
                raise RuntimeError("disk full")

            runner = svc._scheduler_service()._runners["offload"]
            runner._receipt_writer = explode  # type: ignore[attr-defined]
            assert svc.job_dispatch(fixture.job_id).state == "succeeded"
        finally:
            svc.close()


class TestProxyRuns:
    def test_a_proxy_run_writes_its_own_receipt(self, tmp_path: Path) -> None:
        fixture = _setup(tmp_path, {"A001.mov": b"media-content"}, command="offload")
        svc = fixture.service
        try:
            svc.job_dispatch(fixture.job_id)
            # The proxy job runs over the same session, so it shares nothing
            # with the offload's receipt but the session -- including the
            # `kind` half of the receipts table's unique key.
            proxy_job = svc.job_create(
                CreateJobParams(
                    projectId=fixture.project_id, command="proxy", sessionId=fixture.session_id
                )
            )
            for from_state, to_state in (
                ("planned", "awaiting_review"),
                ("awaiting_review", "queued"),
            ):
                svc.job_transition(
                    JobTransitionParams(id=proxy_job.id, fromState=from_state, toState=to_state)
                )
            proxy_runner = svc._scheduler_service()._runners["proxy"]
            proxy_runner._proxy_fn = lambda _src, out: Path(out).write_bytes(b"proxy")  # type: ignore[attr-defined]
            assert svc.job_dispatch(proxy_job.id).state == "succeeded"
            receipt = _receipt(svc, proxy_job.id)
            assert receipt["kind"] == "proxy"
            assert receipt["finalState"] == "succeeded"
            assert len(receipt["actual"]) == 1
        finally:
            svc.close()


class TestReceiptStoreReplace:
    def _store(self, tmp_path: Path) -> tuple[ReceiptStore, Path]:
        db = tmp_path / "ferry.db"
        svc = ApplicationService(db_path=db, app_data_dir=tmp_path / "app")
        svc.bootstrap()
        svc.close()
        return ReceiptStore(tmp_path / "app"), db

    def _receipt(self, final_state: str) -> OperationReceipt:
        return build_receipt(
            operation_id="op-1",
            kind="offload",
            app_version="0.3.0",
            protocol_version=1,
            final_state=final_state,
        )

    def test_a_duplicate_insert_still_raises_without_replace(self, tmp_path: Path) -> None:
        """Project receipts carry a fresh uuid4, so a collision there means
        something is wrong and the constraint should still bite."""
        store, db = self._store(tmp_path)
        from file_ferry.persistence.connection import transaction

        with transaction(db) as conn:
            store.write(conn, self._receipt("created"))
        with pytest.raises(sqlite3.IntegrityError), transaction(db) as conn:
            store.write(conn, self._receipt("created"))

    def test_replace_supersedes_and_prior_hash_reports_it(self, tmp_path: Path) -> None:
        store, db = self._store(tmp_path)
        from file_ferry.persistence.connection import transaction

        first = self._receipt("failed")
        with transaction(db) as conn:
            store.write(conn, first, replace=True)
        with transaction(db) as conn:
            assert store.prior_hash(conn, "op-1", "offload") == first.receipt_hash()
            store.write(conn, self._receipt("succeeded"), replace=True)
        with transaction(db) as conn:
            row = conn.execute(
                "SELECT receipt_json FROM operation_receipts WHERE operation_id = 'op-1'"
            ).fetchone()
        assert json.loads(row["receipt_json"])["finalState"] == "succeeded"

    def test_prior_hash_is_none_when_nothing_is_there(self, tmp_path: Path) -> None:
        store, db = self._store(tmp_path)
        from file_ferry.persistence.connection import transaction

        with transaction(db) as conn:
            assert store.prior_hash(conn, "op-missing", "offload") is None
