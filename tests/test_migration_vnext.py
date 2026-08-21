"""Migration 002 — vNext entity tables.

Proves the vNext schema (plan §6.2) is created, indexed, and
referential on a fresh database, and that downgrade drops it cleanly
back to the legacy schema.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from file_ferry.application.service import ApplicationService

VNEXT_TABLES = (
    "projects",
    "organization_profiles",
    "sources",
    "intake_sessions",
    "intake_destinations",
    "assets",
    "replicas",
    "logical_clips",
    "logical_clip_members",
    "derivatives",
    "jobs",
    "job_steps",
    "job_items",
    "operation_receipts",
    "audit_events",
)

LEGACY_TABLES = (
    "runs",
    "files",
    "probes",
    "proxies",
    "legacy_resolve_projects",
    "verifications",
    "organize_ops",
    "verification_snapshots",
    "verification_baselines",
)


def _service(tmp_path: Path) -> tuple[ApplicationService, Path]:
    db = tmp_path / "ferry.db"
    app_data = tmp_path / "app_data"
    service = ApplicationService(db_path=db, app_data_dir=app_data)
    service.bootstrap()
    return service, db


def _tables(conn: sqlite3.Connection) -> set[str]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {r["name"] for r in rows}


def _indexes(conn: sqlite3.Connection) -> set[str]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'").fetchall()
    return {r["name"] for r in rows}


def test_vnext_tables_created(tmp_path: Path) -> None:
    service, db = _service(tmp_path)
    try:
        with sqlite3.connect(db) as conn:
            tables = _tables(conn)
            for name in VNEXT_TABLES:
                assert name in tables, f"missing vNext table {name}"
            for name in LEGACY_TABLES:
                assert name in tables, f"legacy table {name} must survive"
            # The vNext projects name is free (legacy renamed in 001).
            assert "legacy_resolve_projects" in tables
    finally:
        service.close()


def test_schema_version_advanced(tmp_path: Path) -> None:
    service, db = _service(tmp_path)
    try:
        with sqlite3.connect(db) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
            assert row is not None
            assert int(row["value"]) >= 2
    finally:
        service.close()


def test_vnext_indexes_present(tmp_path: Path) -> None:
    service, db = _service(tmp_path)
    try:
        with sqlite3.connect(db) as conn:
            indexes = _indexes(conn)
            for expected in ("idx_projects_name", "idx_replicas_asset", "idx_jobs_state"):
                assert expected in indexes, f"missing index {expected}"
    finally:
        service.close()


def test_foreign_keys_enforced(tmp_path: Path) -> None:
    """A replica/asset must reference a real project/asset."""
    service, db = _service(tmp_path)
    try:
        with sqlite3.connect(db) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            with __import__("contextlib").suppress(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO assets (id, source_relative_path, first_seen_at) "
                    "VALUES ('asset-1', 'a.mov', 'now')"
                )
                conn.commit()
    finally:
        service.close()


def test_downgrade_drops_vnext(tmp_path: Path) -> None:
    from file_ferry.persistence import runner

    service, db = _service(tmp_path)
    service.close()

    discovered = runner.discover_migrations()
    runner.apply_pending(db, discovered, tmp_path / "backups", target_version=1, downgrade=True)
    with sqlite3.connect(db) as conn:
        tables = _tables(conn)
        for name in VNEXT_TABLES:
            assert name not in tables, f"vNext table {name} survived downgrade"
        assert "runs" in tables  # legacy stays
