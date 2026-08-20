"""Migration 002 — vNext entity tables.

This migration creates the full set of vNext entities from the plan
Section 6.2 plus the storage-policy shape required by ADR-0004. It
runs on top of ``001_initial_legacy`` (which bootstrapped the v0.2.4
schema and renamed the legacy ``projects`` table to
``legacy_resolve_projects`` to free the name).

Entities created:

- ``projects`` (vNext) with an embedded JSON ``storage_policy``.
- ``organization_profiles`` — versioned source-to-destination templates.
- ``sources`` — a detected card, volume, or folder.
- ``intake_sessions`` / ``intake_destinations`` — offload / adoption intent.
- ``assets`` — stable media identity.
- ``replicas`` — physical locations + verification state (ADR-0004).
- ``logical_clips`` / ``logical_clip_members`` — multi-file clip groups.
- ``derivatives`` — proxy / derived outputs.
- ``jobs`` / ``job_steps`` / ``job_items`` — durable operations.
- ``operation_receipts`` — immutable receipts + hash.
- ``audit_events`` — append-only events, linkable to legacy ``runs``.

All vNext tables use TEXT primary keys (UUID) where the identity is a
durable external id and INTEGER primary keys for local rows. Foreign
keys and indexes are created here so the schema is validated at
migration time (``PRAGMA foreign_keys`` is ON for every connection).

See ADR-0003 (persistence model) and ADR-0004 (safe-to-format policy).
"""

from __future__ import annotations

import sqlite3

DDL = """
-- ------------------------------------------------------------------
-- projects (vNext) — project identity, roots, policy, defaults
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'active',
    working_root TEXT NOT NULL,
    backup_root TEXT,
    storage_policy TEXT NOT NULL,
    organization_profile_id INTEGER REFERENCES organization_profiles(id),
    proxy_defaults TEXT,
    resolve_defaults TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived_at TEXT
);

-- ------------------------------------------------------------------
-- organization_profiles — versioned source-to-destination templates
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS organization_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    version INTEGER NOT NULL,
    template TEXT NOT NULL,
    conflict_policy TEXT NOT NULL DEFAULT 'skip',
    mutation_policy TEXT NOT NULL DEFAULT 'copy',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- ------------------------------------------------------------------
-- sources — a detected card, volume, or folder
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    root_path TEXT NOT NULL,
    label TEXT,
    volume_fingerprint TEXT,
    manifest_hash TEXT,
    file_count INTEGER NOT NULL DEFAULT 0,
    total_bytes INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'detected',
    source_readable_at TEXT,
    captured_at TEXT NOT NULL,
    UNIQUE(root_path, kind)
);

-- ------------------------------------------------------------------
-- intake_sessions — offload / adoption intent
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS intake_sessions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    source_id INTEGER REFERENCES sources(id),
    kind TEXT NOT NULL,
    plan_fingerprint TEXT,
    policy_fingerprint TEXT,
    status TEXT NOT NULL DEFAULT 'planned',
    safe_to_format INTEGER NOT NULL DEFAULT 0,
    source_readable_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS intake_destinations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    intake_session_id TEXT NOT NULL REFERENCES intake_sessions(id),
    kind TEXT NOT NULL,
    root_path TEXT NOT NULL,
    role TEXT,
    required INTEGER NOT NULL DEFAULT 1,
    verified INTEGER NOT NULL DEFAULT 0,
    verified_at TEXT,
    UNIQUE(intake_session_id, kind)
);

-- ------------------------------------------------------------------
-- assets — stable media identity, observed metadata, lifecycle
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS assets (
    id TEXT PRIMARY KEY,
    source_id INTEGER REFERENCES sources(id),
    source_relative_path TEXT NOT NULL,
    observed_size INTEGER,
    observed_mtime REAL,
    observed_checksum TEXT,
    checksum_algo TEXT,
    lifecycle_state TEXT NOT NULL DEFAULT 'discovered',
    media_kind TEXT,
    probed_at TEXT,
    first_seen_at TEXT NOT NULL,
    UNIQUE(source_id, source_relative_path)
);

-- ------------------------------------------------------------------
-- replicas — a physical asset location + verification state
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS replicas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id TEXT NOT NULL REFERENCES assets(id),
    project_id TEXT NOT NULL REFERENCES projects(id),
    path TEXT NOT NULL,
    volume_fingerprint TEXT,
    size INTEGER,
    checksum TEXT,
    checksum_algo TEXT,
    verified INTEGER NOT NULL DEFAULT 0,
    verified_at TEXT,
    source_checksum TEXT,
    availability TEXT NOT NULL DEFAULT 'present',
    last_checked_at TEXT,
    UNIQUE(asset_id, path)
);

-- ------------------------------------------------------------------
-- logical_clips / logical_clip_members — multi-file / spanned clips
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS logical_clips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER REFERENCES sources(id),
    clip_name TEXT NOT NULL,
    detection_confidence REAL NOT NULL DEFAULT 0.0,
    resolved INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(source_id, clip_name)
);

CREATE TABLE IF NOT EXISTS logical_clip_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    logical_clip_id INTEGER NOT NULL REFERENCES logical_clips(id),
    asset_id TEXT NOT NULL REFERENCES assets(id),
    role TEXT NOT NULL DEFAULT 'primary',
    UNIQUE(logical_clip_id, asset_id)
);

-- ------------------------------------------------------------------
-- derivatives — proxy / derived outputs
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS derivatives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id TEXT NOT NULL REFERENCES assets(id),
    kind TEXT NOT NULL,
    output_path TEXT NOT NULL,
    settings_fingerprint TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    readiness INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(asset_id, kind, output_path)
);

-- ------------------------------------------------------------------
-- jobs / job_steps / job_items — durable operations
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS jobs (
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

CREATE TABLE IF NOT EXISTS job_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    step TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending',
    started_at TEXT,
    finished_at TEXT,
    error TEXT,
    UNIQUE(job_id, step)
);

CREATE TABLE IF NOT EXISTS job_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    step TEXT NOT NULL,
    asset_id TEXT REFERENCES assets(id),
    source_path TEXT,
    dest_path TEXT,
    temp_path TEXT,
    byte_progress INTEGER NOT NULL DEFAULT 0,
    total_bytes INTEGER,
    state TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    UNIQUE(job_id, step, asset_id)
);

-- ------------------------------------------------------------------
-- operation_receipts — immutable receipts + hash
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS operation_receipts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    receipt_json TEXT NOT NULL,
    receipt_hash TEXT NOT NULL,
    display_summary TEXT,
    receipt_path TEXT,
    export_version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE(operation_id, kind)
);

-- ------------------------------------------------------------------
-- audit_events — append-only events, linkable to legacy runs
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at TEXT NOT NULL,
    actor TEXT,
    event_type TEXT NOT NULL,
    entity_type TEXT,
    entity_id TEXT,
    data TEXT,
    run_id INTEGER REFERENCES runs(id)
);

-- ------------------------------------------------------------------
-- Indexes
-- ------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_projects_name ON projects(name);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);
CREATE INDEX IF NOT EXISTS idx_sources_kind ON sources(kind);
CREATE INDEX IF NOT EXISTS idx_sources_root ON sources(root_path);
CREATE INDEX IF NOT EXISTS idx_sources_vol ON sources(volume_fingerprint);
CREATE INDEX IF NOT EXISTS idx_intake_project ON intake_sessions(project_id);
CREATE INDEX IF NOT EXISTS idx_intake_source ON intake_sessions(source_id);
CREATE INDEX IF NOT EXISTS idx_intake_status ON intake_sessions(status);
CREATE INDEX IF NOT EXISTS idx_intake_dest_session ON intake_destinations(intake_session_id);
CREATE INDEX IF NOT EXISTS idx_assets_source ON assets(source_id);
CREATE INDEX IF NOT EXISTS idx_assets_rel ON assets(source_relative_path);
CREATE INDEX IF NOT EXISTS idx_replicas_asset ON replicas(asset_id);
CREATE INDEX IF NOT EXISTS idx_replicas_project ON replicas(project_id);
CREATE INDEX IF NOT EXISTS idx_replicas_verified ON replicas(verified);
CREATE INDEX IF NOT EXISTS idx_clip_members_clip ON logical_clip_members(logical_clip_id);
CREATE INDEX IF NOT EXISTS idx_clip_members_asset ON logical_clip_members(asset_id);
CREATE INDEX IF NOT EXISTS idx_deriv_asset ON derivatives(asset_id);
CREATE INDEX IF NOT EXISTS idx_jobs_project ON jobs(project_id);
CREATE INDEX IF NOT EXISTS idx_jobs_session ON jobs(session_id);
CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state);
CREATE INDEX IF NOT EXISTS idx_job_steps_job ON job_steps(job_id);
CREATE INDEX IF NOT EXISTS idx_job_items_job ON job_items(job_id);
CREATE INDEX IF NOT EXISTS idx_job_items_asset ON job_items(asset_id);
CREATE INDEX IF NOT EXISTS idx_receipts_operation ON operation_receipts(operation_id);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_events(entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_type ON audit_events(event_type);
"""

# The order tables are dropped in downgrade (reverse of dependency).
_DROP_ORDER = (
    "audit_events",
    "operation_receipts",
    "job_items",
    "job_steps",
    "jobs",
    "derivatives",
    "logical_clip_members",
    "logical_clips",
    "replicas",
    "assets",
    "intake_destinations",
    "intake_sessions",
    "sources",
    "organization_profiles",
    "projects",
)

VERSION = 2


def upgrade(conn: sqlite3.Connection) -> None:
    """Create the vNext entity tables. Idempotent."""
    conn.executescript(DDL)


def downgrade(conn: sqlite3.Connection) -> None:
    """Drop the vNext entity tables. Idempotent."""
    for table in _DROP_ORDER:
        conn.execute(f"DROP TABLE IF EXISTS {table}")
