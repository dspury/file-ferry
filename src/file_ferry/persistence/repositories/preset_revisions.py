"""Repository for ``organization_profile_revisions`` (spec §4.2).

Rows are immutable: this repository only inserts and reads. Saving an
edit creates a new revision; nothing updates an existing one.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, fields


@dataclass(frozen=True)
class PresetRevisionRow:
    """One immutable preset revision."""

    id: int
    preset_id: int
    revision: int
    name: str
    description: str | None
    rules_json: str
    groups_json: str
    fallback_template: str
    conflict_policy: str
    exclusions_json: str
    review_json: str
    legacy_template_json: str | None
    schema_version: int
    content_hash: str
    created_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> PresetRevisionRow:
        return cls(**{f.name: row[f.name] for f in fields(cls)})


_COLUMNS = (
    "id, preset_id, revision, name, description, rules_json, groups_json, "
    "fallback_template, conflict_policy, exclusions_json, review_json, "
    "legacy_template_json, schema_version, content_hash, created_at"
)


def insert_revision(conn: sqlite3.Connection, rev: PresetRevisionRow) -> int:
    cur = conn.execute(
        """
        INSERT INTO organization_profile_revisions (
            preset_id, revision, name, description, rules_json, groups_json,
            fallback_template, conflict_policy, exclusions_json, review_json,
            legacy_template_json, schema_version, content_hash, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            rev.preset_id,
            rev.revision,
            rev.name,
            rev.description,
            rev.rules_json,
            rev.groups_json,
            rev.fallback_template,
            rev.conflict_policy,
            rev.exclusions_json,
            rev.review_json,
            rev.legacy_template_json,
            rev.schema_version,
            rev.content_hash,
            rev.created_at,
        ),
    )
    lastrowid = cur.lastrowid
    if lastrowid is None:
        raise RuntimeError("insert_revision failed to return a row id")
    return int(lastrowid)


def get_revision(
    conn: sqlite3.Connection, preset_id: int, revision: int
) -> PresetRevisionRow | None:
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM organization_profile_revisions "
        "WHERE preset_id = ? AND revision = ?",
        (preset_id, revision),
    ).fetchone()
    return PresetRevisionRow.from_row(row) if row is not None else None


def latest_revision(conn: sqlite3.Connection, preset_id: int) -> PresetRevisionRow | None:
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM organization_profile_revisions "
        "WHERE preset_id = ? ORDER BY revision DESC LIMIT 1",
        (preset_id,),
    ).fetchone()
    return PresetRevisionRow.from_row(row) if row is not None else None


def max_revision(conn: sqlite3.Connection, preset_id: int) -> int:
    """The highest revision number ever written for this preset (0 if none).

    Revisions are monotonic across *both* writers — the legacy profile
    save and the new revision save — so each derives its next number
    from this, never from its own side's counter alone (spec §4.2).
    """
    row = conn.execute(
        "SELECT MAX(revision) FROM organization_profile_revisions WHERE preset_id = ?",
        (preset_id,),
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def list_revisions(
    conn: sqlite3.Connection, preset_id: int, *, limit: int = 50, after_id: int = 0
) -> tuple[list[PresetRevisionRow], int]:
    """Newest-first page of revisions plus the total count.

    The cursor is the last ``id`` from the prior page; the next page
    is ``id < after_id`` for DESC order, so passing 0 means "from the
    newest end" (sqlite evaluates ``id < 0`` as always false, which
    yields nothing — we special-case the first page).
    """
    total = int(
        conn.execute(
            "SELECT COUNT(*) FROM organization_profile_revisions WHERE preset_id = ?",
            (preset_id,),
        ).fetchone()[0]
    )
    if after_id:
        rows = conn.execute(
            f"SELECT {_COLUMNS} FROM organization_profile_revisions "
            "WHERE preset_id = ? AND id < ? ORDER BY id DESC LIMIT ?",
            (preset_id, after_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT {_COLUMNS} FROM organization_profile_revisions "
            "WHERE preset_id = ? ORDER BY id DESC LIMIT ?",
            (preset_id, limit),
        ).fetchall()
    return [PresetRevisionRow.from_row(r) for r in rows], total
