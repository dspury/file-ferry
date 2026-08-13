"""Repository for the ``organization_profiles`` table."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, fields


@dataclass(frozen=True)
class ProfileRow:
    """One row from the ``organization_profiles`` table."""

    id: int
    name: str
    version: int
    template: str
    conflict_policy: str
    mutation_policy: str
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> ProfileRow:
        return cls(**{f.name: row[f.name] for f in fields(cls)})


def insert_profile(conn: sqlite3.Connection, profile: ProfileRow) -> int:
    cur = conn.execute(
        """
        INSERT INTO organization_profiles (
            name, version, template, conflict_policy, mutation_policy, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            profile.name,
            profile.version,
            profile.template,
            profile.conflict_policy,
            profile.mutation_policy,
            profile.created_at,
            profile.updated_at,
        ),
    )
    lastrowid = cur.lastrowid
    if lastrowid is None:
        raise RuntimeError("insert_profile failed to return a row id")
    return int(lastrowid)


def get_profile(conn: sqlite3.Connection, profile_id: int) -> ProfileRow | None:
    row = conn.execute("SELECT * FROM organization_profiles WHERE id = ?", (profile_id,)).fetchone()
    return ProfileRow.from_row(row) if row is not None else None


def get_profile_by_name(conn: sqlite3.Connection, name: str) -> ProfileRow | None:
    row = conn.execute("SELECT * FROM organization_profiles WHERE name = ?", (name,)).fetchone()
    return ProfileRow.from_row(row) if row is not None else None


def list_profiles(conn: sqlite3.Connection) -> list[ProfileRow]:
    rows = conn.execute(
        "SELECT * FROM organization_profiles ORDER BY name ASC, version DESC"
    ).fetchall()
    return [ProfileRow.from_row(r) for r in rows]


def bump_version(
    conn: sqlite3.Connection,
    profile_id: int,
    *,
    template: str,
    conflict_policy: str,
    mutation_policy: str,
    version: int,
    updated_at: str,
) -> None:
    conn.execute(
        """
        UPDATE organization_profiles SET
            template = ?, conflict_policy = ?, mutation_policy = ?, version = ?, updated_at = ?
        WHERE id = ?
        """,
        (template, conflict_policy, mutation_policy, version, updated_at, profile_id),
    )
