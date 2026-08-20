"""Replica service + safe-to-format gate (ADR-0004)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ferry.application.policies import default_policy
from ferry.application.replicas import (
    ReplicaService,
    compute_checksum,
    evaluate_gate,
)


@pytest.fixture
def db(tmp_path: Path) -> Path:
    from ferry.application.service import ApplicationService

    db = tmp_path / "ferry.db"
    boot = ApplicationService(db_path=db, app_data_dir=tmp_path / "app")
    boot.bootstrap()
    boot.close()
    return db


# ---- gate: pure function (ADR-0004 conditions 1-5) -------------------


def test_gate_safe_when_all_conditions_hold() -> None:
    result = evaluate_gate(
        policy=default_policy(),
        required_destinations=["working", "backup"],
        verified_destination_kinds={"working", "backup"},
        source_readable_at="2026-01-01T00:00:00Z",
        needs_attention_open=False,
        uncertain_warning=False,
        replica_metadata_ok=True,
    )
    assert result.safe is True
    assert result.unmet == []


def test_gate_unsafe_missing_verified_destination() -> None:
    result = evaluate_gate(
        policy=default_policy(),
        required_destinations=["working", "backup"],
        verified_destination_kinds={"working"},  # backup missing
        source_readable_at="2026-01-01T00:00:00Z",
        needs_attention_open=False,
        uncertain_warning=False,
        replica_metadata_ok=True,
    )
    assert result.safe is False
    assert any("backup" in u for u in result.unmet)


def test_gate_unsafe_source_never_readable() -> None:
    result = evaluate_gate(
        policy=default_policy(),
        required_destinations=["working"],
        verified_destination_kinds={"working"},
        source_readable_at=None,
        needs_attention_open=False,
        uncertain_warning=False,
        replica_metadata_ok=True,
    )
    assert result.safe is False
    assert any("readable" in u for u in result.unmet)


def test_gate_unsafe_on_needs_attention() -> None:
    result = evaluate_gate(
        policy=default_policy(),
        required_destinations=["working"],
        verified_destination_kinds={"working"},
        source_readable_at="2026-01-01T00:00:00Z",
        needs_attention_open=True,
        uncertain_warning=False,
        replica_metadata_ok=True,
    )
    assert result.safe is False
    assert any("needs-attention" in u for u in result.unmet)


def test_gate_unsafe_on_uncertain_warning() -> None:
    result = evaluate_gate(
        policy=default_policy(),
        required_destinations=["working"],
        verified_destination_kinds={"working"},
        source_readable_at="2026-01-01T00:00:00Z",
        needs_attention_open=False,
        uncertain_warning=True,
        replica_metadata_ok=True,
    )
    assert result.safe is False
    assert any("uncertain" in u for u in result.unmet)


def test_gate_unsafe_on_missing_metadata() -> None:
    result = evaluate_gate(
        policy=default_policy(),
        required_destinations=["working"],
        verified_destination_kinds={"working"},
        source_readable_at="2026-01-01T00:00:00Z",
        needs_attention_open=False,
        uncertain_warning=False,
        replica_metadata_ok=False,
    )
    assert result.safe is False
    assert any("metadata" in u for u in result.unmet)


# ---- checksum helpers ------------------------------------------------


def test_compute_checksum_sha256(tmp_path: Path) -> None:
    f = tmp_path / "a.bin"
    f.write_bytes(b"hello world")
    import hashlib

    assert compute_checksum(f, "sha256") == hashlib.sha256(b"hello world").hexdigest()


def test_compute_checksum_xxhash64(tmp_path: Path) -> None:
    f = tmp_path / "a.bin"
    f.write_bytes(b"hello world")
    import xxhash

    assert compute_checksum(f, "xxhash64") == xxhash.xxh64(b"hello world").hexdigest()


def test_compute_checksum_unknown_algo(tmp_path: Path) -> None:
    f = tmp_path / "a.bin"
    f.write_bytes(b"x")
    with pytest.raises(ValueError):
        compute_checksum(f, "md5")


# ---- replica verify --------------------------------------------------


def _seed_asset_and_replica(db: Path, dest_path: str, *, verified: bool = False) -> int:
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO projects (id, name, status, working_root, storage_policy, created_at, updated_at) "
            "VALUES ('proj-1', 'proj-1', 'active', '/tmp', '{}', 'now', 'now')"
        )
        conn.execute(
            "INSERT INTO assets (id, source_relative_path, first_seen_at) "
            "VALUES ('asset-1', 'clip.mov', 'now')"
        )
        cur = conn.execute(
            """
            INSERT INTO replicas (asset_id, project_id, path, checksum, checksum_algo,
                verified, verified_at, source_checksum, availability)
            VALUES ('asset-1', 'proj-1', ?, '', 'xxhash64', ?, ?, 'src-hash', 'present')
            """,
            (dest_path, 1 if verified else 0, "2026-01-01T00:00:00Z" if verified else None),
        )
        conn.commit()
        return int(cur.lastrowid)


def test_verify_success_marks_verified(db: Path, tmp_path: Path) -> None:
    source = tmp_path / "source"
    dest = tmp_path / "dest"
    source.write_bytes(b"same content")
    dest.write_bytes(b"same content")
    rid = _seed_asset_and_replica(db, str(dest))

    svc = ReplicaService(db)
    result = svc.verify(rid, source, "xxhash64")
    assert result.verified is True
    assert result.replica_checksum == result.source_checksum

    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT verified, verified_at FROM replicas WHERE id = ?", (rid,)
        ).fetchone()
        assert row["verified"] == 1
        assert row["verified_at"] is not None


def test_verify_failure_does_not_overwrite_baseline(db: Path, tmp_path: Path) -> None:
    source = tmp_path / "source"
    dest = tmp_path / "dest"
    source.write_bytes(b"AAA")
    dest.write_bytes(b"BBB")  # mismatch
    rid = _seed_asset_and_replica(db, str(dest), verified=True)

    svc = ReplicaService(db)
    result = svc.verify(rid, source, "xxhash64")
    assert result.verified is False

    # The prior verified baseline must be preserved (ADR-0004).
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT verified, verified_at FROM replicas WHERE id = ?", (rid,)
        ).fetchone()
        assert row["verified"] == 1
        assert row["verified_at"] is not None


def test_verify_missing_dest_marks_missing(db: Path, tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.write_bytes(b"AAA")
    rid = _seed_asset_and_replica(db, str(tmp_path / "gone.mov"))

    svc = ReplicaService(db)
    result = svc.verify(rid, source, "xxhash64")
    assert result.verified is False
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT availability FROM replicas WHERE id = ?", (rid,)).fetchone()
        assert row["availability"] == "missing"
