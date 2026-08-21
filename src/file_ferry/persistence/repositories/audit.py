"""Repository for ``audit_events`` and legacy ``runs`` backfill."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, fields


@dataclass(frozen=True)
class AuditEventRow:
    """One row from the ``audit_events`` table."""

    id: int
    occurred_at: str
    actor: str | None
    event_type: str
    entity_type: str | None
    entity_id: str | None
    data: str | None
    run_id: int | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> AuditEventRow:
        return cls(**{f.name: row[f.name] for f in fields(cls)})


def insert_event(conn: sqlite3.Connection, event: AuditEventRow) -> None:
    conn.execute(
        """
        INSERT INTO audit_events (
            occurred_at, actor, event_type, entity_type, entity_id, data, run_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event.occurred_at,
            event.actor,
            event.event_type,
            event.entity_type,
            event.entity_id,
            event.data,
            event.run_id,
        ),
    )


def list_events(
    conn: sqlite3.Connection, entity_id: str | None = None, limit: int = 200
) -> list[AuditEventRow]:
    if entity_id is None:
        rows = conn.execute(
            "SELECT * FROM audit_events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM audit_events WHERE entity_id = ? ORDER BY id DESC LIMIT ?",
            (entity_id, limit),
        ).fetchall()
    return [AuditEventRow.from_row(r) for r in rows]


def legacy_run_backfill_count(conn: sqlite3.Connection) -> int:
    """Return the number of legacy ``runs`` not yet linked to an audit event."""
    row = conn.execute(
        """
        SELECT COUNT(*) AS n FROM runs r
        WHERE NOT EXISTS (SELECT 1 FROM audit_events a WHERE a.run_id = r.id)
        """
    ).fetchone()
    return int(row["n"])
