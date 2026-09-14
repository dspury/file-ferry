"""Repository for ``transfer_plans`` and entries (spec §4.3).

Plans are immutable records: the only mutation after creation is the
approval-state transition (draft → approved, or invalidation), never
the mapped substance. A changed substance is a different fingerprint
and therefore a new plan.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, fields


@dataclass(frozen=True)
class TransferPlanRow:
    """One immutable plan header."""

    id: str
    destination_id: int | None
    destination_binding_path: str
    preset_id: int | None
    preset_revision: int | None
    preset_content_hash: str | None
    project_id: str | None
    inventory_snapshot_json: str
    destination_identity_json: str | None
    conflict_policy: str
    checksum_algo: str
    free_space_reserve: int
    free_bytes: int | None
    blocking_count: int
    decisions_json: str
    preset_review_json: str
    rule_exclusion_count: int
    derived_from: str | None
    superseded_by: str | None
    category_map_version: int
    fingerprint: str
    status: str
    approved_fingerprint: str | None
    capacity_ok: int
    capacity_unknown: int
    capacity_override_reason: str | None
    needed_bytes: int
    total_bytes: int
    total_files: int
    conflict_count: int
    exclusion_count: int
    warnings_json: str
    created_at: str
    approved_at: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> TransferPlanRow:
        return cls(**{f.name: row[f.name] for f in fields(cls)})


@dataclass(frozen=True)
class TransferPlanEntryRow:
    """One planned mapping."""

    id: int
    plan_id: str
    inventory_id: int | None
    inventory_entry_id: int | None
    source_path: str
    rel_path: str
    entry_type: str
    dest_rel_path: str
    matched_rule: str | None
    size: int
    mtime: float | None
    action: str
    conflict: str | None
    exclusion_reason: str | None
    excluded_by_user: int
    renamed_from: str | None
    group_id: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> TransferPlanEntryRow:
        return cls(**{f.name: row[f.name] for f in fields(cls)})


_PLAN_COLUMNS = (
    "id, destination_id, destination_binding_path, preset_id, preset_revision, "
    "preset_content_hash, project_id, inventory_snapshot_json, "
    "destination_identity_json, conflict_policy, checksum_algo, free_space_reserve, "
    "free_bytes, blocking_count, decisions_json, preset_review_json, "
    "rule_exclusion_count, derived_from, superseded_by, category_map_version, "
    "fingerprint, status, approved_fingerprint, "
    "capacity_ok, capacity_unknown, capacity_override_reason, needed_bytes, "
    "total_bytes, total_files, conflict_count, exclusion_count, warnings_json, "
    "created_at, approved_at"
)

_ENTRY_COLUMNS = (
    "id, plan_id, inventory_id, inventory_entry_id, source_path, rel_path, "
    "entry_type, dest_rel_path, matched_rule, size, mtime, action, conflict, "
    "exclusion_reason, excluded_by_user, renamed_from, group_id"
)


def insert_plan(conn: sqlite3.Connection, plan: TransferPlanRow) -> None:
    conn.execute(
        """
        INSERT INTO transfer_plans (
            id, destination_id, destination_binding_path, preset_id, preset_revision,
            preset_content_hash, project_id, inventory_snapshot_json,
            destination_identity_json, conflict_policy, checksum_algo,
            free_space_reserve, free_bytes, blocking_count,
            decisions_json, preset_review_json, rule_exclusion_count,
            derived_from, superseded_by, category_map_version,
            fingerprint, status, approved_fingerprint,
            capacity_ok, capacity_unknown, capacity_override_reason, needed_bytes,
            total_bytes, total_files, conflict_count, exclusion_count, warnings_json,
            created_at, approved_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                  ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            plan.id,
            plan.destination_id,
            plan.destination_binding_path,
            plan.preset_id,
            plan.preset_revision,
            plan.preset_content_hash,
            plan.project_id,
            plan.inventory_snapshot_json,
            plan.destination_identity_json,
            plan.conflict_policy,
            plan.checksum_algo,
            plan.free_space_reserve,
            plan.free_bytes,
            plan.blocking_count,
            plan.decisions_json,
            plan.preset_review_json,
            plan.rule_exclusion_count,
            plan.derived_from,
            plan.superseded_by,
            plan.category_map_version,
            plan.fingerprint,
            plan.status,
            plan.approved_fingerprint,
            plan.capacity_ok,
            plan.capacity_unknown,
            plan.capacity_override_reason,
            plan.needed_bytes,
            plan.total_bytes,
            plan.total_files,
            plan.conflict_count,
            plan.exclusion_count,
            plan.warnings_json,
            plan.created_at,
            plan.approved_at,
        ),
    )


def insert_plan_entries(
    conn: sqlite3.Connection, plan_id: str, entries: list[TransferPlanEntryRow]
) -> None:
    conn.executemany(
        """
        INSERT INTO transfer_plan_entries (
            plan_id, inventory_id, inventory_entry_id, source_path, rel_path, entry_type,
            dest_rel_path, matched_rule, size, mtime, action, conflict,
            exclusion_reason, excluded_by_user, renamed_from, group_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                plan_id,
                e.inventory_id,
                e.inventory_entry_id,
                e.source_path,
                e.rel_path,
                e.entry_type,
                e.dest_rel_path,
                e.matched_rule,
                e.size,
                e.mtime,
                e.action,
                e.conflict,
                e.exclusion_reason,
                e.excluded_by_user,
                e.renamed_from,
                e.group_id,
            )
            for e in entries
        ],
    )


def get_plan(conn: sqlite3.Connection, plan_id: str) -> TransferPlanRow | None:
    row = conn.execute(
        f"SELECT {_PLAN_COLUMNS} FROM transfer_plans WHERE id = ?", (plan_id,)
    ).fetchone()
    return TransferPlanRow.from_row(row) if row is not None else None


def get_plan_by_fingerprint(conn: sqlite3.Connection, fingerprint: str) -> TransferPlanRow | None:
    row = conn.execute(
        f"SELECT {_PLAN_COLUMNS} FROM transfer_plans WHERE fingerprint = ?", (fingerprint,)
    ).fetchone()
    return TransferPlanRow.from_row(row) if row is not None else None


def set_plan_status(
    conn: sqlite3.Connection,
    plan_id: str,
    *,
    status: str,
    approved_fingerprint: str | None = None,
    approved_at: str | None = None,
) -> None:
    if approved_fingerprint is not None or approved_at is not None:
        conn.execute(
            "UPDATE transfer_plans SET status = ?, approved_fingerprint = ?, approved_at = ? "
            "WHERE id = ?",
            (status, approved_fingerprint, approved_at, plan_id),
        )
    else:
        conn.execute("UPDATE transfer_plans SET status = ? WHERE id = ?", (status, plan_id))


def mark_superseded(conn: sqlite3.Connection, plan_id: str, *, by_plan_id: str) -> None:
    """Invalidate a plan because a reviewed decision produced its successor.

    The approval is cleared as well as the status: leaving
    ``approved_fingerprint`` set on an invalidated plan would let a later
    reader conclude the plan had been approved in the shape it now has
    (R19).
    """
    conn.execute(
        "UPDATE transfer_plans SET status = 'invalidated', approved_fingerprint = NULL, "
        "superseded_by = ? WHERE id = ?",
        (by_plan_id, plan_id),
    )


def count_plan_entries(conn: sqlite3.Connection, plan_id: str) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM transfer_plan_entries WHERE plan_id = ?", (plan_id,)
        ).fetchone()[0]
    )


def page_plan_entries(
    conn: sqlite3.Connection, plan_id: str, *, limit: int, after_id: int
) -> list[TransferPlanEntryRow]:
    rows = conn.execute(
        f"""
        SELECT {_ENTRY_COLUMNS}
        FROM transfer_plan_entries
        WHERE plan_id = ? AND id > ?
        ORDER BY id ASC
        LIMIT ?
        """,
        (plan_id, after_id, limit),
    ).fetchall()
    return [TransferPlanEntryRow.from_row(r) for r in rows]


def invalidate_plans_for_destination(conn: sqlite3.Connection, destination_id: int) -> int:
    """Unexecuted plans for this destination become invalidated.

    Editing, rebinding, or archiving a destination invalidates
    unexecuted approvals (spec §4.1). Plans that already reached
    ``executing``/``executed`` are historical snapshots and are left
    exactly as they were.

    The caller must run this on the *same* connection/transaction as
    the configuration change so the two can never be observed apart
    (R04).
    """
    cur = conn.execute(
        "UPDATE transfer_plans SET status = 'invalidated', approved_fingerprint = NULL "
        "WHERE destination_id = ? AND status IN ('draft', 'approved')",
        (destination_id,),
    )
    return cur.rowcount


def invalidate_plans_for_preset(conn: sqlite3.Connection, preset_id: int) -> int:
    """Unexecuted plans pinned to this preset become invalidated."""
    cur = conn.execute(
        "UPDATE transfer_plans SET status = 'invalidated', approved_fingerprint = NULL "
        "WHERE preset_id = ? AND status IN ('draft', 'approved')",
        (preset_id,),
    )
    return cur.rowcount


def count_entries_with_action(conn: sqlite3.Connection, plan_id: str, action: str) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM transfer_plan_entries WHERE plan_id = ? AND action = ?",
            (plan_id, action),
        ).fetchone()[0]
    )


def get_plan_entry(
    conn: sqlite3.Connection, plan_id: str, entry_id: int
) -> TransferPlanEntryRow | None:
    row = conn.execute(
        f"SELECT {_ENTRY_COLUMNS} FROM transfer_plan_entries WHERE plan_id = ? AND id = ?",
        (plan_id, entry_id),
    ).fetchone()
    return TransferPlanEntryRow.from_row(row) if row is not None else None
