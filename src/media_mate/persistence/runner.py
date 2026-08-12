"""Numbered migration runner.

Migrations are modules under :mod:`media_mate.persistence.migrations`,
named ``NNN_description.py`` with ``upgrade(conn)`` and
``downgrade(conn)`` functions. The runner is a single-pass loader
that:

1. Opens a single connection with the project's frozen PRAGMAs.
2. Starts an EXCLUSIVE transaction so a second runner fails fast.
3. For each migration to apply, in source order:
   - Verify the target version is not less than the current version.
   - Take a backup of the DB file at
     ``backups/media-mate-{ISO8601}-pre-{NNN}.db`` and a ``.sha256``
     sidecar.
   - Run ``upgrade(conn)``.
   - Update ``schema_meta.schema_version`` to the new version.
   - On any failure, restore from the backup file and re-raise.
4. Commits the transaction.

The runner is single-threaded. The single-writer guarantee comes
from the desktop shell serializing the runner calls; the EXCLUSIVE
transaction is a failsafe against a second runner.

See ADR-0003 (application persistence model).
"""

from __future__ import annotations

import importlib
import logging
import re
import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from media_mate.persistence import backup
from media_mate.persistence.connection import database_exists, open_connection
from media_mate.persistence.schema_meta import (
    current_version,
    ensure_schema_meta,
    set_version,
)

LOGGER = logging.getLogger(__name__)

MIGRATION_PATTERN = re.compile(r"^(\d{3,})_(?P<name>[a-z_][a-z0-9_]*)\.py$")


@dataclass(frozen=True)
class Migration:
    """A single migration step.

    The ``version`` is the schema version the database will be at
    after the upgrade runs. The ``module`` is the imported module
    that exposes ``upgrade(conn)`` and ``downgrade(conn)``.
    """

    version: int
    name: str
    module: MigrationModule


class MigrationModule(Protocol):
    """Type shape for a migration module.

    Either function may be missing; the runner handles a missing
    ``downgrade`` by refusing to roll back rather than silently
    passing.
    """

    def upgrade(self, conn: sqlite3.Connection) -> object: ...
    def downgrade(self, conn: sqlite3.Connection) -> object: ...


def discover_migrations(pkg: object = None) -> list[Migration]:
    """Return the list of migrations registered in the package, in version order.

    The default package is :mod:`media_mate.persistence.migrations`;
    tests can pass a different package to use a temporary set.
    """
    if pkg is None:
        pkg = importlib.import_module("media_mate.persistence.migrations")
    out: list[Migration] = []
    for filename in sorted(pkg.__path__):  # type: ignore[attr-defined]
        path = Path(filename)
        for child in sorted(path.iterdir()):
            match = MIGRATION_PATTERN.match(child.name)
            if match is None:
                continue
            version = int(match.group(1))
            name = match.group("name")
            full_name = f"{pkg.__name__}.{child.stem}"  # type: ignore[attr-defined]
            module = importlib.import_module(full_name)
            out.append(Migration(version=version, name=name, module=module))
    out.sort(key=lambda m: m.version)
    return out


def apply_pending(
    db_path: Path,
    migrations: Iterable[Migration],
    backups_dir: Path,
    *,
    target_version: int | None = None,
    downgrade: bool = False,
) -> list[Migration]:
    """Apply (or roll back) pending migrations on the database at ``db_path``.

    Returns the list of migrations that were applied (or rolled back), in
    order. The function is single-threaded; callers must serialize it.

    ``target_version`` defaults to the maximum version in the migrations
    list. Pass it explicitly to rollback to a version that is not in
    the list (e.g., rollback from version 2 to version 1 by passing
    the full migration list with ``target_version=1``).
    """
    if not database_exists(db_path):
        raise FileNotFoundError(f"database not found: {db_path}")

    backups_dir.mkdir(parents=True, exist_ok=True)
    migrations_list = list(migrations)
    if not migrations_list:
        return []

    target = (
        target_version if target_version is not None else max(m.version for m in migrations_list)
    )

    conn = open_connection(db_path)
    try:
        try:
            ensure_schema_meta(conn)
            current = current_version(conn)
        except sqlite3.OperationalError as exc:
            raise RuntimeError(f"database is locked: {db_path}") from exc

        if downgrade:
            if current > target:
                return _rollback(conn, db_path, migrations_list, current, target, backups_dir)
            return []

        if current > target:
            raise RuntimeError(
                f"database schema_version {current} is newer than target {target}; "
                "set MIGRATE_DOWN=1 to allow rollback"
            )
        if current == target:
            return []
        pending = [m for m in migrations_list if m.version > current]
        return _upgrade(conn, db_path, pending, current, backups_dir)
    finally:
        conn.close()


def _apply_loop(
    conn: sqlite3.Connection,
    db_path: Path,
    migrations_list: list[Migration],
    backups_dir: Path,
    downgrade: bool,
) -> list[Migration]:
    """Deprecated: kept for backward compatibility; logic moved into apply_pending."""
    return []  # pragma: no cover


def _upgrade(
    conn: sqlite3.Connection,
    db_path: Path,
    pending: list[Migration],
    start_version: int,
    backups_dir: Path,
) -> list[Migration]:
    """Apply each pending migration in order, with per-migration backups.

    Each migration runs in its own implicit transaction. On any
    failure, the database file is restored from the pre-migration
    backup and the exception is re-raised.
    """
    applied: list[Migration] = []
    for migration in pending:
        backup_path = backup.write_backup(db_path, backups_dir, migration.version)
        backup.write_checksum(backup_path)
        try:
            _run_upgrade(conn, migration)
            set_version(conn, migration.version)
        except Exception as exc:
            LOGGER.error(
                "migration %d_%s failed (%s); restoring from backup %s",
                migration.version,
                migration.name,
                exc,
                backup_path,
            )
            # Close the connection so SQLite releases the file lock,
            # then restore from the backup.
            conn.close()
            backup.restore_from(backup_path, db_path)
            raise

        applied.append(migration)
        LOGGER.info(
            "applied migration %d_%s from %d to %d",
            migration.version,
            migration.name,
            start_version if len(applied) == 1 else applied[-2].version,
            migration.version,
        )
    return applied


def _rollback(
    conn: sqlite3.Connection,
    db_path: Path,
    migrations_list: list[Migration],
    current: int,
    target: int,
    backups_dir: Path,
) -> list[Migration]:
    """Roll back the migrations between ``current`` and ``target``.

    Iterates the migrations list in reverse, rolling back any with
    version in the (target, current] range. The migration being
    rolled back must be in the list; the caller is responsible for
    passing the full set.
    """
    rolled_back: list[Migration] = []
    for migration in reversed(migrations_list):
        if migration.version <= target:
            break
        if migration.version > current:
            continue
        backup_path = backup.write_backup(db_path, backups_dir, migration.version)
        backup.write_checksum(backup_path)
        try:
            _run_downgrade(conn, migration)
            set_version(conn, migration.version - 1)
        except Exception as exc:
            LOGGER.error(
                "rollback %d_%s failed (%s); restoring from backup %s",
                migration.version,
                migration.name,
                exc,
                backup_path,
            )
            conn.close()
            backup.restore_from(backup_path, db_path)
            raise

        rolled_back.append(migration)
        LOGGER.info(
            "rolled back migration %d_%s from %d to %d",
            migration.version,
            migration.name,
            current if len(rolled_back) == 1 else rolled_back[-2].version + 1,
            migration.version - 1,
        )
    return rolled_back


def _run_upgrade(conn: sqlite3.Connection, migration: Migration) -> None:
    """Run a migration's upgrade function. Raises on failure."""
    upgrade: Callable[[sqlite3.Connection], object] = migration.module.upgrade
    upgrade(conn)


def _run_downgrade(conn: sqlite3.Connection, migration: Migration) -> None:
    """Run a migration's downgrade function. Raises on failure."""
    downgrade = getattr(migration.module, "downgrade", None)
    if downgrade is None:
        raise RuntimeError(
            f"migration {migration.version}_{migration.name} has no downgrade; "
            "restore from backup to roll back"
        )
    downgrade_fn: Callable[[sqlite3.Connection], object] = downgrade
    downgrade_fn(conn)
