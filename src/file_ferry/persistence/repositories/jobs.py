"""Repository for ``jobs``, ``job_steps``, and ``job_items``."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, fields


@dataclass(frozen=True)
class JobRow:
    """One row from the ``jobs`` table."""

    id: str
    project_id: str
    session_id: str | None
    command: str
    args_fingerprint: str | None
    state: str
    owner: str | None
    current_step: str | None
    total_steps: int
    started_at: str | None
    updated_at: str
    finished_at: str | None
    error: str | None
    resumable: int

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> JobRow:
        return cls(**{f.name: row[f.name] for f in fields(cls)})


@dataclass(frozen=True)
class JobStepRow:
    """One row from the ``job_steps`` table."""

    id: int
    job_id: str
    step: str
    state: str
    started_at: str | None
    finished_at: str | None
    error: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> JobStepRow:
        return cls(**{f.name: row[f.name] for f in fields(cls)})


@dataclass(frozen=True)
class JobItemRow:
    """One row from the ``job_items`` table."""

    id: int
    job_id: str
    step: str
    asset_id: str | None
    source_path: str | None
    dest_path: str | None
    temp_path: str | None
    byte_progress: int
    total_bytes: int | None
    state: str
    error: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> JobItemRow:
        return cls(**{f.name: row[f.name] for f in fields(cls)})


def insert_job(conn: sqlite3.Connection, job: JobRow) -> None:
    conn.execute(
        """
        INSERT INTO jobs (
            id, project_id, session_id, command, args_fingerprint, state, owner,
            current_step, total_steps, started_at, updated_at, finished_at, error, resumable
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job.id,
            job.project_id,
            job.session_id,
            job.command,
            job.args_fingerprint,
            job.state,
            job.owner,
            job.current_step,
            job.total_steps,
            job.started_at,
            job.updated_at,
            job.finished_at,
            job.error,
            job.resumable,
        ),
    )


def get_job(conn: sqlite3.Connection, job_id: str) -> JobRow | None:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return JobRow.from_row(row) if row is not None else None


def list_jobs(conn: sqlite3.Connection, project_id: str | None = None) -> list[JobRow]:
    if project_id is None:
        rows = conn.execute("SELECT * FROM jobs ORDER BY updated_at DESC, id DESC").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE project_id = ? ORDER BY updated_at DESC, id DESC",
            (project_id,),
        ).fetchall()
    return [JobRow.from_row(r) for r in rows]


def update_job(
    conn: sqlite3.Connection,
    job_id: str,
    *,
    state: str | None = None,
    current_step: str | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    updated_at: str | None = None,
    error: str | None = None,
    resumable: int | None = None,
) -> None:
    updates: list[str] = []
    values: list[object] = []
    for column, value in (
        ("state", state),
        ("current_step", current_step),
        ("started_at", started_at),
        ("finished_at", finished_at),
        ("updated_at", updated_at),
        ("error", error),
        ("resumable", resumable),
    ):
        if value is not None:
            updates.append(f"{column} = ?")
            values.append(value)
    if not updates:
        return
    values.append(job_id)
    conn.execute(f"UPDATE jobs SET {', '.join(updates)} WHERE id = ?", tuple(values))


def insert_step(conn: sqlite3.Connection, step: JobStepRow) -> None:
    conn.execute(
        """
        INSERT INTO job_steps (job_id, step, state, started_at, finished_at, error)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (step.job_id, step.step, step.state, step.started_at, step.finished_at, step.error),
    )


def get_steps(conn: sqlite3.Connection, job_id: str) -> list[JobStepRow]:
    rows = conn.execute(
        "SELECT * FROM job_steps WHERE job_id = ? ORDER BY id ASC", (job_id,)
    ).fetchall()
    return [JobStepRow.from_row(r) for r in rows]


def update_step(
    conn: sqlite3.Connection,
    job_id: str,
    step: str,
    *,
    state: str | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    error: str | None = None,
) -> None:
    updates: list[str] = []
    values: list[object] = []
    for column, value in (
        ("state", state),
        ("started_at", started_at),
        ("finished_at", finished_at),
        ("error", error),
    ):
        if value is not None:
            updates.append(f"{column} = ?")
            values.append(value)
    if not updates:
        return
    values.append(job_id)
    values.append(step)
    conn.execute(
        f"UPDATE job_steps SET {', '.join(updates)} WHERE job_id = ? AND step = ?",
        tuple(values),
    )


def insert_item(conn: sqlite3.Connection, item: JobItemRow) -> None:
    conn.execute(
        """
        INSERT INTO job_items (
            job_id, step, asset_id, source_path, dest_path, temp_path,
            byte_progress, total_bytes, state, error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item.job_id,
            item.step,
            item.asset_id,
            item.source_path,
            item.dest_path,
            item.temp_path,
            item.byte_progress,
            item.total_bytes,
            item.state,
            item.error,
        ),
    )


@dataclass(frozen=True)
class JobItemProgress:
    """Aggregated per-file progress for one job."""

    total: int
    completed: int
    failed: int
    bytes_done: int
    bytes_total: int


def item_progress(conn: sqlite3.Connection, job_id: str) -> JobItemProgress:
    """Summarise a job's items in one query.

    Aggregated in SQL rather than by loading the rows: a camera card can be
    tens of thousands of items and this is read on every progress event.
    """
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS total,
            COALESCE(SUM(state = 'succeeded'), 0) AS completed,
            COALESCE(SUM(state = 'failed'), 0) AS failed,
            COALESCE(SUM(byte_progress), 0) AS bytes_done,
            COALESCE(SUM(total_bytes), 0) AS bytes_total
        FROM job_items
        WHERE job_id = ?
        """,
        (job_id,),
    ).fetchone()
    return JobItemProgress(
        total=int(row["total"]),
        completed=int(row["completed"]),
        failed=int(row["failed"]),
        bytes_done=int(row["bytes_done"]),
        bytes_total=int(row["bytes_total"]),
    )


def get_items(conn: sqlite3.Connection, job_id: str) -> list[JobItemRow]:
    rows = conn.execute(
        "SELECT * FROM job_items WHERE job_id = ? ORDER BY id ASC", (job_id,)
    ).fetchall()
    return [JobItemRow.from_row(r) for r in rows]


def update_item_progress(
    conn: sqlite3.Connection,
    job_id: str,
    asset_id: str,
    *,
    byte_progress: int | None = None,
    state: str | None = None,
    error: str | None = None,
) -> None:
    updates: list[str] = []
    values: list[object] = []
    for column, value in (
        ("byte_progress", byte_progress),
        ("state", state),
        ("error", error),
    ):
        if value is not None:
            updates.append(f"{column} = ?")
            values.append(value)
    if not updates:
        return
    values.append(job_id)
    values.append(asset_id)
    conn.execute(
        f"UPDATE job_items SET {', '.join(updates)} WHERE job_id = ? AND asset_id = ?",
        tuple(values),
    )
