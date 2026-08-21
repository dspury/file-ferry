"""Repository for the vNext ``replicas`` table."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, fields


@dataclass(frozen=True)
class ReplicaRow:
    """One row from the ``replicas`` table."""

    id: int
    asset_id: str
    project_id: str
    path: str
    volume_fingerprint: str | None
    size: int | None
    checksum: str | None
    checksum_algo: str | None
    verified: int
    verified_at: str | None
    source_checksum: str | None
    availability: str
    last_checked_at: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> ReplicaRow:
        return cls(**{f.name: row[f.name] for f in fields(cls)})


def insert_replica(conn: sqlite3.Connection, replica: ReplicaRow) -> int:
    cur = conn.execute(
        """
        INSERT INTO replicas (
            asset_id, project_id, path, volume_fingerprint, size, checksum,
            checksum_algo, verified, verified_at, source_checksum, availability,
            last_checked_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            replica.asset_id,
            replica.project_id,
            replica.path,
            replica.volume_fingerprint,
            replica.size,
            replica.checksum,
            replica.checksum_algo,
            replica.verified,
            replica.verified_at,
            replica.source_checksum,
            replica.availability,
            replica.last_checked_at,
        ),
    )
    lastrowid = cur.lastrowid
    if lastrowid is None:
        raise RuntimeError("insert_replica failed to return a row id")
    return int(lastrowid)


def get_replica(conn: sqlite3.Connection, replica_id: int) -> ReplicaRow | None:
    row = conn.execute("SELECT * FROM replicas WHERE id = ?", (replica_id,)).fetchone()
    return ReplicaRow.from_row(row) if row is not None else None


def list_replicas(conn: sqlite3.Connection, asset_id: str) -> list[ReplicaRow]:
    rows = conn.execute(
        "SELECT * FROM replicas WHERE asset_id = ? ORDER BY id ASC", (asset_id,)
    ).fetchall()
    return [ReplicaRow.from_row(r) for r in rows]


def record_verification_attempt(
    conn: sqlite3.Connection,
    replica_id: int,
    *,
    checksum: str | None,
    algo: str,
    source_checksum: str,
    verified: bool,
    verified_at: str,
    size: int | None,
    availability: str,
    last_checked_at: str,
) -> None:
    """Record a verification attempt.

    When ``verified`` is False this NEVER overwrites a prior verified
    baseline (ADR-0004 "no silent baseline replacement"): the row keeps
    its prior verified/verified_at/source_checksum values and only the
    current attempt's checksum fields are updated.
    """
    conn.execute(
        """
        UPDATE replicas SET
            checksum = ?,
            checksum_algo = ?,
            size = ?,
            availability = ?,
            last_checked_at = ?
        WHERE id = ?
        """,
        (checksum, algo, size, availability, last_checked_at, replica_id),
    )
    if verified:
        conn.execute(
            """
            UPDATE replicas SET verified = 1, verified_at = ?, source_checksum = ?
            WHERE id = ?
            """,
            (verified_at, source_checksum, replica_id),
        )


def count_verified(conn: sqlite3.Connection, asset_id: str, algo: str) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS n FROM replicas
        WHERE asset_id = ? AND verified = 1 AND checksum_algo = ?
        """,
        (asset_id, algo),
    ).fetchone()
    return int(row["n"])


def has_required_checksum_metadata(conn: sqlite3.Connection, asset_id: str) -> bool:
    row = conn.execute(
        """
        SELECT COUNT(*) AS n FROM replicas WHERE asset_id = ? AND checksum_algo IS NULL
        """,
        (asset_id,),
    ).fetchone()
    return int(row["n"]) == 0
