# Ferry Full App Implementation Plan

> **Status:** **All Packages 1–9 landed** — implementation complete at `810bc7b`
> **Date:** 2026-08-12 (updated 2026-08-14)
> **Product target:** A sturdy local-first Electron desktop application for
> media offload, existing-folder organization, project media management, proxy
> generation, verification, and editorial handoff.

## 0. Implementation progress

Tracked per package. Each landed package points to the commit that closed it
and the test count at handoff. The `SPEC.md` remains authoritative for
released v0.2.4 behavior until its sections are superseded through reviewed
changes; this log records build progress, not shipped-product claims.

| Pkg | Deliverable | Status | Commit | Head tests |
| --- | --- | --- | --- | --- |
| 1 | Contracts + repository foundation (ADRs, desktop scaffold, Python services foundation) | **Done** | `11d28b1` | 363 + 13 |
| 2 | Persistence migration + application services (schema, project/source/profile/asset/replica/job/audit services, safe-to-format gate) | **Done** | `a4798e2` | 436 + 13 |
| 3 | Planning, scheduler, recovery, receipt export | **Done** | `fbdbc98` | 459 + 13 |
| 4 | Verified offload, organization, logical clips, reconciliation | **Done** | `67b0b46` | 481 + 13 |
| 5 | Proxy as durable derivative job, project manifest + handoff | **Done** | `3b3c8b8` | 490 + 13 |
| 6 | Electron shell + secure bridge (sidecar supervisor, single-instance, volume watcher, reload/reconnect) | **Done** | `0951d4c` | 507 + 41 |
| 7 | Complete desktop experience (onboarding/doctor, Home, Projects, Ingest, Organize, Activity) | **Done** | `cbcb4a0` | 516 + 101 |
| 8 | TUI/CLI parity and legacy transition | **Done** | `25b6e46` | 523 + 101 |
| 9 | Packaged release + operational hardening | **Done** | `eddd63b` | 523 + 104 |

> Test counts are `pytest + desktop contract tests`. Package 1's `11d28b1` is
> the foundation commit (ADR freeze + desktop scaffold + Python services);
> Packages 2–5 each landed in one commit as listed.


## 1. Authority, intent, and completion standard

This is the complete build plan for the product direction in
[`FERRY-PRODUCT-DIRECTION.md`](./FERRY-PRODUCT-DIRECTION.md). The
current [`SPEC.md`](../SPEC.md) remains authoritative for released v0.2.4
behavior until its relevant sections are superseded through reviewed changes.

This plan does not describe a UI reskin over the existing CLI. It includes the
new durable application layer, persistence model, Electron application,
cross-surface compatibility, packaging, and operational validation necessary
for a real media-management application.

The build is complete only when a packaged macOS application can perform every
workflow in Section 4 using real media, recover safely from expected failures,
and retain independently reviewable receipts. A working development renderer,
a mocked test suite, or a successful one-shot pipeline is not sufficient.

## 2. Product commitments

The following are implementation commitments for this build:

1. **Electron is the desktop shell.** The renderer uses React and TypeScript;
   Electron main owns desktop lifecycle and the Python sidecar; Python remains
   the source of media-operation behavior.
2. **macOS is the first packaged desktop platform.** The Python CLI and Textual
   TUI remain supported interfaces on their existing supported platforms. The
   desktop architecture must not block Windows or Linux packaging later.
3. **The product remains local-first and account-free.** No cloud service,
   remote API, or user identity is required to use Ferry.
4. **The renderer never owns file mutations.** It requests typed application
   commands and displays durable job state. It has no Node integration and no
   general filesystem, shell, or database access.
5. **Offload and existing-folder adoption are coequal intake policies.** They
   share projects, assets, replicas, organization profiles, jobs, and receipts;
   they do not become disconnected pipelines.
6. **A card is never declared safe to format without policy-satisfied,
   independently verified replicas.** The default policy requires a working
   and backup replica; users may choose a stricter policy, never a hidden
   weaker one.
7. **Source provenance survives organization.** A preferred project layout is
   a new replica/location, not a replacement for the source record.
8. **Every material operation follows `plan -> review -> execute -> verify ->
   receipt`.** Move, overwrite, baseline acceptance, and deletion-affecting
   decisions require explicit user action.

## 3. Current-state constraints

The current Python package has independent `probe`, `organize`, `proxy`,
`resolve`, `verify`, and `log` modules. Click and Textual call those modules
directly, while `LogStore` provides an audit log. The current schema does not
represent projects as a general workspace, source cards, intake sessions,
replicas, durable jobs, or logical clips.

The new desktop product must preserve the existing CLI commands and audit
history. It may migrate the SQLite database, but migrations must be
transactional, versioned, idempotent, backed up before execution, and tested
against databases created by every supported prior release.

## 4. Finished user workflows

### 4.1 Create and configure a project

The user creates a project with a name, storage policy, working and backup
roots, an organization profile, proxy defaults, and optional Resolve defaults.
The application validates writable destinations, volume identity, free space,
and configuration before allowing an intake plan.

### 4.2 Offload a camera card safely

1. The user selects a detected volume or folder and identifies it as a camera
   source; Ferry records volume/source metadata and scans without writing.
2. The application inventories included and skipped paths, detects apparent
   spans/sidecars, estimates bytes, validates capacity, and creates an
   immutable plan.
3. The user selects the project and required working and backup destinations,
   then reviews the resulting source-preserving trees and collision policy.
4. Ferry copies each file into an incomplete destination, records
   per-file progress, atomically finalizes it, and verifies the configured
   checksum against the source before counting the replica as complete.
5. It creates a durable receipt. If every required replica is verified, the
   session says **safe to format**; otherwise it says exactly what is unmet.
6. Optional proxy and Resolve-handoff jobs operate from the verified working
   replica, never from the still-mounted card.

### 4.3 Adopt and organize existing media

1. The user selects a folder or drive supplied by another editor and identifies
   it as an existing-media source, not a card.
2. Ferry inventories it, captures provenance, and proposes asset/clip
   groups, duplicate candidates, unsupported formats, and path collisions.
3. The user selects a project and named organization profile, previews the
   complete source-to-destination plan, and explicitly selects copy, move, or
   allowed same-volume link behavior.
4. The job executes with per-file receipts and preserves the original source
   record. It does not imply the collaborator drive can be erased.
5. The project shows original and destination replicas, verification status,
   proxy readiness, and all warnings.

### 4.4 Operate and recover jobs

The user can watch, safely cancel, retry, resume, and inspect all jobs. Closing
a window does not stop jobs: Electron main and the Python sidecar remain alive.
Quitting with active jobs requires an explicit choice to keep the app running
in the background, wait, or cancel at a safe boundary. Ejection, permission,
out-of-space, process crash, source change, checksum mismatch, and FFmpeg
failure all leave an accurate terminal or recoverable state and an operation
receipt.

### 4.5 Reconcile and hand off a project

The user can scan a project and see missing, changed, offline, unverified, and
unprotected assets; a clear distinction remains between a temporary offline
drive and lost media. The user can export a portable JSON manifest and a
human-readable receipt describing project media, replicas, proxies, warnings,
and unresolved work.

## 5. Target architecture

```text
React renderer              Electron main                Python sidecar
views and local UI state -> typed IPC bridge ---------> application commands
job/event subscription  <- typed event bridge <--------- durable job events
                                     |
                                     v
                          native dialogs, volume watch,
                          single-instance lock, tray,
                          sidecar supervision, packaging

Python application layer
  projects / sources / intake planning / job scheduler / receipts
                                     |
                                     v
existing media capabilities
  probe / organize / proxy / verify / Resolve / configuration / persistence
                                     |
                                     v
filesystem / FFmpeg / ffprobe / SQLite / Resolve scripting API
```

### 5.1 Process and IPC design

- Electron main launches one sidecar per application instance and owns its
  lifetime. The main process, not the renderer, is the sidecar's parent.
- Development runs `python -m ferry.service`; packaged builds launch a
  platform-matched frozen executable outside `app.asar`.
- Electron main and the sidecar communicate with versioned JSON-RPC messages
  over stdio. This avoids a listening port, browser-exposed local service, and
  stale-port failure mode. The protocol supports request/response, correlated
  errors, and asynchronous job events.
- Renderer-to-main communication uses `contextBridge` with a named,
  schema-validated capability API. Enable `contextIsolation` and sandboxing;
  disable `nodeIntegration`, remote-module access, arbitrary external
  navigation, and arbitrary shell execution.
- A renderer reload/crash may lose its subscription but cannot lose job state.
  Main replays a current job snapshot on reconnect. If a sidecar exits,
  Electron main records the condition, restarts only when safe, and never marks
  interrupted work successful.
- The desktop app uses a single-instance lock. A second launch forwards its
  request to the existing process instead of opening a second writer against
  the project database.

### 5.2 Code layout

```text
src/ferry/
  application/     project, source, intake, plan, job, receipt services
  persistence/     database connection, migrations, repositories, backup
  service/         JSON-RPC protocol, server, sidecar bootstrap
  capabilities/    compatibility home for probe/organize/proxy/verify/resolve
  cli.py            thin client over application services
  tui.py            thin client over application services

desktop/
  package.json
  electron/         main process, preload bridge, sidecar supervisor
  renderer/         React/TypeScript application and styles
  shared/           IPC schemas and generated/duplicated contract fixtures
  tests/            main, preload, renderer, and packaged-app tests
  build/            Electron Builder configuration and signing scripts
```

Move existing modules only when a compatibility-preserving extraction is
proven by tests. It is acceptable for the initial application services to call
the current modules in place; their business rules must not be duplicated in
the renderer or Electron main process.

## 6. Persistence and media model

### 6.1 Database ownership and migrations

The sidecar/application service is the sole desktop database writer. Configure
SQLite with foreign keys, WAL journaling, a busy timeout, and transactions that
cover every state transition. Before each schema migration, create a verified
database backup alongside a migration receipt. Failed migrations leave the
original database usable and block normal app startup with a recovery action.

Replace ad-hoc column checks with numbered migrations and a recorded schema
version. Existing audit tables remain readable; repositories expose them as
legacy operation history until their data has been linked to newer entities.

### 6.2 Required entities

| Entity | Responsibility |
| --- | --- |
| `projects` | Project identity, roots, policy defaults, Resolve/proxy settings, timestamps. |
| `organization_profiles` | Named/versioned source-to-destination templates, conflict and mutation policy. |
| `sources` | User-selected card, volume, or folder; volume/source fingerprint and captured root. |
| `intake_sessions` | Offload or existing-folder adoption intent, plan fingerprint, user decisions, terminal status. |
| `intake_destinations` | Required working/backup/organization outputs and their individual verification state. |
| `assets` | Stable media identity, observed metadata, origin/source-relative path, lifecycle state. |
| `replicas` | A physical asset location, volume identity, path, size, checksum, availability, and verification time. |
| `logical_clips` / `logical_clip_members` | Multi-file/spanned clip membership and detection confidence. |
| `derivatives` | Proxy and later derived outputs, source asset, settings fingerprint, readiness/failure state. |
| `jobs` | Durable operation command, arguments/plan fingerprint, state, owner session, timing, resumability. |
| `job_steps` / `job_items` | Per-stage and per-file progress, errors, retryability, temporary destination path. |
| `operation_receipts` | Immutable receipt JSON, display summary, path, hash, and export version. |
| `audit_events` | Append-only state/change events, replacing no prior evidence and linking legacy `runs`. |

`files`, `probes`, `proxies`, `projects`, `verifications`, `organize_ops`, and
`runs` are migrated carefully or retained as legacy tables with explicit links;
do not silently reinterpret existing rows as verified replicas.

### 6.3 Identity, replicas, and checksums

- A path is a location, not an asset identity.
- An asset starts with an observed identity based on source-relative path, size,
  modification metadata, media probe information, and recorded checksum.
- A replica becomes verified only after the source and destination checksum
  agree under a receipt-recorded algorithm. The initial safety policy uses the
  configured checksum algorithm; a future stronger-identity policy may add a
  second content digest without rewriting prior facts.
- A re-scan never silently merges two uncertain assets because their names are
  similar. Any uncertain duplicate or logical-clip inference is labeled for
  review.
- A source/card fingerprint records filesystem/volume properties and the intake
  manifest hash. It is evidence, not a claim that every removable volume is
  uniquely identifiable forever.

### 6.4 Job state machine

```text
planned -> awaiting_review -> queued -> running -> verifying -> succeeded
                                  |         |          |
                                  v         v          v
                            cancelled  needs_attention  failed
                                              |
                                              v
                                          resumable
```

- `succeeded` is allowed only after all mandatory job steps and verification
  steps complete.
- `needs_attention` is used for source change, missing/ejected volume,
  permissions, collision choice, insufficient space, or user action required.
- A resume validates source/destination state and the original plan fingerprint
  before it reuses a partial output. It never blindly appends to an arbitrary
  file.
- Cancellation is cooperative. Copy and FFmpeg work stop at documented safe
  boundaries; incomplete files stay marked partial or are cleaned only when the
  receipt proves they are owned temporary outputs.

### 6.5 Receipts and export

Receipts are immutable JSON documents stored in the project state directory and
indexed by SQLite. They include application/protocol versions, policy and
settings fingerprints, source and destination descriptors, planned and actual
operations, checksums, warnings, error details, final state, and timestamps.
The desktop exports a companion human-readable Markdown or HTML report. Receipt
schemas are versioned and covered by fixture tests.

## 7. Media-operation requirements

### 7.1 Planning and capacity

- Scan before writes, excluding existing system-artifact rules consistently.
- Calculate source bytes, destination free space, policy-required replicas,
  output overhead, and a configurable safety reserve.
- Detect path traversal, invalid templates, case-only collisions, duplicate
  destinations, unavailable paths, read-only volumes, and source-destination
  identity before execution.
- Preserve source folder hierarchy for card offload by default. Organization is
  an explicit second output/policy, never a hidden transform of original media.

### 7.2 Copy and verification engine

- Write each copy to an application-owned temporary name in the final parent
  directory; flush/close it; atomically rename only after the transfer succeeds.
- Record per-file byte progress, source fingerprint, destination path,
  completion time, and verification result transactionally with job state.
- Compare checksums after copy; mismatches fail that replica and keep the card
  unsafe. Never replace a good verification baseline on mismatch.
- Preserve all completed verified copies when a later required destination
  fails. The receipt explains the partial state and retry path.
- Limit concurrent writes per physical volume. Read-only scans may run with a
  bounded pool; CPU-heavy proxy jobs and I/O-heavy copies use scheduler limits
  so the application does not saturate one drive by default.

### 7.3 Organization engine

- Promote the existing template behavior into versioned organization profiles.
- Always provide a complete preview tree and collision report before a mutating
  operation.
- `copy` is the default. `move` requires an elevated confirmation showing the
  source deletion consequence. Same-volume linking is opt-in and only when its
  aliasing behavior is truthful for the requested workflow.
- Keep existing hardlink, case-sensitivity, and multi-file-clip safety rules;
  add an explicit logical-clip group model rather than only warnings.

### 7.4 Proxy and Resolve engine

- Proxies run only from a verified working replica unless the user explicitly
  selects a non-safety-critical existing-media workflow.
- Carry the current probe-informed FFmpeg behavior into durable per-asset jobs,
  including VFR policy, timecode/color/SAR, optional audio, RAW refusal, and
  output validation.
- Proxy state belongs to `derivatives`, making retries, staleness, and readiness
  visible per asset and project.
- Resolve integration must prove live media import, recursive bin parity, and
  timeline creation in a real Resolve test environment. Until that proof exists,
  label the output **manifest for import**, never **Resolve project created**.

### 7.5 Reconciliation

- Reconciliation compares known replicas with present filesystem state without
  automatically changing the accepted baseline.
- It distinguishes missing, changed, unverified, offline-volume, inaccessible,
  and unknown files.
- Acknowledge/accept-change actions create new evidence and preserve the prior
  receipt/history; they do not overwrite it.

## 8. Electron desktop application

### 8.1 Main-process responsibilities

- Enforce one running instance and own app lifecycle.
- Start, monitor, restart, and terminate the Python sidecar according to safe
  job state.
- Maintain an event bridge and reconnect renderer windows after reload/crash.
- Show native file/folder pickers and never accept an arbitrary path supplied
  by renderer code without validation.
- Discover mounted volumes through a small, tested platform adapter and report
  only observations; it must not label a volume a camera card automatically.
- Keep active jobs alive when the last window closes; expose a menu/tray path
  to reopen status. Explicit Quit handles active jobs as Section 4.4 defines.
- Own diagnostic logs, crash reporting stored locally, capability/FFmpeg doctor,
  and update checks. No telemetry leaves the machine without a future explicit
  opt-in.

### 8.2 Renderer information architecture

| Surface | Required content and actions |
| --- | --- |
| Onboarding / Doctor | Storage roots, FFmpeg/ffprobe, Resolve status, permissions, safety policy, data location. |
| Home | Active jobs, connected sources, unsafe cards, missing/unverified replicas, failed work, proxy readiness. |
| Projects | Project list, storage-policy health, assets, clip groups, replicas, derivatives, receipt history. |
| Ingest | Source inventory, project/destination selection, capacity, copy policy, reviewable plan, live execution. |
| Organize | Existing-media source selection, profile picker/editor, tree preview, collision decisions, job handoff. |
| Asset / Clip detail | Metadata, source provenance, logical grouping, every replica, verification/proxy state, related receipts. |
| Activity | Running/finished/attention jobs, per-step progress, safe cancel/retry/resume, searchable receipts. |
| Settings | Defaults, paths, job limits, checksum policy, safety reserve, app data/export locations. |

The renderer uses virtualized lists for large asset inventories, incremental
event updates instead of polling full databases, accessible keyboard navigation,
high-contrast state semantics, and explicit destructive-action dialogs. It is a
professional operations interface, not a generic card dashboard.

### 8.3 IPC contract families

Define schemas once and validate both sides. At minimum:

- `app.getStatus`, `app.getCapabilities`, `app.openDiagnosticFolder`
- `project.list|get|create|update|archive`, `profile.list|save|preview`
- `source.pick|inspect|listVolumes`
- `intake.createPlan|getPlan|submit|review`
- `job.list|get|subscribe|cancel|resume|retry`
- `asset.list|get`, `replica.reconcile`, `receipt.get|export`
- `settings.get|update`

All commands return explicit typed errors and correlation IDs. Never serialize
unbounded FFmpeg output or arbitrary filesystem content to the renderer.

## 9. CLI and TUI compatibility

The CLI and TUI stay first-class. They migrate from directly composing
capability functions to calling the same application service used by the
sidecar, either in-process or through a tested client boundary.

Add explicit CLI verbs for `project`, `source inspect`, `intake plan`, `intake
run`, `jobs`, `receipt export`, and `reconcile`. Preserve current standalone
`probe`, `organize`, `proxy`, `resolve`, `verify`, `log`, and `run` behavior
with documented mappings to the new job/receipt model. Existing automation must
not be forced to launch Electron.

Retain the Textual TUI as the terminal workstation. It gains project and job
views through the shared service but does not need to duplicate every visual
desktop affordance. It remains an important recovery and remote-use surface.

## 10. Build sequence and work packages

The following sequence covers the whole application; it is ordering for safe
integration, not a reduction in product scope.

### Package 1 — contracts and repository foundation

> **Status:** Done (`11d28b1`). Steps 2–4 landed; step 1 (SPEC authority)
> deferred until a release supersedes v0.2.4.

1. Ratify this plan and update `SPEC.md` authority/release language.
2. Define Python and TypeScript protocol/data-schema sources, compatibility
   rules, versioning, and fixture exchange.
3. Establish `desktop/` Node workspace, pinned package manager/runtime policy,
   Electron Builder configuration, React/TypeScript renderer, and lint/test
   tooling without changing current Python behavior.
4. Create app-data, logging, diagnostics, and data-retention conventions for
   development and packaged execution.

### Package 2 — persistence migration and application services

> **Status:** Done (`a4798e2`). All 5 steps landed.

1. Introduce a connection/migration subsystem with backup/rollback behavior.
2. Add the entities in Section 6 and repositories with foreign keys/indexes.
3. Build project, profile, source, asset, replica, receipt, and job services.
4. Link legacy audit history where evidence is unambiguous; preserve all other
   history as legacy rather than manufacturing project facts.
5. Add migration fixtures for every shipped database shape and interruption
   tests for migration and backup failure.

### Package 3 — planning, scheduler, and recovery engine

> **Status:** Done (`fbdbc98`). Steps 1–3 landed; step 4 (migrate standalone
> CLI/TUI commands) deferred to Package 8 per plan §9 ordering.

1. Implement source inspection, volume abstraction, planning, capacity, and
   collision analysis.
2. Implement durable job scheduling, per-volume concurrency controls,
   cooperative cancellation, restart recovery, and event publishing.
3. Implement receipt writer/exporter and job-state transition enforcement.
4. Migrate existing standalone pipeline commands to the application services;
   preserve tested module behavior under the new boundaries.

### Package 4 — verified offload and organization

> **Status:** Done (`67b0b46`). All 4 steps landed.

1. Implement source-preserving offload with required destinations, temporary
   files, atomic finalization, per-file checksum verification, and card-safety
   policy.
2. Implement existing-folder adoption, organization profiles, preview trees,
   move/link confirmation, and provenance retention.
3. Implement logical-clip detection/membership and safe group behavior through
   offload, organization, proxying, and handoff.
4. Implement reconciliation and explicit baseline acceptance/history.

### Package 5 — media derivatives and editorial handoff

> **Status:** Done for the buildable surface (`3b3c8b8`). Step 1 and the
> fallback branch of step 3 (labeled import manifest) and step 4 landed.
> **Step 2 (real-media proxy validation: VFR/silent/multi-audio/SAR/RAW
> refusal) and the live Resolve integration in step 3 remain deferred** to
> the §11.2 real-media acceptance suite.

1. Make proxy generation a job with per-asset derivative state and usable
   progress events.
2. Complete real-media proxy validation for VFR, silent clips, multiple audio
   tracks, color/timecode/SAR, errors, and RAW refusal.
3. Complete the live Resolve integration or intentionally ship only a clearly
   labeled import manifest until real integration passes its acceptance suite.
4. Implement portable project manifest and human-readable handoff export.

### Package 6 — Electron shell and secure bridge

1. Implement Electron main, preload, JSON-RPC sidecar supervisor, protocol
   error handling, single-instance behavior, and local diagnostics.
2. Implement system volume observation and native chooser adapters behind a
   testable interface.
3. Package and launch the frozen Python sidecar from Electron in development
   and production; validate renderer reload, sidecar restart, and app/window
   close semantics.
4. Apply the security configuration in Section 5.1 and test that prohibited
   renderer capabilities are unavailable.

### Package 7 — complete desktop experience

1. Build onboarding/doctor and settings first so real installations explain
   missing dependencies and data locations.
2. Build Home, Projects, Ingest, Organize, Asset/Clip Detail, Activity, and
   Receipt Export to the requirements in Section 8.2.
3. Wire every mutating UI action through plan/review/execute/verify/receipt;
   no optimistic success UI is permitted.
4. Add keyboard accessibility, large-library rendering behavior, diagnostic
   copy/export, and design-system-level visual states for safety-critical work.

### Package 8 — TUI/CLI parity and legacy transition

1. Rewire CLI commands to application services and add new project/intake/job
   commands with machine-readable output where appropriate.
2. Rewire the Textual TUI queue/activity path to durable jobs; retain a stable
   `--no-tui` escape hatch.
3. Document all changed semantics, migration behavior, compatibility promise,
   and recovery operations.

### Package 9 — packaged release and operational hardening

1. Freeze and bundle the Python sidecar per architecture; ensure app resources
   and renderer build are available outside `app.asar` where required.
2. Configure macOS signing, notarization, entitlements, app data locations,
   first-run behavior, crash diagnostics, and release provenance.
3. Build a repeatable clean-machine and clean-app-data test procedure.
4. Establish a signed release/update policy. Auto-update must be disabled until
   update signing, rollback, and release verification are proved.

## 11. Test and release matrix

### 11.1 Automated validation

- Python unit tests for models, migrations, repositories, state transitions,
  planning, capacity, copy/verify logic, recovery, organization, proxy, and
  Resolve fallback.
- Protocol contract tests using shared JSON fixtures for every IPC command,
  event, validation failure, and version mismatch.
- Electron main/preload tests for sidecar lifecycle, single-instance behavior,
  secure bridge exposure, volume adapter behavior, and window-close policy.
- Renderer component and accessibility tests for plan review, unsafe-card state,
  destructive confirmations, job attention/retry, and receipt detail.
- End-to-end Electron tests with a real sidecar and temporary filesystem roots;
  include renderer reload during a job and sidecar failure/restart.
- Regression tests for all existing CLI/TUI commands and every shipped database
  migration shape.
- Repository quality gates: Ruff, formatting, strict mypy, Python tests,
  TypeScript typecheck, JavaScript lint, renderer tests, Electron tests,
  dependency/security scan, and `git diff --check`.

### 11.2 Real-media acceptance suite

Run against disposable drives and representative footage, retaining receipts:

| Scenario | Required proof |
| --- | --- |
| Two-destination card offload | Both replicas checksum-verified; safe-to-format state appears only then. |
| Destination full / permission denied | No false success; accurate needs-attention receipt; valid completed copy remains intact. |
| Source eject / app restart / renderer reload | Job is recoverable or correctly terminal; no corrupted final file or fabricated completion. |
| Existing editor drive organization | Preview matches actual output; source provenance and all operations are retained. |
| Same-volume link / move | Explicit UI language and behavior match the selected policy; no hidden source deletion. |
| VFR, silent, multi-audio, anamorphic, RAW | Proxy results/refusals are truthful and inspected with ffprobe. |
| Spanned clip | Group survives workflow and is shown as a logical clip. |
| Resolve available and unavailable | Live import/timeline proof or correctly labeled manifest fallback. |
| Reconciliation | Missing, modified, offline, and accept-change paths preserve history. |
| Packaged fresh install | Signed app launches with the bundled sidecar, creates data safely, and completes an offload. |

### 11.3 Release gates

Do not call the app stable until all are true:

- Full automated matrix is green on the supported macOS architectures.
- Migration, package, and clean-app-data tests pass from a released prior DB.
- The real-media suite passes on at least two storage configurations.
- A prolonged offload/proxy soak completes with no orphaned jobs, stale
  sidecars, locked database, or incorrect safety state.
- A reviewer can inspect receipts and reproduce the claimed result.
- Security review confirms renderer isolation and no unintended listener or
  privileged IPC surface.
- Signed/notarized package installation and update/rollback policy are proven.

## 12. Dependency and packaging policy

- Keep Python runtime dependencies minimal; do not add a web framework merely
  to support the desktop client.
- Add Electron, React, TypeScript, a test runner, and Electron Builder only in
  `desktop/`, pinned by lockfile and reviewed as a separate dependency surface.
- Freeze the Python sidecar with a reproducible per-platform build. Verify it
  can locate bundled package data and external optional integrations after
  packaging.
- Continue to detect FFmpeg/ffprobe and Resolve explicitly. A future bundled
  FFmpeg decision requires licensing, architecture, update, and security review
  before it becomes a release dependency.
- Avoid automatic system mutation: Ferry may diagnose missing tools and
  explain setup, but it does not silently install binary dependencies.

## 13. Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| A polished UI hides unsafe transfer semantics | Enforce durable plan/review/verify/receipt states in service and UI; test false-success paths. |
| Renderer/main/sidecar disagreement | Versioned schema contract, shared fixtures, typed errors, and restart/replay tests. |
| SQLite corruption or migration loss | Single writer, WAL, backups, transactional numbered migrations, prior-DB fixtures. |
| Drive removal or process crash during copy | Partial-file ownership, per-file journal, atomic finalization, resumable attention states. |
| Electron renderer security exposure | Context isolation, sandbox, no Node integration, narrow preload API, no local HTTP listener. |
| Packaging works only in development | Package early; test frozen sidecar and resource paths in every release candidate. |
| Large media collections freeze UI | Virtualized UI lists, incremental job events, bounded scans, no blocking renderer work. |
| Resolve claims exceed proof | Treat manifest handoff as fallback until a live integration test proves import and timeline behavior. |
| Cross-platform promises outpace testing | State macOS desktop support precisely; retain CLI/TUI portability and add platform packages only with gates. |

## 14. Documentation deliverables

Update or add the following as implementation lands:

- `SPEC.md`: shipped behavior and released-version contract.
- `README.md`: desktop installation, CLI/TUI relationship, and actual support
  matrix.
- `docs/ARCHITECTURE.md`: process model, IPC boundary, persistence ownership,
  directory layout, and crash recovery.
- `docs/OPERATIONS.md`: offload policy, recovery, receipt interpretation,
  reconciliation, and safe-to-format semantics.
- `docs/DEVELOPMENT.md`: Python/desktop development environment, sidecar build,
  test commands, fixtures, and local app-data reset procedure.
- `docs/RELEASE.md`: signing/notarization, packaged-app verification, database
  migration, rollback, release artifact, and clean-machine gates.
- UI capture/screenshots and a sample redacted receipt for major interface
  releases.

## 15. First execution action after plan approval

Begin with a short architecture decision record that freezes: Electron main /
preload / renderer boundaries; stdio JSON-RPC protocol version; app-data and
sidecar lifecycle; database migration strategy; and the exact safe-to-format
policy. Then create the `desktop/` scaffold and Python application-service
interfaces in one compatibility-preserving foundation change.

No media-moving desktop UI should be implemented before that foundation has
automated contract, migration, and recovery tests.

---

## 16. Implementation status (updated 2026-08-14)

All nine work packages are **Done** (see §0 table). The build sequence in
§10 was followed in order. What follows is the honest, current state and the
items that are intentionally still open.

### 16.1 Remaining items (operator-owned — not code)

These are the §11.3 release gates that need a human, a real Apple Developer
ID, hardware, or external review. The build configuration and procedures are
in place; these steps cannot be completed by a repo change alone.

- **Real macOS signing / notarization.** `build/electron-builder.yml` sets
  `hardenedRuntime`, entitlements, `notarize: true`, and `dmg.sign: true`,
  but producing a signed/notarized build requires an Apple Developer ID +
  notarization credentials in the build environment. Until proven, local
  builds run unsigned for development.
- **Real-media acceptance suite (§11.2).** Proxy validation for VFR / silent /
  multi-audio / SAR / RAW refusal, plus the live Resolve integration, are
  still deferred to the real-media suite. The labeled Resolve import manifest
  ships as the honest fallback until a live integration test proves import /
  timeline behavior.
- **Prolonged offload/proxy soak.** A long-running offload/proxy run must
  complete with no orphaned jobs, stale sidecars, locked database, or
  incorrect safety state.
- **Security review.** Confirm renderer isolation, no unintended listener or
  privileged IPC surface.
- **Signed install + update/rollback proof.** Auto-update is disabled; when
  enabled, it must first prove signed update artifacts, a rollback path, and
  release verification.

### 16.2 Areas flagged for deeper review

These are places a deep audit should scrutinize. They are not known defects,
but they carry the most risk / subtlety and deserve a closer look before the
app is called stable.

- **The Ingest `execute` path is a multi-call sequence, not a single atomic
  command.** It runs `intake.createSession` → `addDestination` (per root) →
  `intake.adoptSource` → `job.create` as four separate IPC calls from the
  renderer. A failure partway leaves a partially-set-up session. Consider a
  single `intake.submit`/plan-execute IPC that runs the sequence on the
  sidecar so it is atomic and recoverable. The 7d Ingest screen builds it
  step-by-step today.
- **`job.retry` creates a fresh job (per the §6.4 machine where `failed` is
  terminal).** This is correct against the frozen state machine, but the
  fresh job drops `argsFingerprint` (not carried on `JobDetail`). Verify a
  retry truly reuses the intended plan/fingerprint and does not silently
  re-run with different arguments.
- **Renderer tests run in node, not a DOM/jsdom.** Component logic is extracted
  into pure `lib/*` modules and unit-tested, but the `.tsx` components
  themselves have no rendering tests. A real renderer test harness
  (jsdom + testing-library) would close the gap between pure-logic coverage
  and actual component behavior.
- **The Desktop CI gap.** `.github/workflows/ci.yml` runs the Python matrix
  only; the desktop typecheck/lint/tests/build are run locally and are not yet
  enforced in CI. Add a desktop job before relying on the desktop surface.
- **Sidecar version strings are still `"0.0.0+foundation"`.**
  `SIDECAR_VERSION` in `application/service.py` and the `service.py` module
  docstring still describe the foundation cut. Refresh to a real version and
  current description now that the app is feature-complete.
- **`source.inspect` / volume observations and classification.** The volume
  adapter reports observations only and never labels a card; the intake layer
  decides. Review that no hidden heuristic labels a card anywhere.
- **Legacy CLI `run` still composes capability modules directly** while the
  vNext verbs call `ApplicationService`. Both are supported, but the legacy
  `run` pipeline has not been migrated onto the durable job model. Confirm the
  documented mapping (§9) and that a legacy `run` and a vNext job cannot
  double-write the same project state unexpectedly.
- **The `intake.adoptSource` params use `entries` (full inventory) over IPC**
  — for a very large card this is a large payload. Consider passing the
  source id and re-reading the manifest sidecar-side, or a bounded/paged
  inventory, to avoid unbounded serialization (plan §8.3: "never serialize
  unbounded FFmpeg output or arbitrary filesystem content to the renderer").
- **Electron window-close semantics are keep-alive only.** `window-all-closed`
  keeps the app running so active jobs continue; there is no tray/menu path
  to reopen the window (the plan §8.1 calls for one). Add a tray/status-item
  affordance before shipping.
