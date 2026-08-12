"""Migration runner tests.

The migration runner is the load-bearing piece of the persistence
layer. It must:

1. Bootstrap from an empty database to the current schema version.
2. Apply pending migrations in order, with a pre-migration backup.
3. Restore the original database when a migration fails.
4. Be idempotent (re-running it on a current database is a no-op).
5. Refuse to start when the database is newer than the running code.

See ADR-0003 (application persistence model).
"""

from __future__ import annotations

import sqlite3
import sys
import types
from pathlib import Path

import pytest

from media_mate.persistence import backup, runner
from media_mate.persistence.runner import Migration


@pytest.fixture
def fresh_db(tmp_path: Path) -> Path:
    """A fresh empty SQLite database file (no schema yet, but a real SQLite file)."""
    db_path = tmp_path / "test.db"
    # Initialize the file as a real SQLite database so the backup API
    # accepts it. The runner will populate the schema via migration.
    conn = sqlite3.connect(str(db_path))
    conn.close()
    return db_path


@pytest.fixture
def backups_dir(tmp_path: Path) -> Path:
    return tmp_path / "backups"


@pytest.fixture
def failing_migration(tmp_path: Path) -> types.ModuleType:
    """A migration module whose upgrade raises."""
    pkg = tmp_path / "failing_migrations_pkg"
    pkg.mkdir()
    init = pkg / "__init__.py"
    init.write_text("")

    one = pkg / "001_one_works.py"
    one.write_text(
        "import sqlite3\n"
        "def upgrade(conn):\n"
        "    conn.execute('CREATE TABLE one (id INTEGER)')\n"
        "def downgrade(conn):\n"
        "    conn.execute('DROP TABLE one')\n"
    )

    two = pkg / "002_two_fails.py"
    two.write_text(
        "import sqlite3\n"
        "def upgrade(conn):\n"
        "    conn.execute('CREATE TABLE two (id INTEGER)')\n"
        "    raise RuntimeError('boom')\n"
        "def downgrade(conn):\n"
        "    conn.execute('DROP TABLE two')\n"
    )

    three = pkg / "003_three_works.py"
    three.write_text(
        "import sqlite3\n"
        "def upgrade(conn):\n"
        "    conn.execute('CREATE TABLE three (id INTEGER)')\n"
        "def downgrade(conn):\n"
        "    conn.execute('DROP TABLE three')\n"
    )

    sys.path.insert(0, str(tmp_path))
    module = __import__(pkg.name)
    yield module
    sys.path.remove(str(tmp_path))
    sys.modules.pop(pkg.name, None)


@pytest.fixture
def good_migrations(tmp_path: Path) -> types.ModuleType:
    """A migration package whose upgrades all succeed."""
    pkg = tmp_path / "good_migrations_pkg"
    pkg.mkdir()
    init = pkg / "__init__.py"
    init.write_text("")

    one = pkg / "001_one.py"
    one.write_text(
        "import sqlite3\n"
        "def upgrade(conn):\n"
        "    conn.execute('CREATE TABLE one (id INTEGER)')\n"
        "def downgrade(conn):\n"
        "    conn.execute('DROP TABLE one')\n"
    )

    two = pkg / "002_two.py"
    two.write_text(
        "import sqlite3\n"
        "def upgrade(conn):\n"
        "    conn.execute('CREATE TABLE two (id INTEGER)')\n"
        "def downgrade(conn):\n"
        "    conn.execute('DROP TABLE two')\n"
    )

    sys.path.insert(0, str(tmp_path))
    module = __import__(pkg.name)
    yield module
    sys.path.remove(str(tmp_path))
    sys.modules.pop(pkg.name, None)


def _discover(package: types.ModuleType) -> list[Migration]:
    return runner.discover_migrations(pkg=package)


def test_discovers_migrations_in_version_order(failing_migration: types.ModuleType) -> None:
    """The discoverer should sort by version number, not by name."""
    discovered = _discover(failing_migration)
    assert [m.version for m in discovered] == [1, 2, 3]
    assert [m.name for m in discovered] == ["one_works", "two_fails", "three_works"]


def test_applies_pending_migrations_on_empty_db(
    fresh_db: Path,
    backups_dir: Path,
    failing_migration: types.ModuleType,
) -> None:
    """The first call applies every migration in order."""
    discovered = _discover(failing_migration)
    applied = runner.apply_pending(fresh_db, [discovered[0]], backups_dir)
    assert len(applied) == 1
    assert applied[0].version == 1

    with sqlite3.connect(fresh_db) as conn:
        assert _table_exists(conn, "one")


def test_reapply_on_current_db_is_noop(
    fresh_db: Path,
    backups_dir: Path,
    failing_migration: types.ModuleType,
) -> None:
    """A second call should not re-apply existing migrations."""
    discovered = _discover(failing_migration)
    runner.apply_pending(fresh_db, [discovered[0]], backups_dir)
    applied = runner.apply_pending(fresh_db, [discovered[0]], backups_dir)
    assert applied == []


def test_failed_migration_restores_from_backup(
    fresh_db: Path,
    backups_dir: Path,
    failing_migration: types.ModuleType,
) -> None:
    """A migration that raises must leave the database unchanged."""
    discovered = _discover(failing_migration)
    with pytest.raises(RuntimeError, match="boom"):
        runner.apply_pending(fresh_db, discovered, backups_dir)

    # The first migration must have been applied (and its backup written).
    with sqlite3.connect(fresh_db) as conn:
        assert _table_exists(conn, "one")
        assert not _table_exists(conn, "two")
        assert not _table_exists(conn, "three")

    # The migration that failed was the second; the runner must NOT
    # advance the schema version past it.
    with sqlite3.connect(fresh_db) as conn:
        row = conn.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'").fetchone()
        assert row is not None and row[0] == "1"


def test_failed_migration_writes_backup_file(
    fresh_db: Path,
    backups_dir: Path,
    failing_migration: types.ModuleType,
) -> None:
    """A pre-migration backup must be written before every upgrade."""
    discovered = _discover(failing_migration)
    with pytest.raises(RuntimeError):
        runner.apply_pending(fresh_db, discovered, backups_dir)
    backups = list(backups_dir.glob("media-mate-*-pre-002.db"))
    assert len(backups) == 1
    assert backup.verify_checksum(backups[0])


def test_refuses_to_start_when_db_is_newer_than_target(
    fresh_db: Path,
    backups_dir: Path,
    failing_migration: types.ModuleType,
) -> None:
    """The runner must refuse to down-migrate implicitly."""
    discovered = _discover(failing_migration)
    # Apply just the first migration (works), then bump the schema
    # version to 99 so the runner must reject a target of 1.
    runner.apply_pending(fresh_db, discovered[:1], backups_dir)
    with sqlite3.connect(fresh_db) as conn:
        from media_mate.persistence.schema_meta import set_version

        set_version(conn, 99)

    with pytest.raises(RuntimeError, match="newer than target"):
        runner.apply_pending(fresh_db, discovered[:1], backups_dir)


def test_rollback_drops_tables(
    fresh_db: Path,
    backups_dir: Path,
    good_migrations: types.ModuleType,
) -> None:
    """Downgrading restores the schema to a previous version."""
    discovered = _discover(good_migrations)
    runner.apply_pending(fresh_db, discovered, backups_dir)
    with sqlite3.connect(fresh_db) as conn:
        assert _table_exists(conn, "one")
        assert _table_exists(conn, "two")

    rolled_back = runner.apply_pending(
        fresh_db, discovered, backups_dir, target_version=1, downgrade=True
    )
    assert [m.version for m in rolled_back] == [2]
    with sqlite3.connect(fresh_db) as conn:
        assert _table_exists(conn, "one")
        assert not _table_exists(conn, "two")


def test_backup_round_trip(tmp_path: Path) -> None:
    """A backup can be restored to its original contents."""
    db = tmp_path / "live.db"
    # Initialize the live DB with a table so the backup has content.
    with sqlite3.connect(str(db)) as conn:
        conn.execute("CREATE TABLE one (id INTEGER, value TEXT)")
        conn.execute("INSERT INTO one VALUES (1, 'hello')")
        conn.commit()
    backups = tmp_path / "backups"
    backup_path = backup.write_backup(db, backups, version=1)
    backup.write_checksum(backup_path)
    assert backup_path.exists()
    assert backup.verify_checksum(backup_path)

    # Verify the backup contains the table.
    with sqlite3.connect(str(backup_path)) as conn:
        row = conn.execute("SELECT value FROM one WHERE id = 1").fetchone()
        assert row is not None and row[0] == "hello"

    # Corrupt the live DB and restore from backup.
    db.write_bytes(b"corrupted")
    with sqlite3.connect(str(db)) as conn, pytest.raises(sqlite3.DatabaseError):
        # Sanity: the corrupted file is no longer a valid SQLite DB.
        conn.execute("SELECT 1").fetchone()
    backup.restore_from(backup_path, db)
    with sqlite3.connect(str(db)) as conn:
        row = conn.execute("SELECT value FROM one WHERE id = 1").fetchone()
        assert row is not None and row[0] == "hello"


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def test_bootstrap_creates_legacy_schema(tmp_path: Path) -> None:
    """The first migration recreates the v0.2.4 schema on an empty DB."""
    from media_mate.application.service import ApplicationService

    db_path = tmp_path / "media-mate.db"
    app_data = tmp_path / "app_data"
    service = ApplicationService(db_path=db_path, app_data_dir=app_data)
    service.bootstrap()

    with sqlite3.connect(db_path) as conn:
        # The legacy schema is intact.
        assert _table_exists(conn, "runs")
        assert _table_exists(conn, "files")
        assert _table_exists(conn, "probes")
        assert _table_exists(conn, "legacy_resolve_projects")
        assert _table_exists(conn, "verification_baselines")
