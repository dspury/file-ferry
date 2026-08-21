"""Migration 001 — bootstrap the legacy v0.2.4 schema.

This is the foundation cut's bootstrap migration. It re-creates the
v0.2.4 schema (the schema the existing CLI / TUI uses) so the
vNext application services can run on the same database file. The
new vNext entities (projects vNext, sources, intake_sessions, etc.)
land in migration 002.

The DDL is a verbatim copy of the v0.2.4 ``SCHEMA_SQL`` with one
rename: the legacy ``projects`` table is renamed to
``legacy_resolve_projects`` to free the name for the vNext entity
per ADR-0003. The legacy CLI / TUI read it through the legacy
view.

See ADR-0003 (application persistence model).
"""

from __future__ import annotations

import sqlite3

# Verbatim copy of the v0.2.4 SCHEMA_SQL, with the legacy `projects`
# table renamed to avoid collision with the vNext entity.
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    command TEXT NOT NULL,
    config_hash TEXT,
    status TEXT NOT NULL,
    error TEXT
);

CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL UNIQUE,
    size INTEGER,
    mtime REAL,
    first_seen_run INTEGER REFERENCES runs(id),
    last_seen_run INTEGER REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS probes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER REFERENCES files(id),
    run_id INTEGER REFERENCES runs(id),
    codec TEXT,
    container TEXT,
    width INTEGER,
    height INTEGER,
    frame_rate REAL,
    r_frame_rate REAL,
    is_vfr INTEGER NOT NULL DEFAULT 0,
    color_space TEXT,
    color_transfer TEXT,
    color_primaries TEXT,
    bit_depth INTEGER,
    sample_aspect_ratio TEXT,
    timecode TEXT,
    audio_codec TEXT,
    audio_channels INTEGER,
    audio_sample_rate INTEGER,
    audio_bit_depth INTEGER,
    duration REAL,
    modification_time TEXT,
    probed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS proxies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file_id INTEGER REFERENCES files(id),
    proxy_path TEXT NOT NULL,
    run_id INTEGER REFERENCES runs(id),
    codec TEXT,
    width INTEGER,
    height INTEGER,
    file_size INTEGER,
    generated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS legacy_resolve_projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    manifest_path TEXT,
    run_id INTEGER REFERENCES runs(id),
    resolution TEXT,
    frame_rate TEXT,
    color_space TEXT,
    bin_count INTEGER,
    timeline_count INTEGER,
    resolve_version TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS verifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folder TEXT NOT NULL,
    run_id INTEGER REFERENCES runs(id),
    files_checked INTEGER,
    files_missing INTEGER,
    files_modified INTEGER,
    files_added INTEGER,
    checksum_algo TEXT,
    verified_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS organize_ops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER REFERENCES runs(id),
    source_path TEXT NOT NULL,
    destination_path TEXT NOT NULL,
    operation TEXT NOT NULL,
    codec_family TEXT,
    resolution_bucket TEXT,
    file_size INTEGER,
    moved_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS verification_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folder TEXT NOT NULL,
    path TEXT NOT NULL,
    checksum TEXT NOT NULL,
    size INTEGER,
    mtime REAL,
    algo TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    UNIQUE(folder, path)
);

CREATE TABLE IF NOT EXISTS verification_baselines (
    folder TEXT PRIMARY KEY,
    algo TEXT NOT NULL,
    is_empty INTEGER NOT NULL DEFAULT 0,
    recorded_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_files_path ON files(path);
CREATE INDEX IF NOT EXISTS idx_probes_file_id ON probes(file_id);
CREATE INDEX IF NOT EXISTS idx_probes_run_id ON probes(run_id);
CREATE INDEX IF NOT EXISTS idx_proxies_run_id ON proxies(run_id);
CREATE INDEX IF NOT EXISTS idx_legacy_resolve_projects_run_id ON legacy_resolve_projects(run_id);
CREATE INDEX IF NOT EXISTS idx_verifications_run_id ON verifications(run_id);
CREATE INDEX IF NOT EXISTS idx_runs_started_at ON runs(started_at);
CREATE INDEX IF NOT EXISTS idx_organize_ops_run_id ON organize_ops(run_id);
CREATE INDEX IF NOT EXISTS idx_organize_ops_source ON organize_ops(source_path);
CREATE INDEX IF NOT EXISTS idx_verif_snap_folder ON verification_snapshots(folder);
"""

# The v0.2.4 schema applies the same DDL idempotently; we mirror that
# pattern here so the migration is safe to re-run after a partial
# failure.
VERSION = 1


def upgrade(conn: sqlite3.Connection) -> None:
    """Apply the legacy v0.2.4 schema. Idempotent."""
    conn.executescript(SCHEMA_SQL)


def downgrade(conn: sqlite3.Connection) -> None:
    """Drop the legacy v0.2.4 schema. Idempotent."""
    for table in (
        "verification_baselines",
        "verification_snapshots",
        "organize_ops",
        "verifications",
        "legacy_resolve_projects",
        "proxies",
        "probes",
        "files",
        "runs",
    ):
        conn.execute(f"DROP TABLE IF EXISTS {table}")
