"""A job runner writes an operation receipt (issue #81).

The receipt machinery worked and was proven -- the project service has written
one on every create/update/archive since Package 2 -- but no job runner ever
called it. Nothing landed in ``operation_receipts`` keyed by a job id, so
``receipt.export({operationId: job.id})``, which is what the Activity screen's
Receipt button calls, failed for every job ever run.

The original vehicle for these tests was the **offload** runner. That runner
was withdrawn in B-6 (a camera card is a source type inside the Transfer
workspace now), so the generic coverage rides on the **proxy** runner, which
is still a shipped runner over the same session, and on the transfer e2e
suite for the durable path. The receipt *store* semantics -- one row per
(operation, kind), replace/supersede -- are pinned directly below.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import NamedTuple

import pytest

from file_ferry.application.receipts import OperationReceipt, ReceiptStore, build_receipt
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
    source: Path


def _setup(tmp_path: Path, files: dict[str, bytes]) -> Fixture:
    """A project, a card, and a session to hang a runner job off."""
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
    return Fixture(svc, pid, session.id, src)


def _queue(svc: ApplicationService, job_id: str) -> None:
    for from_state, to_state in (("planned", "awaiting_review"), ("awaiting_review", "queued")):
        svc.job_transition(JobTransitionParams(id=job_id, fromState=from_state, toState=to_state))


def _receipt(svc: ApplicationService, job_id: str) -> dict[str, object]:
    return svc.receipt_get(job_id)


class TestProxyRuns:
    def _proxy_job(self, fixture: Fixture) -> str:
        job = fixture.service.job_create(
            CreateJobParams(projectId=fixture.project_id, command="proxy", sessionId=fixture.session_id)
        )
        _queue(fixture.service, job.id)
        return job.id

    def test_a_proxy_run_writes_its_own_receipt(self, tmp_path: Path) -> None:
        fixture = _setup(tmp_path, {"A001.mov": b"media-content"})
        svc = fixture.service
        try:
            job_id = self._proxy_job(fixture)
            # A proxy job runs over the same session, so it shares nothing
            # with any other job's receipt but the session -- including the
            # `kind` half of the receipts table's unique key.
            proxy_runner = svc._scheduler_service()._runners["proxy"]
            proxy_runner._proxy_fn = lambda _src, out: Path(out).write_bytes(b"proxy")  # type: ignore[attr-defined]
            assert svc.job_dispatch(job_id).state == "succeeded"
            receipt = _receipt(svc, job_id)
            assert receipt["kind"] == "proxy"
            assert receipt["finalState"] == "succeeded"
            assert len(receipt["actual"]) == 1
        finally:
            svc.close()

    def test_a_raising_receipt_writer_does_not_fail_the_run(self, tmp_path: Path) -> None:
        """A verified copy must not be undone by a failure to write the
        paperwork about it."""
        fixture = _setup(tmp_path, {"A001.mov": b"media-content"})
        svc = fixture.service
        try:
            job_id = self._proxy_job(fixture)
            proxy_runner = svc._scheduler_service()._runners["proxy"]
            proxy_runner._proxy_fn = lambda _src, out: Path(out).write_bytes(b"proxy")  # type: ignore[attr-defined]

            def explode(_receipt: OperationReceipt) -> None:
                raise RuntimeError("disk full")

            proxy_runner._receipt_writer = explode  # type: ignore[attr-defined]
            assert svc.job_dispatch(job_id).state == "succeeded"
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
