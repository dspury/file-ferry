"""Migration fixtures and interruption tests (Package 2 step 5).

Proves the migration runner can upgrade a database at every shipped
prior shape and that a failing migration is recoverable from its
pre-migration backup.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from file_ferry.persistence import runner

VNEXT_TABLES = ("projects", "sources", "assets", "replicas", "jobs", "operation_receipts")
LEGACY_TABLES = ("runs", "files", "probes", "legacy_resolve_projects")


def _discover() -> list[runner.Migration]:
    return runner.discover_migrations()


def _apply(db: Path, backups: Path, *, to: int | None = None) -> list[runner.Migration]:
    return runner.apply_pending(db, _discover(), backups, target_version=to)


def _fresh_db(tmp_path: Path) -> Path:
    db = tmp_path / "fixture.db"
    conn = sqlite3.connect(str(db))
    conn.close()
    return db


def _tables(db: Path) -> set[str]:
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        return {r["name"] for r in rows}


def test_upgrade_from_legacy_shape_preserves_data(tmp_path: Path) -> None:
    """A v0.2.4-shaped DB (version 1) upgrades to vNext and keeps its data."""
    db = _fresh_db(tmp_path)
    backups = tmp_path / "backups"

    # Simulate a prior release DB at schema version 1 with real data.
    discovered = _discover()
    runner.apply_pending(db, [discovered[0]], backups)  # version 1 only
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO runs (started_at, command, status) VALUES ('now', 'probe', 'completed')"
        )
        conn.commit()

    # Upgrade to the current head. Derived from the discovered set rather
    # than hard-coded: every new migration otherwise fails this test for a
    # reason that has nothing to do with what it is proving.
    head = discovered[-1].version
    applied = runner.apply_pending(db, discovered, backups)
    assert applied and applied[-1].version == head

    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        for name in LEGACY_TABLES:
            assert name in _tables(db), f"legacy table {name} lost"
        for name in VNEXT_TABLES:
            assert name in _tables(db), f"vNext table {name} missing"
        # The destination-presets migration added new tables.
        for name in (
            "saved_destinations",
            "organization_profile_revisions",
            "source_inventories",
            "source_inventory_entries",
            "transfer_plans",
            "transfer_plan_entries",
        ):
            assert name in _tables(db), f"v4 table {name} missing"
        # The transfer-execution migration added the run-time ledger.
        for name in (
            "transfer_executions",
            "transfer_execution_items",
            "transfer_path_reservations",
            "transfer_receipts",
        ):
            assert name in _tables(db), f"v5 table {name} missing"
        # The fingerprint column landed on intake_sessions.
        cols = {
            row["name"] for row in conn.execute("PRAGMA table_info(intake_sessions)").fetchall()
        }
        assert "volume_fingerprint_at_scan" in cols
        # jobs.project_id is now nullable (general transfers don't require
        # a project — spec §4.1).
        proj = next(
            row for row in conn.execute("PRAGMA table_info(jobs)") if row[1] == "project_id"
        )
        assert proj[3] == 0  # notnull = 0
        # Legacy data survived the migration.
        row = conn.execute("SELECT command FROM runs WHERE command = 'probe'").fetchone()
        assert row is not None


def test_fixture_at_current_shape_is_idempotent(tmp_path: Path) -> None:
    db = _fresh_db(tmp_path)
    backups = tmp_path / "backups"
    _apply(db, backups)
    assert _apply(db, backups) == []  # no pending


def test_fixture_versions_are_sequential(tmp_path: Path) -> None:
    versions = [m.version for m in _discover()]
    assert versions == list(range(1, versions[-1] + 1))


def test_interrupted_migration_restores_prior_state(tmp_path: Path) -> None:
    """A failing migration restores the DB to its pre-migration backup."""
    db = _fresh_db(tmp_path)
    backups = tmp_path / "backups"

    # Build a custom migration set where 002 fails.
    pkg = tmp_path / "interrupt_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "001_base.py").write_text(
        "import sqlite3\n"
        "def upgrade(c):\n"
        "    c.execute('CREATE TABLE base (id INTEGER)')\n"
        "    c.execute('INSERT INTO base VALUES (1)')\n"
        "def downgrade(c):\n"
        "    c.execute('DROP TABLE base')\n"
    )
    (pkg / "002_fails.py").write_text(
        "import sqlite3\n"
        "def upgrade(c):\n"
        "    c.execute('CREATE TABLE broken (id INTEGER)')\n"
        "    raise RuntimeError('boom')\n"
        "def downgrade(c):\n"
        "    c.execute('DROP TABLE broken')\n"
    )
    import sys

    sys.path.insert(0, str(tmp_path))
    try:
        pkg_module = __import__(pkg.name)
        mods = runner.discover_migrations(pkg=pkg_module)
        # Apply 001 only, then attempt the full set and expect failure.
        runner.apply_pending(db, [mods[0]], backups)
        with pytest.raises(RuntimeError, match="boom"):
            runner.apply_pending(db, mods, backups)

        # DB is usable and at version 1 with base data intact.
        with sqlite3.connect(db) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT value FROM schema_meta WHERE key='schema_version'"
            ).fetchone()
            assert int(row["value"]) == 1
            assert "broken" not in _tables(db)
            assert conn.execute("SELECT COUNT(*) FROM base").fetchone()[0] == 1
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop(pkg.name, None)


def test_v4_database_with_the_superseded_shape_fails_loudly(tmp_path: Path) -> None:
    """Migration 004 was amended in place; a stale v4 database must say so.

    The runner keys migrations by version, and 004's DDL is
    ``CREATE TABLE IF NOT EXISTS``, so a database already stamped v4
    skips it forever and keeps the old columns. Without a guard that
    surfaces as ``no such column: review_json`` somewhere deep in a
    service. No released database can be in this state — only a
    development one — but that is exactly who needs the message.
    """
    import importlib

    from file_ferry.persistence.connection import open_connection

    v4 = importlib.import_module("file_ferry.persistence.migrations.004_destination_presets")

    db = _fresh_db(tmp_path)
    _apply(db, tmp_path / "backups")

    conn = open_connection(db)
    try:
        v4.assert_v4_shape(conn)  # the freshly migrated shape is fine
        conn.execute("ALTER TABLE organization_profile_revisions DROP COLUMN review_json")
        conn.execute("ALTER TABLE transfer_plans DROP COLUMN blocking_count")
        with pytest.raises(v4.IncompatibleDevelopmentSchemaError) as caught:
            v4.assert_v4_shape(conn)
    finally:
        conn.close()

    message = str(caught.value)
    assert "organization_profile_revisions.review_json" in message
    assert "transfer_plans.blocking_count" in message
    assert "cannot be upgraded in place" in message
    assert "export them first" in message, "the message must not imply deleting real records"


def test_bootstrap_refuses_a_database_with_the_superseded_shape(tmp_path: Path) -> None:
    """The guard is wired where a developer will actually hit it."""
    import importlib

    from file_ferry.application.service import ApplicationService
    from file_ferry.persistence.connection import open_connection

    v4 = importlib.import_module("file_ferry.persistence.migrations.004_destination_presets")

    db_path = tmp_path / "ferry.db"
    first = ApplicationService(db_path=db_path, app_data_dir=tmp_path / "app")
    first.bootstrap()
    first.close()

    conn = open_connection(db_path)
    try:
        conn.execute("ALTER TABLE source_inventories DROP COLUMN heartbeat_at")
    finally:
        conn.close()

    stale = ApplicationService(db_path=db_path, app_data_dir=tmp_path / "app")
    with pytest.raises(v4.IncompatibleDevelopmentSchemaError, match="heartbeat_at"):
        stale.bootstrap()
    stale.close()
