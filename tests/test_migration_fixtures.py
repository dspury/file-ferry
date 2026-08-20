"""Migration fixtures and interruption tests (Package 2 step 5).

Proves the migration runner can upgrade a database at every shipped
prior shape and that a failing migration is recoverable from its
pre-migration backup.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ferry.persistence import runner

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

    # Upgrade to the current head (version 3 after the
    # safe-to-format fingerprint migration landed).
    applied = runner.apply_pending(db, discovered, backups)
    assert applied and applied[-1].version == 3

    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        for name in LEGACY_TABLES:
            assert name in _tables(db), f"legacy table {name} lost"
        for name in VNEXT_TABLES:
            assert name in _tables(db), f"vNext table {name} missing"
        # The fingerprint column landed on intake_sessions.
        cols = {
            row["name"] for row in conn.execute("PRAGMA table_info(intake_sessions)").fetchall()
        }
        assert "volume_fingerprint_at_scan" in cols
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
