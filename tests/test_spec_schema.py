"""SPEC.md §7 must not drift from the schema the code actually creates.

Issue #43: the sketch in SPEC.md had silently diverged from `log.py` —
tables, column names and types all disagreed. Rather than fix it once and
let it rot again, this executes the SPEC's own SQL into a scratch database
and diffs it against a freshly initialized one, so drift fails the suite.

The comparison is on structure, not text: table names, and per table the
column names with their declared type, NOT NULL flag and default. Column
*order* is deliberately not compared — `ALTER TABLE ADD COLUMN` appends to
the end, while the sketch groups columns by meaning.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

from file_ferry.log import LogStore

SPEC_PATH = Path(__file__).resolve().parent.parent / "SPEC.md"

# Column -> (declared type, not-null, default). Keyed by name, so order is free.
TableSchema = dict[str, tuple[str, bool, str | None]]


def _spec_sql() -> str:
    """Extract the ```sql block from SPEC.md §7."""
    text = SPEC_PATH.read_text()
    start = text.index("## 7. Data model")
    end = text.index("## 8. CLI surface", start)
    match = re.search(r"```sql\n(.*?)```", text[start:end], re.S)
    assert match is not None, "SPEC.md §7 has no ```sql block"
    return match.group(1)


def _schema(conn: sqlite3.Connection) -> dict[str, TableSchema]:
    """Read the structural schema of every user table in a connection."""
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    out: dict[str, TableSchema] = {}
    for (table,) in tables:
        # PRAGMA table_info: cid, name, type, notnull, dflt_value, pk
        out[table] = {
            row[1]: (row[2].upper(), bool(row[3]), row[4])
            for row in conn.execute(f"PRAGMA table_info({table})")
        }
    return out


@pytest.fixture
def spec_schema() -> dict[str, TableSchema]:
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(_spec_sql())
        return _schema(conn)
    finally:
        conn.close()


@pytest.fixture
def code_schema(tmp_path: Path) -> dict[str, TableSchema]:
    """The effective schema: SCHEMA_SQL plus every migration in _migrate."""
    db_path = tmp_path / "schema.db"
    LogStore(db_path).initialize()
    conn = sqlite3.connect(db_path)
    try:
        return _schema(conn)
    finally:
        conn.close()


def test_spec_documents_every_table(
    spec_schema: dict[str, TableSchema], code_schema: dict[str, TableSchema]
) -> None:
    assert set(spec_schema) == set(code_schema)


@pytest.mark.parametrize(
    "table",
    [
        "schema_meta",
        "runs",
        "files",
        "probes",
        "proxies",
        "projects",
        "verifications",
        "organize_ops",
        "verification_snapshots",
        "verification_baselines",
    ],
)
def test_spec_table_matches_code(
    table: str, spec_schema: dict[str, TableSchema], code_schema: dict[str, TableSchema]
) -> None:
    """Each documented table matches the real one, column for column."""
    assert table in spec_schema, f"SPEC.md §7 does not document {table}"
    assert table in code_schema, f"{table} is documented but the code never creates it"
    assert spec_schema[table] == code_schema[table]


def test_migration_only_columns_are_documented(
    spec_schema: dict[str, TableSchema], code_schema: dict[str, TableSchema]
) -> None:
    """Columns added by _migrate rather than SCHEMA_SQL still reach the SPEC.

    These are the easiest to miss, because reading SCHEMA_SQL alone does not
    show them (issue #43 missed projects.manifest_path for exactly this
    reason).
    """
    for table, column in (("projects", "manifest_path"), ("probes", "is_vfr")):
        assert column in code_schema[table], f"{table}.{column} vanished from the code"
        assert column in spec_schema[table], f"{table}.{column} is missing from SPEC.md §7"
