"""Schema-version bookkeeping.

The :class:`SchemaMeta` table is the single source of truth for the
current database schema version. Every migration is a numbered step
that advances the version. The migration runner refuses to start
when the database version is greater than the running code's
target version (unless ``MIGRATE_DOWN=1`` is set).

See ADR-0003 (application persistence model).
"""

from __future__ import annotations

import sqlite3

SCHEMA_META_DDL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""

CURRENT_VERSION_KEY = "schema_version"


def ensure_schema_meta(conn: sqlite3.Connection) -> None:
    """Create the ``schema_meta`` table if missing."""
    conn.executescript(SCHEMA_META_DDL)


def current_version(conn: sqlite3.Connection) -> int:
    """Return the current ``schema_version``. Returns 0 if unset."""
    row = conn.execute(
        "SELECT value FROM schema_meta WHERE key = ?",
        (CURRENT_VERSION_KEY,),
    ).fetchone()
    if row is None:
        return 0
    return int(row["value"])


def set_version(conn: sqlite3.Connection, version: int) -> None:
    """Set the current ``schema_version``."""
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
        (CURRENT_VERSION_KEY, str(version)),
    )
