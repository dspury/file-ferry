"""Repository for the vNext ``assets`` table."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, fields


@dataclass(frozen=True)
class AssetRow:
    """One row from the ``assets`` table."""

    id: str
    source_id: int | None
    source_relative_path: str
    observed_size: int | None
    observed_mtime: float | None
    observed_checksum: str | None
    checksum_algo: str | None
    lifecycle_state: str
    media_kind: str | None
    probed_at: str | None
    first_seen_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> AssetRow:
        return cls(**{f.name: row[f.name] for f in fields(cls)})


def insert_asset(conn: sqlite3.Connection, asset: AssetRow) -> None:
    conn.execute(
        """
        INSERT INTO assets (
            id, source_id, source_relative_path, observed_size, observed_mtime,
            observed_checksum, checksum_algo, lifecycle_state, media_kind,
            probed_at, first_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            asset.id,
            asset.source_id,
            asset.source_relative_path,
            asset.observed_size,
            asset.observed_mtime,
            asset.observed_checksum,
            asset.checksum_algo,
            asset.lifecycle_state,
            asset.media_kind,
            asset.probed_at,
            asset.first_seen_at,
        ),
    )


def get_asset(conn: sqlite3.Connection, asset_id: str) -> AssetRow | None:
    row = conn.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
    return AssetRow.from_row(row) if row is not None else None


def get_asset_by_path(conn: sqlite3.Connection, source_id: int, rel_path: str) -> AssetRow | None:
    row = conn.execute(
        "SELECT * FROM assets WHERE source_id = ? AND source_relative_path = ?",
        (source_id, rel_path),
    ).fetchone()
    return AssetRow.from_row(row) if row is not None else None


def list_assets(conn: sqlite3.Connection, project_id: str | None = None) -> list[AssetRow]:
    if project_id is None:
        rows = conn.execute("SELECT * FROM assets ORDER BY source_relative_path ASC").fetchall()
    else:
        rows = conn.execute(
            """
            SELECT DISTINCT a.* FROM assets a
            JOIN replicas r ON r.asset_id = a.id
            WHERE r.project_id = ?
            ORDER BY a.source_relative_path ASC
            """,
            (project_id,),
        ).fetchall()
    return [AssetRow.from_row(r) for r in rows]


def update_observed_checksum(
    conn: sqlite3.Connection,
    asset_id: str,
    *,
    checksum: str,
    algo: str,
    lifecycle_state: str | None = None,
) -> None:
    updates = ["observed_checksum = ?", "checksum_algo = ?"]
    values: list[object] = [checksum, algo]
    if lifecycle_state is not None:
        updates.append("lifecycle_state = ?")
        values.append(lifecycle_state)
    values.append(asset_id)
    conn.execute(f"UPDATE assets SET {', '.join(updates)} WHERE id = ?", tuple(values))
