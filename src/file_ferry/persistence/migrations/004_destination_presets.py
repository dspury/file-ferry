"""Migration 004 — saved destinations, preset revisions, inventories, plans.

Implements the persistence contracts of the destination-presets spec §4:

- ``saved_destinations`` (§4.1): saved destination folders with identity
  evidence, pinned preset revision, conflict/checksum/reserve defaults,
  and last-confirmed binding. Display names are not identity; multiple
  saved folders may live on one volume.
- ``organization_profile_revisions`` (§4.2): immutable revision rows.
  Saving edits creates a new revision; nothing ever updates an existing
  one. Legacy profiles get their current template snapshotted as a
  revision at their existing version number, with pre-migration history
  recorded as unavailable — never fabricated.
- ``source_inventories`` / ``source_inventory_entries`` (§4.3): full
  server-side inventories so a UI page limit can never limit planning.
  Entries carry type/size/mtime/scan-status/error; directories are
  represented for empty-folder preservation.
- ``transfer_plans`` / ``transfer_plan_entries`` (§4.3): immutable plan
  records with destination binding snapshot, preset revision + content
  hash, per-entry mapping and action, capacity estimate, and a
  deterministic fingerprint. Plans may reference a project but never
  require one.
- ``jobs.project_id`` relaxed to nullable via table rebuild (§4.1): a
  general transfer must not invent a fake video project. Existing rows
  are copied unchanged; project-linked behavior is unchanged for rows
  that have a project.

The downgrade drops the new tables and restores the jobs constraint,
discarding any project-less job rows (downgrades are development-only
per ADR-0003).

**Development-schema hazard.** This migration was amended in place after
an earlier revision of it had already been applied to development
databases (it has never been committed or shipped, so no user database
can carry the old shape). The DDL is written with ``CREATE TABLE IF NOT
EXISTS``, so a database already stamped ``schema_version = 4`` skips it
entirely and keeps the *old* columns — and this migration never runs
again to correct them. :func:`assert_v4_shape` exists so that shows up
as one actionable error at startup instead of a confusing "no such
column: review_json" somewhere deep in a service. Rebuild disposable
test databases; export anything worth keeping first.
"""

from __future__ import annotations

import json
import sqlite3

from file_ferry.application.preset_compat import (
    canonical_revision_payload,
    convert_legacy_template,
)

VERSION = 4

_NEW_TABLES_DDL = """
-- ------------------------------------------------------------------
-- saved_destinations (spec §4.1)
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS saved_destinations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    location_kind TEXT NOT NULL
        CHECK (location_kind IN ('local_folder', 'volume_folder', 'mounted_share_folder')),
    last_root_path TEXT NOT NULL,
    subfolder_path TEXT,
    identity_kind TEXT
        CHECK (identity_kind IS NULL OR identity_kind IN
               ('volume_uuid', 'disk_uuid', 'server_share', 'path_only')),
    identity_value TEXT,
    identity_confidence TEXT
        CHECK (identity_confidence IS NULL OR identity_confidence IN
               ('strong', 'medium', 'weak')),
    identity_provenance TEXT,
    default_preset_id INTEGER REFERENCES organization_profiles(id),
    pinned_revision INTEGER,
    conflict_policy TEXT NOT NULL DEFAULT 'keep_both',
    checksum_algo TEXT NOT NULL DEFAULT 'xxhash64',
    free_space_reserve INTEGER NOT NULL DEFAULT 0,
    last_binding_path TEXT,
    last_seen_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived_at TEXT
);

-- ------------------------------------------------------------------
-- organization_profile_revisions (spec §4.2) — immutable rows
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS organization_profile_revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    preset_id INTEGER NOT NULL REFERENCES organization_profiles(id),
    revision INTEGER NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    rules_json TEXT NOT NULL,
    groups_json TEXT NOT NULL,
    fallback_template TEXT NOT NULL,
    conflict_policy TEXT NOT NULL,
    exclusions_json TEXT NOT NULL,
    -- Content that needs a human decision before this revision may be
    -- used for a transfer: unknown legacy template keys, legacy
    -- conflict policies with no safe equivalent (spec §4.2 — such keys
    -- are never silently ignored).
    review_json TEXT NOT NULL DEFAULT '[]',
    -- The legacy profile template this revision was converted from,
    -- verbatim. Conversion never discards the original.
    legacy_template_json TEXT,
    schema_version INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(preset_id, revision)
);

-- ------------------------------------------------------------------
-- source_inventories / entries (spec §4.3)
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS source_inventories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    root_path TEXT NOT NULL,
    label TEXT,
    status TEXT NOT NULL DEFAULT 'scanning'
        CHECK (status IN ('scanning', 'complete', 'failed')),
    -- Diagnostic for a failed scan, and the owning process/heartbeat so
    -- a scan abandoned by a crash is recovered at startup rather than
    -- staying 'scanning' indefinitely (spec §4.3, §7.3).
    error TEXT,
    owner_pid INTEGER,
    heartbeat_at TEXT,
    file_count INTEGER NOT NULL DEFAULT 0,
    dir_count INTEGER NOT NULL DEFAULT 0,
    total_bytes INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    excluded_count INTEGER NOT NULL DEFAULT 0,
    manifest_hash TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS source_inventory_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inventory_id INTEGER NOT NULL REFERENCES source_inventories(id) ON DELETE CASCADE,
    rel_path TEXT NOT NULL,
    -- The kind of filesystem object. A read failure is *not* a type:
    -- it is scan_status='error' with the diagnostic in ``error``, and
    -- entry_type='unknown' when the object could not be stat'd at all.
    entry_type TEXT NOT NULL DEFAULT 'file'
        CHECK (entry_type IN ('file', 'dir', 'symlink', 'other', 'unknown')),
    size INTEGER NOT NULL DEFAULT 0,
    mtime REAL,
    scan_status TEXT NOT NULL DEFAULT 'ok' CHECK (scan_status IN ('ok', 'error')),
    error TEXT,
    UNIQUE(inventory_id, rel_path)
);

-- ------------------------------------------------------------------
-- transfer_plans / entries (spec §4.3) — immutable plan records
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS transfer_plans (
    id TEXT PRIMARY KEY,
    destination_id INTEGER REFERENCES saved_destinations(id),
    destination_binding_path TEXT NOT NULL,
    preset_id INTEGER REFERENCES organization_profiles(id),
    preset_revision INTEGER,
    preset_content_hash TEXT,
    project_id TEXT REFERENCES projects(id),
    -- The complete approved substance (spec §4.3, §7.1): which
    -- inventories at which manifest revision, the destination identity
    -- evidence as it stood, and the policy/reserve in force. All of it
    -- is hashed into ``fingerprint``; a change is a different plan.
    inventory_snapshot_json TEXT NOT NULL DEFAULT '[]',
    destination_identity_json TEXT,
    conflict_policy TEXT NOT NULL DEFAULT 'keep_both',
    checksum_algo TEXT NOT NULL DEFAULT 'xxhash64',
    free_space_reserve INTEGER NOT NULL DEFAULT 0,
    free_bytes INTEGER,
    blocking_count INTEGER NOT NULL DEFAULT 0,
    -- Decisions a person made about this plan's findings, carried
    -- forward when the plan is rebuilt (spec §6.4, §8: planResolve
    -- produces a new plan revision rather than mutating one). Keyed by
    -- (inventory, source-relative path) so they survive a rebuild, which
    -- reassigns entry ids.
    decisions_json TEXT NOT NULL DEFAULT '[]',
    -- Review evidence carried by the pinned preset revision — unknown
    -- legacy template keys, legacy conflict policies with no safe
    -- equivalent. Non-empty blocks approval (spec §4.2, R14); it is kept
    -- on the plan so the refusal can name the items rather than pointing
    -- at a revision the reviewer would have to go and read.
    preset_review_json TEXT NOT NULL DEFAULT '[]',
    -- Excluded entries split by origin (spec §7.3): a preset exclusion
    -- rule and a reviewer's decision are both explicit, but they are not
    -- the same thing and a receipt must not merge them.
    rule_exclusion_count INTEGER NOT NULL DEFAULT 0,
    -- The plan this one was derived from by resolving decisions, the
    -- plan that superseded it, and the versioned extension map used to
    -- classify its files (spec §6.1, §8).
    derived_from TEXT,
    superseded_by TEXT,
    category_map_version INTEGER NOT NULL DEFAULT 1,
    fingerprint TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'approved', 'invalidated', 'executing', 'executed')),
    approved_fingerprint TEXT,
    capacity_ok INTEGER NOT NULL DEFAULT 1,
    capacity_unknown INTEGER NOT NULL DEFAULT 0,
    capacity_override_reason TEXT,
    needed_bytes INTEGER NOT NULL DEFAULT 0,
    total_bytes INTEGER NOT NULL DEFAULT 0,
    total_files INTEGER NOT NULL DEFAULT 0,
    conflict_count INTEGER NOT NULL DEFAULT 0,
    exclusion_count INTEGER NOT NULL DEFAULT 0,
    warnings_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    approved_at TEXT
);

CREATE TABLE IF NOT EXISTS transfer_plan_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id TEXT NOT NULL REFERENCES transfer_plans(id) ON DELETE CASCADE,
    -- Source identity is (inventory, entry), never the relative name:
    -- two drives holding ``same.txt`` are two entries that collide at
    -- one destination path, not one entry (spec §4.3, A04).
    inventory_id INTEGER REFERENCES source_inventories(id),
    inventory_entry_id INTEGER,
    source_path TEXT NOT NULL,
    rel_path TEXT NOT NULL DEFAULT '',
    entry_type TEXT NOT NULL DEFAULT 'file',
    dest_rel_path TEXT NOT NULL,
    matched_rule TEXT,
    size INTEGER NOT NULL DEFAULT 0,
    mtime REAL,
    action TEXT NOT NULL DEFAULT 'copy'
        CHECK (action IN ('copy', 'skip_identical', 'exclude', 'needs_review', 'dir')),
    conflict TEXT,
    -- Why an entry is excluded, and whether a user actually decided it.
    -- An implicit exclusion is never an approved one (spec §6.2, §7.3).
    exclusion_reason TEXT,
    excluded_by_user INTEGER NOT NULL DEFAULT 0,
    -- Set when keep-both moved this copy off its natural name, so review
    -- shows the rename instead of the receipt revealing it later.
    renamed_from TEXT,
    -- The keep-together group this entry belongs to, if any. Carried so
    -- the allocator can resolve a collision at the group root instead of
    -- suffixing an internal member and breaking its references
    -- (spec §6.3, examples E16).
    group_id TEXT,
    UNIQUE(plan_id, inventory_id, source_path)
);

-- ------------------------------------------------------------------
-- transfer_plan_preflights (spec §7.1) — evidence that the world still
-- matches the plan. Approval requires a passing, current one; the row
-- records what was checked so a refusal can be explained and a pass can
-- be audited.
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS transfer_plan_preflights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id TEXT NOT NULL REFERENCES transfer_plans(id) ON DELETE CASCADE,
    -- The fingerprint this preflight validated. A plan that changes
    -- afterwards has a different fingerprint and needs its own run.
    fingerprint TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'passed', 'failed')),
    findings_json TEXT NOT NULL DEFAULT '[]',
    checked_entries INTEGER NOT NULL DEFAULT 0,
    total_entries INTEGER NOT NULL DEFAULT 0,
    resolved_binding_path TEXT,
    destination_status TEXT,
    free_bytes INTEGER,
    started_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_preflight_plan ON transfer_plan_preflights(plan_id);
CREATE INDEX IF NOT EXISTS idx_saved_dest_name ON saved_destinations(name);
CREATE INDEX IF NOT EXISTS idx_preset_rev_preset ON organization_profile_revisions(preset_id);
CREATE INDEX IF NOT EXISTS idx_inv_entries_inv ON source_inventory_entries(inventory_id);
CREATE INDEX IF NOT EXISTS idx_inv_root ON source_inventories(root_path);
CREATE INDEX IF NOT EXISTS idx_plan_entries_plan ON transfer_plan_entries(plan_id);
CREATE INDEX IF NOT EXISTS idx_plans_fingerprint ON transfer_plans(fingerprint);
CREATE INDEX IF NOT EXISTS idx_plans_destination ON transfer_plans(destination_id);
CREATE INDEX IF NOT EXISTS idx_inv_status ON source_inventories(status);
"""


def _snapshot_legacy_profiles(conn: sqlite3.Connection, now: str) -> None:
    """Give every legacy profile an immutable revision at its current version.

    The conversion is deliberate, not lossy and not silently permissive
    (spec §4.2):

    - A root-only legacy template becomes an *equivalent valid* revision:
      the root is the literal prefix and the original relative path is
      preserved beneath it, i.e. ``<root>/{relative_dir}/{filename}``.
      A root that is not a safe relative path, or that carries template
      tokens, is not reinterpreted as a literal prefix — it becomes a
      blocking review item instead.
    - Any other key in the legacy template is unknown to this schema and
      is recorded as a blocking review item; it is never dropped.
    - Legacy conflict policies are mapped explicitly (see
      ``_LEGACY_CONFLICT_MAP``). ``skip`` and ``overwrite`` have no safe
      equivalent in the new contract and become ``needs_review``.
    - The original template is kept verbatim in ``legacy_template_json``.

    Pre-migration revision *history* is recorded as unavailable: version
    numbers are preserved, historical content is not fabricated.
    """
    rows = conn.execute(
        "SELECT id, name, version, template, conflict_policy FROM organization_profiles"
    ).fetchall()
    for row in rows:
        existing = conn.execute(
            "SELECT 1 FROM organization_profile_revisions WHERE preset_id = ? AND revision = ?",
            (row["id"], row["version"]),
        ).fetchone()
        if existing is not None:
            continue
        try:
            template = json.loads(row["template"]) if row["template"] else {}
        except (TypeError, ValueError):
            template = {}
        if not isinstance(template, dict):
            template = {"__unparsed__": template}
        fallback, policy, review = convert_legacy_template(template, row["conflict_policy"])
        payload = canonical_revision_payload(
            description="legacy snapshot taken at migration 004; earlier revisions unavailable",
            rules=[],
            groups=[],
            fallback_template=fallback,
            conflict_policy=policy,
            exclusions=[],
            review=review,
        )
        conn.execute(
            """
            INSERT INTO organization_profile_revisions (
                preset_id, revision, name, description, rules_json, groups_json,
                fallback_template, conflict_policy, exclusions_json, review_json,
                legacy_template_json, schema_version, content_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["id"],
                row["version"],
                row["name"],
                "legacy snapshot taken at migration 004; earlier revisions unavailable",
                "[]",
                "[]",
                fallback,
                policy,
                "[]",
                json.dumps(review, sort_keys=True, separators=(",", ":")),
                json.dumps(template, sort_keys=True, separators=(",", ":")),
                1,
                _sha256(payload),
                now,
            ),
        )


def _sha256(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _relax_jobs_project_id(conn: sqlite3.Connection) -> None:
    """Rebuild ``jobs`` with a nullable ``project_id`` (spec §4.1).

    General transfers must not require a project. A plain ``ALTER``
    cannot relax a NOT NULL constraint, so the table is rebuilt: rows
    are copied verbatim. Runs with foreign keys disabled because
    ``job_steps``/``job_items`` reference ``jobs`` and a drop with
    enforcement on would cascade-or-fail; references re-resolve by name
    after the rename.
    """
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.executescript(
            """
            CREATE TABLE jobs_v4_new (
                id TEXT PRIMARY KEY,
                project_id TEXT REFERENCES projects(id),
                session_id TEXT REFERENCES intake_sessions(id),
                command TEXT NOT NULL,
                args_fingerprint TEXT,
                state TEXT NOT NULL DEFAULT 'planned',
                owner TEXT,
                current_step TEXT,
                total_steps INTEGER NOT NULL DEFAULT 0,
                started_at TEXT,
                updated_at TEXT NOT NULL,
                finished_at TEXT,
                error TEXT,
                resumable INTEGER NOT NULL DEFAULT 0
            );
            INSERT INTO jobs_v4_new (
                id, project_id, session_id, command, args_fingerprint, state, owner,
                current_step, total_steps, started_at, updated_at, finished_at, error,
                resumable
            )
            SELECT
                id, project_id, session_id, command, args_fingerprint, state, owner,
                current_step, total_steps, started_at, updated_at, finished_at, error,
                resumable
            FROM jobs;
            DROP TABLE jobs;
            ALTER TABLE jobs_v4_new RENAME TO jobs;
            CREATE INDEX idx_jobs_project ON jobs(project_id);
            CREATE INDEX idx_jobs_session ON jobs(session_id);
            CREATE INDEX idx_jobs_state ON jobs(state);
            """
        )
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def upgrade(conn: sqlite3.Connection) -> None:
    """Create the destination-preset tables. Idempotent."""
    from datetime import UTC, datetime

    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    conn.executescript(_NEW_TABLES_DDL)
    _snapshot_legacy_profiles(conn, now)
    # A v4 database already migrated (idempotent re-run) has nullable
    # project_id; detect before rebuilding.
    cols = {
        row["name"]: dict(row)["notnull"]
        for row in conn.execute("PRAGMA table_info(jobs)").fetchall()
    }
    if cols.get("project_id") == 1:
        _relax_jobs_project_id(conn)


def downgrade(conn: sqlite3.Connection) -> None:
    """Drop the destination-preset tables; restore the jobs constraint.

    Project-less job rows cannot survive the NOT NULL constraint and
    are dropped (documented lossy downgrade; production rollbacks
    restore from backup per ADR-0003).
    """
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        for table in (
            "transfer_plan_entries",
            "transfer_plans",
            "source_inventory_entries",
            "source_inventories",
            "organization_profile_revisions",
            "saved_destinations",
        ):
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.executescript(
            """
            CREATE TABLE jobs_v4_old (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id),
                session_id TEXT REFERENCES intake_sessions(id),
                command TEXT NOT NULL,
                args_fingerprint TEXT,
                state TEXT NOT NULL DEFAULT 'planned',
                owner TEXT,
                current_step TEXT,
                total_steps INTEGER NOT NULL DEFAULT 0,
                started_at TEXT,
                updated_at TEXT NOT NULL,
                finished_at TEXT,
                error TEXT,
                resumable INTEGER NOT NULL DEFAULT 0
            );
            INSERT INTO jobs_v4_old (
                id, project_id, session_id, command, args_fingerprint, state, owner,
                current_step, total_steps, started_at, updated_at, finished_at, error,
                resumable
            )
            SELECT
                id, project_id, session_id, command, args_fingerprint, state, owner,
                current_step, total_steps, started_at, updated_at, finished_at, error,
                resumable
            FROM jobs WHERE project_id IS NOT NULL;
            DROP TABLE jobs;
            ALTER TABLE jobs_v4_old RENAME TO jobs;
            CREATE INDEX idx_jobs_project ON jobs(project_id);
            CREATE INDEX idx_jobs_session ON jobs(session_id);
            CREATE INDEX idx_jobs_state ON jobs(state);
            """
        )
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


#: Columns added to the v4 tables after the first development revision of
#: this migration. A database stamped v4 without them was created by the
#: superseded revision (see the module docstring).
_AMENDED_V4_COLUMNS: dict[str, tuple[str, ...]] = {
    "source_inventories": ("error", "owner_pid", "heartbeat_at"),
    "organization_profile_revisions": ("review_json", "legacy_template_json"),
    "transfer_plans": (
        "decisions_json",
        "derived_from",
        "category_map_version",
        "inventory_snapshot_json",
        "destination_identity_json",
        "conflict_policy",
        "checksum_algo",
        "free_space_reserve",
        "free_bytes",
        "blocking_count",
        "preset_review_json",
        "rule_exclusion_count",
        "superseded_by",
    ),
    "transfer_plan_preflights": ("plan_id", "fingerprint", "status", "findings_json"),
    "transfer_plan_entries": (
        "inventory_id",
        "inventory_entry_id",
        "rel_path",
        "entry_type",
        "mtime",
        "exclusion_reason",
        "excluded_by_user",
        "renamed_from",
        "group_id",
    ),
}


class IncompatibleDevelopmentSchemaError(RuntimeError):
    """A v4 database created by the superseded revision of this migration."""


def assert_v4_shape(conn: sqlite3.Connection) -> None:
    """Fail loudly on a v4 database carrying the superseded shape.

    Called once at bootstrap for databases already at v4. A database
    created by the earlier development revision of this migration is not
    upgradable in place — the migration will not run again, and every
    ``CREATE TABLE IF NOT EXISTS`` is a no-op against the tables it
    already has. Saying so here, naming the missing columns, is the
    difference between a five-second diagnosis and an afternoon.
    """
    missing: list[str] = []
    for table, columns in _AMENDED_V4_COLUMNS.items():
        try:
            present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        except sqlite3.Error:  # pragma: no cover - table_info does not raise for absent tables
            continue
        if not present:
            # The table is absent entirely; that is a different problem
            # and the migration runner reports it.
            continue
        missing.extend(f"{table}.{column}" for column in columns if column not in present)
    if not missing:
        return
    raise IncompatibleDevelopmentSchemaError(
        "this database is stamped schema_version 4 but was created by a superseded "
        "development revision of migration 004; it is missing "
        f"{len(missing)} column(s): {', '.join(sorted(missing))}. Migration 004 was "
        "amended in place before it was ever committed or shipped, so no released "
        "database can be in this state — only a development or test database. It "
        "cannot be upgraded in place (the migration will not re-run, and its DDL is "
        "IF NOT EXISTS). Delete and recreate a disposable test database; for one "
        "holding records you want, export them first or write a follow-up migration."
    )
