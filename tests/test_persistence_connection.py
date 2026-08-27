"""SQLite connection factory (ADR-0003).

Covers the frozen PRAGMA set and the same-thread invariant #111 asked
about: connections are open->use->close inside one call stack, so
sqlite3's native cross-thread guard is left enabled to enforce it.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from file_ferry.persistence.connection import open_connection, transaction


def test_open_connection_applies_the_frozen_pragmas(tmp_path: Path) -> None:
    conn = open_connection(tmp_path / "ferry.db")
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        # NORMAL is synchronous level 1.
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1
    finally:
        conn.close()


def test_open_connection_creates_the_parent_directory(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "deeper" / "ferry.db"
    conn = open_connection(db_path)
    conn.close()
    assert db_path.parent.is_dir()


def test_a_connection_refuses_use_from_another_thread(tmp_path: Path) -> None:
    """The guard #111 asked us to restore is active.

    Sharing one connection across threads is a bug, not a supported
    pattern; sqlite3 raises rather than letting it corrupt quietly.
    """
    conn = open_connection(tmp_path / "ferry.db")
    captured: list[BaseException] = []

    def use_it() -> None:
        try:
            conn.execute("SELECT 1")
        except BaseException as exc:  # recording it *is* the assertion
            captured.append(exc)

    thread = threading.Thread(target=use_it)
    thread.start()
    thread.join()
    conn.close()

    assert len(captured) == 1
    assert isinstance(captured[0], sqlite3.ProgrammingError)


def test_transaction_works_from_a_non_main_thread(tmp_path: Path) -> None:
    """The invariant holds for the dispatcher: open your own connection.

    ``JobDispatcher`` runs on a daemon thread and reaches the database
    through ``transaction()``, which opens a fresh connection per call --
    so nothing crosses a thread boundary and the guard never fires.
    """
    db_path = tmp_path / "ferry.db"
    with transaction(db_path) as conn:
        conn.execute("CREATE TABLE t (n INTEGER)")

    errors: list[BaseException] = []

    def insert(n: int) -> None:
        try:
            with transaction(db_path) as conn:
                conn.execute("INSERT INTO t (n) VALUES (?)", (n,))
        except BaseException as exc:  # recorded and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=insert, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    with transaction(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 8


def test_transaction_rolls_back_on_failure(tmp_path: Path) -> None:
    db_path = tmp_path / "ferry.db"
    with transaction(db_path) as conn:
        conn.execute("CREATE TABLE t (n INTEGER)")

    with pytest.raises(RuntimeError), transaction(db_path) as conn:
        conn.execute("INSERT INTO t (n) VALUES (1)")
        raise RuntimeError("boom")

    with transaction(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0
