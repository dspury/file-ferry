# ADR-0003 — Application persistence model

- **Status:** Accepted
- **Date:** 2026-08-12
- **Supersedes:** v0.2.4 `SPEC.md` §7 schema sketch (additive only)

## Context

The v0.2.4 SQLite audit log is a working system of record for the
existing CLI + TUI capabilities. The vNext direction adds new
entities (projects, sources, intake_sessions, replicas, jobs,
logical_clips, derivatives, organization_profiles, operation_receipts,
audit_events) per the plan §6.2. The existing tables (runs, files,
probes, proxies, projects v0.2.4, verifications, organize_ops,
verification_snapshots, verification_baselines) must remain readable
and continue to be written by the existing capabilities.

The plan §6.1 demands:

- A single desktop writer.
- Numbered, versioned migrations.
- Pre-migration backups with a per-migration receipt.
- Transactional schema changes; failed migrations leave the original
  database usable.
- Tested against every shipped prior database shape.

## Decision

**Single writer, the sidecar.** Configure SQLite with:

- `journal_mode = WAL`
- `foreign_keys = ON`
- `busy_timeout = 5000` ms
- `synchronous = NORMAL`
- A connection-per-transaction model; the connection is short-lived
  and never held across an external-tool invocation (ffmpeg, ffprobe,
  Resolve).

**App data layout** (`~/.media-mate/` on macOS and Linux;
`%APPDATA%/media-mate/` on Windows):

```
~/.media-mate/
├── media-mate.db          # the SQLite database (WAL + SHM alongside)
├── media-mate.db-shm
├── media-mate.db-wal
├── backups/
│   ├── media-mate-2026-08-12T17-30-00Z-pre-007.db
│   └── media-mate-2026-08-12T17-30-00Z-pre-007.db.sha256
├── logs/
│   └── sidecar.log        # JSON-line timeline of sidecar events
├── receipts/
│   ├── {intake_session_id}.json
│   └── {operation_id}.json
├── crashes/
│   └── sidecar-{ISO8601}.crash
└── preferences.toml       # per-user, non-tracked choices
```

**Numbered migrations.** Migrations are Python modules under
`src/media_mate/persistence/migrations/`, named `NNN_description.py`
with `upgrade(conn)` and `downgrade(conn)` functions. The migration
runner is a single-pass loader that:

1. Acquires an exclusive lock on the database file.
2. Snapshots the current `schema_version` from `schema_meta`.
3. Computes the target version for the running code.
4. For each migration to apply, in source order:
   - Verify the target version is not less than the current version.
   - Take a backup of the DB file at
     `backups/media-mate-{ISO8601}-pre-{NNN}.db` and a `.sha256`
     sidecar.
   - Run `upgrade(conn)` inside a transaction.
   - Update `schema_meta.schema_version` to the new version.
   - On any failure, run `downgrade(conn)` if defined, otherwise
     restore from the backup file.
   - Always emit a migration receipt to `logs/sidecar.log`.
5. On startup with a stale (lower) version, refuses to run unless
   `MIGRATE_DOWN=1` is set (off by default).

**Legacy tables stay readable.** The legacy tables (`runs`, `files`,
`probes`, `proxies`, `projects` v0.2.4, `verifications`,
`organize_ops`, `verification_snapshots`,
`verification_baselines`) are not migrated into the new entities by
default. They remain the source of legacy audit history. New
code reads them through the `audit_events` view when evidence is
unambiguous; otherwise they remain legacy and are surfaced as
"pre-vNext history" in the UI.

**New entities are added in their own migration wave.** Migration
`007_vnext_entities.sql` (or equivalent Python module) creates the
new tables: `projects` vNext, `organization_profiles`, `sources`,
`intake_sessions`, `intake_destinations`, `assets`, `replicas`,
`logical_clips`, `logical_clip_members`, `derivatives`, `jobs`,
`job_steps`, `job_items`, `operation_receipts`, `audit_events`. The
old `projects` table is renamed to `legacy_resolve_projects` to
free the name for the new entity.

**Receipts.** Each durable operation (intake, organize, reconcile,
proxy batch) writes an `operation_receipts` row plus a JSON file at
`receipts/{intake_session_id}.json`. The JSON file is the human- and
machine-readable record; the row is the index.

**Backup retention.** Backups are kept for 30 days or the last 10
migrations, whichever is more. Cleanup runs at sidecar startup.

**Concurrency.** Reads (from the renderer via the schema-validated
IPC) and writes (from the sidecar) share the same WAL database. The
sidecar is the only writer; the renderer never reads or writes
directly.

## Consequences

Positive:

- The existing CLI / TUI capabilities continue to work unchanged;
  the legacy audit log is preserved.
- A failed migration never leaves the user with a broken database;
  the backup file is the recovery artifact.
- The single-writer model means we never have to reason about
  concurrent writes.
- WAL allows concurrent reads while a write is in progress, which
  the renderer uses for live job updates.

Negative:

- The migration runner is a critical piece of code. It will be
  tested extensively (every prior DB shape, every interrupted
  migration, every backup failure).
- The legacy tables grow without automatic compaction. A future
  migration can archive them, but for now the DB file grows.

Neutral:

- The CLI's `--db` flag continues to work; the desktop app does not
  introduce a new database path.
- Cross-platform app-data paths are handled by `platformdirs` (or
  stdlib equivalent) so the desktop app and the CLI agree on the
  location.

## References

- `docs/MEDIA-MATE-FULL-APP-IMPLEMENTATION-PLAN.md` §6.1, §6.2, §6.5
- v0.2.4 `SPEC.md` §7 (legacy schema, preserved)
- SQLite WAL docs: https://www.sqlite.org/wal.html
- SQLite backup API: https://www.sqlite.org/backup.html
