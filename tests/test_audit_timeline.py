"""The audit timeline is actually written by the vNext lifecycle (#118).

Before this, `audit_events` had exactly two writers -- `reconcile.acceptChange`
and the legacy `runs` backfill -- so a database with four succeeded offloads,
five intake sessions and five receipts in it had **zero** events. These tests
pin the events to the state changes that produce them, and pin the granularity
decision (operations and transitions, not files) that keeps the trail readable.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from file_ferry.application.audit import AuditService, record_event
from file_ferry.application.jobs import JobService
from file_ferry.application.replicas import ReplicaService
from file_ferry.persistence.connection import transaction
from file_ferry.service.protocol import (
    CreateJobParams,
    JobTransitionParams,
    ListAuditParams,
)


@pytest.fixture
def db(tmp_path: Path) -> Path:
    from file_ferry.application.service import ApplicationService

    path = tmp_path / "ferry.db"
    boot = ApplicationService(db_path=path, app_data_dir=tmp_path / "app")
    boot.bootstrap()
    boot.close()
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            INSERT INTO projects
                (id, name, status, working_root, storage_policy, created_at, updated_at)
            VALUES ('proj-1', 'proj-1', 'active', '/tmp', '{}', 'now', 'now')
            """
        )
        conn.commit()
    return path


def _events(db: Path, *, entity_id: str | None = None) -> list[sqlite3.Row]:
    """Timeline in the order it happened (the repo's list() is newest-first)."""
    with transaction(db) as conn:
        if entity_id is None:
            rows = conn.execute("SELECT * FROM audit_events ORDER BY id ASC").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM audit_events WHERE entity_id = ? ORDER BY id ASC",
                (entity_id,),
            ).fetchall()
    return list(rows)


def _types(db: Path, *, entity_id: str | None = None) -> list[str]:
    return [r["event_type"] for r in _events(db, entity_id=entity_id)]


# ---------------------------------------------------------------------------
# record_event: transactional by construction
# ---------------------------------------------------------------------------


def test_record_event_writes_on_the_callers_connection(db: Path) -> None:
    with transaction(db) as conn:
        record_event(
            conn,
            "test.thing",
            entity_type="widget",
            entity_id="w-1",
            data={"b": 2, "a": 1},
        )
    rows = _events(db)
    assert len(rows) == 1
    assert rows[0]["event_type"] == "test.thing"
    assert rows[0]["entity_type"] == "widget"
    assert rows[0]["entity_id"] == "w-1"
    # Sorted keys, so two events describing the same facts are byte-identical.
    assert rows[0]["data"] == '{"a": 1, "b": 2}'


def test_an_event_rolls_back_with_the_change_it_describes(db: Path) -> None:
    """The trail cannot claim something that did not commit."""
    with pytest.raises(RuntimeError), transaction(db) as conn:
        record_event(conn, "test.thing", entity_id="w-1")
        raise RuntimeError("the state change failed")
    assert _events(db) == []


def test_record_without_a_connection_opens_its_own_transaction(db: Path) -> None:
    AuditService(db).record("test.standalone", entity_type="widget", entity_id="w-2")
    assert _types(db) == ["test.standalone"]


def test_data_is_omitted_rather_than_stored_as_null_string(db: Path) -> None:
    with transaction(db) as conn:
        record_event(conn, "test.bare")
    assert _events(db)[0]["data"] is None


# ---------------------------------------------------------------------------
# The job lifecycle spine
# ---------------------------------------------------------------------------


def test_creating_a_job_records_it(db: Path) -> None:
    job = JobService(db).create(
        CreateJobParams(projectId="proj-1", command="offload", totalSteps=3)
    )
    rows = _events(db, entity_id=job.id)
    assert [r["event_type"] for r in rows] == ["job.created"]
    assert rows[0]["entity_type"] == "job"
    data = json.loads(rows[0]["data"])
    assert data["command"] == "offload"
    assert data["project_id"] == "proj-1"
    assert data["state"] == "planned"
    assert data["total_steps"] == 3


def test_every_transition_is_recorded_in_order(db: Path) -> None:
    """One offload's worth of lifecycle, end to end.

    `JobService.transition` is the only place job state changes -- the
    scheduler, the dispatcher and the `job.transition` IPC call all reach it
    -- so this sequence is what any real run produces.
    """
    svc = JobService(db)
    job = svc.create(CreateJobParams(projectId="proj-1", command="offload"))
    for frm, to in [
        ("planned", "awaiting_review"),
        ("awaiting_review", "queued"),
        ("queued", "running"),
        ("running", "verifying"),
        ("verifying", "succeeded"),
    ]:
        svc.transition(JobTransitionParams(id=job.id, fromState=frm, toState=to))

    assert _types(db, entity_id=job.id) == [
        "job.created",
        "job.awaiting_review",
        "job.queued",
        "job.running",
        "job.verifying",
        "job.succeeded",
    ]


def test_a_transition_event_names_both_states(db: Path) -> None:
    svc = JobService(db)
    job = svc.create(CreateJobParams(projectId="proj-1", command="offload"))
    svc.transition(JobTransitionParams(id=job.id, fromState="planned", toState="awaiting_review"))
    data = json.loads(_events(db, entity_id=job.id)[-1]["data"])
    assert data["from_state"] == "planned"
    assert data["to_state"] == "awaiting_review"
    assert data["command"] == "offload"
    assert data["project_id"] == "proj-1"


def test_failure_and_cancellation_are_on_the_timeline(db: Path) -> None:
    svc = JobService(db)
    failed = svc.create(CreateJobParams(projectId="proj-1", command="offload"))
    for frm, to in [
        ("planned", "awaiting_review"),
        ("awaiting_review", "queued"),
        ("queued", "running"),
        ("running", "verifying"),
        ("verifying", "failed"),
    ]:
        svc.transition(JobTransitionParams(id=failed.id, fromState=frm, toState=to))
    assert _types(db, entity_id=failed.id)[-1] == "job.failed"

    cancelled = svc.create(CreateJobParams(projectId="proj-1", command="offload"))
    svc.transition(
        JobTransitionParams(id=cancelled.id, fromState="planned", toState="awaiting_review")
    )
    svc.transition(
        JobTransitionParams(id=cancelled.id, fromState="awaiting_review", toState="cancelled")
    )
    assert _types(db, entity_id=cancelled.id)[-1] == "job.cancelled"


def test_an_illegal_transition_records_nothing(db: Path) -> None:
    """A rejected transition is not a state change, so it is not an event."""
    from file_ferry.application.jobs import InvalidTransitionError

    svc = JobService(db)
    job = svc.create(CreateJobParams(projectId="proj-1", command="offload"))
    with pytest.raises(InvalidTransitionError):
        svc.transition(JobTransitionParams(id=job.id, fromState="planned", toState="succeeded"))
    assert _types(db, entity_id=job.id) == ["job.created"]


# ---------------------------------------------------------------------------
# Replicas, and the granularity decision
# ---------------------------------------------------------------------------


def _asset_with_replica(db: Path, tmp_path: Path, *, content: bytes) -> tuple[str, int, Path]:
    src = tmp_path / "src.mov"
    src.write_bytes(content)
    dest = tmp_path / "dest.mov"
    dest.write_bytes(content)
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            INSERT INTO assets (id, source_relative_path, lifecycle_state, first_seen_at)
            VALUES ('asset-1', 'src.mov', 'known', 'now')
            """
        )
        conn.commit()
    replica_id = ReplicaService(db).record(
        "asset-1",
        "proj-1",
        str(dest),
        checksum="",
        algo="xxhash64",
        source_checksum="",
        verified=False,
    )
    return "asset-1", replica_id, src


def test_operator_initiated_verify_is_recorded(db: Path, tmp_path: Path) -> None:
    _, replica_id, src = _asset_with_replica(db, tmp_path, content=b"matching bytes")
    ReplicaService(db).verify(replica_id, src, "xxhash64")
    row = _events(db, entity_id=str(replica_id))[-1]
    assert row["event_type"] == "replica.verified"
    assert row["entity_type"] == "replica"
    data = json.loads(row["data"])
    assert data["verified"] is True
    assert data["algo"] == "xxhash64"
    assert data["asset_id"] == "asset-1"


def test_a_mismatch_is_recorded_as_a_mismatch(db: Path, tmp_path: Path) -> None:
    _, replica_id, src = _asset_with_replica(db, tmp_path, content=b"original")
    # Diverge the replica after it was recorded.
    with transaction(db) as conn:
        dest = conn.execute("SELECT path FROM replicas WHERE id = ?", (replica_id,)).fetchone()[0]
    Path(dest).write_bytes(b"corrupted")

    result = ReplicaService(db).verify(replica_id, src, "xxhash64")
    assert result.verified is False
    row = _events(db, entity_id=str(replica_id))[-1]
    assert row["event_type"] == "replica.mismatch"
    assert json.loads(row["data"])["verified"] is False


def test_the_per_file_offload_path_stays_silent(db: Path, tmp_path: Path) -> None:
    """The granularity decision, guarded.

    `record_verified` is what the offload engine calls per file. A 2000-file
    card must not produce 2000 timeline rows -- that evidence lives in
    `job_items` and the receipt's checksum list. If someone adds an event
    here, this test says why not.
    """
    _asset_with_replica(db, tmp_path, content=b"bytes")
    before = len(_events(db))
    for i in range(5):
        ReplicaService(db).record_verified(
            "asset-1",
            "proj-1",
            str(tmp_path / f"copy-{i}.mov"),
            checksum="abc",
            algo="xxhash64",
            source_checksum="abc",
        )
    assert len(_events(db)) == before


# ---------------------------------------------------------------------------
# The IPC surface that was returning [] for everything
# ---------------------------------------------------------------------------


def test_audit_list_now_returns_lifecycle_events(db: Path) -> None:
    svc = JobService(db)
    job = svc.create(CreateJobParams(projectId="proj-1", command="offload"))
    svc.transition(JobTransitionParams(id=job.id, fromState="planned", toState="awaiting_review"))

    events = AuditService(db).list(ListAuditParams(limit=50))
    assert [e.event_type for e in events] == ["job.awaiting_review", "job.created"]
    assert all(e.entity_id == job.id for e in events)
    # `data` round-trips as a dict through the wire model, not a JSON string.
    assert events[0].data is not None
    assert events[0].data["to_state"] == "awaiting_review"


def test_audit_list_filters_lifecycle_events_by_entity(db: Path) -> None:
    svc = JobService(db)
    a = svc.create(CreateJobParams(projectId="proj-1", command="offload"))
    b = svc.create(CreateJobParams(projectId="proj-1", command="proxy"))

    only_a = AuditService(db).list(ListAuditParams(entityId=a.id))
    assert [e.entity_id for e in only_a] == [a.id]
    assert b.id not in [e.entity_id for e in only_a]


# ---------------------------------------------------------------------------
# Intake milestones
# ---------------------------------------------------------------------------


def _intake_setup(tmp_path: Path):
    """A project plus an inspected source, via the real ApplicationService."""
    from file_ferry.application.service import ApplicationService
    from file_ferry.service.protocol import (
        CreateProjectParams,
        SourceInspectParams,
        StoragePolicy,
    )

    svc = ApplicationService(db_path=tmp_path / "ferry.db", app_data_dir=tmp_path / "app")
    svc.bootstrap()
    working = tmp_path / "project" / "working"
    backup = tmp_path / "project" / "backup"
    working.mkdir(parents=True)
    backup.mkdir(parents=True)
    pid = svc.create_project(
        CreateProjectParams(
            name="Episode-2",
            workingRoot=str(working),
            backupRoot=str(backup),
            # tmp_path is one device, so relax the same-volume rule.
            storagePolicy=StoragePolicy(
                requiredReplicas=2,
                backupOnDifferentVolume=False,
                checksumAlgo="xxhash64",
                safetyReserveBytes=0,
                requireSourceFingerprint=True,
            ),
            acknowledgeWeaker=True,
        )
    )
    src = tmp_path / "card" / "DCIM"
    src.mkdir(parents=True)
    (src / "A001.mov").write_bytes(b"the-media-bytes")
    inspected = svc.source_inspect(SourceInspectParams(path=str(src.parent), kind="card"))
    return svc, pid, inspected, working


def test_intake_session_and_destinations_are_recorded(tmp_path: Path) -> None:
    from file_ferry.service.protocol import AddDestinationParams, CreateIntakeSessionParams

    svc, pid, inspected, working = _intake_setup(tmp_path)
    db = tmp_path / "ferry.db"

    session = svc.intake_create_session(
        CreateIntakeSessionParams(projectId=pid, sourceId=inspected.source_id, kind="offload")
    )
    created = _events(db, entity_id=session.id)
    assert [r["event_type"] for r in created] == ["intake.session_created"]
    assert created[0]["entity_type"] == "intake_session"
    data = json.loads(created[0]["data"])
    assert data["project_id"] == pid
    assert data["kind"] == "offload"
    assert data["source_id"] == inspected.source_id

    svc.intake_add_destination(
        AddDestinationParams(
            intakeSessionId=session.id,
            kind="working",
            rootPath=str(working),
            required=True,
        )
    )
    types = _types(db, entity_id=session.id)
    assert types == ["intake.session_created", "intake.destination_added"]
    dest_data = json.loads(_events(db, entity_id=session.id)[-1]["data"])
    assert dest_data["kind"] == "working"
    assert dest_data["root_path"] == str(working)
    assert dest_data["required"] is True
    svc.close()


def test_adoption_records_one_event_with_the_asset_count(tmp_path: Path) -> None:
    from file_ferry.service.protocol import CreateIntakeSessionParams

    svc, pid, inspected, working = _intake_setup(tmp_path)
    db = tmp_path / "ferry.db"
    session = svc.intake_create_session(
        CreateIntakeSessionParams(projectId=pid, sourceId=inspected.source_id, kind="offload")
    )
    asset_ids = svc.intake_adopt_source(
        session.id,
        inspected.source_id,
        list(inspected.entries),
        str(working),
        project_id=pid,
    )
    adopted = [
        r for r in _events(db, entity_id=session.id) if r["event_type"] == "intake.source_adopted"
    ]
    # One event for the adoption, not one per asset.
    assert len(adopted) == 1
    data = json.loads(adopted[0]["data"])
    assert data["asset_count"] == len(asset_ids)
    assert data["destination_root"] == str(working)
    svc.close()


def test_evaluating_the_gate_records_nothing(tmp_path: Path) -> None:
    """`evaluate` is a repeatable read that persists nothing.

    Recording it would put the same determination on the timeline once per
    poll. The events that *change* the answer are recorded instead.
    """
    from file_ferry.service.protocol import CreateIntakeSessionParams

    svc, pid, inspected, _working = _intake_setup(tmp_path)
    db = tmp_path / "ferry.db"
    session = svc.intake_create_session(
        CreateIntakeSessionParams(projectId=pid, sourceId=inspected.source_id, kind="offload")
    )
    before = len(_events(db))
    for _ in range(3):
        svc.intake_evaluate(session.id)
    assert len(_events(db)) == before
    svc.close()
