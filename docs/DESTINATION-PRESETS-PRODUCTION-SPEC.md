# Ferry saved destinations and organization presets — execution specification

Status: Draft for implementation and subsequent review; nothing in this document is a shipped claim.
Date: 2026-09-10
Baseline inspected: `123aafd` (revalidate HEAD and working tree before execution).
Scope owner: User-requested general-purpose organization and verified transfers.

## 1. Outcome and authority

Deliver a local-first workflow in which a user selects one or more sources, selects a saved destination, reviews that destination's organization preset, and performs a complete, verified, recoverable transfer. Destinations can be mounted network shares, removable disks, fixed volumes, or local folders. No NAS vendor, private hostname, user-specific path, or personal taxonomy belongs in application code.

The user can save destinations and reusable presets, recognize previously saved storage when it returns, and organize mixed files without FFmpeg or media probing being a prerequisite. Proxies remain optional existing functionality.

This spec defines the next scoped increment after the historical full-app plan. Existing accepted ADRs and compatibility contracts remain applicable except where this document explicitly replaces behavior. If implementation exposes a structural conflict, document the conflict and proposed resolution before the affected edit. Do not use historical “all packages landed” statements as proof of completion.

Read in order: global rules, any current repo AGENTS.md, ARCHITECTURE.md if present, accepted ADRs, this document, then relevant source. No repo AGENTS.md or ARCHITECTURE.md was found during drafting; recheck rather than creating either just to satisfy a checklist.

### 1.1 Completion levels

- **Implemented:** phased changes and automated acceptance tests pass; not sufficient to claim production readiness.
- **Pilot-ready:** packaged desktop and CLI exercise the entire copy workflow in disposable storage with verified receipts and injected failures.
- **Production-validated for a configuration:** real storage matrix in §12 has evidence for the named platform, filesystem, and mount protocol. Unsupported/unrun configurations remain explicitly unverified.
- **Review-ready:** execution report, commits/diff, test evidence, unresolved items, and this spec's acceptance ledger are ready for the requesting user to return to the reviewing agent.

The implementing agent must not self-certify unperformed operator gates. Finish all independent implementation and local validation even if external hardware is unavailable.

### 1.2 Non-goals

No automatic mounting, network credentials storage, network host discovery, cloud adapters, automatic start on mount, AI classification, semantic content indexing, automatic duplicate deletion, filesystem-level deduplication, new proxy/NLE features, or broad UI redesign. Discover already-mounted storage. macOS is the first packaged production target; retain existing Python portability and report other platform coverage honestly.

The new workflow is **copy-only** for this increment. Existing legacy interfaces are preserved, but unsafe desktop Organize move/link actions must be explicitly disabled with an explanation until they meet an independently specified safety contract. Do not silently change a requested move into copy. This is a deliberate visible restriction, not removal of legacy commands.

## 2. Verified baseline and implementation map

The drafting assessment was read-only. Full Python suite: 644 passed, 1 failed (`tests/test_migration_vnext.py::test_downgrade_drops_vnext`, SQLite backup “unable to open database file”); isolated rerun passed. Focused organization/offload suite: 50 passed. Desktop Vitest: 254 passed. These are baseline observations, not current implementation evidence.

Confirmed with disposable fixtures:

1. Organize reports no collision for an existing destination and overwrites it.
2. Source inspection reports 5,001 files but returns only 5,000; desktop Organize passes that truncated list to execution.
3. A template root of `../outside` produces a path outside the selected destination.

Confirmed in code:

- `application/organize.py` only prefixes the original relative path and uses direct `shutil.copy2`; move immediately unlinks without checksum comparison.
- `application/service.py::organize_apply` bypasses durable jobs, replica registration, and receipt writing.
- `application/plan.py::detect_collisions` checks planned entries, not existing destination files. `offload.py` publishes via `os.replace`, allowing replacement.
- Desktop Organize rescans at apply time; profile changes do not invalidate the displayed preview.
- Profiles overwrite stored template content while incrementing version; historical revisions are not retained.
- Existing volume observations are path-based; `st_dev` and mount paths are insufficient durable destination identity.
- Source scanning silently skips some read/stat failures. A successful result cannot establish that every source entry was accounted for.

| Area | Existing files to inspect/use |
| --- | --- |
| Source enumeration | `src/file_ferry/application/sources.py`, `drives.py`, `paths.py` |
| Plan and execution | `application/plan.py`, `organize.py`, `offload.py`, `scheduler.py`, `dispatcher.py` |
| Persistence | `persistence/migrations/`, `persistence/repositories/`, `application/profiles.py`, `assets.py`, `replicas.py` |
| Protocol and assembly | `service/protocol.py`, `service/wiring.py`, `application/service.py`, `desktop/shared/`, `desktop/electron/preload.ts` |
| Storage observations | `application/volumes.py`, `drives.py`, desktop mount observation wiring in `electron/main.ts` |
| Desktop | `renderer/src/screens/Organize.tsx`, `Ingest.tsx`, `Settings.tsx`, `Activity.tsx`, `Projects.tsx`; corresponding `lib/` modules |
| Other interfaces | `cli_vnext.py`, `cli.py`, `tui.py`, `service/client.py` |
| Evidence | `tests/`, `desktop/tests/`, `scripts/verify-packaged.sh`, `docs/RELEASE.md` |

Paths under application/persistence above are relative to `src/file_ferry/`; desktop renderer paths are relative to `desktop/`. Add narrowly scoped services/repositories where needed. Python owns classification, path decisions, identity matching, and mutations; the renderer presents typed results.

## 3. Phase 0 — repo cleanup and baseline (must precede features)

### Tasks

1. Record HEAD, branch, dirty files, tool versions, dependency manifests, current CI commands, tracked build artifacts, and applicable repo instructions. Preserve unrelated changes. Use a focused branch/worktree if necessary; do not reset, clean, delete app data, or remove user artifacts.
2. Build a short map of legacy CLI/TUI versus shared application paths. Identify actual callers before deleting anything. Do not mass-rename modules or move legacy capabilities; follow ADR-0005.
3. Reconcile stale documentation: desktop README still describes a placeholder shell; root README/history claim implementation completion; release docs refer to absent or stale instructions. Correct broken local links and distinguish current behavior, historical milestones, and upcoming work. Link this spec as planned work without claiming features landed.
4. Inventory duplicate organization, scanning, collision, and volume logic. Designate shared application services as the authority for the new workflow. Extract only behavior required by subsequent phases. Keep compatibility adapters small and tested.
5. Run baseline Python and desktop checks from §11. Diagnose failures, including the intermittent migration backup failure, before declaring a green baseline. Preserve failure logs; do not solve failures by removing assertions, loosening warnings, or adding arbitrary sleeps.
6. Remove only proven unused, tracked task-relevant code or obsolete references. Ignored caches/build outputs and untracked files are not cleanup targets. Dependency upgrades and blanket formatting are out of scope.
7. Create `docs/DESTINATION-PRESETS-EXECUTION-REPORT.md` containing phase status, evidence, decisions, and blockers. Do not embed source-drive inventories or private paths in committed evidence.

### Exit gate P0

- Reproducible baseline recorded, failures explained or fixed with regression coverage.
- Repo map and cleanup changes are small, reviewable, and preserve compatibility.
- No new product functionality is falsely advertised.

## 4. Domain and persistence contracts

Use existing SQLite migration/backup patterns. Never modify already-applied migration files. Add forward migrations and fixture coverage from both fresh and pre-change databases. Do not invent a parallel job or asset ledger.

### 4.1 Saved destination

Persist these logical fields (exact SQL naming may follow repository conventions):

- Stable internal ID; display name; created/updated timestamps; archived flag.
- Location kind: `local_folder`, `volume_folder`, or `mounted_share_folder`.
- Last observed root path for display/recovery, plus selected folder's relative path beneath its storage mount when applicable.
- Identity evidence: kind, normalized identifier, confidence, and platform provenance. Store no passwords, tokens, or credentials embedded in share URLs.
- Default preset ID and **pinned revision**, default conflict policy, checksum algorithm, free-space reserve.
- Last confirmed binding and last-seen time. Availability is an observation, not a persisted promise of writability.

Multiple saved folders on one volume are allowed. Display names are not identity. Archiving removes an item from the picker but retains references in plans/receipts. Editing destination configuration invalidates unexecuted approvals; historical plan snapshots remain unchanged.

General transfers must not require a fake video project. Make project association optional using existing nullable associations where possible. If current constraints require migration, explicitly migrate them; do not create an invisible “NAS project.”

### 4.2 Preset and immutable revisions

Reuse existing organization profile identities where feasible. Add immutable revision storage rather than retaining only the most recent template. A preset revision contains:

- Schema version, preset ID, monotonically increasing revision, name/description snapshot.
- Ordered rules with stable IDs, match conditions, destination template, and priority defined by list order.
- Ordered preserve-group rules (§6.3).
- Fallback template; conflict default; explicit exclusion rules; creation timestamp.

Saving edits creates a revision. Destinations remain pinned until the user chooses an update. Deleting/archiving a preset must not destroy historical revisions or queued plans. Copying a preset creates a new identity.

Legacy root-only profiles migrate to equivalent preserve-relative-path rules. Unknown/unsupported legacy template keys require review; never silently ignore them. Existing version numbers must be preserved without fabricating unavailable historical content. Mark pre-migration revision history as unavailable where necessary.

Provide portable JSON import/export of **presets only** with schema validation; no absolute destination paths or identities in exported presets. An imported preset creates a new local identity and never overwrites an existing preset implicitly.

### 4.3 Inventory, plan, and execution records

Persist full source inventories server-side. A UI page limit must never limit planning or execution. Inventory entries need source ID, relative path, type, size, observed mtime at available precision, scan status/error, and available file identity evidence. Keep exclusion counts/reasons. Directories needed for empty-folder preservation must be represented.

Plans are immutable durable records containing source inventory revisions, destination identity/binding snapshot, preset revision/content hash, mapping entries, conflict decisions, capacity estimate, exclusions/errors, and fingerprint. Plan entries contain original source, destination-relative path, matched rule/reason, size, action, and verification status reference.

Support paginated inventory and plan queries: default 200 rows, maximum 1,000 per response, stable ordering/cursor, server-provided totals. No full-inventory JSON response requirement for large transfers. Hash large files incrementally, never into memory at once.

Execution references a plan ID and approved fingerprint; it does not accept a caller-supplied list of arbitrary source/destination paths. Receipt and job item data must retain source-to-destination provenance even without a project.

## 5. Saved storage recognition and discovery

### 5.1 Matching contract

Return `available`, `offline`, `needs_confirmation`, `ambiguous`, or `unwritable`, with a human-readable reason and candidate locations.

- Local volumes: prefer a platform-provided stable filesystem/volume identifier. A label, `st_dev`, size, or previous mount path alone is weak evidence and must not authorize rebinding.
- Mounted shares: use sanitized server/share identity when available and selected subfolder; do not treat a reused `/Volumes/...` path as identity. Host aliases without established equivalence require confirmation.
- Local folders: preserve the explicit path binding; validate resolved location and underlying storage evidence before execution. A vanished folder must not be recreated on a different backing filesystem implicitly.
- Match relative folder path only within a matched volume/share. Multiple matching devices or duplicated identifiers are ambiguous.
- If a platform cannot provide trustworthy identity, allow explicit user confirmation of a currently selected path for the reviewed plan. Do not pretend weak matching is automatic recognition.
- Rebinding updates saved configuration only after user action and invalidates pending plan approval. Never write a marker file to a destination merely to discover it.

### 5.2 Observation behavior

Extend the current volume adapter/observer; avoid a second discovery loop. Refresh on startup, periodic observation, and manual refresh. Handle spaces and Unicode in mount paths correctly. An empty baseline must remain distinguishable from an uninitialized observer.

Discover local mounted volumes and mounted network shares, not remote servers. Discovery failures show a recoverable warning while manual folder selection remains usable. Do not block the UI with slow mount metadata calls; time-bound platform probes and retain last observation as explicitly stale.

Before each file publication, and after reconnect, validate destination binding. If a network share disappears but its mount directory remains on the local disk, stop; never continue into that local directory. Disconnection puts work in `needs_attention`, not success. Recognition never starts a job automatically.

## 6. Organization rule semantics

### 6.1 Deterministic routing

All regular files are eligible without FFmpeg. Process preserved groups first, then ordered ordinary rules. First matching rule wins. Conditions within a rule are AND; values within one condition are OR. Supported first-release conditions:

- Source-relative path glob with documented case sensitivity and `/` separators.
- Extension set, normalized case-insensitively including explicit extensionless matching.
- File category from an explicit versioned extension map: video, audio, image, document, archive, other. Describe this as extension classification, not content verification.
- Optional source label match for deliberate per-source routing.

No arbitrary expressions, executable plugins, regex supplied to a shell, or scripting in presets. Invalid fields/tokens reject the revision with field-specific errors.

### 6.2 Templates and dates

Supported tokens: `{source_label}`, `{relative_dir}`, `{filename}`, `{stem}`, `{ext}`, `{category}`, `{year}`, `{month}`. Define `{filename}` as the complete basename; `{ext}` includes the leading dot or is empty; `{relative_dir}` excludes the basename. Normalize source labels safely and show the resulting value in review.

For v1, `{year}` and `{month}` refer explicitly to **source modification time in UTC**, not capture date. The UI must label this. No implicit fallback to current time. Missing metadata routes to the configured fallback with a warning. Capture-date extraction is deferred rather than guessed from filesystem dates.

All rendered destinations must be relative beneath the selected destination root. Reject absolute paths, `..` components, NUL, unsupported names, path-length violations detectable on the target, and symlink escapes. Do not sanitize collisions away invisibly. Normalize Unicode for collision comparison while retaining actual filenames; treat unknown case sensitivity conservatively. Target filesystem rules belong in backend validation.

Default fallback: `Unsorted/{source_label}/{relative_dir}/{filename}`. User may edit it. Unknown files must be copied to fallback or explicitly excluded in the reviewed plan; never silently omitted. Default generic preset: preserve `Sources/{source_label}/{relative_dir}/{filename}`. Include one optional generic category preset; no personal NAS layout.

### 6.3 Folder groups and companion files

Users can mark selected source subtrees or glob-matched directories as “keep together.” A matched group routes as a unit, preserving all descendants and relative names. The outermost matching group wins; rule order resolves multiple rules matching the same root. Group rules specify a group destination template and preserve descendants beneath it.

Do not split camera-card structures, application packages, project folders, or sidecars by extension when inside a preserved group. For recognizable package directories, default to preserved groups and show the decision. Do not claim automatic detection of all project dependencies. UI must let a user mark additional folders before approval. Files outside groups use ordinary rules; companion grouping is explicit, not a guessed basename join.

Preserve empty directories unless explicitly excluded. Symlinks, sockets, devices, and unsupported filesystem objects must be inventoried and flagged. First release does not dereference or recreate them automatically: block approval until the user explicitly excludes them or selects a supported source subtree. Record exclusions in receipts.

### 6.4 Conflicts and repeated transfers

Default: keep both using deterministic suffix allocation, never overwrite. Supported decisions:

- `keep_both`: reserve a stable non-conflicting name during planning, including other sources and existing target contents.
- `skip_identical`: permitted only after full content checksum equality; size/name/mtime alone is insufficient. Record verified existing content and provenance.
- `needs_review`: block execution pending a per-item or scoped user decision.

No replace/delete option in the new workflow. Same-name/different-content, same-content/different-name, case-only, Unicode-normalization, file-versus-directory, and ancestor-path conflicts are distinct findings. Automatic identical skipping only compares intended target candidates; whole-NAS duplicate indexing is out of scope.

For a repeated transfer, consult prior completed mappings for the same source identity, content, destination, and preset revision before allocating keep-both names. Reuse that mapped output only after checksum validation and record it as verified existing content. A missing/changed output becomes a new conflict; no unrelated file is adopted by name alone. Without matching provenance, keep-both remains the default.

A new file appearing at a reserved path after approval invalidates that entry; do not replace it or silently select a new name. Replan and obtain review. Serialize/reserve destination paths across concurrent Ferry jobs, but also protect against external writers at publication.

## 7. Transfer safety and recovery contract

### 7.1 Planning and approval

- Scan all selected sources and intended destination paths. Scan/read/stat errors must appear explicitly and block approval unless excluded by the user.
- Destination-inside-source, source-equals-destination, resolved symlink aliases, and unsafe path overlaps are rejected. Detect nested duplicate sources and ask for a single non-overlapping selection.
- Capacity accounts for all sources, all planned writes, temporary-file overhead, and one configured reserve per physical destination storage pool. Unknown free space is shown and requires explicit override recorded in the plan. This is a planning estimate; execution still handles ENOSPC/quota failures.
- Hash plan substance deterministically: source snapshot, mapping/actions, destination binding, preset revision, policies, and exclusions. Editing any input clears approval.
- Preflight checks source and destination against approved evidence. Additions/removals/changed files require replan; do not rescan and substitute a different file list invisibly.

### 7.2 Execution

Reuse scheduler/dispatcher and extract shared transfer primitives from offload; do not maintain a weaker organization copier.

For each file: validate source/binding, write a unique job-owned temporary sibling in chunks, flush/fsync where supported, compare source and destination checksums, validate source stability, then publish without replacing existing content. Record final destination and verified outcome durably. Recheck binding before publication. Use a filesystem-appropriate exclusive/no-clobber publication strategy; `exists()` followed by `os.replace()` is insufficient. If a target cannot provide safe publication, fail explicitly rather than falling back to overwrite.

Protect against source edits during copy with pre/post metadata/file-identity checks and consistent checksum evidence; a detected change fails the item. File bytes are the verification guarantee. Preserve basic mtime where supported and report metadata preservation failures; do not claim ACL/xattr/resource-fork equivalence without implementing and testing it. Surface known metadata limitations during review for relevant file types/storage.

Cancellation is checked during copy and hashing, at least once per chunk, not only between large files. Cancellation leaves source untouched, verified completed files intact, and owned temporary files cleaned or documented for recovery. UI acknowledges cancellation promptly; a blocked filesystem call may delay completion and must not be represented as already cancelled.

### 7.3 Recovery and receipts

On restart, unfinished jobs become `needs_attention`. Resume must revalidate original plan/source/destination identity. Reuse a completed output only after verifying it matches recorded evidence. Resume remaining files; do not recopy all verified files. Byte-offset resume inside a partially copied file is not required: discard only that job's partial and restart that file.

Recovery reconciles crash windows: temporary written but unpublished; published but item not committed; item committed but receipt not exported. Persist sufficient item evidence to recover without guessing or overwriting. Never delete unrelated `.part` files.

Receipt contains plan ID/fingerprint, destination binding snapshot, preset revision, original source paths, actual destination paths, actions, expected/actual counts and bytes, checksums/algorithm, exclusions, warnings, errors, timestamps, interruption/retry lineage, and final state. Durable database receipt is required; export failures are visible and retriable. If receipt persistence fails, show `needs_attention`/incomplete audit status; do not claim fully completed audited transfer.

No green success if files failed, scans were incomplete, or required verification/receipt is missing. Explicitly excluded entries are counted separately from successful copies. Existing card safe-to-format policy must not be weakened by general transfer presets; one NAS copy does not satisfy a two-independent-replica policy.

## 8. API, CLI, and desktop contract

Use typed Python protocol models and matching TypeScript contracts with contract tests. Add capability discovery for new methods. Exact implementation symbols can follow current conventions, but expose these operations:

| Operation | Required behavior |
| --- | --- |
| destination list/save/archive/resolve/confirmBinding | Saved data separated from live availability; explicit revision/binding handling |
| profile list/getRevision/saveRevision/import/export | Immutable validated presets; retain compatibility with existing profile reads |
| inventory create/status/entries | Async full scan; paginated results and explicit error counts |
| transfer planCreate/planGet/planEntries | Durable, asynchronous if expensive; structured conflict/rule explanations |
| transfer planResolve/approve | Produce a new plan revision after decisions; approve exact fingerprint |
| transfer start | Takes approved plan ID/fingerprint; returns existing durable job promptly |
| existing job status/cancel/resume/receipt | Shared implementation for desktop and CLI |

Do not change old RPC response shapes silently. Introduce new methods/version capabilities as needed. Unsafe old organize apply calls must return an actionable unsupported/safety error or safely adapt into approved durable execution; never retain an unguarded write bypass. Existing legacy capability commands keep documented semantics, with shared safety fixes where applicable and regression coverage.

### Desktop flow

1. Source picker supports multiple folders/drives and displays inventory progress/totals/errors.
2. Destination picker shows saved locations with availability and discovered unsaved storage. Manual folder selection remains available. “Save destination” captures name, subfolder, and preset.
3. Preset editor supports ordered rules, extension/category/path conditions, keep-together groups, fallback, and conflict default. Provide a sample preview; users need not author JSON.
4. Selecting a destination loads its pinned preset. A per-transfer override does not silently change the saved default. Explicit actions save/update defaults.
5. Review displays source and target trees/table, total files/bytes, copy/identical/excluded/review counts, capacity, matched rules, conflicts, metadata limitations, and destination identity status. Paginate/virtualize the entire plan; first-page rendering is not the total inventory.
6. Changing source, destination, binding, preset, rules, or conflict choices invalidates approval. Start remains disabled until the exact new plan is reviewed.
7. Transfer navigates to Activity with byte/file progress, hashing/copying stages, cancellation, recoverable errors, and receipt access. Closing/reopening a view cannot lose the job.
8. Saved destinations/presets remain editable through existing navigation patterns; no unrelated reskin.

CLI exposes equivalent destination/preset management, scan/plan export, explicit plan approval/start, status/cancel/resume/receipt operations with JSON output. Provide actual commands in final docs. TUI must retain existing functionality and must not expose unsafe new shortcuts; full new preset editing in TUI is deferred, with an honest pointer to CLI/desktop.

## 9. Implementation phases and dependencies

Complete and validate each phase before proceeding. Record checkboxes/evidence in the execution report, not by changing this spec's requirements to match a partial implementation.

| Phase | Deliverables and likely change surface | Exit gate |
| --- | --- | --- |
| P0 | Cleanup/baseline in §3 | Small reviewed baseline and accurate docs |
| P1 | Regression fixtures for known blockers; guard unsafe organize paths; fix destination/path safety in shared code | Overwrite, truncation, traversal, and false verification reproductions fail safely |
| P2 | Migrations, immutable preset revisions, saved destinations, inventory/plan persistence; repositories/services/protocol | Fresh/upgrade/backward-compatibility tests; complete paginated inventories |
| P3 | Volume identity adapters, discovery, availability and rebinding services | Renamed mounts, same-name wrong drives, ambiguous shares and disconnected mount directories handled |
| P4 | Rule engine, group preservation, conflict planner, capacity and approval fingerprint | Deterministic mixed-source mapping and full conflict matrix |
| P5 | Shared durable verified copy runner, cancellation, resume, receipt recovery | Failure injection proves no overwrite/source deletion, no false success, correct recovery |
| P6 | Desktop destination/preset editor and full review/transfer flow; CLI parity | Actual end-to-end service integration, responsive large plans, stale previews blocked |
| P7 | Packaging, mixed-file pilot, real storage/soak matrix, operational docs | §12 evidence and explicit production support boundary |
| P8 | Final consistency review and handoff | §13 complete; no unacknowledged requirements dropped |

P1 may disable unsafe functionality temporarily while P2–P5 build its replacement. Do not defer known data-loss prevention until the UI phase. Apply shared safeguards to offload as well as organized transfers without changing source-preserving card semantics.

## 10. Required automated acceptance matrix

Use isolated temporary files/databases and fake platform adapters. Real NAS data must never be unit-test input. Test behavior and failure boundaries, not snapshots that merely mirror implementation.

| ID | Fixture/trigger | Required result |
| --- | --- | --- |
| A01 | 5,001 and 10,001 mixed files; paginated UI | All eligible entries planned/executed; no silent cap |
| A02 | Existing same-name different-content file | No replacement; deterministic keep-both or review |
| A03 | Existing identical file | Full checksum proof; explicit skipped-identical receipt |
| A04 | Two source drives with same labels/relative names | Unique source identities; deterministic conflict resolution |
| A05 | Case/Unicode aliases, file/dir ancestor conflict | Detected before writes; conservative unknown filesystem handling |
| A06 | Absolute/traversal template, symlink root escape | Reject outside-root destinations; no writes |
| A07 | Missing/unreadable entry, broken symlink, unsupported object | Visible inventory finding; no false complete scan |
| A08 | Change preset/source/binding after preview | Stale approval rejected server-side and UI-side |
| A09 | Destination file created externally after approval | Exclusive publication refuses overwrite |
| A10 | Large file cancelled while copying/hashing | Bounded checks, source intact, accurate partial receipt |
| A11 | ENOSPC, permission loss, write/fsync/hash failure | Failed/attention item, source intact, no published corrupt success |
| A12 | Share unmounted, mount folder still exists | Stop before writing to backing local filesystem |
| A13 | Same volume remounted at new path | Strong identity plus relative subfolder resolves correctly |
| A14 | Different drive reuses label/path; duplicate identity | No automatic execution; confirmation/ambiguity state |
| A15 | Process termination at publication/DB/receipt boundaries | Resume reconstructs truthful state without duplicate overwrite |
| A16 | Source modified during copy, source changed before resume | Reject changed evidence; require replan |
| A17 | Preserved group with video, XML, audio, project files | Entire group retains internal structure |
| A18 | Unknown extension, extensionless file, empty directory | Fallback/preservation included; explicit counts |
| A19 | Missing FFmpeg | General scan/plan/copy succeeds; proxy capability remains separately unavailable |
| A20 | Preset edit/export/import and old DB upgrade | Immutable old plan remains reproducible; no private paths exported |
| A21 | Two jobs target overlapping paths/storage | Reservation/capacity coordination; no duplicate publication |
| A22 | Receipt persistence/export failure | Visible audit failure and retriable recovery, not clean completion |
| A23 | Repeated completed transfer and partial resume | Verified reuse; no blind recopy or incremental-name explosion |
| A24 | Optional project association and card policy regression | General transfer works independently; card safety rules retained |
| A25 | Discovery with spaces/Unicode, empty mount baseline, slow probe | Correct diffs, timeout warning, manual selection usable |
| A26 | Weak identity and unknown capacity | Explicit recorded confirmation/override; no inferred approval |

Add targeted end-to-end tests through real service wiring for scan → save destination → save preset → plan → approve → execute → receipt. Desktop pure-helper tests alone are insufficient. Validate renderer/backend contract field names and capability negotiation.

## 11. Commands and evidence discipline

Recheck manifests/CI for exact commands. Current baseline commands:

```sh
.venv/bin/python -m pytest
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy src
```

From `desktop/`:

```sh
npm run typecheck
npm run lint
npm test
npm run build
```

Run repo-defined secret scan and packaging verification as applicable after reading the scripts. Do not run destructive clean-app-data scripts against the user's real profile. Use a separate test application-data location. Do not commit generated release stamps/artifacts accidentally.

Small targeted tests precede full matrix. Record command, commit, environment, result, and artifact location. A flaky failure is not green because an isolated rerun passes: investigate and report it. No lint/test bypasses. New dependencies require concrete justification and license/runtime consideration; prefer standard library and existing dependencies.

## 12. Pilot and production validation

### 12.1 Disposable local pilot

Use independent source and destination directories, isolated application data, and mixed files (not only tiny text renamed `.mov`). Include known hashes, actual representative media/documents/archives where licensed/available, nested bundles, large files, empty folders, and overlapping filenames. Verify final output independently from Ferry's own status using a separate checksum walk. Account for every original as copied, verified-identical, explicitly excluded, or failed.

Exercise packaged app start/restart and CLI against the same service contracts. Prove no FFmpeg requirement for general transfer. Verify actual packaged release provenance and sidecar, not merely a source checkout.

### 12.2 Real storage matrix

Required for the initial macOS production claim:

- External local drive → a separate local destination volume.
- External local drive → an already-mounted network share.
- At least one populated destination with overlaps and two sequential source drives.
- At least 10,001 entries and one file of at least 10 GiB across the campaign; record actual counts/bytes.
- A prolonged transfer of at least two hours, or a full representative drive offload if longer; record sustained throughput, memory behavior, DB/job state, and receipt integrity. Do not manufacture confidence from repeated tiny-file tests.
- Controlled cancellation, application/sidecar restart, and network disconnection/reconnection using disposable targets. Get authorization for actual device/network disruption; simulated adapters do not satisfy the real interruption gate.

Record OS, Ferry commit/package provenance, source/destination filesystem, network mount protocol, counts/bytes, duration, peak memory, observed issues, and independent hash comparison. Keep private addresses and filenames out of committed artifacts.

No hard throughput number is specified without hardware evidence. Planning/UI should stay responsive: job creation returns without waiting for copy; large plan pages are bounded; cancel request is acknowledged within two seconds under normal local conditions. Report measurements and explain OS-blocked I/O exceptions. Measure 100,000-entry synthetic planning separately to expose memory/IPC growth; do not send the whole plan to the renderer.

If storage/hardware or operator permission is unavailable, mark the exact gate `NOT RUN`, provide a reproducible procedure, and finish all other work. Do not mark P7 production-validated. Signing/notarization follows existing release policy; an unsigned local pilot is not a public stable release.

### 12.3 Operational documentation

Update root/desktop READMEs, release instructions, and CLI/TUI parity docs for final behavior. Include preset examples, supported tokens and date semantics, destination recognition limits, recovery steps, metadata limitations, exclusion behavior, conflict policies, and how to inspect/export receipts. Distinguish copies verified from storage redundancy and backup guarantees.

## 13. Final handoff and review protocol

The implementation agent must provide:

1. Completed execution report with P0–P8 and A01–A26 statuses (`PASS`, `FAIL`, `NOT RUN`, or `BLOCKED`), each linked to tests/evidence.
2. Summary of files changed and architecture decisions, migration/backward-compatibility behavior, and any explicit deviations needing review.
3. Exact validation commands/results, including all failed or flaky runs relevant to readiness.
4. Reproduction steps for a fresh user: save destination, create/import preset, inspect sources, review plan, execute copy, inspect receipt, reconnect/resume.
5. Packaged artifact location/provenance if built; declared support boundary and unperformed real-storage gates.
6. Remaining risks and a clear statement of implemented/pilot-ready/production-validated status.

Do not publish, merge, upload user data, or perform the user's actual migration merely because implementation is complete. The deliverable is an implemented and evidenced candidate for the user's requested review.

### 13.1 Reviewer revision appendix

Reserved for the subsequent reviewing agent. Do not mark anticipated findings as addressed before review. Append findings without erasing original requirements or evidence.

Use this format for each revision:

- **Revision ID:** R01, R02, ...
- **Severity / affected acceptance ID:**
- **Observed behavior and evidence:**
- **Required change:**
- **Regression/validation requirement:**
- **Implementer response / commit:**
- **Reviewer disposition:** pending / accepted / needs further work

No reviewer revisions have been appended yet.
