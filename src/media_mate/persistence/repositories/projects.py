"""Repository for the vNext ``projects`` table."""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass, fields


@dataclass(frozen=True)
class ProjectRow:
    """One row from the vNext ``projects`` table."""

    id: str
    name: str
    status: str
    working_root: str
    backup_root: str | None
    storage_policy: str
    organization_profile_id: int | None
    proxy_defaults: str | None
    resolve_defaults: str | None
    created_at: str
    updated_at: str
    archived_at: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> ProjectRow:
        """Build from a ``sqlite3.Row`` by column name."""
        return cls(**{f.name: row[f.name] for f in fields(cls)})


_COLUMNS = ",".join(f.name for f in fields(ProjectRow))


def insert_project(conn: sqlite3.Connection, project: ProjectRow) -> None:
    conn.execute(
        f"INSERT INTO projects ({_COLUMNS}) VALUES ({','.join('?' * len(fields(ProjectRow)))})",
        tuple(asdict(project).values()),
    )


def get_project(conn: sqlite3.Connection, project_id: str) -> ProjectRow | None:
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return ProjectRow.from_row(row) if row is not None else None


def get_project_by_name(conn: sqlite3.Connection, name: str) -> ProjectRow | None:
    row = conn.execute("SELECT * FROM projects WHERE name = ?", (name,)).fetchone()
    return ProjectRow.from_row(row) if row is not None else None


def list_projects(conn: sqlite3.Connection) -> list[ProjectRow]:
    rows = conn.execute("SELECT * FROM projects ORDER BY created_at ASC, name ASC").fetchall()
    return [ProjectRow.from_row(row) for row in rows]


def update_project(
    conn: sqlite3.Connection,
    project_id: str,
    *,
    name: str | None = None,
    status: str | None = None,
    working_root: str | None = None,
    backup_root: str | None = None,
    storage_policy: str | None = None,
    organization_profile_id: int | None = None,
    proxy_defaults: str | None = None,
    resolve_defaults: str | None = None,
    updated_at: str | None = None,
    archived_at: str | None = None,
) -> None:
    """Update the mutable fields of a project. ``None`` leaves a field unchanged."""
    updates: list[str] = []
    values: list[object] = []
    for column, value in (
        ("name", name),
        ("status", status),
        ("working_root", working_root),
        ("backup_root", backup_root),
        ("storage_policy", storage_policy),
        ("organization_profile_id", organization_profile_id),
        ("proxy_defaults", proxy_defaults),
        ("resolve_defaults", resolve_defaults),
        ("updated_at", updated_at),
        ("archived_at", archived_at),
    ):
        if value is not None:
            updates.append(f"{column} = ?")
            values.append(value)
    if not updates:
        return
    values.append(project_id)
    conn.execute(
        f"UPDATE projects SET {', '.join(updates)} WHERE id = ?",
        tuple(values),
    )
