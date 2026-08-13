"""Repository for the vNext ``sources`` table."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, fields


@dataclass(frozen=True)
class SourceRow:
    """One row from the ``sources`` table."""

    id: int
    kind: str
    root_path: str
    label: str | None
    volume_fingerprint: str | None
    manifest_hash: str | None
    file_count: int
    total_bytes: int
    status: str
    source_readable_at: str | None
    captured_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> SourceRow:
        return cls(**{f.name: row[f.name] for f in fields(cls)})


def insert_source(conn: sqlite3.Connection, source: SourceRow) -> int:
    cur = conn.execute(
        """
        INSERT INTO sources (
            kind, root_path, label, volume_fingerprint, manifest_hash,
            file_count, total_bytes, status, source_readable_at, captured_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source.kind,
            source.root_path,
            source.label,
            source.volume_fingerprint,
            source.manifest_hash,
            source.file_count,
            source.total_bytes,
            source.status,
            source.source_readable_at,
            source.captured_at,
        ),
    )
    lastrowid = cur.lastrowid
    if lastrowid is None:
        raise RuntimeError("insert_source failed to return a row id")
    return int(lastrowid)


def get_source(conn: sqlite3.Connection, source_id: int) -> SourceRow | None:
    row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    return SourceRow.from_row(row) if row is not None else None


def update_scan_result(
    conn: sqlite3.Connection,
    source_id: int,
    *,
    manifest_hash: str | None = None,
    file_count: int | None = None,
    total_bytes: int | None = None,
    status: str | None = None,
    volume_fingerprint: str | None = None,
    source_readable_at: str | None = None,
) -> None:
    updates: list[str] = []
    values: list[object] = []
    for column, value in (
        ("manifest_hash", manifest_hash),
        ("file_count", file_count),
        ("total_bytes", total_bytes),
        ("status", status),
        ("volume_fingerprint", volume_fingerprint),
        ("source_readable_at", source_readable_at),
    ):
        if value is not None:
            updates.append(f"{column} = ?")
            values.append(value)
    if not updates:
        return
    values.append(source_id)
    conn.execute(f"UPDATE sources SET {', '.join(updates)} WHERE id = ?", tuple(values))
