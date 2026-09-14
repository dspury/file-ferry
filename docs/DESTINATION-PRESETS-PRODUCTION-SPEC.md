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

**Review evidence blocks approval.** A revision whose `reviewRequired` is non-empty holds something the conversion could not resolve safely. A plan built against it records that evidence on the plan itself, so the refusal can name the items, and **approval is refused** — surfacing it as a warning and approving anyway is precisely the silent ignore this section forbids. The only way through is a corrected revision that resolves the item, pinned in place of the old one; nothing clears it on the user's behalf.

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

- Source-relative path glob. The dialect is fixed and documented, because a preset author must be able to predict which files a pattern claims: separators are always `/` (a backslash reads as one, leading and trailing separators are ignored); matching is **case-insensitive**, since sources are frequently exFAT/FAT/HFS+ and a pattern that stopped matching on `DCIM` versus `dcim` would be a silent routing bug; `*` **spans separators**, so `DCIM/*` claims `DCIM/100MEDIA/A001.MOV` and `*.mov` claims a `.mov` at any depth; there is no distinct `**`; `?` matches one character and `[seq]` one character from a set; nothing else is special — no regex, no braces, no negation. A *group* glob is matched against directory paths rather than file paths, so it claims a subtree by its shallowest matching directory.
- Extension set, normalized case-insensitively including explicit extensionless matching.
- File category from an explicit versioned extension map: video, audio, image, document, archive, other. Describe this as extension classification, not content verification.
- Optional source label match for deliberate per-source routing.

Preset **exclusion rules are evaluated before routing**, using the same conditions, and they apply everywhere — including inside a preserved group, because a rule the user wrote about every `.tmp` was written about every `.tmp`. An excluded entry is recorded as an entry with the rule that claimed it and that rule's stated reason, never as an absence; when the exclusion takes a member out of a preserved group, review says so. Excluding a directory excludes its descendants, which inherit the same rule. An exclusion rule requires at least one condition and a non-empty reason: a condition-free rule would empty the transfer, and the reason is the whole account a receipt gives for every file left behind. Exclusions applied by a preset rule are counted separately from exclusions a reviewer decided (§7.3); both are explicit, and they are not the same fact.

No arbitrary expressions, executable plugins, regex supplied to a shell, or scripting in presets. Invalid fields/tokens reject the revision with field-specific errors.

### 6.2 Templates and dates

Supported tokens: `{source_label}`, `{relative_dir}`, `{filename}`, `{stem}`, `{ext}`, `{category}`, `{year}`, `{month}`. Define `{filename}` as the complete basename; `{ext}` includes the leading dot or is empty; `{relative_dir}` excludes the basename. Normalize source labels safely and show the resulting value in review.

For v1, `{year}` and `{month}` refer explicitly to **source modification time in UTC**, not capture date. The UI must label this. No implicit fallback to current time. Missing metadata routes to the configured fallback with a warning. Capture-date extraction is deferred rather than guessed from filesystem dates.

All rendered destinations must be relative beneath the selected destination root. Reject absolute paths, `..` components, NUL, unsupported names, path-length violations detectable on the target, and symlink escapes. Do not sanitize collisions away invisibly. Normalize Unicode for collision comparison while retaining actual filenames; treat unknown case sensitivity conservatively. Target filesystem rules belong in backend validation.

Default fallback: `Unsorted/{source_label}/{relative_dir}/{filename}`. User may edit it. Unknown files must be copied to fallback or explicitly excluded in the reviewed plan; never silently omitted. Default generic preset: preserve `Sources/{source_label}/{relative_dir}/{filename}`. Include one optional generic category preset; no personal NAS layout. The category preset preserves source-relative structure inside each category (`Video/{source_label}/{relative_dir}/{filename}` and the same shape for audio, images, documents, archives) and contains **no date routing**: `{year}` is source modification time, which is usually not a capture date, so it is an opt-in a user makes knowingly rather than a default they inherit.

**Empty directories.** A source directory holding entries this plan copies gets no plan entry of its own — writing its contents creates it. Emitting one anyway produces an empty fallback duplicate of every source parent, which is wrong in the ordinary case and actively misleading under a category preset, where the parent's contents routed elsewhere entirely. A *genuinely* empty source directory is different: nothing else will create it, so it keeps its entry and is preserved (§6.3). A directory is considered implied only by a descendant this plan will actually write — a copy, or a retained empty directory; a folder whose every child was excluded or blocked keeps its own entry.

### 6.3 Folder groups and companion files

Users can mark selected source subtrees or glob-matched directories as “keep together.” A matched group routes as a unit, preserving all descendants and relative names. The outermost matching group wins; rule order resolves multiple rules matching the same root. Group rules specify a group destination template and preserve descendants beneath it.

**Group destinations are evaluated once, for the group's root directory**, and every descendant's source-relative path is appended to the result unchanged. `{filename}` is the group root's complete basename and `{relative_dir}` its parent path; `{source_label}` is available. `{ext}`, `{stem}`, `{category}`, `{year}` and `{month}` are **rejected at save time** for a group destination with a field-specific error: they are meaningless for a directory, and a date token would make a preserved subtree's location depend on metadata one directory may not have — relocating or splitting the very thing the group protects. The group's own root directory is a member of its group and routes with it, not through the fallback.

**A group's collision is resolved at its root, never member by member.** If anything already occupies a group's destination root, the whole group moves to a deterministically suffixed root with every internal relative path unchanged, and the move is recorded on the group root entry; under a non-`keep_both` policy the whole group blocks instead. Merging into an existing tree is not attempted — proving a merge safe needs per-file evidence and reviewed decisions. Suffixing an individual member is never done automatically: the internal names are precisely what the group was marked to protect. Plan entries carry their group id so review can show the containment.

Do not split camera-card structures, application packages, project folders, or sidecars by extension when inside a preserved group. For recognizable package directories, default to preserved groups and show the decision. Do not claim automatic detection of all project dependencies. UI must let a user mark additional folders before approval. Files outside groups use ordinary rules; companion grouping is explicit, not a guessed basename join.

Preserve empty directories unless explicitly excluded. Symlinks, sockets, devices, and unsupported filesystem objects must be inventoried and flagged. First release does not dereference or recreate them automatically: block approval until the user explicitly excludes them or selects a supported source subtree. Record exclusions in receipts.

### 6.4 Conflicts and repeated transfers

Default: keep both using deterministic suffix allocation, never overwrite. Supported decisions:

- `keep_both`: reserve a stable non-conflicting name during planning, including other sources and existing target contents. The suffix form is `name (n).ext`, counting from 2 because the original is conceptually copy 1, allocated deterministically so the same plan yields the same names on every rebuild. The form is fixed here rather than left to the examples so receipts and re-runs are reproducible.
- `skip_identical`: permitted only after full content checksum equality; size/name/mtime alone is insufficient. Record verified existing content and provenance.
- `needs_review`: block execution pending a per-item or scoped user decision.

No replace/delete option in the new workflow. Same-name/different-content, same-content/different-name, case-only, Unicode-normalization, file-versus-directory, and ancestor-path conflicts are distinct findings. Automatic identical skipping only compares intended target candidates; whole-NAS duplicate indexing is out of scope.

For a repeated transfer, consult prior completed mappings for the same source identity, content, destination, and preset revision before allocating keep-both names. Reuse that mapped output only after checksum validation and record it as verified existing content. A missing/changed output becomes a new conflict; no unrelated file is adopted by name alone. Without matching provenance, keep-both remains the default.

A new file appearing at a reserved path after approval invalidates that entry; do not replace it or silently select a new name. Replan and obtain review. Serialize/reserve destination paths across concurrent Ferry jobs, but also protect against external writers at publication.

## 7. Transfer safety and recovery contract

### 7.1 Planning and approval

- Scan all selected sources and intended destination paths. Scan/read/stat errors must appear explicitly and block approval unless excluded by the user.
- Destination-inside-source, source-equals-destination, resolved symlink aliases, and unsafe path overlaps are rejected. Detect nested duplicate sources and ask for a single non-overlapping selection.
- **Ferry never writes through a symbolic link at the destination**, whatever it points to. A symlink at *any* component of a planned destination path — the leaf or any parent directory — is a blocking finding at planning time and a preflight failure if it appears afterwards. `is_dir()` follows links and so reports a symlinked parent as an ordinary directory; the test must be `lstat`-based, and it must cover every component, because the planner emits no directory entry for a parent its own routed children imply.
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
| transfer planResolve/approve | Produce a new plan revision after decisions, and invalidate the plan it came from in the same operation — a reviewer's own decision must not leave a superseded plan standing approved beside its successor; approve exact fingerprint |
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

### Progress review — 2026-09-10 (P2 stalled)

Reviewed committed P0/P1 through `9d0d460` plus the uncommitted P2 working tree. Verdict: **NEEDS CHANGES**. P0 has useful cleanup, P1 materially improves copy safety, P2 is incomplete, and P3 completion is not evidenced. This review does not require P4–P8 to be implemented early; it requires the exposed P2 contracts to fail safely and the handoff to describe actual progress.

Validation executed: full Python suite **695 passed, 1 failed** (`test_inventory_service.py::test_scan_errors_recorded`); mypy passed (74 source files); Ruff lint failed (3 findings); Ruff format check failed (4 files); desktop typecheck passed; desktop Vitest **254 passed**. No packaged, desktop UI, or NAS smoke was performed. Disposable service-level reproductions below used isolated databases and temporary folders. No implementation fixes were made during review.

#### R01 — Correct the execution report before handoff

- **Severity / affected acceptance ID:** Major; P0–P3 evidence integrity.
- **Observed behavior and evidence:** `docs/DESTINATION-PRESETS-EXECUTION-REPORT.md` marks P2/P3 PASS and cites `test_migration_destinations.py`, `test_transfer_plan.py`, `test_destination_resolver.py`, and `test_destination_end_to_end.py`, which do not exist in the reviewed tree. It describes platform identity adapters and CLI commands that are not implemented. P2 files are largely untracked/uncommitted. Current checks are not green.
- **Required change:** Replace prospective claims with observed status. Mark P2 incomplete, P3 not completed, missing tests NOT RUN, and distinguish helper resolver code from actual platform discovery. Record current validation failures and exact committed/uncommitted boundary. Retain earlier claims only as explicitly corrected history.
- **Regression/validation requirement:** Every PASS must reference an existing test/evidence artifact and a recorded result. Run the actual checks after repairs; do not infer their outcomes.
- **Implementer response / commit:** Addressed in the working tree. `docs/DESTINATION-PRESETS-EXECUTION-REPORT.md` rewritten: a correction notice names the four wrongly-cited test files, the fictional platform adapters, and the fictional CLI commands rather than quietly dropping them; P3 is marked NOT RUN with an explanation of what does and does not exist; the committed/uncommitted boundary is spelled out file by file; validation figures come from commands actually run (753 Python tests, 258 desktop tests, ruff/format/mypy clean, desktop typecheck/lint/build). A12/A13/A14/A25 moved from PASS to NOT RUN. Every remaining PASS names an existing file. Earlier P0 figures are retained explicitly as history.
- **Reviewer disposition:** implementer addressed; reviewer verification pending

#### R02 — Never deduplicate source entries by relative pathname

- **Severity / affected acceptance ID:** Critical before execution is connected; A01, A04, A07, A18.
- **Observed behavior and evidence:** `application/transfer_plan.py::_build_plan` uses a single `seen_paths` set across inventories. Two different source roots containing `same.txt` produced one plan entry and one automatic exclusion. Non-file/error findings are also silently counted as exclusions without a user decision.
- **Required change:** Preserve source identity plus relative path for every inventory entry. Same destination paths are conflicts, not duplicate source identities. Keep unsupported/error findings in the plan as blocking review items until explicitly excluded. Persist original inventory references and exclusion decisions. Reject duplicate/nested source selections explicitly.
- **Regression/validation requirement:** Two inventories with same relative names and different content must both remain accounted for, with a conflict or distinct reviewed target paths. Unsupported entries must never acquire an implicit approved exclusion.
- **Implementer response / commit:** Addressed in the working tree. `application/transfer_plan.py` rewritten. Source identity is now `(inventory_id, inventory_entry_id)`; `transfer_plan_entries` carries both plus `rel_path`, `entry_type`, `mtime`, `exclusion_reason`, and `excluded_by_user`, and its uniqueness key is `(plan_id, inventory_id, source_path)`. `_mark_destination_collisions` keeps every entry and marks a shared destination path `needs_review`/`duplicate_destination_path` on all participants. Scan errors become `source_scan_error`, non-file objects become `unsupported_source_object:<type>`, unsafe renders become `unsafe_destination_path` — all blocking, none counted as exclusions; `excluded_by_user` is 0 everywhere because no exclusion workflow exists yet (that is P4). Duplicate, nested, and destination-overlapping source selections are rejected by `_reject_overlapping_sources`. Plans store an inventory snapshot (manifest hash + counts) per source.
- **Reviewer disposition:** implementer addressed; reviewer verification pending

#### R03 — Remove size-only identical classification

- **Severity / affected acceptance ID:** Critical before execution is connected; A03.
- **Observed behavior and evidence:** `_build_plan` sets `skip_identical` when target size equals source size. Source `AAA` and destination `ZZZ` produced `skip_identical` without a checksum or conflict.
- **Required change:** Until full hashing is available, classify these as unresolved existing-file conflicts. Only use `skip_identical` after full content equality evidence is stored; do not let a provisional planner emit an executable false identity claim.
- **Regression/validation requirement:** Equal-size unequal-content fixtures remain unresolved; equal-content skipping requires recorded checksum evidence. Include existing symlink targets as distinct conflicts.
- **Implementer response / commit:** Addressed in the working tree. The size comparison is gone; `_classify_existing_target` never returns `skip_identical`. Existing destination objects are distinguished as `existing_destination_file`, `existing_destination_symlink` (checked before `exists()`, so a broken symlink is still caught), `existing_directory`, `existing_special`, and `existing_destination_unreadable`, each `needs_review`. A test asserts no plan in this increment emits `skip_identical` at all, including for byte-identical content — identity needs the checksum evidence P5 will record.
- **Reviewer disposition:** implementer addressed; reviewer verification pending

#### R04 — Enforce approval validity and snapshot completeness

- **Severity / affected acceptance ID:** Major; A08, A26, P2 immutable-plan contract.
- **Observed behavior and evidence:** `TransferPlanService.approve` approved a plan with one unresolved conflict. `DestinationService.save` changed the destination path while the original plan remained approved. Fingerprints omit inventory manifest/revision, file sizes/mtimes, storage identity, policy and exclusions; tables do not retain complete inventory/identity snapshots. Capacity uses total bytes but ignores the destination's reserve: a 3-byte plan with a 10^18-byte reserve reported capacity OK. `create` accepts an arbitrary binding path without confirmation validation.
- **Required change:** Reject approval for blocking conflicts, unresolved scan findings, unavailable/unconfirmed destinations, or inadequate capacity; only allow documented explicit unknown-capacity override. Invalidate plans atomically with destination edits/rebinding/archive. Persist and hash the complete approved substance from §4.3/§7.1. Enforce saved/confirmed binding and archive status. Account for reserve and planned write actions. If approval cannot meet the contract yet, leave it unavailable instead of reporting approved.
- **Regression/validation requirement:** Real-service tests for destination edits, source snapshot changes, unresolved conflicts, reserve shortfall, unknown capacity, archived destinations and unconfirmed binding overrides. Verify invalidation happens in the same transaction as configuration changes.
- **Implementer response / commit:** Addressed in the working tree. `TransferPlanService._assert_approvable` refuses: any blocking entry; a destination that is missing, archived, rebound, or whose identity evidence or reserve changed; a preset revision whose content hash moved or that no longer exists; an inventory that is no longer `complete` or whose manifest hash changed; insufficient capacity; and unknown capacity without a recorded override reason. Capacity is `planned bytes + largest-file temporary overhead + the destination's free_space_reserve`, with observed free bytes stored on the plan. `transfer_plans` gained `inventory_snapshot_json`, `destination_identity_json`, `conflict_policy`, `checksum_algo`, `free_space_reserve`, `free_bytes`, and `blocking_count`; the fingerprint hashes all of it plus per-entry size and mtime. Invalidation on save/confirmBinding/archive now runs in the same transaction as the configuration change, and clears `approved_fingerprint`. `create` accepts only the destination's confirmed binding path and refuses archived destinations.
- **Reviewer disposition:** implementer addressed; reviewer verification pending

#### R05 — Persist and honor pinned preset revisions

- **Severity / affected acceptance ID:** Major; A20, §4.1–4.2.
- **Observed behavior and evidence:** `DestinationService.save` always initializes `pinned_revision=None`; `_load_preset_revision` selects latest when no override is supplied. Saving a destination against revision 1 and then creating revision 2 caused its next plan to select revision 2 automatically.
- **Required change:** Save an explicitly selected or resolved current revision at destination creation/update, validate the preset/revision pair, expose it in the save contract, and default plans to that pinned revision. Changing the pin must be explicit and invalidate unexecuted approvals.
- **Regression/validation requirement:** Revision 2 creation must leave existing destination plans on revision 1. Explicit pin updates select revision 2; nonexistent or mismatched revision pairs fail validation.
- **Implementer response / commit:** Addressed in the working tree. `SaveDestinationParams` gained `pinnedRevision`. `DestinationService._resolve_pin` validates an explicit pin against the named preset, keeps an existing pin for the same preset across unrelated edits, and otherwise pins that preset's current revision — so a pin is always a concrete revision. `_load_preset_revision` uses the pin, never `latest_revision`; an explicit `presetRevision` is a per-transfer override and a preset that is not the destination's default requires one. Moving the pin is an explicit save and invalidates unexecuted approvals through the shared same-transaction path.
- **Reviewer disposition:** implementer addressed; reviewer verification pending

#### R06 — Complete inventory representation and error persistence

- **Severity / affected acceptance ID:** Major; A07, A18, P2 inventory persistence.
- **Observed behavior and evidence:** Shared `_walk` does not yield ordinary directories or directory symlinks, so two fixture inventories with empty directories each reported `dir_count=0`. Inventory worker stores `entry_type='error'`, which migration 004's CHECK constraint disallows. The full suite's unreadable-directory test failed with a failed inventory and zero file count. Exception handling resets counts and discards the diagnostic detail; `_record_failure` does not persist its `detail` argument.
- **Required change:** Define compatible entry type/status representation for read failures; retain the relevant source-relative path and error text. Enumerate directory and directory-symlink findings. Preserve partial counts/entries truthfully on failure. Add lifecycle shutdown/restart handling so abandoned scans cannot stay `scanning` indefinitely. Do not weaken the unreadable-path test to accept unexplained inventory loss; its expectation of two readable files also needs correction for a genuinely inaccessible subtree.
- **Regression/validation requirement:** Deterministic injected stat/walk failures plus real permission fixture where supported, empty directories, directory symlinks, partial scan persistence, and restart recovery. Verify stored diagnostic text and count consistency across pages.
- **Implementer response / commit:** Addressed in the working tree. `sources.py::_walk` yields ordinary directories (empty ones included) and directory symlinks, which `os.walk` lists but never descends. Read failures are represented as `scan_status='error'` with the diagnostic in `error` and `entry_type='unknown'` — compatible with migration 004's CHECK constraint, which the previous `entry_type='error'` violated — and keep the source-relative path they occurred at, including for `onerror` descent failures. `ScanItem` gained `scan_status`; `DetailedScan` gained `dirs`. A failed scan keeps the counts and entries it genuinely reached and persists why it stopped (`source_inventories.error`, surfaced on `InventoryStatus`), rather than resetting to zeros. Inventories carry `owner_pid`/`heartbeat_at`, and `recover_abandoned_scans` — called from `ApplicationService.bootstrap` — fails scans orphaned by a process exit while preserving their partial entries. The unreadable-path test was corrected, not weakened: it now expects one readable file plus an explicit error finding carrying the path and text, since the second file genuinely is inaccessible.
- **Reviewer disposition:** implementer addressed; reviewer verification pending

#### R07 — Reconcile legacy profiles with immutable revisions

- **Severity / affected acceptance ID:** Major; A20, P2 compatibility/migration gate.
- **Observed behavior and evidence:** Legacy `ProfileService.save` still updates only `organization_profiles`. After two new-style revisions, a legacy save produced profile version 3 while latest immutable revision remained 2. Migration 004 stores legacy rules as an object; `_content_of` treats non-list rules as empty, losing unknown-key review information. Legacy conflict policy values such as `skip` are not members of the new preset model. The current planner also does not apply the stored legacy root prefix despite the execution report claiming equivalent legacy semantics.
- **Required change:** Route legacy saves through a compatibility-aware revision writer, or explicitly reject unsupported conversions without mutating one side. Migrate root-only layouts to equivalent valid revision content, preserve unknown keys as blocking review evidence, map legacy conflicts deliberately, and retain historical absence honestly. Do not expose advanced token templates as a literal legacy root. Add the missing fresh/upgrade and service-wiring tests before P2 completion.
- **Regression/validation requirement:** Populate a pre-v4 DB with root-only, unknown-key, and supported legacy-policy profiles; upgrade and read/export them. Test legacy save after new-style save and vice versa, monotonic versions, exact root mapping, and immutable prior content. Verify old jobs and dependent rows survive migration with `foreign_key_check` clean.
- **Implementer response / commit:** Addressed in the working tree. New `application/preset_compat.py` holds one conversion used by migration 004, `ProfileService.save`, and revision reads, so the same legacy input always produces the same revision content. Root-only templates convert to `<root>/{relative_dir}/{filename}`; a root that is absolute, escaping, or token-bearing is *not* reinterpreted as a literal prefix (that would route files somewhere the user never asked for) but becomes a blocking review item with the default fallback; unknown template keys are preserved as review items carrying their values; legacy conflict policies map deliberately — `rename` → `keep_both`, `skip` and `overwrite` → `needs_review`, since name-only skipping and replacement both violate §6.4. The original template is stored verbatim in `legacy_template_json`, and review evidence in `review_json`, surfaced as `PresetContent.reviewRequired` and as plan warnings. `ProfileService.save` writes its matching immutable revision in the same transaction as the version bump, and both writers take their next version from `max(profile.version, max_revision(preset))`, so the histories cannot diverge in either order. The planner now applies the stored legacy root prefix. Fresh/upgrade/service-wiring coverage added in `tests/test_preset_compat.py` (including pre-v4 databases with root-only, unknown-key, and token-root profiles, `PRAGMA foreign_key_check` clean, dependent job rows surviving). While building those fixtures, `persistence/runner.py::apply_pending` was found to accept `target_version` on an upgrade and then ignore it — fixed and noted in the report.
- **Reviewer disposition:** implementer addressed; reviewer verification pending

#### R08 — Close the remaining P1 scan-error execution bypass

- **Severity / affected acceptance ID:** Major; A07, P1 safety guard.
- **Observed behavior and evidence:** `source.inspect` now exposes scan errors, but the existing Organize screen still forwards only `inspected.entries` to preview/apply and does not gate on `errorCount`. The compatibility planner still uses files-only `scan_inventory`. Thus recording errors in inspection does not by itself prevent a partial set from being transferred and reported as successful. Directory symlinks are absent from the scanner entirely (R06).
- **Required change:** Fail closed in the backend for incomplete/unsupported source scans in active legacy shared-service entry points until the explicit exclusion workflow exists. Surface actionable UI errors. Do not rely only on renderer validation or claim A07 passed based on inspection tests.
- **Regression/validation requirement:** Exercise actual source.inspect → organize.preview/apply and offload planning wiring with injected scan errors; no successful partial transfer without an explicit supported exclusion record. Retain P1 overwrite/verification regressions.
- **Implementer response / commit:** Addressed in the working tree. The backend fails closed rather than relying on renderer validation. `OrganizeService.preview`/`apply` rescan the source with `scan_inventory_detailed` and refuse when there are read failures or unsupported objects, and when the caller's entry list omits files the scan found (extra entries are still allowed — a caller may organize a chosen subset; missing ones are not, because nobody chose to omit them). `IntakePlanner.build` uses the detailed scan and refuses an unaccounted source with the same actionable message; `scan_inventory` is no longer used for planning. `sourceScanBlocker` in the desktop Organize screen blocks preview and apply with a specific message so the user is told before pressing a button — a courtesy, not the guarantee. Directory symlinks are now scanned (R06). Coverage: `tests/test_organize_safety.py::TestScanErrorsFailClosed` (6 tests, one driving `source.inspect` → `plan.build` through the real `ApplicationService`, all asserting nothing was written), `desktop/tests/r08-scan-gate.test.ts` (4 tests). P1's overwrite/verification regressions are unchanged and still pass. Note the visible behavior change recorded in the report: a source containing a symlink can no longer be organized through the legacy path until the explicit exclusion workflow lands in P4.
- **Reviewer disposition:** implementer addressed; reviewer verification pending

Resume order: correct the report (R01), fix scan/data-accounting defects (R02/R03/R06/R08), then approval/pinning/compatibility (R04/R05/R07), run the full P2 exit checks, and only then continue P3. P4 rules and P5 execution remain later work; provisional P2 APIs must stay conservative until those phases land.

### Implementer pass — 2026-09-10

R01–R08 addressed in the working tree; see each revision's implementer
response above and `DESTINATION-PRESETS-EXECUTION-REPORT.md` for evidence.
P3 was then implemented within the boundaries the reviewer set — discovery,
identity, availability, explicit rebinding; no conflict resolution, no
automatic mounting. Validation after both passes: Python **805 passed / 0
failed**, Ruff check and format clean, mypy clean (76 files), desktop
typecheck/lint/build clean, desktop Vitest **259 passed**. Packaged-app,
desktop-UI, and real-storage (§12.2) gates remain NOT RUN.

No revision below is self-certified as resolved: each records what was
changed and stays at *implementer addressed; reviewer verification pending*
until the reviewer inspects the tree and reruns the checks.

Three consequences were raised for the reviewer and have been ruled on
(reviewer response, 2026-09-10):

1. **Migration 004 was amended in place rather than superseded by a 005.**
   It has never been committed or shipped, so no released database can carry
   the old shape — but *uncommitted is not unapplied*: the earlier tests
   exercised v4, so development databases do carry it. Because the DDL is
   `CREATE TABLE IF NOT EXISTS` and the migration never re-runs at the same
   version, such a database is silently incompatible rather than upgraded.
   `assert_v4_shape` (called from `ApplicationService.bootstrap`) now fails
   at startup naming the missing columns. **Rebuild disposable test
   databases only**; a database holding useful records must have them
   exported or be migrated explicitly, never deleted.
2. **Legacy `organize.*` and `plan.build` fail closed** on sources that do
   not scan cleanly, and the restriction stays. The refusal names the exact
   paths responsible and states that the restriction concerns symlinks
   *inside* the source tree — selecting a source path that is itself an alias
   for a mount point is ordinary and is not what blocks. P3 may distinguish a
   confirmed root mount alias from in-tree symlinks; blanket dereferencing is
   not to be introduced to accommodate presumed card layouts.
3. **P2 approval stays strict.** With no exclusion workflow, every finding
   blocks — a single pre-existing file at the destination stops the whole
   plan. That is correct for P2. P4 is to make conflicts practical through
   reviewed keep-both decisions and checksum-proven identical reuse, not by
   loosening this gate.

### Follow-up review — 2026-09-11 (revisions + P3)

Verdict: **NEEDS CHANGES — focused P2/P3 integration fixes remain.** Reviewed the uncommitted tree based on HEAD `9d0d460`. The earlier multi-source omission, size-only identity claim, missing preset pins, inventory representation errors, legacy revision divergence, and scan-error bypass have substantive fixes and regression coverage. R04 is only partially closed: persisted configuration/snapshot comparisons are implemented, but live validation is not connected to approval. P3 adapters and resolver are now real implementation, rather than prospective report text.

Independent checks executed: `.venv/bin/python -m pytest` **805 passed**; Ruff check and format passed; mypy passed (**76 source files**); desktop typecheck, lint, Vitest and build passed (Vitest reports **259 tests**). Packaged app, actual desktop interaction, and real NAS transfer/disconnect tests remain NOT RUN. Temporary fixture reproductions below use isolated databases and paths, not user storage. Review changed documentation only.

#### R09 — Connect approval to fresh source and destination validation

- **Severity / affected acceptance ID:** Major; R04 remains partial, A08/A12/A14/A26, §7.1.
- **Observed behavior and evidence:** `application/service.py::transfer_plan_approve` directly calls `TransferPlanService.approve`; `_assert_approvable` compares saved DB rows, stored inventory hashes and old capacity values, without fresh source or storage observations. In a disposable fixture, after building a clean plan, changing source bytes and removing the destination directory, destination resolution correctly returned `offline` but approval still returned `approved`. A stored inventory hash does not change when files change on disk. The report's statement that the resolver and approve provide the binding check for P5 is therefore not yet true.
- **Required change:** Use a shared backend preflight for approval that validates current source evidence, resolved storage identity and binding, destination availability, and current capacity against the immutable plan. Wire it through actual application services; do not merely update saved manifest rows in tests. Fail closed for unavailable, ambiguous, stale, or mismatched storage. Keep another mandatory validation immediately before execution/publication in P5; approval-time checks do not replace it. Expensive scans must remain observable and must not block the IPC handler indefinitely. If approval cannot yet perform this validation, expose it as unavailable rather than returning approved.
- **Regression/validation requirement:** Build a real plan, mutate source files on disk without modifying DB records, and require replan. Remove/replace destination storage after planning, inject fresh observations through the real service wiring, and refuse approval. Change available capacity after planning and enforce reserve. Include successful unchanged-source/identity approval.
- **Implementer response / commit:** Addressed in the working tree. Reproduced first: a plan built cleanly, then source bytes changed and the destination directory removed, still returned `approved` while the resolver correctly said `offline`. Root cause accepted as stated — every check read a stored row, and stored rows do not move when the filesystem does. New `application/preflight.py` + `transfer_plan_preflights` table: a preflight re-walks each source root and recomputes the *same* manifest hash the inventory stored (catching files added, removed, resized, or re-saved), confirms every planned source still exists, resolves the destination through the real resolver using **fresh observations** (refusing unavailable/ambiguous/rebound storage), refuses any planned target that has acquired content since planning (§6.4, including broken symlinks, which `exists()` misses), and recomputes capacity against live free space plus the reserve. `TransferPlanService.approve` now requires a preflight that is passing, bound to the exact fingerprint, not superseded by a later failure, and newer than `PREFLIGHT_TTL_SECONDS` (300s) — otherwise it refuses with the findings. Preflight runs on a background thread with a persisted progress counter and is exposed as `transfer.preflightStart` / `transfer.preflightStatus`, so a 100,000-entry plan never blocks the IPC handler; `run_blocking` exists for CLI and tests only. Abandoned `running` rows are failed at startup so "not failed" can never read as "fine". The documented limitation: a same-size, same-mtime content change is not detected — only checksums can, and those are the P5 runner's, whose publication-time checks this does not replace. Regressions in `tests/test_preflight.py` (16 tests) drive the real `ApplicationService` and mutate actual files and directories rather than editing rows.
- **Reviewer disposition:** implementer addressed; reviewer verification pending

#### R10 — Cached identity is display evidence, not current recognition authority

- **Severity / affected acceptance ID:** Major; A14/A25, §5.1–5.2.
- **Observed behavior and evidence:** `application/volumes.py::SystemVolumeAdapter._identities` reuses a cached strong identity when a fresh probe fails at the same path. `DestinationObservation.from_volume` conveys no freshness/degraded marker; the resolver reports `available`. Reproduced successful probe followed by failed probe at the same path: `degraded=True`, but resolution remained `available`. A drive can be swapped between observations, so absence of a witnessed unmount does not establish continuity. The exception branch also returns before evicting cache entries for paths no longer present. `destination_discovery.stale` uses only time since the latest snapshot, not whether that snapshot reused old evidence.
- **Required change:** Preserve cached identity for display with its original timestamp, per-mount freshness and error state. Never authorize automatic recognition/rebinding from failed or stale evidence unless independent current storage-continuity evidence proves it; otherwise return `needs_confirmation`/unavailable with the reason. Carry freshness into resolver inputs and approval. Mark degraded evidence stale immediately and prune disappeared paths on every exit path, including raised-probe exceptions.
- **Regression/validation requirement:** Original drive observed; different drive appears at the same path between polls; fresh probe fails. It must not resolve available as the original drive. Also test unmount during a raised probe, reappearance, cached discovery responses, and recovery after a fresh successful probe. Verify that display retains useful old evidence without elevating it to current authority.
- **Implementer response / commit:** Addressed in the working tree. Reproduced: a successful probe followed by a failed probe at the same path left `degraded=True` while resolution stayed `available`. The finding is correct and the original reasoning was wrong in a specific way — retaining cached evidence was right, treating it as *current* was not, and the two were conflated. `DestinationIdentity` gained `observed_at` and `stale`; `SystemVolumeAdapter._identities` keeps unrefreshed evidence but returns it marked stale with the timestamp it was actually observed and its provenance annotated, and sets `degraded` immediately. `_classify_match` never returns `strong` for stale evidence, so the resolver answers `needs_confirmation` and says why — "a drive can be swapped between observations". Cache pruning now happens *first*, before the probe, so it runs on every exit path including a raised exception. `destination.discovery.stale` is no longer purely time-based: a snapshot taken one second ago that reused remembered identity is stale, and the response names the mounts affected. Evidence is still shown, never elevated. Regressions in `tests/test_destinations.py::TestStaleEvidenceIsNotAuthority` (swap, failed probe, recovery after a fresh pass) and `tests/test_volumes.py` (retention, raised probe, pruning).
- **Reviewer disposition:** implementer addressed; reviewer verification pending

#### R11 — Validate the saved folder's backing storage and containment

- **Severity / affected acceptance ID:** Major; A06/A12/A14, §5.1.
- **Observed behavior and evidence:** `_candidate_path` joins a validated relative string beneath the recognized mount, but `_resolve_within` only checks exists/is_dir/writability, following symlinks. Reproduced a recognized mount with `folder` symlinked to a separate directory outside it: resolver returned `available` for that folder. `_resolve_local_folder` bypasses observations entirely, so it cannot detect replacement of a folder's backing storage or a changed alias. A matching parent volume identity does not prove a selected folder still resides on that volume (symlink or nested mount).
- **Required change:** Verify resolved subfolder containment and actual backing mount against current storage evidence before returning available; reject or explicitly confirm a changed storage target. Preserve intentional root aliases by binding them to their resolved storage, rather than banning all root symlinks. Validate local-folder backing evidence too. Ensure confirmBinding records a consistent mount/subfolder/resolved binding and does not simply accept contradictory path and identity fields. Keep the required publication-time recheck in P5.
- **Regression/validation requirement:** Subfolder symlink escaping the recognized mount, nested different mount, local root alias switched to another location, and legitimate confirmed root alias. Test through service wiring and verify that the plan cannot be approved for a path the resolver cannot establish on the saved storage.
- **Implementer response / commit:** Addressed in the working tree. Reproduced: a recognized mount with `folder` symlinked outside it resolved `available`. `_resolve_within` now runs a containment check before returning available — the resolved subfolder must be inside the *resolved* mount, and on the same `st_dev`. Comparing resolved forms is what preserves an intentional root alias while still rejecting an escaping subfolder: the rule is containment, not a ban on symlinks. A different filesystem mounted inside the volume is caught by the device comparison, which a path cannot reveal. `_resolve_local_folder` now receives observations and validates backing evidence: a local folder whose disk now reports a different identity returns `needs_confirmation` rather than `available`. `confirm_binding` refuses a path/identity pair that current observations contradict (it would persist evidence that was never true, and the resolver would then reason from it), derives `subfolder_path` from the mount the confirmation happened on so mount/subfolder/binding stay consistent across a remount, and records the platform's own evidence when the caller supplies none. Because approval now requires a passing preflight (R09), and preflight requires `available`, a plan cannot be approved for a path the resolver cannot establish on the saved storage. Regressions in `tests/test_destinations.py::TestSubfolderContainment` and `::TestConfirmBindingConsistency`, plus `tests/test_destination_end_to_end.py::test_confirm_binding_refuses_a_contradictory_identity` through the wiring.
- **Reviewer disposition:** implementer addressed; reviewer verification pending

Remaining scope notes: P3 discovery is currently synchronous and on demand. The final integration must satisfy the spec's bounded/responsive discovery requirement: subprocess timeouts do not bound `disk_usage`/filesystem calls on an unresponsive share. Periodic desktop refresh belongs to P6, but must use one observation authority. The report's process-wide abandoned-inventory recovery caveat also needs resolution before concurrent CLI/desktop use is declared supported; a second application bootstrap must not fail another live owner's scan. These are explicitly retained implementation gates, not proof of current operational readiness.

Recommended next action: address R09–R11 with real service-boundary regressions, correct phase status to distinguish passing unit tests from pending integration sign-off, then resume P4. No merge or production-readiness approval is given by this review.

### Implementer pass — R09–R11 (2026-09-11)

All three reproduced first, then fixed, then re-run against the fixed
tree: approval of a changed source with a removed destination is refused,
a failed probe no longer authorizes recognition, and an escaping
subfolder symlink no longer resolves available. Details per revision
above. Validation: Python **836 passed / 0 failed**, Ruff check and
format clean, mypy clean (78 files), desktop typecheck/lint/build clean,
desktop Vitest **259 passed**.

The two retained scope notes were also addressed rather than deferred:

- **Concurrent startup no longer terminates a live scan.** Abandoned-scan
  recovery now fails only inventories whose `owner_pid` is gone (probed
  with `signal 0`; anything undeterminable is treated as alive, because
  wrongly failing a live scan is worse than leaving a dead one for the
  next startup). Regression:
  `test_a_live_owners_scan_is_never_failed_by_another_process`.
- **Filesystem metadata calls are bounded.** `disk_usage` runs on a
  daemon thread with a 5s budget, so an unresponsive share degrades to
  "capacity unknown" with a warning instead of hanging discovery. Stated
  honestly: the syscall cannot be cancelled, so the thread stays blocked
  until the mount answers or the process exits — what this buys is that
  discovery returns and manual selection stays usable. Regression:
  `TestBoundedFilesystemCalls`.

Still open and **not** claimed: periodic desktop refresh (P6, must use
the one observation authority), and the publication-time revalidation
that P5 owes — preflight bounds the window between review and execution,
it does not close it. Phase status in the execution report distinguishes
passing tests from operational sign-off, which remains the reviewer's.

### Follow-up gate review — 2026-09-11 (R09–R11 implementation)

Verdict: **NEEDS CHANGES — two bounded items before P4 sign-off.** Background live preflight now gates approval; mounted-volume stale evidence is demoted and subfolder containment is checked. Those changes substantially address R09–R11. This is not a request to repeat the earlier work or implement P5 prematurely.

Independent validation: full Python run **833 passed, 3 failed**. Failures were `tests/test_migration_vnext.py::{test_schema_version_advanced,test_vnext_indexes_present,test_foreign_keys_enforced}`, all reaching `source.backup(dest)` in `persistence/backup.py:72` and raising `sqlite3.OperationalError: unable to open database file`. An isolated rerun of the complete migration-vNext module passed **5 tests**; the intermittent full-run failure remains unresolved. Ruff lint/format and mypy passed (78 source files). Desktop typecheck/lint/tests/build passed. Packaged/real-storage gates remain NOT RUN.

#### R12 — Apply stale/missing evidence restrictions to local folders too

- **Severity / affected acceptance ID:** Major; residual R10/R11, A12/A14/A25.
- **Observed behavior and evidence:** `application/destinations.py::_backing_failure` returns no failure when observations are empty or no owning mount is found. It also accepts every `_classify_match` result other than `none`, which includes stale/weak evidence. Disposable reproduction: save a `local_folder`, confirm a strong volume UUID, then resolve once with no observations and once with that UUID marked stale; both return `available` with “local folder exists and is writable.” `local_folder` is the default destination kind, so this is not an obscure optional path.
- **Required change:** When backing identity has been recorded, require fresh sufficient matching evidence or return `needs_confirmation`/unavailable. Missing owner/observations must not imply a match. Keep any deliberately permitted manual weak-identity confirmation explicit, scoped, and distinguishable from automatic recognition; do not let a prior path confirmation become permanent authority over replacement storage. Exercise the result through preflight as well as direct resolver calls.
- **Regression/validation requirement:** Confirmed local-folder identity with empty observations, unknown owner, stale matching UUID, weak matching evidence, different UUID, and fresh strong matching UUID. Only the valid supported confirmation/fresh-match cases may pass preflight. Preserve intentional confirmed aliases and ordinary local-folder usability.
- **Implementer response / commit:** Addressed in the working tree. Reproduced first, and all four cases behaved exactly as described: with a strong volume UUID confirmed on a `local_folder`, resolving with no observations, with an unknown owner, with that UUID marked stale, and with weak matching evidence all returned `available`. `_backing_failure` was doing two wrong things — treating absence of contradiction as confirmation, and accepting every `_classify_match` result other than `none`, which swallowed exactly the stale/weak evidence R10 had just established as non-authoritative. Rewritten: once identity evidence has been recorded, recognition requires **fresh, strong, matching** evidence; empty observations, an undeterminable owner, stale evidence, weak evidence, and a different identity each return `needs_confirmation` with a reason naming which of those it was. Two cases still pass and both are explicit rather than incidental: a local folder for which no identity was ever recorded (the user saved a path and never confirmed storage — the explicit path binding is the whole of the request, and ordinary local-folder usage keeps working), and a recorded `path_only` identity, the §5.1 escape hatch for storage the platform cannot identify. The latter is **scoped, not permanent**: `_path_only_failure` expires it the moment the platform *can* identify that storage, so a prior path confirmation never becomes standing authority over replacement storage. Regressions: `tests/test_destinations.py::TestLocalFolderBackingEvidence` covers all six enumerated cases plus both permitted ones; `tests/test_preflight.py::test_a_local_folder_with_unverifiable_backing_fails_preflight` and `::test_an_ordinary_local_folder_still_passes_preflight` exercise the result through preflight and approval, not only the resolver.
- **Reviewer disposition:** implementer addressed; reviewer verification pending

#### R13 — Diagnose the recurring SQLite backup failure

- **Severity / affected acceptance ID:** Major validation blocker; P0 baseline and P2 migration gate.
- **Observed behavior and evidence:** Three full-suite failures described above; isolated module rerun passes. Earlier hardening annotates connect failures but the failure occurs during `source.backup(dest)`, so the emitted exception still lacks source/target context. No claim that this review proves a new regression: it is a recurring unresolved baseline defect.
- **Required change:** Capture source and target paths and relevant SQLite/runtime context around backup-operation failures without dumping database content. Investigate full-suite lifecycle/concurrency and backup-file handling, then fix the demonstrated cause or document an evidence-backed environment limitation. Do not treat isolated rerun success as closure or relax tests. Preserve useful databases; use disposable fixtures for diagnosis.
- **Regression/validation requirement:** Targeted regression for the identified cause and a clean full run. Record original failure and subsequent results in the execution report; if nondeterminism remains, report it rather than marking the gate PASS.
- **Implementer response / commit:** Partially addressed; **not closed, and the gate is not marked PASS.** The required diagnostics are in: `persistence/backup.py::_backup_failure` now wraps `source.backup(dest)` and re-raises with both paths, each file's size/mode, which `-wal`/`-shm`/`-journal` sidecars exist, the target directory's existence/writability/entry count, and the SQLite version — file metadata only, no database content, since this text reaches logs and reports. Regression: `tests/test_persistence_runner.py::test_backup_failure_names_both_databases_and_their_state`, which also asserts no schema text leaks. Investigating full-suite lifecycle turned up two real defects, both fixed: (1) **background threads outlived shutdown.** Inventory scans and preflights run on daemon threads that `shutdown()` did not stop, so they kept opening connections against a database their owner believed it had released — including while a later bootstrap of the same path took migration backups. `InventoryService.shutdown` and `PreflightService.shutdown` now cancel and join with a bounded wait (a walk blocked in the kernel cannot be interrupted, so shutdown waits and moves on rather than hanging), wired into `ApplicationService.shutdown`; regressions in `tests/test_inventory_service.py`. (2) **a test left directories permanently unreadable.** `test_sources.py`'s `chmod(0o000)` restore sat in a `finally` that covered only the last assertion, so an earlier failure left an undeletable directory and every subsequent run accumulated another temp root pytest could not clean; now the restore covers every assertion. **The root cause is not demonstrated.** I could not reproduce the failure on this machine across: 27 full-suite runs, 60 iterations of the migration/bootstrap-heavy modules, 300 direct `write_backup` iterations holding an open WAL connection on the source under concurrent subprocess pressure, and 2 full-suite runs with undeletable temp roots artificially recreated. Isolated rerun success is explicitly not being treated as closure, no test was relaxed, and the two fixes above are contributing defects rather than a proven cause. If it recurs the exception will now name the file that could not be opened, which is what the next diagnosis needs. Reported as unresolved nondeterminism.
- **Reviewer disposition:** implementer addressed; reviewer verification pending

P4 organization design can proceed independently, but P0–P3 are not yet signed off as a completed foundation. Address R12/R13 before declaring that transition complete.

### P4 implemented — 2026-09-11

Proceeding on the reviewer's authorization to continue with R13
explicitly open. The agreed direction is retained: saved destinations
lead the workflow; the user chooses between preserving structure and
organizing by reusable rules; "keep selected folders intact" is a
general rule, not a project-specific feature; conflict decisions are
reviewed, and nothing silently overwrites or disappears.

Delivered: the rule engine (`application/rules.py`) with groups-first
ordering, AND/OR condition semantics, a versioned extension map,
UTC-mtime date tokens that never fall back to "now", and rendered-path
validation that rejects rather than repairs; the conflict planner
(`application/conflicts.py`) with deterministic keep-both allocation
reserved against both planned entries and existing destination contents,
and the six distinct conflict kinds §6.4 requires; and the explicit
exclusion workflow (`transfer.planResolve`), which produces a new plan
revision rather than editing the reviewed one and carries decisions
across rounds.

`skip_identical` is still never issued — it needs the checksum proof the
P5 runner produces. Repeated-transfer reuse and cross-job path
reservation likewise belong to P5. The preset editor is P6.

Validation: Python **931 passed / 0 failed**, Ruff check and format
clean, mypy clean (80 files), desktop typecheck/lint/build clean, desktop
Vitest **259 passed**. Acceptance coverage added at the planner layer for
A02, A05, A17, and A18. **R13 remains open and P0–P3 remain unsigned-off;
P4 is development progress, not a baseline claim.**

### Implementer pass — R12–R13 (2026-09-11)

R12 is fixed and regression-covered through both the resolver and
preflight. **R13 is not closed**: the diagnostics it requires are in
place and two genuine lifecycle defects were found and fixed, but the
root cause was not demonstrated and the failure did not reproduce here.
Per R13's own instruction, that is reported rather than marked PASS —
P0–P3 remain *not signed off*.

Validation: Python **849 passed / 0 failed** on the final tree, plus 27
additional full-suite runs during the flake hunt (all green; the single
failure seen was a test of mine mid-edit, not a SQLite failure). Ruff
check and format clean, mypy clean (78 files), desktop
typecheck/lint/build clean, desktop Vitest **259 passed**.

### P4 review — 2026-09-11 (R09–R13 verification, P4 findings)

Verdict: **NEEDS CHANGES — P4 is real and well-structured, but four
Major defects stand between it and the §6 contract.** Reviewed the
uncommitted tree on HEAD `9d0d460`. No implementation code was changed by
this review; documentation only.

Independent validation on this workstation: `.venv/bin/python -m pytest`
**931 passed, 0 failed**; Ruff check and format clean (141 files); mypy
clean (80 source files); desktop typecheck, lint, Vitest (**259 passed**)
and build clean. Three additional full-suite runs were made looking for
R13 (results recorded in the execution report). Every finding below was
reproduced against a disposable database and temporary directories
through the real `TransferPlanService` / `PreflightService` /
`DestinationService`, not by editing rows.

#### Dispositions for R09–R13

- **R09 — accepted.** Reproduced the fixed behavior: after planning,
  changing source bytes fails preflight with the manifest finding, and
  removing the destination directory fails it with `offline`. Approval
  without a current passing preflight is refused. The documented
  same-size/same-mtime gap is stated and belongs to P5.
- **R10 — accepted.** `TestStaleEvidenceIsNotAuthority` and the
  `test_volumes.py` retention/raised-probe/pruning cases pass; the
  resolver code path never rates stale evidence `strong`.
- **R11 — accepted.** `TestSubfolderContainment` and
  `TestConfirmBindingConsistency` pass; `_resolve_within` compares
  resolved forms and `st_dev`. Note that R16 below is a *sibling* gap on
  the planner side, not a reopening of R11.
- **R12 — accepted.** Reproduced independently: a `local_folder` with a
  confirmed strong volume UUID returns `needs_confirmation` with no
  observations and with the UUID marked stale, and `available` only on a
  fresh strong match.
- **R13 — remains open; disposition unchanged.** The diagnostics and the
  two lifecycle fixes are accepted as such. The gate is still not PASS,
  and P0–P3 remain unsigned-off, exactly as the implementer recorded.

#### R14 — Review-required preset revisions must block approval

- **Severity / affected acceptance ID:** Major; A20, §4.2, R07 residual.
- **Observed behavior and evidence:** `PresetContent.review_required`
  is documented in `protocol.py` as "Non-empty blocks plan approval", and
  R07's response describes unknown legacy keys as *blocking review
  items*. In fact `_build_plan` only appends them to `warnings` and
  hashes them into the fingerprint; `_assert_approvable` never looks at
  them and `blocking_count` stays 0. Reproduced: a revision with
  `review_json = ["unknown legacy template key 'foo' = 'bar'"]` planned,
  preflighted, and **approved**. The existing test
  (`test_a_preset_needing_review_is_surfaced_on_the_plan`) asserts only
  that the text appears in warnings.
- **Required change:** Treat non-empty revision review evidence as a
  blocking condition in `_assert_approvable` (and reflect it in
  `blocking_count` or a distinct counter the UI can show). Provide the
  explicit path through it: either a decision recorded on the plan or a
  new revision that resolves the item. Do not clear it silently.
- **Regression/validation requirement:** A plan against a
  review-required revision refuses approval naming the items; the same
  plan approves after a corrected revision is pinned. Keep the existing
  surfacing test.
- **Implementer response / commit:** Fixed. Reproduced first: a revision
  with `reviewRequired` non-empty planned, preflighted and approved, with
  `blocking_count = 0`. `transfer_plans` gained `preset_review_json`, so
  the evidence travels with the plan and the refusal can name the items
  instead of pointing at a revision the reviewer would have to go and
  read. `_assert_approvable` now refuses first, before every other check,
  and the message states the way through: save a corrected revision that
  resolves the item and pin it. Nothing clears the evidence on the user's
  behalf. `presetReviewRequired` is on `TransferPlanStatusModel` and the
  TypeScript contract. Spec §4.2 now states the rule. Regressions in
  `tests/test_transfer_plan.py`:
  `test_a_preset_needing_review_refuses_approval_and_names_the_item`
  (asserts the preflight *passes* — the world is fine, the preset is not)
  and `test_a_corrected_revision_makes_the_same_plan_approvable`. The
  existing surfacing test is unchanged and still passes.
- **Reviewer disposition:** pending

#### R15 — Preset-level `exclusions` are stored, hashed, and never applied

- **Severity / affected acceptance ID:** Major; A18, §4.2 ("explicit
  exclusion rules"), §6.3 ("never silently omitted").
- **Observed behavior and evidence:** `PresetContent.exclusions` is
  validated, persisted in `exclusions_json`, covered by the content hash,
  exported and imported — and referenced nowhere in `rules.py` or
  `transfer_plan.py`. Reproduced: a revision excluding `extensions:
  [".tmp"]` planned `junk.tmp` as an ordinary `copy` with no warning,
  `exclusion_count = 0`. A user who saved that rule believes those files
  are excluded; the plan does the opposite and says nothing. This is the
  silent-ignore §4.2 forbids, in the opposite direction from the usual
  case.
- **Required change:** Either apply preset exclusions during routing
  (producing `action = exclude` entries with `exclusion_reason` naming
  the rule, counted separately per §7.3 and recorded in receipts) or
  remove the field from the accepted model until it is implemented, with
  a field-specific validation error. Shipping an accepted-but-inert
  field is not an option.
- **Regression/validation requirement:** Extension, glob, and category
  exclusions each produce recorded exclusions; a rule with no conditions
  is rejected like a routing rule; `excluded_by_user` stays 0 for
  preset-driven exclusions so the two origins remain distinguishable.
- **Implementer response / commit:** Fixed by applying the field, not by
  removing it. Reproduced first: `.tmp` planned as an ordinary `copy`,
  `exclusion_count = 0`. `rules.find_exclusion` is a separate function
  called before routing, because an exclusion decides whether an entry is
  routed at all and that is the planner's call to record. Excluded
  entries get `action = exclude`, `matched_rule = "exclusion:<id>"`, and a
  reason quoting the rule's own words. `excluded_by_user` stays 0, and a
  new `rule_exclusion_count` on the plan and the status model counts them
  apart from a reviewer's decisions, per §7.3.

  Two things the finding did not name, found while fixing it. First, the
  actual cause: `_effective_content` rebuilt the content from the
  template alone when a revision had no rules or groups, dropping the
  exclusions (and the review evidence) on the way — so exactly the preset
  most likely to be exclusion-only was the one where they vanished. It
  now carries both. Second, excluding a directory while copying its
  contents is incoherent — the files would land under a parent the plan
  said it would not create — so descendants inherit the rule, named as
  inherited.

  Validation at save time matches routing rules: at least one condition,
  unique id, and a non-empty reason (it is the whole account a receipt
  gives for every skipped file). Exclusions apply inside preserved groups
  too, and the spec §6.1 now says so and why. Six regressions in
  `tests/test_transfer_plan.py`, four in `tests/test_presets.py`, four in
  `tests/test_rules.py`.
- **Reviewer disposition:** pending

#### R16 — A directory symlink at the destination is accepted as a directory

- **Severity / affected acceptance ID:** Major; A06, A12, §6.2 (symlink
  escapes), §7.1.
- **Observed behavior and evidence:** `conflicts.allocate` for
  `entry_type == "dir"` checks `exists_on_disk` and then `is_dir()`,
  which follows symlinks. `_describe_collision` flags an existing *file*
  symlink as `existing_destination_symlink` and says it is "never
  replaced", but a *directory* symlink passes as an ordinary existing
  directory. Reproduced: with `Sources/card/Photos` a symlink to a
  directory outside the destination root, the plan recorded the `dir`
  clean, every file beneath it as a clean `copy`, preflight passed, and
  approval succeeded. Publication would then write through the link.
  P1's containment check at write time may catch this, but the plan and
  preflight both told the user it was fine, and §7.1 requires it caught
  before approval.
- **Required change:** Use `lstat`-based classification for directory
  targets: an existing symlink at a planned directory path is
  `existing_destination_symlink` (blocking) regardless of what it points
  to. Preflight's `_check_entries` should apply the same rule to `dir`
  entries, not only `copy` entries.
- **Regression/validation requirement:** Directory symlink pointing
  inside and outside the destination root; both block. A real existing
  directory continues to merge. Exercise through preflight and approval.
- **Implementer response / commit:** Fixed, and wider than the finding
  asked. Reproduced first: with `Sources/card/Photos` a symlink to an
  outside directory, the plan recorded every file beneath it as a clean
  `copy`, preflight passed, approval succeeded.

  Fixing only the `dir` entry would not have closed it. R18's
  implied-directory rule (correctly) stops emitting a plan entry for a
  directory whose routed children create it — so in the very case
  reproduced, there is no `Photos` entry to check. The rule implemented
  is therefore: **no component of a planned destination path may be a
  symbolic link**, leaf or parent. `Reservations.symlink_ancestor` walks
  the ancestor chain with `os.path.islink` and caches per directory, so a
  plan with a hundred thousand files pays for the depth of the tree
  rather than its size; the `dir` branch of `allocate` tests the leaf
  with `lstat` before `is_dir()`, which follows links. Preflight applies
  the same check to `copy` and `dir` entries, with its own per-directory
  cache, and reports a count with samples.

  Where it points is not the question — a link inside the destination
  root blocks too. An ordinary existing directory still merges, which is
  covered so the fix cannot quietly turn re-use of a destination into a
  blocker. Spec §7.1 states the rule. Three regressions in
  `tests/test_transfer_plan.py`, two in `tests/test_preflight.py` (the
  preflight ones create the link *after* planning, which is the case
  stored rows cannot show).
- **Reviewer disposition:** pending

#### R17 — Preserved groups: the root is not routed by the group, and members are renamed individually

- **Severity / affected acceptance ID:** Major; A17, §6.3, examples E08/E16.
- **Observed behavior and evidence:** Two related defects, reproduced
  together with group `pathGlob: "Proj"` → `Collections/{source_label}/{relative_dir}/{filename}`:
  1. `_group_root` iterates `range(1, len(parts))`, so the group root
     directory's own inventory entry is never a group member. The `dir`
     entry `Proj` routed to **`Unsorted/card/Proj`** via the fallback
     while its children went to `Collections/card/Proj/...` — an empty
     stray folder and a group that is not, in fact, kept together.
  2. With an existing `Collections/card/Proj/clip.mov` at the
     destination, keep-both renamed the member to
     **`clip (2).mov`** automatically, `blocking_count = 0`.
     `Routing.group_id` is dropped in `_draft_for`, so the allocator
     cannot know the entry belongs to a group. The examples document (E16,
     decision 5) is explicit: never suffix internal members
     automatically; resolve at the group root or require review.
- **Required change:** Include the group root itself in group routing.
  Carry `group_id` onto the draft/plan entry, and make the allocator
  resolve group collisions at the group root (allocate a new root name
  and keep every internal path) or mark the whole group `needs_review`.
  Record the group id on plan entries so the review screen can show the
  containment.
- **Regression/validation requirement:** Group root directory lands under
  the group destination; an existing file inside the group's target
  either moves the whole group to a suffixed root with internal paths
  intact, or blocks; no member is individually renamed. Extend the A17
  test accordingly.
- **Implementer response / commit:** Both defects fixed. Reproduced
  together first, with the reviewer's own preset: the `Proj` dir entry
  routed to `Unsorted/card/Proj`, and a colliding member was renamed to
  `clip (2).mov` with `blocking_count = 0`.

  1. `_group_root` now considers the entry itself when the entry is a
     directory, so a group's own root is a member of its group. Files are
     unaffected: a group claims a directory, and a file is claimed by
     being inside one.
  2. `Routing` carries `group_id`, `group_root` and `group_dest_root`;
     `_Draft` and `transfer_plan_entries.group_id` carry them onward.
     Groups are now allocated *first* and as whole subtrees:
     `conflicts.allocate_group_root` resolves the collision one level up,
     and `_allocate_group` rebases every member under the result. Under
     `keep_both` the whole group moves to a suffixed root with every
     internal path unchanged; under any other policy the whole group
     blocks. No member is ever suffixed. Merging into an existing tree is
     not attempted, per E16.

  The relocation is recorded on the group root's directory entry —
  `renamed_from`, the detail, and one plan warning naming the group — so
  the decision has a home even though a directory with routed children is
  otherwise implied by them (that entry is explicitly retained). Group
  destinations are now restricted to `{source_label}`, `{relative_dir}`
  and `{filename}` at save time, per examples §4, which also removes the
  "group could not render its destination" fallback path the review noted
  separately. Spec §6.3 states all of it. Five regressions across
  `tests/test_rules.py` and `tests/test_transfer_plan.py`.
- **Reviewer disposition:** pending

#### R18 — Built-in category preset and empty-directory placement diverge from the agreed examples

- **Severity / affected acceptance ID:** Moderate; A18, §6.2,
  `docs/ORGANIZATION-PRESET-EXAMPLES.md` §2, §5, decision 2.
- **Observed behavior and evidence:**
  - `BUILTIN_PRESETS["sort-by-category"]` routes to
    `Video/{year}/{filename}` (and likewise for audio, image, document).
    The examples document specifies
    `Video/{source_label}/{relative_dir}/{filename}`, promises "keeping
    their source folders traceable", and §5 says plainly "Do not include
    date routing in the two starter presets." The shipped shape drops
    both the source label and the relative directory, so every card's
    `IMG_0001.JPG` collides in `Images/2026/` and keep-both suffixes
    multiply; it also makes the mtime-year caveat a default behavior
    rather than an opt-in.
  - Every inventory directory is routed as its own `dir` entry through
    the rules. With the category preset, `Photos` and `Photos/Trip`,
    whose only contents were routed to `Images/…`, were recreated as
    empty `Unsorted/card/Photos/Trip`. The examples say: "A directory
    containing routed files is not itself an empty directory; do not
    create an empty fallback duplicate for every source parent."
- **Required change:** Align the built-in with the examples (or amend
  the examples first and say why). Route only *genuinely empty*
  directories through the empty-directory rule; directories that
  contained routed entries are implied by their children. Record the
  chosen semantics in the spec, not only in the examples file.
- **Regression/validation requirement:** Category preset output for the
  examples' §2 table matches; a parent of routed files produces no
  fallback directory; a truly empty directory still does.
- **Implementer response / commit:** Both parts aligned to the examples;
  the examples were not amended, because they were right.

  The category preset now routes `Video/{source_label}/{relative_dir}/{filename}`
  and the same shape for audio, images, documents and archives, with rule
  ids matching the examples' table. No `{year}` in either starter preset.
  `tests/test_presets.py` now checks the examples' §2 table verbatim,
  including the two fallback rows, plus a test asserting no date token
  appears in either starter.

  Empty directories: `_drop_implied_directories` keeps only directories
  nothing else will create. A directory is implied by a descendant this
  plan will actually *write* — a copy, or a retained empty directory —
  computed deepest-first so a kept empty subdirectory implies its own
  parents. A folder whose every child was excluded or blocked is not
  implied by them and keeps its entry. The end-to-end test's entry count
  went from 5 to 3 and now asserts the reason rather than the number
  alone.

  While fixing this I found that `tests/test_presets.py` fixtures used
  `{filename}{ext}` throughout. `{filename}` is the complete basename per
  §6.2, so those templates rendered `a.mov.mov`; nothing asserted the
  rendered result, so it had gone unnoticed. Fixture-only, corrected.
  Spec §6.2 now carries the empty-directory rule and the category
  preset's shape.
- **Reviewer disposition:** pending

#### R19 — Resolving an approved plan leaves the original approval standing

- **Severity / affected acceptance ID:** Moderate; A08, §7.1, §8.
- **Observed behavior and evidence:** `TransferPlanService.resolve`
  refuses `executing`/`executed` plans but accepts an `approved` one.
  Reproduced: approve plan A, resolve one entry, obtain draft B with
  `derived_from = A`; A remains `approved` with `approved_fingerprint`
  set. Two plans for the same sources and destination, one approved and
  one superseded by a reviewer's own decision, now coexist; P5 could
  legitimately start A.
- **Required change:** Deriving a new revision from a plan should
  invalidate the parent's approval (status `invalidated`, reason
  "superseded by <B>") in the same transaction, or `resolve` should
  refuse approved plans and tell the caller to invalidate first. Either
  is acceptable; silently leaving both is not.
- **Regression/validation requirement:** After `resolve`, the parent
  cannot be approved or started; `derived_from` links survive.
- **Implementer response / commit:** Fixed. Reproduced first: approve A,
  resolve one entry, and A remained `approved` with its
  `approved_fingerprint` set beside its own successor. `resolve` now calls
  `plan_repo.mark_superseded`, which sets the parent `invalidated`,
  clears `approved_fingerprint` (leaving it set would let a later reader
  conclude the plan was approved in the shape it now has), and records
  `superseded_by`. `derived_from` is unchanged, so the lineage survives in
  both directions.

  One ordering note: the invalidation happens after the successor exists
  rather than inside one transaction with it, because building the
  successor runs its own transaction. The consequence is the safe one — a
  failed rebuild leaves the reviewed plan exactly as it was, rather than
  invalidating it and producing nothing. `resolve` also now refuses a plan
  that is already superseded and names the successor, so further
  decisions accumulate in one line of revisions instead of two siblings
  each holding half the review. `supersededBy` is on the status model and
  the TypeScript contract. Two regressions in
  `tests/test_transfer_plan.py`.
- **Reviewer disposition:** pending

#### R20 — Glob semantics and keep-both naming need to be specified, not inferred

- **Severity / affected acceptance ID:** Minor; §6.1 ("documented case
  sensitivity and `/` separators"), examples E05.
- **Observed behavior and evidence:** `fnmatch` lets `*` span `/`, so
  `DCIM/*` matches `DCIM/100MEDIA/a.mov`, `*.mov` matches at any depth,
  and a group glob of `*` claims every top-level directory. None of this
  is written down for the preset author. Separately, the allocator emits
  `name (2).ext` while the examples show `a-2.jpg`; either is fine, one
  must be chosen and documented.
- **Required change:** Document the glob dialect (case-insensitive,
  `/`-separated, `*` spans separators, no `**` distinction) in the spec
  §6.1 and the examples; add a test pinning it. Reconcile the suffix
  style in the examples with the implementation.
- **Regression/validation requirement:** Documentation; one pinning test.
- **Implementer response / commit:** Documented and pinned; the suffix
  style was reconciled in favor of the implementation.

  The glob dialect is now written out in spec §6.1 and in
  `path_glob_matches`: `/` separators always (a backslash reads as one,
  leading and trailing separators ignored), case-insensitive, `*` spans
  separators, no distinct `**`, `?` and `[seq]` as usual, nothing else
  special. It also records that a group glob is matched against directory
  paths rather than file paths. `TestGlobDialect` in
  `tests/test_rules.py` pins all six behaviors, including the two that
  most surprise — `*` crossing `/`, and a pattern naming a directory not
  claiming its children.

  On the suffix: `name (n).ext` from 2 is kept and the examples updated
  to match, rather than the reverse. The examples document explicitly
  left the punctuation open, the parenthesised form does not collide with
  filenames that legitimately end in `-1`, and the behavior is already
  covered by tests. E05 and E06 now read in that form, the shared-behavior
  bullet records the decision and that it changed, and spec §6.4 states
  the form so a receipt is reproducible.
- **Reviewer disposition:** pending

#### Notes retained without a revision number

- `Reservations.exists_on_disk` caches by folded comparison key, so on a
  case-sensitive target the cached answer for `foo.txt` is reused for
  `Foo.txt`. In the orders the planner produces this is conservative;
  worth a comment and a test, not a fix round.
  **Addressed:** the docstring now states the asymmetry explicitly — the
  cache can report a free name as taken, which costs a keep-both suffix,
  and never the reverse, which would cost a file.
- When a group's destination template cannot render (missing mtime),
  the group lands at its own folder name rather than the configured
  fallback. Defensible for a group; state it in §6.2.
  **Addressed differently:** the case no longer exists. Group
  destinations may only use `{source_label}`, `{relative_dir}` and
  `{filename}`, rejected at save time (examples §4, R17), so rendering a
  group root cannot fail on missing file metadata. The fallback branch
  was removed rather than documented.
- A source component ending in `.` or a space (legal on APFS) blocks its
  whole subtree as `unroutable`. Correct per §6.2's rejection rule and
  excludable via `planResolve`; the message should say the exclusion path.
  **Addressed:** every `unroutable` finding now ends with the three ways
  out, `transfer.planResolve` named.
- `import_preset` validates the same content twice; harmless.
  **Addressed:** the duplicate `model_validate` block is gone.

P5 must not start against this tree until R14–R17 are closed. R18–R20
may be batched with them. No merge or production-readiness approval is
given by this review; R13 and the P0–P3 sign-off remain exactly where
the implementer left them.

### Implementer pass — R14–R20 (2026-09-11)

All seven addressed, plus the four retained notes. Every finding was
reproduced first through the real services against a disposable database
and temporary directories — `TransferPlanService`, `PreflightService`,
`PresetRevisionService` over `tests/test_transfer_plan.py::Harness` and
`tests/test_preflight.py::World` — and each reproduction is now a
regression asserting the corrected behavior.

Three things worth the reviewer's attention beyond the individual
responses:

1. **R16 is fixed more widely than it was filed**, and had to be. Fixing
   only the planned `dir` entry would have left the reproduced case open,
   because R18's implied-directory rule means the symlinked parent has no
   plan entry at all. The rule implemented is that no *component* of a
   planned destination path may be a symbolic link, in the planner and in
   preflight, both with per-directory caches.
2. **R15's cause was upstream of where it was filed.**
   `_effective_content` rebuilt preset content from the fallback template
   alone whenever a revision had no rules or groups, discarding the
   exclusions and the review evidence — so the exclusion-only preset, the
   one most likely to exist in practice, was exactly where the field
   disappeared. That also means R14 and R15 shared a cause in part.
3. **R18 and R17 interact**, and the resolution is stated in §6.2 and
   §6.3 rather than left implicit: directories route group-aware (R17),
   and a directory whose contents this plan writes is then implied by
   them and gets no entry (R18) — *except* a relocated group root, which
   is retained because it is where the relocation decision is recorded.

Two defects found while fixing these, neither filed, both corrected:
the `{filename}{ext}` fixtures in `tests/test_presets.py` (see R18), and
`resolve` accepting a plan that had already been superseded (see R19).

Schema: migration 004 amended in place again — `transfer_plans` gained
`preset_review_json`, `rule_exclusion_count` and `superseded_by`;
`transfer_plan_entries` gained `group_id`. All four are registered in
`_AMENDED_V4_COLUMNS`, so a development database already stamped v4
fails `assert_v4_shape` with one actionable error rather than a missing
column deep in a service. It has still never been committed or shipped,
so no user database can carry an older shape; rebuild disposable test
databases.

Validation: **976 Python tests passed** (931 before this pass), Ruff
check and format clean (141 files), mypy clean (80 source files);
desktop typecheck, lint, **259 Vitest tests** and build clean.

**R13 remains open and P0–P3 remain unsigned-off.** No stress runs were
made this pass, per the standing instruction; nothing here bears on the
SQLite backup failure either way.
