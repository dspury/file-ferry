"""Migration 005 — transfer execution, path reservations, durable receipts.

Implements the persistence side of the destination-presets spec §7.2/§7.3
(the P5 runner's durable state):

- ``transfer_executions``: one row per started transfer job, linking the
  durable job to the approved plan fingerprint and recording the binding
  evidence the run validated against (resolved root, ``st_dev``, the
  resolver's binding snapshot). This is what resume revalidates against
  and what a receipt cites.
- ``transfer_execution_items``: per-entry execution state — the crash
  window ledger. ``copying`` rows carry the job-owned temporary path so
  recovery can discard exactly this job's partials and never a foreign
  ``.ferry-part``; ``published`` but uncommitted rows are the window a
  resume verifies with a full checksum rather than re-copying.
- ``transfer_path_reservations``: cross-job serialization of destination
  paths (spec §6.4). A partial unique index keeps one active reservation
  per ``(dest_root, rel_path)``; release is a column update, so history
  is retained for the receipt's provenance.
- ``transfer_receipts``: the durable database receipt (§7.3) — written
  first, before any file export. ``exported_path``/``export_error``
  record the file-export outcome so a failure is visible and retriable
  without ever implying the audit record itself is missing.

The downgrade drops all four tables. Execution state is reproducible
from the destination and the plan; receipts are exported to JSON before
the downgrade matters (development-only per ADR-0003).
"""

from __future__ import annotations

import sqlite3

VERSION = 5

_TABLES_DDL = """
CREATE TABLE IF NOT EXISTS transfer_executions (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    dest_root TEXT NOT NULL,
    dest_st_dev INTEGER,
    binding_json TEXT NOT NULL DEFAULT '{}',
    state TEXT NOT NULL DEFAULT 'running'
        CHECK (state IN ('running', 'succeeded', 'failed', 'cancelled', 'needs_attention')),
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_executions_plan ON transfer_executions (plan_id);
CREATE INDEX IF NOT EXISTS idx_executions_job ON transfer_executions (job_id);
CREATE INDEX IF NOT EXISTS idx_executions_fingerprint ON transfer_executions (fingerprint);

CREATE TABLE IF NOT EXISTS transfer_execution_items (
    execution_id TEXT NOT NULL REFERENCES transfer_executions (id) ON DELETE CASCADE,
    plan_entry_id INTEGER NOT NULL,
    dest_rel_path TEXT NOT NULL,
    source_path TEXT NOT NULL,
    size INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL DEFAULT 'pending'
        CHECK (state IN ('pending', 'copying', 'published', 'committed', 'skipped_identical',
                         'reused', 'excluded', 'failed')),
    temp_path TEXT,
    source_checksum TEXT,
    dest_checksum TEXT,
    checksum_algo TEXT,
    bytes_copied INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    warning TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (execution_id, plan_entry_id)
);
CREATE INDEX IF NOT EXISTS idx_exec_items_dest ON transfer_execution_items (execution_id, dest_rel_path);

CREATE TABLE IF NOT EXISTS transfer_path_reservations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dest_root TEXT NOT NULL,
    rel_path TEXT NOT NULL,
    execution_id TEXT NOT NULL REFERENCES transfer_executions (id) ON DELETE CASCADE,
    acquired_at TEXT NOT NULL,
    released_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_reservations_active
    ON transfer_path_reservations (dest_root, rel_path)
    WHERE released_at IS NULL;

CREATE TABLE IF NOT EXISTS transfer_receipts (
    execution_id TEXT PRIMARY KEY REFERENCES transfer_executions (id) ON DELETE CASCADE,
    plan_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    receipt_json TEXT NOT NULL,
    receipt_hash TEXT NOT NULL,
    final_state TEXT NOT NULL,
    written_at TEXT NOT NULL,
    exported_path TEXT,
    export_error TEXT
);
"""

_DROP_DDL = """
DROP TABLE IF EXISTS transfer_receipts;
DROP TABLE IF EXISTS transfer_path_reservations;
DROP TABLE IF EXISTS transfer_execution_items;
DROP TABLE IF EXISTS transfer_executions;
"""


def upgrade(conn: sqlite3.Connection) -> None:
    conn.executescript(_TABLES_DDL)


def downgrade(conn: sqlite3.Connection) -> None:
    conn.executescript(_DROP_DDL)
