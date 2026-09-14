"""Repository for transfer execution state (spec §7.2/§7.3, migration 005).

The execution tables are the runner's durable ledger: one row per
started transfer, per-entry crash-window state, cross-job path
reservations, and the database-first receipt. Rows are mutated by the
runner as work proceeds — unlike plans, which are immutable — but every
mutation records *more* evidence, never less.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, fields


@dataclass(frozen=True)
class TransferExecutionRow:
    id: str
    job_id: str
    plan_id: str
    fingerprint: str
    dest_root: str
    dest_st_dev: int | None
    binding_json: str
    state: str
    started_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> TransferExecutionRow:
        return cls(**{f.name: row[f.name] for f in fields(cls)})


@dataclass(frozen=True)
class TransferReceiptRow:
    """One row from the ``transfer_receipts`` table."""

    execution_id: str
    plan_id: str
    fingerprint: str
    receipt_json: str
    receipt_hash: str
    final_state: str
    written_at: str
    exported_path: str | None
    export_error: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> TransferReceiptRow:
        return cls(**{f.name: row[f.name] for f in fields(cls)})


@dataclass(frozen=True)
class TransferExecutionItemRow:
    execution_id: str
    plan_entry_id: int
    dest_rel_path: str
    source_path: str
    size: int
    state: str
    temp_path: str | None
    source_checksum: str | None
    dest_checksum: str | None
    checksum_algo: str | None
    bytes_copied: int
    error: str | None
    warning: str | None
    updated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> TransferExecutionItemRow:
        return cls(**{f.name: row[f.name] for f in fields(cls)})


_EXEC_COLUMNS = (
    "id, job_id, plan_id, fingerprint, dest_root, dest_st_dev, binding_json, "
    "state, started_at, updated_at"
)

_ITEM_COLUMNS = (
    "execution_id, plan_entry_id, dest_rel_path, source_path, size, state, "
    "temp_path, source_checksum, dest_checksum, checksum_algo, bytes_copied, "
    "error, warning, updated_at"
)


def insert_execution(conn: sqlite3.Connection, execution: TransferExecutionRow) -> None:
    conn.execute(
        f"INSERT INTO transfer_executions ({_EXEC_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            execution.id,
            execution.job_id,
            execution.plan_id,
            execution.fingerprint,
            execution.dest_root,
            execution.dest_st_dev,
            execution.binding_json,
            execution.state,
            execution.started_at,
            execution.updated_at,
        ),
    )


def update_execution_state(
    conn: sqlite3.Connection,
    execution_id: str,
    *,
    state: str,
    updated_at: str,
    dest_st_dev: int | None = None,
) -> None:
    if dest_st_dev is None:
        conn.execute(
            "UPDATE transfer_executions SET state = ?, updated_at = ? WHERE id = ?",
            (state, updated_at, execution_id),
        )
    else:
        conn.execute(
            "UPDATE transfer_executions SET state = ?, updated_at = ?, dest_st_dev = ? "
            "WHERE id = ?",
            (state, updated_at, dest_st_dev, execution_id),
        )


def get_execution(conn: sqlite3.Connection, execution_id: str) -> TransferExecutionRow | None:
    row = conn.execute(
        f"SELECT {_EXEC_COLUMNS} FROM transfer_executions WHERE id = ?", (execution_id,)
    ).fetchone()
    return TransferExecutionRow.from_row(row) if row is not None else None


def get_execution_by_job(conn: sqlite3.Connection, job_id: str) -> TransferExecutionRow | None:
    row = conn.execute(
        f"SELECT {_EXEC_COLUMNS} FROM transfer_executions WHERE job_id = ?", (job_id,)
    ).fetchone()
    return TransferExecutionRow.from_row(row) if row is not None else None


def latest_execution_for_plan(
    conn: sqlite3.Connection, plan_id: str
) -> TransferExecutionRow | None:
    row = conn.execute(
        f"SELECT {_EXEC_COLUMNS} FROM transfer_executions WHERE plan_id = ? "
        "ORDER BY started_at DESC, id DESC LIMIT 1",
        (plan_id,),
    ).fetchone()
    return TransferExecutionRow.from_row(row) if row is not None else None


def latest_execution_for_fingerprint(
    conn: sqlite3.Connection, fingerprint: str
) -> TransferExecutionRow | None:
    row = conn.execute(
        f"SELECT {_EXEC_COLUMNS} FROM transfer_executions WHERE fingerprint = ? "
        "ORDER BY started_at DESC, id DESC LIMIT 1",
        (fingerprint,),
    ).fetchone()
    return TransferExecutionRow.from_row(row) if row is not None else None


# ---- items -----------------------------------------------------------------


def insert_execution_items(conn: sqlite3.Connection, items: list[TransferExecutionItemRow]) -> None:
    conn.executemany(
        f"INSERT INTO transfer_execution_items ({_ITEM_COLUMNS}) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                i.execution_id,
                i.plan_entry_id,
                i.dest_rel_path,
                i.source_path,
                i.size,
                i.state,
                i.temp_path,
                i.source_checksum,
                i.dest_checksum,
                i.checksum_algo,
                i.bytes_copied,
                i.error,
                i.warning,
                i.updated_at,
            )
            for i in items
        ],
    )


def get_execution_items(
    conn: sqlite3.Connection, execution_id: str
) -> list[TransferExecutionItemRow]:
    rows = conn.execute(
        f"SELECT {_ITEM_COLUMNS} FROM transfer_execution_items "
        "WHERE execution_id = ? ORDER BY plan_entry_id ASC",
        (execution_id,),
    ).fetchall()
    return [TransferExecutionItemRow.from_row(r) for r in rows]


def get_execution_item(
    conn: sqlite3.Connection, execution_id: str, plan_entry_id: int
) -> TransferExecutionItemRow | None:
    row = conn.execute(
        f"SELECT {_ITEM_COLUMNS} FROM transfer_execution_items "
        "WHERE execution_id = ? AND plan_entry_id = ?",
        (execution_id, plan_entry_id),
    ).fetchone()
    return TransferExecutionItemRow.from_row(row) if row is not None else None


def update_execution_item(
    conn: sqlite3.Connection,
    execution_id: str,
    plan_entry_id: int,
    *,
    state: str | None = None,
    temp_path: str | None = None,
    clear_temp: bool = False,
    source_checksum: str | None = None,
    dest_checksum: str | None = None,
    checksum_algo: str | None = None,
    bytes_copied: int | None = None,
    error: str | None = None,
    clear_error: bool = False,
    warning: str | None = None,
    updated_at: str = "",
) -> None:
    """Update one item row, setting only the fields supplied.

    ``clear_temp`` exists because ``temp_path`` is nullable and a value
    of ``None`` must mean "leave alone" for every optional field — the
    runner clears the temp explicitly once the copy it tracked is done.
    ``clear_error`` is the same idea for ``error``: a resume re-arming a
    previously failed item has to drop the stale reason, or the receipt
    reports an error for an item that went on to succeed.
    """
    sets: list[str] = []
    params: list[object] = []
    if state is not None:
        sets.append("state = ?")
        params.append(state)
    if clear_temp:
        sets.append("temp_path = NULL")
    elif temp_path is not None:
        sets.append("temp_path = ?")
        params.append(temp_path)
    if source_checksum is not None:
        sets.append("source_checksum = ?")
        params.append(source_checksum)
    if dest_checksum is not None:
        sets.append("dest_checksum = ?")
        params.append(dest_checksum)
    if checksum_algo is not None:
        sets.append("checksum_algo = ?")
        params.append(checksum_algo)
    if bytes_copied is not None:
        sets.append("bytes_copied = ?")
        params.append(bytes_copied)
    if clear_error:
        sets.append("error = NULL")
    elif error is not None:
        sets.append("error = ?")
        params.append(error)
    if warning is not None:
        sets.append("warning = ?")
        params.append(warning)
    if updated_at:
        sets.append("updated_at = ?")
        params.append(updated_at)
    if not sets:
        return
    params.extend([execution_id, plan_entry_id])
    conn.execute(
        f"UPDATE transfer_execution_items SET {', '.join(sets)} "
        "WHERE execution_id = ? AND plan_entry_id = ?",
        params,
    )


# ---- reservations (spec §6.4 cross-job serialization) ---------------------


def active_reservation_conflicts(
    conn: sqlite3.Connection, dest_root: str, rel_paths: list[str]
) -> dict[str, str]:
    """Map each ``rel_path`` already actively reserved to its holder.

    The holder is named as the *job* id, because that is what an
    operator can act on (status, cancel, or wait). Returns only
    conflicts; a path reserved by this same execution is not a conflict
    and is absent (the caller passes its own execution id).
    """
    if not rel_paths:
        return {}
    placeholders = ", ".join("?" for _ in rel_paths)
    rows = conn.execute(
        "SELECT r.rel_path, r.execution_id, e.job_id FROM transfer_path_reservations r "
        "JOIN transfer_executions e ON e.id = r.execution_id "
        f"WHERE r.released_at IS NULL AND r.dest_root = ? AND r.rel_path IN ({placeholders})",
        [dest_root, *rel_paths],
    ).fetchall()
    return {row["rel_path"]: row["job_id"] for row in rows}


def insert_reservations(
    conn: sqlite3.Connection,
    *,
    dest_root: str,
    rel_paths: list[str],
    execution_id: str,
    acquired_at: str,
) -> None:
    conn.executemany(
        "INSERT INTO transfer_path_reservations (dest_root, rel_path, execution_id, acquired_at) "
        "VALUES (?, ?, ?, ?)",
        [(dest_root, rel, execution_id, acquired_at) for rel in rel_paths],
    )


def release_reservations(conn: sqlite3.Connection, execution_id: str, *, released_at: str) -> int:
    cur = conn.execute(
        "UPDATE transfer_path_reservations SET released_at = ? "
        "WHERE execution_id = ? AND released_at IS NULL",
        (released_at, execution_id),
    )
    return cur.rowcount


def release_reservations_for_dead_executions(
    conn: sqlite3.Connection, *, alive_job_states: set[str], released_at: str
) -> list[str]:
    """Release reservations held by executions whose job is not alive.

    Called at bootstrap: a crash can leave rows held forever otherwise.
    ``alive_job_states`` is the set of job states that may still run
    (``queued``, ``running``, ``verifying``, ``needs_attention``,
    ``resumable``); anything else means the execution is over and its
    paths are free. Returns the execution ids whose reservations were
    released, for the log.
    """
    placeholders = ", ".join("?" for _ in alive_job_states)
    rows = conn.execute(
        "SELECT DISTINCT r.execution_id FROM transfer_path_reservations r "
        "JOIN transfer_executions e ON e.id = r.execution_id "
        "JOIN jobs j ON j.id = e.job_id "
        f"WHERE r.released_at IS NULL AND j.state NOT IN ({placeholders})",
        list(alive_job_states),
    ).fetchall()
    ids = [row["execution_id"] for row in rows]
    for execution_id in ids:
        conn.execute(
            "UPDATE transfer_path_reservations SET released_at = ? "
            "WHERE execution_id = ? AND released_at IS NULL",
            (released_at, execution_id),
        )
    return ids


# ---- receipts (database first; export visible and retriable) ---------------


def upsert_receipt(
    conn: sqlite3.Connection,
    *,
    execution_id: str,
    plan_id: str,
    fingerprint: str,
    receipt_json: str,
    receipt_hash: str,
    final_state: str,
    written_at: str,
) -> None:
    conn.execute(
        """
        INSERT INTO transfer_receipts (
            execution_id, plan_id, fingerprint, receipt_json, receipt_hash,
            final_state, written_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (execution_id) DO UPDATE SET
            plan_id = excluded.plan_id,
            fingerprint = excluded.fingerprint,
            receipt_json = excluded.receipt_json,
            receipt_hash = excluded.receipt_hash,
            final_state = excluded.final_state,
            written_at = excluded.written_at
        """,
        (execution_id, plan_id, fingerprint, receipt_json, receipt_hash, final_state, written_at),
    )


def get_receipt(conn: sqlite3.Connection, execution_id: str) -> TransferReceiptRow | None:
    row = conn.execute(
        "SELECT execution_id, plan_id, fingerprint, receipt_json, receipt_hash, "
        "final_state, written_at, exported_path, export_error "
        "FROM transfer_receipts WHERE execution_id = ?",
        (execution_id,),
    ).fetchone()
    return TransferReceiptRow.from_row(row) if row is not None else None


def latest_receipt_for_plan(conn: sqlite3.Connection, plan_id: str) -> TransferReceiptRow | None:
    row = conn.execute(
        "SELECT r.execution_id, r.plan_id, r.fingerprint, r.receipt_json, r.receipt_hash, "
        "r.final_state, r.written_at, r.exported_path, r.export_error "
        "FROM transfer_receipts r JOIN transfer_executions e ON e.id = r.execution_id "
        "WHERE r.plan_id = ? ORDER BY e.started_at DESC, e.id DESC LIMIT 1",
        (plan_id,),
    ).fetchone()
    return TransferReceiptRow.from_row(row) if row is not None else None


def mark_receipt_exported(
    conn: sqlite3.Connection, execution_id: str, *, exported_path: str
) -> None:
    conn.execute(
        "UPDATE transfer_receipts SET exported_path = ?, export_error = NULL "
        "WHERE execution_id = ?",
        (exported_path, execution_id),
    )


def mark_receipt_export_failed(conn: sqlite3.Connection, execution_id: str, *, error: str) -> None:
    conn.execute(
        "UPDATE transfer_receipts SET exported_path = NULL, export_error = ? "
        "WHERE execution_id = ?",
        (error, execution_id),
    )


# ---- prior provenance (spec §6.4 repeated transfers) -----------------------


def prior_committed_mapping(
    conn: sqlite3.Connection,
    *,
    source_path: str,
    dest_rel_path: str,
    dest_root: str,
    exclude_execution_id: str,
) -> tuple[str, str] | None:
    """Find a checksum pair a *prior* execution committed for this mapping.

    Provenance for reuse (§6.4): an output may be adopted only when some
    earlier Ferry execution committed the same source to the same
    destination root and relative path, with the checksums it verified.
    Returns ``(source_checksum, dest_checksum)`` or ``None``; the caller
    must still verify the bytes on disk against both — the record says
    what *was* true, the checksums say what *is*.
    """
    row = conn.execute(
        """
        SELECT i.source_checksum, i.dest_checksum
        FROM transfer_execution_items i
        JOIN transfer_executions e ON e.id = i.execution_id
        WHERE i.source_path = ? AND i.dest_rel_path = ? AND i.execution_id != ?
          AND i.state IN ('committed', 'reused', 'skipped_identical')
          AND e.dest_root = ?
          AND i.source_checksum IS NOT NULL AND i.dest_checksum IS NOT NULL
        LIMIT 1
        """,
        (source_path, dest_rel_path, exclude_execution_id, dest_root),
    ).fetchone()
    return (row["source_checksum"], row["dest_checksum"]) if row is not None else None
