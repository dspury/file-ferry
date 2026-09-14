"""Repository for the ``saved_destinations`` table (spec §4.1)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, fields


@dataclass(frozen=True)
class SavedDestinationRow:
    """One row from ``saved_destinations``."""

    id: int
    name: str
    location_kind: str
    last_root_path: str
    subfolder_path: str | None
    identity_kind: str | None
    identity_value: str | None
    identity_confidence: str | None
    identity_provenance: str | None
    default_preset_id: int | None
    pinned_revision: int | None
    conflict_policy: str
    checksum_algo: str
    free_space_reserve: int
    last_binding_path: str | None
    last_seen_at: str | None
    created_at: str
    updated_at: str
    archived_at: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> SavedDestinationRow:
        return cls(**{f.name: row[f.name] for f in fields(cls)})


def insert_destination(conn: sqlite3.Connection, dest: SavedDestinationRow) -> int:
    cur = conn.execute(
        """
        INSERT INTO saved_destinations (
            name, location_kind, last_root_path, subfolder_path,
            identity_kind, identity_value, identity_confidence, identity_provenance,
            default_preset_id, pinned_revision, conflict_policy, checksum_algo,
            free_space_reserve, last_binding_path, last_seen_at,
            created_at, updated_at, archived_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            dest.name,
            dest.location_kind,
            dest.last_root_path,
            dest.subfolder_path,
            dest.identity_kind,
            dest.identity_value,
            dest.identity_confidence,
            dest.identity_provenance,
            dest.default_preset_id,
            dest.pinned_revision,
            dest.conflict_policy,
            dest.checksum_algo,
            dest.free_space_reserve,
            dest.last_binding_path,
            dest.last_seen_at,
            dest.created_at,
            dest.updated_at,
            dest.archived_at,
        ),
    )
    lastrowid = cur.lastrowid
    if lastrowid is None:
        raise RuntimeError("insert_destination failed to return a row id")
    return int(lastrowid)


_COLUMNS = (
    "id, name, location_kind, last_root_path, subfolder_path, "
    "identity_kind, identity_value, identity_confidence, identity_provenance, "
    "default_preset_id, pinned_revision, conflict_policy, checksum_algo, "
    "free_space_reserve, last_binding_path, last_seen_at, "
    "created_at, updated_at, archived_at"
)


def get_destination(conn: sqlite3.Connection, dest_id: int) -> SavedDestinationRow | None:
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM saved_destinations WHERE id = ?", (dest_id,)
    ).fetchone()
    return SavedDestinationRow.from_row(row) if row is not None else None


def list_destinations(
    conn: sqlite3.Connection, *, include_archived: bool = False
) -> list[SavedDestinationRow]:
    query = f"SELECT {_COLUMNS} FROM saved_destinations"
    if not include_archived:
        query += " WHERE archived_at IS NULL"
    query += " ORDER BY name ASC, id ASC"
    return [SavedDestinationRow.from_row(r) for r in conn.execute(query).fetchall()]


def update_destination(
    conn: sqlite3.Connection,
    dest_id: int,
    *,
    name: str | None = None,
    last_root_path: str | None = None,
    subfolder_path: str | None = None,
    identity_kind: str | None = None,
    identity_value: str | None = None,
    identity_confidence: str | None = None,
    identity_provenance: str | None = None,
    default_preset_id: int | None = None,
    pinned_revision: int | None = None,
    conflict_policy: str | None = None,
    checksum_algo: str | None = None,
    free_space_reserve: int | None = None,
    last_binding_path: str | None = None,
    last_seen_at: str | None = None,
    updated_at: str | None = None,
    archived_at: str | None = None,
    clear_pinned_revision: bool = False,
    clear_default_preset_id: bool = False,
) -> None:
    """Update the named columns; ``None`` means "leave alone".

    Clearing a nullable column therefore needs an explicit flag —
    otherwise a destination could never drop its preset pin, and a
    stale pin is exactly the thing that silently re-routes a transfer.
    """
    updates: list[str] = []
    values: list[object] = []
    if clear_pinned_revision:
        updates.append("pinned_revision = NULL")
    if clear_default_preset_id:
        updates.append("default_preset_id = NULL")
    for column, value in (
        ("name", name),
        ("last_root_path", last_root_path),
        ("subfolder_path", subfolder_path),
        ("identity_kind", identity_kind),
        ("identity_value", identity_value),
        ("identity_confidence", identity_confidence),
        ("identity_provenance", identity_provenance),
        ("default_preset_id", default_preset_id),
        ("pinned_revision", pinned_revision),
        ("conflict_policy", conflict_policy),
        ("checksum_algo", checksum_algo),
        ("free_space_reserve", free_space_reserve),
        ("last_binding_path", last_binding_path),
        ("last_seen_at", last_seen_at),
        ("updated_at", updated_at),
        ("archived_at", archived_at),
    ):
        if value is None:
            continue
        if column == "pinned_revision" and clear_pinned_revision:
            continue
        if column == "default_preset_id" and clear_default_preset_id:
            continue
        updates.append(f"{column} = ?")
        values.append(value)
    if not updates:
        return
    values.append(dest_id)
    conn.execute(f"UPDATE saved_destinations SET {', '.join(updates)} WHERE id = ?", tuple(values))


def destinations_by_identity(
    conn: sqlite3.Connection, identity_kind: str, identity_value: str
) -> list[SavedDestinationRow]:
    """All saved destinations sharing one strong identity value.

    More than one is legal (multiple folders on one volume), but a
    *conflicting* identity match across differing mount paths is what
    ambiguity detection consumes (spec §5.1).
    """
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM saved_destinations "
        "WHERE identity_kind = ? AND identity_value = ? AND archived_at IS NULL "
        "ORDER BY id ASC",
        (identity_kind, identity_value),
    ).fetchall()
    return [SavedDestinationRow.from_row(r) for r in rows]


def get_destination_by_name(conn: sqlite3.Connection, name: str) -> SavedDestinationRow | None:
    """Look up one destination by display name (case-insensitive)."""
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM saved_destinations WHERE LOWER(name) = LOWER(?)",
        (name,),
    ).fetchall()
    return SavedDestinationRow.from_row(rows[0]) if rows else None
