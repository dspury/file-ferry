"""Intake service — session, adoption, and the safe-to-format gate."""

from __future__ import annotations

import shutil
from pathlib import Path

from file_ferry.application.service import ApplicationService
from file_ferry.service.protocol import (
    AddDestinationParams,
    CreateIntakeSessionParams,
    CreateProjectParams,
    SourceInspectParams,
    StoragePolicy,
    VerifyReplicaParams,
)

# tmp_path shares one device -> relax the same-volume rule for the project.
SAME_VOLUME_POLICY = StoragePolicy(
    requiredReplicas=2,
    backupOnDifferentVolume=False,
    checksumAlgo="xxhash64",
    safetyReserveBytes=0,
    requireSourceFingerprint=True,
)


def _bootstrapped(tmp_path: Path) -> ApplicationService:
    svc = ApplicationService(db_path=tmp_path / "ferry.db", app_data_dir=tmp_path / "app")
    svc.bootstrap()
    return svc


def _setup(tmp_path: Path):
    svc = ApplicationService(db_path=tmp_path / "ferry.db", app_data_dir=tmp_path / "app")
    svc.bootstrap()

    # A project with relaxed same-volume policy.
    working = tmp_path / "project" / "working"
    backup = tmp_path / "project" / "backup"
    working.mkdir(parents=True)
    backup.mkdir(parents=True)
    pid = svc.create_project(
        CreateProjectParams(
            name="Episode-2",
            workingRoot=str(working),
            backupRoot=str(backup),
            storagePolicy=SAME_VOLUME_POLICY,
            acknowledgeWeaker=True,
        )
    )

    # A source with one media file.
    src = tmp_path / "card" / "DCIM"
    src.mkdir(parents=True)
    (src / "A001.mov").write_bytes(b"the-media-bytes")
    inspected = svc.source_inspect(SourceInspectParams(path=str(src.parent), kind="card"))

    return svc, pid, inspected, working, backup


def _ready_for_format(tmp_path, svc, pid, inspected, working, backup):
    """Drive a session to the 'all destinations verified' state.

    Returns (session, asset_id, rel_path, source_file). Use this to
    stand up the preconditions for safe-to-format tests.
    """
    session = svc.intake_create_session(
        CreateIntakeSessionParams(projectId=pid, sourceId=inspected.source_id, kind="offload")
    )
    svc.intake_add_destination(
        AddDestinationParams(intakeSessionId=session.id, kind="working", rootPath=str(working))
    )
    svc.intake_add_destination(
        AddDestinationParams(intakeSessionId=session.id, kind="backup", rootPath=str(backup))
    )
    asset_ids = svc.intake_adopt_source(
        session.id, inspected.source_id, inspected.entries, str(working)
    )
    asset_id = asset_ids[0]
    rel = inspected.entries[0].path
    source_file = Path(inspected.root_path) / rel
    (working / rel).parent.mkdir(parents=True, exist_ok=True)
    (backup / rel).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_file, working / rel)
    shutil.copy2(source_file, backup / rel)
    # Working replica: adopt_source already created one.
    working_replica = svc.replica_list(asset_id)[0]
    svc.replica_verify(
        VerifyReplicaParams(
            replicaId=working_replica.id,
            sourcePath=str(source_file),
            checksumAlgo="xxhash64",
        )
    )
    # Backup replica: record + verify.
    backup_id = svc.replica_record(
        asset_id,
        pid,
        str(backup / rel),
        checksum="",
        algo="xxhash64",
        source_checksum="",
        verified=False,
    )
    svc.replica_verify(
        VerifyReplicaParams(
            replicaId=backup_id,
            sourcePath=str(source_file),
            checksumAlgo="xxhash64",
        )
    )
    return session, asset_id, rel, source_file


def test_gate_not_safe_until_all_destinations_verified(tmp_path: Path) -> None:
    svc, pid, inspected, working, backup = _setup(tmp_path)

    session = svc.intake_create_session(
        CreateIntakeSessionParams(projectId=pid, sourceId=inspected.source_id, kind="offload")
    )
    svc.intake_add_destination(
        AddDestinationParams(intakeSessionId=session.id, kind="working", rootPath=str(working))
    )
    svc.intake_add_destination(
        AddDestinationParams(intakeSessionId=session.id, kind="backup", rootPath=str(backup))
    )

    # Adopt the source into the working destination (replicas recorded unverified).
    asset_ids = svc.intake_adopt_source(
        session.id, inspected.source_id, inspected.entries, str(working)
    )
    assert len(asset_ids) == 1
    asset_id = asset_ids[0]

    # Not safe: working replica unverified, backup has no replica.
    eval1 = svc.intake_evaluate(session.id)
    assert eval1.safe is False
    assert any("backup" in u for u in eval1.unmet)

    # Copy the file into both destinations and verify both replicas.
    rel = inspected.entries[0].path
    source_file = Path(inspected.root_path) / rel
    (working / rel).parent.mkdir(parents=True, exist_ok=True)
    (backup / rel).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_file, working / rel)
    shutil.copy2(source_file, backup / rel)

    replicas = svc.replica_list(asset_id)
    assert len(replicas) == 1  # only the working one from adopt

    working_replica = replicas[0]
    svc.replica_verify(
        VerifyReplicaParams(
            replicaId=working_replica.id,
            sourcePath=str(source_file),
            checksumAlgo="xxhash64",
        )
    )

    backup_replica_id = svc.replica_record(
        asset_id,
        pid,
        str(backup / rel),
        checksum="",
        algo="xxhash64",
        source_checksum="",
        verified=False,
    )
    svc.replica_verify(
        VerifyReplicaParams(
            replicaId=backup_replica_id,
            sourcePath=str(source_file),
            checksumAlgo="xxhash64",
        )
    )

    eval2 = svc.intake_evaluate(session.id)
    assert eval2.safe is True, eval2.unmet


def test_create_session_captures_volume_fingerprint(tmp_path: Path) -> None:
    """The session row carries the source's fingerprint at scan time.

    Drives ADR-0004 condition (4): without this capture, the gate
    cannot compare a later fingerprint to detect a change.
    """
    import sqlite3

    svc, pid, inspected, *_ = _setup(tmp_path)
    session = svc.intake_create_session(
        CreateIntakeSessionParams(projectId=pid, sourceId=inspected.source_id, kind="offload")
    )

    with sqlite3.connect(tmp_path / "ferry.db") as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT volume_fingerprint_at_scan FROM intake_sessions WHERE id = ?",
            (session.id,),
        ).fetchone()

    assert row is not None
    # Either captured from the source row or from the live fingerprint
    # fallback -- both are non-null when the path is stat-able.
    assert row["volume_fingerprint_at_scan"] is not None
    assert row["volume_fingerprint_at_scan"].startswith("dev:")


def test_gate_fails_when_volume_fingerprint_changes_since_scan(tmp_path: Path) -> None:
    """ADR-0004 condition (4): a fingerprint change since scan fails the gate."""
    svc, pid, inspected, working, backup = _setup(tmp_path)
    session, *_ = _ready_for_format(tmp_path, svc, pid, inspected, working, backup)

    # Baseline: everything verified, so the gate should be safe.
    baseline = svc.intake_evaluate(session.id)
    assert baseline.safe is True, baseline.unmet

    # Simulate the source's volume identity changing mid-offload by
    # replacing the fingerprint function on the intake service.
    intake = svc._intake_service()  # type: ignore[attr-defined]
    original = intake._volume_fingerprint_of  # type: ignore[attr-defined]
    intake._volume_fingerprint_of = lambda path: "simulated-different-dev"  # type: ignore[attr-defined]

    try:
        after = svc.intake_evaluate(session.id)
        assert after.safe is False
        assert any("uncertain" in u.lower() for u in after.unmet), after.unmet
    finally:
        # Restore so the rest of the test suite (and this test, if it
        # is later extended) sees a clean fingerprint function.
        intake._volume_fingerprint_of = original  # type: ignore[attr-defined]

    # And confirm the gate recovers when the fingerprint function is
    # back to its real implementation.
    recovered = svc.intake_evaluate(session.id)
    assert recovered.safe is True, recovered.unmet


def test_gate_fails_when_source_row_is_missing(tmp_path: Path) -> None:
    """If the source row is gone by evaluate-time, fail safe."""
    import sqlite3

    svc, pid, inspected, working, backup = _setup(tmp_path)
    session, *_ = _ready_for_format(tmp_path, svc, pid, inspected, working, backup)

    # Baseline is safe.
    assert svc.intake_evaluate(session.id).safe is True

    # Delete the source row to simulate a "we lost the scan-time row"
    # condition (e.g. the source row was archived before evaluation).
    with sqlite3.connect(tmp_path / "ferry.db") as conn:
        conn.execute("DELETE FROM sources WHERE id = ?", (inspected.source_id,))
        conn.commit()

    # The gate now fails because the source is gone -- the safe default.
    after = svc.intake_evaluate(session.id)
    assert after.safe is False


def test_gate_does_not_flip_on_legacy_session_without_fingerprint(tmp_path: Path) -> None:
    """Sessions predating migration 003 cannot compare fingerprints.

    The gate should fall back to its pre-PR behavior: if no baseline
    was captured, the missing-baseline case is NOT an "uncertain
    warning" -- it is silent (and matches the upstream contract for
    pre-003 sessions).
    """
    import sqlite3

    svc, pid, inspected, *_ = _setup(tmp_path)

    # Inject a session row directly with no fingerprint_at_scan,
    # simulating a database that has not yet run migration 003 for
    # some session, or a session created before the migration.
    with sqlite3.connect(tmp_path / "ferry.db") as conn:
        now = "2026-08-13T12:00:00Z"
        conn.execute(
            "INSERT INTO intake_sessions ("
            " id, project_id, source_id, kind, status, safe_to_format,"
            " source_readable_at, created_at, updated_at, volume_fingerprint_at_scan"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
            (
                "legacy-session",
                pid,
                inspected.source_id,
                "offload",
                "planned",
                0,
                now,
                now,
                now,
            ),
        )
        conn.commit()

    # Evaluate the legacy session. With no fingerprint baseline, the
    # gate must not raise an "uncertain" unmet. Other unmet items
    # (missing destinations, no replicas verified) are fine.
    result = svc.intake_evaluate("legacy-session")
    assert not any("uncertain" in u.lower() for u in result.unmet), result.unmet
