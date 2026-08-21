"""Repository for the ``derivatives`` table."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, fields


@dataclass(frozen=True)
class DerivativeRow:
    """One row from the ``derivatives`` table."""

    id: int
    asset_id: str
    kind: str
    output_path: str
    settings_fingerprint: str | None
    status: str
    readiness: int
    created_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> DerivativeRow:
        return cls(**{f.name: row[f.name] for f in fields(cls)})


def insert_derivative(conn: sqlite3.Connection, deriv: DerivativeRow) -> int:
    cur = conn.execute(
        """
        INSERT INTO derivatives (
            asset_id, kind, output_path, settings_fingerprint, status, readiness, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            deriv.asset_id,
            deriv.kind,
            deriv.output_path,
            deriv.settings_fingerprint,
            deriv.status,
            deriv.readiness,
            deriv.created_at,
        ),
    )
    lastrowid = cur.lastrowid
    if lastrowid is None:
        raise RuntimeError("insert_derivative failed to return a row id")
    return int(lastrowid)


def get_derivative(
    conn: sqlite3.Connection, asset_id: str, kind: str, output_path: str
) -> DerivativeRow | None:
    row = conn.execute(
        "SELECT * FROM derivatives WHERE asset_id = ? AND kind = ? AND output_path = ?",
        (asset_id, kind, output_path),
    ).fetchone()
    return DerivativeRow.from_row(row) if row is not None else None


def update_status(
    conn: sqlite3.Connection,
    asset_id: str,
    kind: str,
    output_path: str,
    *,
    status: str,
    readiness: int,
) -> None:
    conn.execute(
        """
        UPDATE derivatives SET status = ?, readiness = ?
        WHERE asset_id = ? AND kind = ? AND output_path = ?
        """,
        (status, readiness, asset_id, kind, output_path),
    )


def list_for_asset(conn: sqlite3.Connection, asset_id: str) -> list[DerivativeRow]:
    rows = conn.execute(
        "SELECT * FROM derivatives WHERE asset_id = ? ORDER BY id ASC", (asset_id,)
    ).fetchall()
    return [DerivativeRow.from_row(r) for r in rows]
