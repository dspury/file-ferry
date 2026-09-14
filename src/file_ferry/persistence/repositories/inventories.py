"""Repository for ``source_inventories`` and entries (spec §4.3)."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, fields


@dataclass(frozen=True)
class InventoryRow:
    """One inventory header row."""

    id: int
    root_path: str
    label: str | None
    status: str
    error: str | None
    owner_pid: int | None
    heartbeat_at: str | None
    file_count: int
    dir_count: int
    total_bytes: int
    error_count: int
    excluded_count: int
    manifest_hash: str | None
    started_at: str
    finished_at: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> InventoryRow:
        return cls(**{f.name: row[f.name] for f in fields(cls)})


@dataclass(frozen=True)
class InventoryEntryRow:
    """One inventory entry (file, dir, symlink, other, or error finding)."""

    id: int
    inventory_id: int
    rel_path: str
    entry_type: str
    size: int
    mtime: float | None
    scan_status: str
    error: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> InventoryEntryRow:
        return cls(**{f.name: row[f.name] for f in fields(cls)})


_INV_COLUMNS = (
    "id, root_path, label, status, error, owner_pid, heartbeat_at, "
    "file_count, dir_count, total_bytes, "
    "error_count, excluded_count, manifest_hash, started_at, finished_at"
)


def insert_inventory(conn: sqlite3.Connection, inv: InventoryRow) -> int:
    cur = conn.execute(
        """
        INSERT INTO source_inventories (
            root_path, label, status, error, owner_pid, heartbeat_at,
            file_count, dir_count, total_bytes,
            error_count, excluded_count, manifest_hash, started_at, finished_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            inv.root_path,
            inv.label,
            inv.status,
            inv.error,
            inv.owner_pid,
            inv.heartbeat_at,
            inv.file_count,
            inv.dir_count,
            inv.total_bytes,
            inv.error_count,
            inv.excluded_count,
            inv.manifest_hash,
            inv.started_at,
            inv.finished_at,
        ),
    )
    lastrowid = cur.lastrowid
    if lastrowid is None:
        raise RuntimeError("insert_inventory failed to return a row id")
    return int(lastrowid)


def get_inventory(conn: sqlite3.Connection, inventory_id: int) -> InventoryRow | None:
    row = conn.execute(
        f"SELECT {_INV_COLUMNS} FROM source_inventories WHERE id = ?", (inventory_id,)
    ).fetchone()
    return InventoryRow.from_row(row) if row is not None else None


def insert_entries(
    conn: sqlite3.Connection, inventory_id: int, entries: list[InventoryEntryRow]
) -> None:
    conn.executemany(
        """
        INSERT INTO source_inventory_entries (
            inventory_id, rel_path, entry_type, size, mtime, scan_status, error
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                inventory_id,
                e.rel_path,
                e.entry_type,
                e.size,
                e.mtime,
                e.scan_status,
                e.error,
            )
            for e in entries
        ],
    )


def count_entries(conn: sqlite3.Connection, inventory_id: int) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM source_inventory_entries WHERE inventory_id = ?",
            (inventory_id,),
        ).fetchone()[0]
    )


def page_entries(
    conn: sqlite3.Connection, inventory_id: int, *, limit: int, after_id: int
) -> list[InventoryEntryRow]:
    """Stable ordering by insertion id (entries are written sorted)."""
    rows = conn.execute(
        """
        SELECT id, inventory_id, rel_path, entry_type, size, mtime, scan_status, error
        FROM source_inventory_entries
        WHERE inventory_id = ? AND id > ?
        ORDER BY id ASC
        LIMIT ?
        """,
        (inventory_id, after_id, limit),
    ).fetchall()
    return [InventoryEntryRow.from_row(r) for r in rows]


def finalize_inventory(
    conn: sqlite3.Connection,
    inventory_id: int,
    *,
    status: str,
    file_count: int,
    dir_count: int,
    total_bytes: int,
    error_count: int,
    excluded_count: int,
    manifest_hash: str | None,
    finished_at: str,
    error: str | None = None,
) -> None:
    """Write the terminal state of a scan.

    Counts are written as observed — a failed scan keeps the partial
    counts it actually reached rather than reporting zeros, so the
    inventory never claims it saw nothing when it saw something (spec
    §4.3; the planner refuses to plan from a non-``complete`` inventory
    either way).
    """
    conn.execute(
        """
        UPDATE source_inventories SET
            status = ?, file_count = ?, dir_count = ?, total_bytes = ?,
            error_count = ?, excluded_count = ?, manifest_hash = ?,
            finished_at = ?, error = ?, owner_pid = NULL
        WHERE id = ?
        """,
        (
            status,
            file_count,
            dir_count,
            total_bytes,
            error_count,
            excluded_count,
            manifest_hash,
            finished_at,
            error,
            inventory_id,
        ),
    )


def heartbeat(conn: sqlite3.Connection, inventory_id: int, at: str) -> None:
    """Record liveness for an in-progress scan (crash recovery input)."""
    conn.execute(
        "UPDATE source_inventories SET heartbeat_at = ? WHERE id = ? AND status = 'scanning'",
        (at, inventory_id),
    )


def list_scanning(conn: sqlite3.Connection) -> list[InventoryRow]:
    """Every inventory still marked ``scanning``."""
    rows = conn.execute(
        f"SELECT {_INV_COLUMNS} FROM source_inventories WHERE status = 'scanning' ORDER BY id ASC"
    ).fetchall()
    return [InventoryRow.from_row(r) for r in rows]


def fail_abandoned_scans(
    conn: sqlite3.Connection,
    *,
    finished_at: str,
    reason: str,
    is_live: Callable[[int], bool],
) -> list[int]:
    """Fail ``scanning`` inventories whose owning process is gone.

    A scan lives on a daemon thread, so a process that exits mid-walk
    leaves its inventory ``scanning`` forever and a later planner would
    read a silently partial set as if it were the source. Recovery marks
    those failed, keeping the partial counts and entries visible rather
    than deleting the evidence (spec §7.3).

    ``is_live`` is what keeps this safe when a CLI and the desktop run
    at once: a second process starting up must not shoot down a scan
    that another live owner is still running. A row with no recorded
    owner predates ``owner_pid`` and is treated as abandoned.
    """
    rows = conn.execute(
        "SELECT id, owner_pid FROM source_inventories WHERE status = 'scanning'"
    ).fetchall()
    abandoned = [
        int(r["id"]) for r in rows if r["owner_pid"] is None or not is_live(int(r["owner_pid"]))
    ]
    for inventory_id in abandoned:
        conn.execute(
            "UPDATE source_inventories SET status = 'failed', finished_at = ?, error = ?, "
            "owner_pid = NULL WHERE id = ?",
            (finished_at, reason, inventory_id),
        )
    return abandoned


def count_entries_with_status(conn: sqlite3.Connection, inventory_id: int, scan_status: str) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM source_inventory_entries "
            "WHERE inventory_id = ? AND scan_status = ?",
            (inventory_id, scan_status),
        ).fetchone()[0]
    )


def count_entries_of_type(conn: sqlite3.Connection, inventory_id: int, types: list[str]) -> int:
    placeholders = ", ".join("?" for _ in types)
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM source_inventory_entries "
            f"WHERE inventory_id = ? AND entry_type IN ({placeholders})",
            (inventory_id, *types),
        ).fetchone()[0]
    )
