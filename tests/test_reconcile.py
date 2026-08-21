"""Reconciliation (plan §7.5)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from file_ferry.application.reconcile import ReconcileError, ReconcileService
from file_ferry.application.replicas import ReplicaService, compute_checksum


@pytest.fixture
def db(tmp_path: Path) -> Path:
    from file_ferry.application.service import ApplicationService

    db = tmp_path / "ferry.db"
    boot = ApplicationService(db_path=db, app_data_dir=tmp_path / "app")
    boot.bootstrap()
    boot.close()
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO projects (id, name, status, working_root, storage_policy, created_at, "
            "updated_at) VALUES ('proj-1', 'proj-1', 'active', '/tmp', '{}', 'now', 'now')"
        )
        conn.execute(
            "INSERT INTO assets (id, source_relative_path, first_seen_at) "
            "VALUES ('asset-1', 'clip.mov', 'now')"
        )
        conn.commit()
    return db


def _add_verified_replica(db: Path, path: str) -> int:
    svc = ReplicaService(db)
    cs = compute_checksum(Path(path), "xxhash64")
    return svc.record(
        "asset-1",
        "proj-1",
        path,
        checksum=cs,
        algo="xxhash64",
        source_checksum=cs,
        verified=True,
    )


def test_reconcile_verified(tmp_path: Path, db: Path) -> None:
    f = tmp_path / "replica.mov"
    f.write_bytes(b"content")
    _add_verified_replica(db, str(f))

    report = ReconcileService(db).reconcile_asset("asset-1")
    assert report.entries[0].status == "verified"
    assert report.entries[0].availability == "present"


def test_reconcile_detects_change(tmp_path: Path, db: Path) -> None:
    f = tmp_path / "replica.mov"
    f.write_bytes(b"original")
    _add_verified_replica(db, str(f))
    f.write_bytes(b"changed-content")  # mutate after baseline

    report = ReconcileService(db).reconcile_asset("asset-1")
    assert report.entries[0].status == "changed"
    assert report.entries[0].actual_checksum != report.entries[0].expected_checksum


def test_reconcile_detects_missing(tmp_path: Path, db: Path) -> None:
    missing = tmp_path / "gone.mov"
    missing.write_bytes(b"x")
    _add_verified_replica(db, str(missing))
    missing.unlink()

    report = ReconcileService(db).reconcile_asset("asset-1")
    assert report.entries[0].status == "missing"
    assert report.entries[0].availability == "missing"


def test_accept_change_records_new_evidence_and_history(tmp_path: Path, db: Path) -> None:
    f = tmp_path / "replica.mov"
    f.write_bytes(b"original")
    rid = _add_verified_replica(db, str(f))
    f.write_bytes(b"changed-content")

    svc = ReconcileService(db)
    report = svc.accept_change("asset-1", rid, algo="xxhash64")
    assert report.entries[0].status == "verified"

    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT checksum, verified FROM replicas WHERE id = ?", (rid,)
        ).fetchone()
        assert row["verified"] == 1
        assert row["checksum"] == compute_checksum(f, "xxhash64")
        event = conn.execute(
            "SELECT data FROM audit_events WHERE event_type = 'reconcile.accept_change'"
        ).fetchone()
        assert event is not None
        import json

        data = json.loads(event["data"])
        assert "old_checksum" in data
        assert data["new_checksum"] == row["checksum"]


def test_accept_change_missing_file_raises(db: Path) -> None:
    missing = db.parent / "gone.mov"
    missing.write_bytes(b"x")
    rid = _add_verified_replica(db, str(missing))
    missing.unlink()
    with pytest.raises(ReconcileError):
        ReconcileService(db).accept_change("asset-1", rid, algo="xxhash64")
