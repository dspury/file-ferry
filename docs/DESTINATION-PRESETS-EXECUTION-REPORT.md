# Destination presets — execution report

Companion to [`DESTINATION-PRESETS-PRODUCTION-SPEC.md`](DESTINATION-PRESETS-PRODUCTION-SPEC.md).
This report records phase status, evidence, decisions, and blockers as work
proceeds. Statuses are `PASS`, `FAIL`, `NOT RUN`, or `BLOCKED`. Nothing here
is a production claim; §1.1 completion levels apply.

## Environment

- Machine: macOS (developer workstation), Python 3.14.3 (`.venv`), Node 22+.
- Baseline commit: `123aafd` (`main`), clean tree except the untracked spec.
- Commands: `docs/DESTINATION-PRESETS-PRODUCTION-SPEC.md` §11.

## Phase status

| Phase | Status | Notes |
| --- | --- | --- |
| P0 cleanup/baseline | PASS | See below |
| P1 safety regressions + guards | PASS | Commit-level evidence below |
| P2 persistence: destinations, preset revisions, inventories, plans | PASS | Migration 004 + services + protocol |
| P3 volume identity, discovery, rebinding | PASS | Identity adapters + resolver |
| P4 rule engine / conflict planner | NOT RUN | Out of this work order |
| P5 durable verified copy runner | NOT RUN | Out of this work order |
| P6 desktop flow / CLI parity | NOT RUN | Out of this work order |
| P7 packaging / pilot / real storage | NOT RUN | Out of this work order |
| P8 final review handoff | NOT RUN | Out of this work order |

## P0 — cleanup and baseline

### Baseline evidence

- `git rev-parse HEAD` → `123aafd`, branch `main`, `git status` clean except
  the untracked spec document (committed as part of this work).
- Python: 645 tests collected, all pass (full suite run ≥ 3 consecutive
  times this session; final run green immediately before the P0 commit).
- `ruff check .` clean; `ruff format --check .` clean; `mypy src` clean
  (64 files).
- Desktop (`desktop/`): typecheck/lint/test/build results recorded with the
  P2 protocol change; baseline before changes: 254 tests passing.

### Flaky `test_downgrade_drops_vnext` diagnosis

The spec's baseline observation (1/645 failure, SQLite backup "unable to
open database file", isolated rerun green) could **not** be reproduced:
15 focused reruns + 30 consecutive full-suite reruns all green this session.
Analysis of the code path (`persistence/backup.py::write_backup`):

- The backup filename was `ferry-{second-resolution ISO8601}-pre-{NNN}.db`;
  any two backups of the same migration version taken within one second
  (two runners sharing a backups dir) collide on one filename, and the
  loser's snapshot silently becomes the winner's file. The runner does not
  hold an EXCLUSIVE transaction (its docstring claimed one; fixed), so a
  concurrent second process is not structurally excluded.
- `sqlite3.connect` failures at either end surfaced as a bare
  "unable to open database file" without identifying which path failed.

Fix applied (no sleeps, no assertion changes):

- `write_backup` now uses microsecond timestamps plus a per-process counter,
  making filename collisions structurally impossible.
- Connect failures at either end re-raise with the offending path embedded.
- `runner.py` docstring corrected to describe actual cross-process
  serialization (write locking + caller serialization), not a phantom
  EXCLUSIVE transaction.

Disposition: hardening applied; failure not reproduced in 45 runs. If it
recurs, the error message now identifies the failing path — reopen with that
evidence.

### Repo map (legacy vs shared application paths)

- Entry points: `cli.py` (v0.2.4 standalone verbs: probe/organize/proxy/
  resolve/verify/run/log), `tui.py` (Textual UI over the same verbs),
  `cli_vnext.py` (durable verbs over `ApplicationService`), desktop sidecar
  (`service/` → `ApplicationService`).
- Shared authority: `application/` services + `persistence/` repositories;
  the legacy `organize.py`/`verify.py`/`proxy.py` modules remain the legacy
  CLI's implementation and were **not** mass-renamed (ADR-0005).
- Duplicate-logic inventory:
  - Organization: legacy `organize.py` (template renderer + conflict
    policies) vs `application/organize.py` (vNext OrganizeService). The
    vNext service is the authority for the new workflow; legacy keeps
    documented semantics.
  - Scanning: `application/sources.py::scan_inventory` is the shared
    scanner (used by inspect + planner). Legacy `probe.py` is media
    probing, distinct purpose.
  - Collisions: `application/plan.py::detect_collisions` (planned entries
    only at baseline) — extended in P1 to cover existing destinations.
  - Volumes: `drives.py::list_external_drives` is the mount-point source of
    truth; `application/volumes.py` adds the typed adapter/observer over it.
    Extended in P3 with identity evidence.
- No deletions were made in P0: no tracked code was proven unused
  (every legacy module has live CLI/TUI callers).

### Documentation reconciliation

- Root `README.md`: replaced the "All nine implementation packages are
  landed" claim with an accurate shipped-vs-gated statement and linked the
  destination-presets spec as planned work.
- `desktop/README.md`: removed the stale "placeholder renderer / not the
  actual screens / services not implemented" section that contradicted the
  existing screens and application services; pointed at the spec + this
  report for in-flight work.
- `docs/RELEASE.md`: fixed the dead `docs/DEVELOPMENT.md` link (points at
  the root README development section now). All referenced scripts exist.

### Decisions

- D0-1: The migration flake is treated as "hardened, not reproduced";
  documented above rather than papered over.
- D0-2: No legacy code deleted in P0 (spec §3 task 6 requires proven
  unused; nothing met that bar).
- D0-3: Backup filename format changed (microseconds + counter). Restores
  keyed on the old format still work — restore paths are provided by the
  caller, not pattern-matched.

## P1 — safety regressions and guards

Known-defect reproductions from spec §2 (all first written as failing
tests, then fixed in shared code):

| ID | Reproduction | Result |
| --- | --- | --- |
| P1-a | Organize overwrite: existing same-name file at destination replaced silently | Now refused: preview reports `existing_destination` collisions; apply publishes exclusively and never replaces (`tests/test_organize_safety.py`) |
| P1-b | Truncation: `source.inspect` reports 5,001 files but returns 5,000 entries; desktop Organize then copies only 5,000 | Cap removed; inspect returns every entry and a `truncated` flag that is always false absent a caller-supplied cap (`tests/test_organize_safety.py`) |
| P1-c | Traversal: template root `../outside` escapes the destination root | Rendered destinations validated against containment (absolute/`..`/NUL/symlink-escape rejected) in shared validation used by organize + new plan code (`tests/test_organize_safety.py`) |
| P1-d | False verification: move unlinks without any comparison; copy reports ok without reading back | move/link disabled with an actionable error (spec §1.2); copy verifies content checksums before reporting success |
| P1-e | Offload `os.replace` replaces externally created destination files | Exclusive publication (`os.link` + unlink of the temp sibling) shared by organize and offload; existing target fails the item, never overwrites (`tests/test_offload.py::test_copy_file_atomic_refuses_overwrite`) |

New shared module `application/transfer_safety.py`:

- `validate_destination_relpath` — containment validation for rendered
  destination paths (rejects absolute components, `..`, NUL, and symlink
  escapes via resolved-parent comparison).
- `publish_exclusive` — atomic no-clobber publication via hard-link;
  explicit `DestinationExistsError`/unsupported-filesystem errors instead
  of overwrite fallback.
- `copy_file_verified` — chunked copy to a job-owned temp sibling, fsync,
  source/destination checksums, source stability re-check, exclusive
  publication. Used by OrganizeService.apply; offload's
  `copy_file_atomic` now publishes exclusively too.

Behavior notes:

- `organize.apply` with `mode="move"`/`"link"` now raises an
  actionable error naming the safety contract (spec §1.2: visible
  restriction until an independently specified safety contract exists).
  The desktop Organize UI's move/link affordances are thereby cut off at
  the service boundary (UI labels updated in P6).
- `source.inspect` grew additive result fields (`truncated`, `errorCount`,
  `scanErrors` bounded list, per-entry `entryType`) — old response shapes
  unchanged otherwise.
- Scan failures are no longer silent: unreadable entries are inventoried
  as errors rather than skipped invisibly (spec §2 confirmed-defect list).

## P2 — persistence, preset revisions, destinations, inventories, plans

Migration `004_destination_presets.py` (schema v4; fresh + upgrade +
downgrade + pre-v4 fixture coverage in `tests/test_migration_destinations.py`
and `tests/test_migration_fixtures.py`):

- `saved_destinations` — §4.1 fields: stable id, display name, location
  kind (`local_folder|volume_folder|mounted_share_folder`), last observed
  root path, subfolder beneath the storage mount, identity evidence
  (kind/normalized value/confidence/platform provenance; no credentials),
  default preset + **pinned revision**, conflict policy, checksum algo,
  free-space reserve, last confirmed binding + last-seen timestamps,
  archived flag.
- `organization_profile_revisions` — immutable revision rows per §4.2
  (schema version, ordered rules with stable ids, ordered preserve groups,
  fallback template, conflict default, exclusions, content hash,
  `UNIQUE(preset_id, revision)`). Legacy profiles snapshot their current
  template as revision N (their existing version number) with pre-migration
  history recorded as unavailable — no fabricated history, no silently
  ignored keys (unknown legacy keys are preserved verbatim in the revision
  payload).
- `source_inventories` / `source_inventory_entries` — full server-side
  inventories (§4.3): entry type/size/mtime/scan status/error per entry,
  directories represented for empty-folder preservation, exclusion counts.
- `transfer_plans` / `transfer_plan_entries` — immutable durable plans
  (§4.3): destination identity/binding snapshot, preset revision + content
  hash, per-entry source → destination-relative path, matched rule, size,
  action, conflict findings, capacity estimate, deterministic fingerprint
  over substance, approval state keyed to the approved fingerprint.
- `jobs.project_id` relaxed to nullable via table rebuild — general
  transfers must not require a fake video project (§4.1); existing rows
  copy unchanged.

Services (shared application layer, no renderer logic):

- `application/destinations.py` — `DestinationService`: save/archive/list,
  resolve (§5.1 contract), confirm binding (explicit user action).
- `application/presets.py` — `PresetRevisionService`: save immutable
  revisions, get/list revisions, portable JSON export/import (presets only;
  schema-validated; no absolute paths or identities; imports create new
  local identities). Legacy `profile.*` methods retained on top of the
  same rows.
- `application/inventory.py` — `InventoryService`: background full scans
  persisted server-side; status + paginated entries (default 200, hard max
  1,000, stable ordering by insertion id, server totals). UI page size can
  never limit planning.
- `application/transfer_plan.py` — `TransferPlanService`: create plans
  from inventories + saved destination + preset revision (preserve-relative
  default template semantics for legacy root-only profiles; full rule
  engine is P4), existing-destination conflict findings, capacity estimate
  with reserve, deterministic fingerprint, approval by exact fingerprint,
  invalidation on input change.

Protocol (`service/protocol.py` + wiring + desktop/shared TS catalog,
updated in the same commits per ADR-0002):

- New methods: `destination.save`, `destination.list`, `destination.archive`,
  `destination.resolve`, `destination.confirmBinding`, `profile.saveRevision`,
  `profile.getRevision`, `profile.listRevisions`, `profile.export`,
  `profile.import`, `inventory.create`, `inventory.status`,
  `inventory.entries`, `transfer.planCreate`, `transfer.planGet`,
  `transfer.planEntries`, `transfer.planApprove`.
- Capability discovery: `app.getCapabilities` lists the new methods
  automatically (METHOD_NAMES is the catalog).
- CLI (`ferry destination …`, `ferry preset …`, `ferry inventory …`,
  `ferry transfer …`) covers the same operations with JSON output; full
  CLI parity including start/resume is P6/P5 respectively.

Exit-gate evidence: fresh-database and upgraded-database (v3 → v4) fixture
tests; legacy `profile.save`/`list`/`get` regression tests green; plan
fingerprint immutability + approval-mismatch rejection tests; pagination
boundary tests (200 default, 1000 max, stable cursor) in
`tests/test_inventory_service.py` and `tests/test_transfer_plan.py`.

## P3 — volume identity, discovery, availability, rebinding

- `application/volumes.py` extended: `VolumeObservation` = the existing
  `MountedVolume` plus typed identity evidence — `VolumeIdentity`
  (`volume_uuid` strong / `disk_uuid` medium / `server_share` /
  `path_only` weak, with normalized value + platform provenance). The
  adapter stays observation-only; classification remains the user's
  decision.
- `SystemVolumeAdapter` gains identity probes, time-bounded (5 s
  subprocess budget per probe; failures degrade to weak identity with the
  last observation retained and marked stale):
  - macOS: `diskutil info -plist` per mount → `VolumeUUID`/`DiskUUID`;
    network shares identified from the mount table device string
    (`//user@server/share`, `smbfs`/`nfs`/`afpfs`) — sanitized server/share
    identity, credentials stripped.
  - Linux: `/proc/self/mountinfo` + `/dev/disk/by-uuid` resolution.
  - Windows / unknown: `path_only` weak identity (honest limitation).
- `DestinationResolver` in `application/destinations.py` implements §5.1:
  - Strong identity match + subfolder match → `available` (binding path
    recorded, last-seen updated).
  - Not mounted → `offline`.
  - Weak/absent identity, host aliases, vanished folders →
    `needs_confirmation` with candidate locations; explicit
    `confirmBinding` (user action) updates the saved binding and
    invalidates pending approvals.
  - Multiple devices presenting the same identifier → `ambiguous`; never
    auto-executes.
  - Existing path but unwritable → `unwritable`.
  - A network share that disappeared while leaving its local mount
    directory behind resolves offline/needs_confirmation — never rebinds
    to the backing local directory (spec §5.2; fixture-tested).
- Recognition never starts jobs and never writes marker files.

Exit-gate evidence (fake adapters, real SQLite): renamed-volume rebinding
(A13-style), same-label wrong-drive refusal (A14-style), lingering mount
directory after share unmount (A12-style), spaces/Unicode paths (A25-style)
in `tests/test_destination_resolver.py`; empty-baseline vs
uninitialized-observer distinction retained in `tests/test_volumes.py`.

## Automated acceptance matrix (§10)

Status for the A-ids covered by P0–P3 work so far. IDs not listed are
`NOT RUN` (they belong to P4–P8).

| ID | Status | Evidence |
| --- | --- | --- |
| A01 (no silent cap) | PASS (service layer) | `test_organize_safety.py::test_inspect_returns_all_entries_*`; paginated inventories `test_inventory_service.py` |
| A06 (traversal/symlink escape) | PASS (service layer) | `test_organize_safety.py` traversal + symlink-root cases |
| A07 (unreadable/broken entries visible) | PASS (scan layer) | `test_sources.py` scan-error cases; inventory error counts |
| A12 (share unmounted, dir remains) | PASS (resolver layer) | `test_destination_resolver.py` |
| A13 (remount at new path) | PASS (resolver layer) | `test_destination_resolver.py` |
| A14 (reused label/path) | PASS (resolver layer) | `test_destination_resolver.py` |
| A25 (spaces/Unicode, empty baseline, slow probe) | PASS (resolver layer) | `test_destination_resolver.py`, `test_volumes.py` |
| A26 (weak identity, unknown capacity) | PASS (resolver/plan layer) | needs_confirmation states; capacity unknown → recorded override requirement |

End-to-end service-wiring tests (scan → save destination → save preset →
plan → approve) run through the real `ApplicationService` in
`tests/test_destination_end_to_end.py`.

## Blockers / unresolved

- Real-storage gates (§12.2) unrun by definition — no production claim made.
- P4+ (rule engine, keep-together groups, conflict planner beyond
  needs_review/keep-both defaulting, durable execution runner, desktop UI)
  not started; `transfer.start` intentionally absent until P5.
- Desktop renderer does not yet consume the new methods (P6); protocol +
  TS types are in place so the renderer work is additive.
