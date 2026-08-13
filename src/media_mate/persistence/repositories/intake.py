"""Repository for ``intake_sessions`` and ``intake_destinations``."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, fields


@dataclass(frozen=True)
class IntakeSessionRow:
    """One row from the ``intake_sessions`` table."""

    id: str
    project_id: str
    source_id: int | None
    kind: str
    plan_fingerprint: str | None
    policy_fingerprint: str | None
    status: str
    safe_to_format: int
    source_readable_at: str | None
    created_at: str
    updated_at: str
    completed_at: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> IntakeSessionRow:
        return cls(**{f.name: row[f.name] for f in fields(cls)})


@dataclass(frozen=True)
class IntakeDestinationRow:
    """One row from the ``intake_destinations`` table."""

    id: int
    intake_session_id: str
    kind: str
    root_path: str
    role: str | None
    required: int
    verified: int
    verified_at: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> IntakeDestinationRow:
        return cls(**{f.name: row[f.name] for f in fields(cls)})


def insert_session(conn: sqlite3.Connection, session: IntakeSessionRow) -> None:
    conn.execute(
        """
        INSERT INTO intake_sessions (
            id, project_id, source_id, kind, plan_fingerprint, policy_fingerprint,
            status, safe_to_format, source_readable_at, created_at, updated_at, completed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session.id,
            session.project_id,
            session.source_id,
            session.kind,
            session.plan_fingerprint,
            session.policy_fingerprint,
            session.status,
            session.safe_to_format,
            session.source_readable_at,
            session.created_at,
            session.updated_at,
            session.completed_at,
        ),
    )


def get_session(conn: sqlite3.Connection, session_id: str) -> IntakeSessionRow | None:
    row = conn.execute("SELECT * FROM intake_sessions WHERE id = ?", (session_id,)).fetchone()
    return IntakeSessionRow.from_row(row) if row is not None else None


def update_session(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    status: str | None = None,
    safe_to_format: int | None = None,
    source_readable_at: str | None = None,
    plan_fingerprint: str | None = None,
    updated_at: str | None = None,
    completed_at: str | None = None,
) -> None:
    updates: list[str] = []
    values: list[object] = []
    for column, value in (
        ("status", status),
        ("safe_to_format", safe_to_format),
        ("source_readable_at", source_readable_at),
        ("plan_fingerprint", plan_fingerprint),
        ("updated_at", updated_at),
        ("completed_at", completed_at),
    ):
        if value is not None:
            updates.append(f"{column} = ?")
            values.append(value)
    if not updates:
        return
    values.append(session_id)
    conn.execute(f"UPDATE intake_sessions SET {', '.join(updates)} WHERE id = ?", tuple(values))


def insert_destination(conn: sqlite3.Connection, dest: IntakeDestinationRow) -> None:
    conn.execute(
        """
        INSERT INTO intake_destinations (
            intake_session_id, kind, root_path, role, required, verified, verified_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            dest.intake_session_id,
            dest.kind,
            dest.root_path,
            dest.role,
            dest.required,
            dest.verified,
            dest.verified_at,
        ),
    )


def list_destinations(conn: sqlite3.Connection, session_id: str) -> list[IntakeDestinationRow]:
    rows = conn.execute(
        "SELECT * FROM intake_destinations WHERE intake_session_id = ? ORDER BY id ASC",
        (session_id,),
    ).fetchall()
    return [IntakeDestinationRow.from_row(r) for r in rows]


def set_destination_verified(
    conn: sqlite3.Connection, dest_id: int, *, verified: bool, verified_at: str
) -> None:
    conn.execute(
        "UPDATE intake_destinations SET verified = ?, verified_at = ? WHERE id = ?",
        (1 if verified else 0, verified_at, dest_id),
    )
