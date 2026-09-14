"""Repository for ``transfer_plan_preflights`` (spec §7.1).

A preflight row is the evidence that the world still matched an
immutable plan at a point in time. Approval reads the latest one; a
refusal quotes its findings, and a pass leaves an audit trail of what
was actually checked rather than what was assumed.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, fields


@dataclass(frozen=True)
class PreflightRow:
    """One preflight run against one plan fingerprint."""

    id: int
    plan_id: str
    fingerprint: str
    status: str
    findings_json: str
    checked_entries: int
    total_entries: int
    resolved_binding_path: str | None
    destination_status: str | None
    free_bytes: int | None
    started_at: str
    finished_at: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> PreflightRow:
        return cls(**{f.name: row[f.name] for f in fields(cls)})


_COLUMNS = (
    "id, plan_id, fingerprint, status, findings_json, checked_entries, total_entries, "
    "resolved_binding_path, destination_status, free_bytes, started_at, finished_at"
)


def insert_preflight(conn: sqlite3.Connection, row: PreflightRow) -> int:
    cur = conn.execute(
        """
        INSERT INTO transfer_plan_preflights (
            plan_id, fingerprint, status, findings_json, checked_entries, total_entries,
            resolved_binding_path, destination_status, free_bytes, started_at, finished_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row.plan_id,
            row.fingerprint,
            row.status,
            row.findings_json,
            row.checked_entries,
            row.total_entries,
            row.resolved_binding_path,
            row.destination_status,
            row.free_bytes,
            row.started_at,
            row.finished_at,
        ),
    )
    lastrowid = cur.lastrowid
    if lastrowid is None:
        raise RuntimeError("insert_preflight failed to return a row id")
    return int(lastrowid)


def get_preflight(conn: sqlite3.Connection, preflight_id: int) -> PreflightRow | None:
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM transfer_plan_preflights WHERE id = ?", (preflight_id,)
    ).fetchone()
    return PreflightRow.from_row(row) if row is not None else None


def latest_for_plan(conn: sqlite3.Connection, plan_id: str) -> PreflightRow | None:
    """The most recent run for a plan, whatever its outcome.

    Deliberately not "the most recent *passing* run": a later failure
    supersedes an earlier pass, and approval must see that.
    """
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM transfer_plan_preflights WHERE plan_id = ? "
        "ORDER BY id DESC LIMIT 1",
        (plan_id,),
    ).fetchone()
    return PreflightRow.from_row(row) if row is not None else None


def update_progress(conn: sqlite3.Connection, preflight_id: int, *, checked_entries: int) -> None:
    conn.execute(
        "UPDATE transfer_plan_preflights SET checked_entries = ? WHERE id = ?",
        (checked_entries, preflight_id),
    )


def finish_preflight(
    conn: sqlite3.Connection,
    preflight_id: int,
    *,
    status: str,
    findings_json: str,
    checked_entries: int,
    resolved_binding_path: str | None,
    destination_status: str | None,
    free_bytes: int | None,
    finished_at: str,
) -> None:
    conn.execute(
        """
        UPDATE transfer_plan_preflights SET
            status = ?, findings_json = ?, checked_entries = ?,
            resolved_binding_path = ?, destination_status = ?, free_bytes = ?,
            finished_at = ?
        WHERE id = ?
        """,
        (
            status,
            findings_json,
            checked_entries,
            resolved_binding_path,
            destination_status,
            free_bytes,
            finished_at,
            preflight_id,
        ),
    )


def fail_abandoned(conn: sqlite3.Connection, *, finished_at: str, reason: str) -> list[int]:
    """Fail preflights left ``running`` by a process that exited.

    A stuck ``running`` row would make approval wait forever; worse, a
    naive reader could treat "not failed" as "fine".
    """
    ids = [
        int(r["id"])
        for r in conn.execute(
            "SELECT id FROM transfer_plan_preflights WHERE status = 'running'"
        ).fetchall()
    ]
    if ids:
        import json

        conn.execute(
            "UPDATE transfer_plan_preflights SET status = 'failed', finished_at = ?, "
            "findings_json = ? WHERE status = 'running'",
            (finished_at, json.dumps([reason])),
        )
    return ids
