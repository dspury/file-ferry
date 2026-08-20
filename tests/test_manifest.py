"""Project manifest / handoff export (plan §4.5, §7.4)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ferry.application.manifest import ManifestError, ManifestService
from ferry.application.replicas import ReplicaService, compute_checksum


@pytest.fixture
def db(tmp_path: Path) -> Path:
    from ferry.application.service import ApplicationService

    db = tmp_path / "ferry.db"
    boot = ApplicationService(db_path=db, app_data_dir=tmp_path / "app")
    boot.bootstrap()
    boot.close()
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO projects (id, name, status, working_root, storage_policy, created_at, "
            "updated_at) VALUES ('proj-1', 'Episode-9', 'active', '/tmp/w', '{}', 'now', 'now')"
        )
        conn.execute(
            "INSERT INTO assets (id, source_relative_path, first_seen_at) "
            "VALUES ('asset-1', 'clip.mov', 'now')"
        )
        conn.commit()
    return db


def _add_replica(db: Path, path: str, *, verified: bool = True) -> None:
    cs = compute_checksum(Path(path), "xxhash64")
    ReplicaService(db).record(
        "asset-1",
        "proj-1",
        path,
        checksum=cs,
        algo="xxhash64",
        source_checksum=cs,
        verified=verified,
    )


def test_export_project_manifest(tmp_path: Path, db: Path) -> None:
    f = tmp_path / "r.mov"
    f.write_bytes(b"content")
    _add_replica(db, str(f))

    manifest = ManifestService(db).export_project("proj-1")
    assert manifest.project_name == "Episode-9"
    assert manifest.manifest_version == 1
    assert len(manifest.assets) == 1
    assert manifest.assets[0].source_relative_path == "clip.mov"
    assert len(manifest.replicas) == 1
    assert manifest.replicas[0].verified is True


def test_export_handoff_markdown(tmp_path: Path, db: Path) -> None:
    f = tmp_path / "r.mov"
    f.write_bytes(b"content")
    _add_replica(db, str(f))

    md = ManifestService(db).export_handoff("proj-1")
    assert "Episode-9" in md
    assert "Verified replicas: 1/1" in md
    assert "clip.mov" in md or "r.mov" in md


def test_resolve_manifest_is_labeled_not_a_project(tmp_path: Path, db: Path) -> None:
    f = tmp_path / "r.mov"
    f.write_bytes(b"content")
    _add_replica(db, str(f))

    manifest = ManifestService(db).export_resolve_manifest("proj-1")
    assert "not a created project" in manifest.label
    assert len(manifest.clips) == 1
    assert manifest.clips[0].name == "r.mov"


def test_export_missing_project_raises(db: Path) -> None:
    with pytest.raises(ManifestError):
        ManifestService(db).export_project("nope")
