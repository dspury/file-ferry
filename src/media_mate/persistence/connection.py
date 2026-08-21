"""SQLite connection factory.

Configures the database with WAL journaling, foreign key enforcement,
a 5-second busy timeout, and NORMAL synchronous mode. The factory
returns a fresh connection per use; the caller is responsible for
the transaction boundary.

See ADR-0003 (application persistence model).
"""

from __future__ import annotations

import contextlib
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    """Apply the frozen set of SQLite PRAGMAs.

    Order matters: ``journal_mode`` requires no transaction; the
    others are applied on the same connection.
    """
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA synchronous = NORMAL")


def open_connection(db_path: Path) -> sqlite3.Connection:
    """Open a SQLite connection with the project's frozen configuration.

    The connection is short-lived; the caller is responsible for
    closing it (or using :func:`transaction`).

    The connection is in autocommit mode (``isolation_level=None``);
    the caller manages transactions explicitly with ``BEGIN`` /
    ``COMMIT`` / ``ROLLBACK``.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(db_path),
        isolation_level=None,
        timeout=5.0,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    _apply_pragmas(conn)
    return conn


@contextmanager
def transaction(db_path: Path) -> Iterator[sqlite3.Connection]:
    """Yield a connection inside a single transaction.

    Commits on success, rolls back on any exception. The connection
    is always closed before the context returns.
    """
    conn = open_connection(db_path)
    try:
        conn.execute("BEGIN")
        yield conn
        conn.execute("COMMIT")
    except Exception:
        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def database_exists(db_path: Path) -> bool:
    """Return True if the database file exists.

    The presence of the file is not the same as ``database_exists`` in
    the SQL sense; this is used by the migration runner to decide
    whether to bootstrap from the legacy schema or apply post-bootstrap
    migrations.
    """
    return db_path.exists()
