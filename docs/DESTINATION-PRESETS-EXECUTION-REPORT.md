# Destination presets — execution report

Companion to [`DESTINATION-PRESETS-PRODUCTION-SPEC.md`](DESTINATION-PRESETS-PRODUCTION-SPEC.md).
This report records phase status, evidence, decisions, and blockers as work
proceeds. Statuses are `PASS`, `FAIL`, `NOT RUN`, or `BLOCKED`. Nothing here
is a production claim; §1.1 completion levels apply.

> **Correction notice (2026-09-10).** An earlier version of this report marked
> P2 and P3 `PASS` and cited `test_migration_destinations.py`,
> `test_transfer_plan.py`, `test_destination_resolver.py`, and
> `test_destination_end_to_end.py` as evidence. Three of those four files did
> not exist in the tree; it also described platform identity adapters and
> `ferry destination|preset|inventory|transfer` CLI commands that were not
> implemented, and reported checks as green while the suite had a failing
> test and Ruff had findings. Those claims were wrong. The review at spec
> §13.1 (R01) required them corrected rather than quietly amended, so the
> incorrect claims are named here and the status table below is rebuilt from
> observed results only. Every `PASS` in this document now names a file that
> exists and a command whose output was read.

## Environment

- Machine: macOS 24.6.0 (developer workstation).
- Python 3.14.3 (`.venv`), Node v22.23.0, Ruff 0.15.20, mypy 2.2.0.
- Baseline for this work was `9d0d460`; everything since is committed — see
  "Committed vs working tree" below for the series and per-commit
  verification.
- Commands: spec §11.

## Phase status

| Phase | Status | Notes |
| --- | --- | --- |
| P0 cleanup/baseline | **Not signed off** — R13 open | Cleanup landed in `f8529d2`; the recurring SQLite backup flake is unresolved |
| P1 safety regressions + guards | Tests pass; **integration sign-off pending** | `232eb36`, `9d0d460`, plus the R08 fail-closed work below |
| P2 persistence: destinations, preset revisions, inventories, plans | Tests pass; **integration sign-off pending** | Migration 004 + services + protocol + wiring; R02–R07, R09 addressed |
| P3 volume identity, discovery, rebinding | Tests pass; **integration sign-off pending** (macOS/Linux; Windows honestly unsupported) | Identity adapters, discovery health, resolver fed real observations; R10–R12 addressed |
| P4 rule engine / conflict planner | Tests pass; **integration sign-off pending** | Rule engine, groups, conflict matrix, exclusion workflow. R14–R20 addressed — see "R14–R20 — the P4 review pass" below; reviewer verification pending |
| P5 durable verified copy runner | NOT RUN | Out of this work order |
| P6 desktop flow / CLI parity | NOT RUN | Out of this work order |
| P7 packaging / pilot / real storage | NOT RUN | Out of this work order |
| P8 final review handoff | NOT RUN | Out of this work order |

### Committed vs working tree

**The working tree is fully committed as of 2026-09-13** (this report, the
spec, and the examples doc land in the docs commit at the tip of the
series). P0/P1 were already committed as `f8529d2`, `232eb36`, `9d0d460`.
The P2–P4 work and the R01–R20 revisions land as eight code commits on
`main` on top of `9d0d460`, ordered so that every commit is independently
green — each was verified in a detached worktree (pytest, mypy, ruff check,
ruff format), with the final tree's desktop checks run directly
(typecheck, lint, 259 Vitest tests, build):

| Commit | Content | Boundary check (pytest / mypy / ruff / fmt) |
| --- | --- | --- |
| `2e7db5d` | feat(p2): schema v4 + protocol contracts (migration 004, repositories, runner/backup fixes, `preset_compat`) | 0 failed / 72 files ✓ / ✓ / 123 files |
| `b8afc89` | feat(p4): rule engine + conflict planner (landed early: presets and the planner import them) | 0 failed / 74 ✓ / ✓ / 127 |
| `b082abf` | feat(p2): immutable preset revisions + legacy profile compatibility | 0 failed / 75 ✓ / ✓ / 130 |
| `867bf05` | feat(p3): volume identity probes + discovery health | 0 failed / 76 ✓ / ✓ / 132 |
| `77e470f` | feat(p2)!: full inventories + fail-closed legacy organize/plan | 0 failed / 77 ✓ / ✓ / 134 |
| `19e859a` | feat(p3): destination resolver, availability, explicit rebinding | 0 failed / 78 ✓ / ✓ / 136 |
| `7ba5a14` | feat(p2/p4): durable plans, preflight-gated approval, service assembly, RPC wiring | 0 failed / 80 ✓ / ✓ / 141 |
| `d609521` | fix(desktop): R08 scan gate + shared IPC contract | 0 failed / 80 ✓ / ✓ / 141 |

Two test files are split across the series so each boundary stays green
without weakening the final coverage: `test_migration_fixtures.py` lands
without the bootstrap-refusal test in `2e7db5d` and complete in `7ba5a14`
(the guard is wired in `ApplicationService.bootstrap`, which that commit
introduces); `test_inventory_service.py` lands without the
service-assembly shutdown test in `77e470f` and complete in `7ba5a14`.
The desktop tree is untouched until `d609521`; boundaries before it run the
baseline desktop, which passed at `9d0d460`.

The earlier statement below is retained as corrected history.

> An earlier version of this section said all P2 work and all R01–R08
> revisions were in the working tree, uncommitted, and listed the untracked
> and modified files. That was true when written (2026-09-10); the series
> above is what replaced it, and the file list it carried is now the
> content of those commits.

## Validation results

Run at the state described above, after the R14–R20 work:

| Command | Result |
| --- | --- |
| `.venv/bin/python -m pytest` | **976 passed**, 0 failed |
| `.venv/bin/ruff check .` | All checks passed |
| `.venv/bin/ruff format --check .` | 141 files already formatted |
| `.venv/bin/mypy src` | Success, 80 source files |
| `desktop/ npm run typecheck` | passed |
| `desktop/ npm run lint` | passed (eslint + oxlint anti-slop) |
| `desktop/ npm test` | **259 passed** (17 files) |
| `desktop/ npm run build` | built |

Not performed: packaged-app smoke, desktop UI run, NAS/real-storage matrix
(§12.2), secret scan, `scripts/verify-packaged.sh`. These remain `NOT RUN`
and no production claim depends on them.

Previous review's failing test `test_inventory_service.py::test_scan_errors_recorded`
now passes — but note it was **corrected, not just fixed**: its expectation of
two readable files under a `chmod 000` subtree was wrong, since the second file
genuinely is inaccessible. It now asserts one readable file plus an explicit,
diagnosable error finding (R06).

## P0 — cleanup and baseline

Committed in `f8529d2`. Content as previously reported: baseline capture,
repo map, documentation reconciliation (root README's "all nine packages
landed" claim, desktop README's stale placeholder section, the dead
`docs/DEVELOPMENT.md` link), and backup-filename hardening
(microsecond timestamps + per-process counter) after the intermittent
`test_downgrade_drops_vnext` failure could not be reproduced in 45 runs.

Correction to the earlier text: it reported "645 tests collected, all pass"
and "mypy clean (64 files)". Those figures were from the P0 commit and are
retained as history; the current figures are in the table above.

## P1 — safety regressions and guards

Committed in `232eb36` and `9d0d460`: verified non-overwriting copies,
exclusive publication, disabled `move`/`link`, containment validation, and
the removal of the silent 5,000-entry inspect cap. Evidence:
`tests/test_organize_safety.py`, `tests/test_offload.py`.

### R08 — the remaining scan-error bypass (closed in this pass)

`source.inspect` reported `errorCount`, but `organize.preview`/`organize.apply`
accept a **caller-supplied** entry list, so a client forwarding only
`inspected.entries` handed over a partial set and got a green result. The
compatibility planner (`application/plan.py`) used the files-only
`scan_inventory`, hiding the same class of problem from intake plans.

- `application/organize.py` now rescans the source itself and refuses when
  the scan has read failures or unsupported objects, and when the supplied
  entry list omits files the scan found. Extra entries are still allowed (a
  caller may organize a chosen subset); missing ones are not, because nobody
  chose to omit them.
- `application/plan.py::IntakePlanner.build` uses `scan_inventory_detailed`
  and refuses an unaccounted source with the same actionable message. The
  files-only `sources.scan_inventory` had no callers left afterwards and was
  removed: leaving a scanner that drops errors and non-files in reach is how
  this defect gets reintroduced.
- Desktop: `sourceScanBlocker` in `renderer/src/lib/organize.ts` blocks
  preview and apply with a specific message. This is a courtesy, not the
  guarantee — the backend refusal is.

Evidence: `tests/test_organize_safety.py::TestScanErrorsFailClosed` (6 tests,
including one driving `source.inspect` → `plan.build` through the real
`ApplicationService`), `desktop/tests/r08-scan-gate.test.ts` (4 tests).

## P2 — persistence, preset revisions, destinations, inventories, plans

Migration `004_destination_presets.py` (schema v4) creates
`saved_destinations`, `organization_profile_revisions`, `source_inventories`,
`source_inventory_entries`, `transfer_plans`, `transfer_plan_entries`, and
rebuilds `jobs` with a nullable `project_id`.

Evidence: `tests/test_migration_fixtures.py` (v1 → v4 upgrade preserving
legacy data, new tables present, `jobs.project_id` nullable, idempotent
re-run) and `tests/test_preset_compat.py` (pre-v4 fixtures with awkward
legacy content, `PRAGMA foreign_key_check` clean, dependent rows survive).

### Review revisions addressed

**R02 — source identity is (inventory, entry), never a relative name.**
`_build_plan` deduplicated by relative path across inventories, so two drives
each holding `same.txt` produced one entry and one automatic exclusion. Plan
entries now carry `inventory_id` + `inventory_entry_id` + `rel_path`; two
sources landing on one destination path are both kept and both marked
`needs_review` with conflict `duplicate_destination_path`. Scan errors and
unsupported objects stay in the plan as blocking items with an
`exclusion_reason`, and `excluded_by_user` distinguishes a decision somebody
made from a finding nobody has decided. Duplicate and nested source
selections, and destination-inside-source, are rejected explicitly.
Evidence: `tests/test_transfer_plan.py` (R02 section, 6 tests).

**R03 — no size-only identical classification.** `skip_identical` is no
longer emitted at all in this increment; every existing destination object is
a distinct conflict (`existing_destination_file`, `existing_destination_symlink`,
`existing_directory`, `existing_special`, `existing_destination_unreadable`).
Evidence: `tests/test_transfer_plan.py` (R03 section, 3 tests), including a
same-size/different-bytes fixture.

**R04 — approval enforces the contract.** `approve` now refuses blocking
findings, an archived/rebound/edited destination, changed destination identity
or reserve, a preset revision whose content hash moved, an inventory that is
no longer complete or whose manifest changed, insufficient capacity, and
unknown capacity without a recorded override. Capacity accounts for planned
bytes **plus** the destination's `free_space_reserve` plus the temporary
sibling a verified copy writes (bounded by the largest file). The plan row
stores the complete approved substance — inventory snapshots with manifest
hashes and counts, destination identity JSON, conflict policy, checksum
algorithm, reserve, observed free bytes — and the fingerprint hashes all of
it plus per-entry size/mtime. Invalidation on edit, rebind, and archive now
happens in the *same transaction* as the change.
Evidence: `tests/test_transfer_plan.py` (R04 section, 10 tests),
`tests/test_destination_end_to_end.py`.

**R05 — pinned preset revisions.** `destination.save` resolves and stores a
concrete `pinned_revision` (explicit `pinnedRevision`, else the existing pin
for the same preset, else that preset's current revision) and validates the
preset/revision pair. Plans use the pin, never "latest"; an explicit
`presetRevision` is a per-transfer override. Moving the pin is explicit and
invalidates unexecuted approvals.
Evidence: `tests/test_transfer_plan.py` (R05 section, 4 tests).

**R06 — inventory representation and error persistence.** `sources.py::_walk`
now yields ordinary directories (empty ones included) and directory symlinks,
which `os.walk` lists but never descends. A read failure is no longer a fifth
`entry_type`: it is `scan_status='error'` with the diagnostic in `error` and
`entry_type='unknown'` when the object could not be stat'd — which is what the
migration's CHECK constraint actually permits. A failed scan keeps the counts
and entries it genuinely reached and records why it stopped. Inventories carry
`owner_pid`/`heartbeat_at`, and `recover_abandoned_scans` (called from
`bootstrap`) fails scans orphaned by a process exit rather than leaving them
`scanning` forever.
Evidence: `tests/test_inventory_service.py` (11 tests, including empty
directories, directory symlinks, injected mid-walk failure, restart recovery,
and the corrected unreadable-subtree test).

**R07 — legacy profiles and revision history reconciled.**
`application/preset_compat.py` is the single conversion shared by the
migration, the legacy `ProfileService.save`, and revision reads. A root-only
legacy template becomes `<root>/{relative_dir}/{filename}`; a root that is
absolute, escaping, or token-bearing is *not* reinterpreted as a literal
prefix but recorded as a blocking review item; unknown template keys are
preserved verbatim as review items; legacy conflict policies map deliberately
(`rename` → `keep_both`; `skip` and `overwrite` → `needs_review`, since
name-only skipping and replacement both violate §6.4). The original template
is kept in `legacy_template_json`. Legacy saves now write their matching
immutable revision in the same transaction, and both writers derive the next
version from `max(profile.version, max_revision)` so the two histories cannot
diverge. The planner applies the stored legacy root prefix, which it
previously recorded and ignored.
Evidence: `tests/test_preset_compat.py` (14 tests).

**Incidental fix found while building the R07 fixtures.**
`persistence/runner.py::apply_pending` accepted `target_version` on an upgrade
and then ignored it, applying every pending migration. A fixture asking for
"a database at version 3" silently got head. Now bounded in both directions.
Evidence: `tests/test_preset_compat.py::_pre_v4_db` depends on it;
`tests/test_migration_fixtures.py` and `tests/test_persistence_runner.py`
still pass.

### Services and protocol

- `application/destinations.py` — save (with pinning), list, archive, resolve
  (§5.1 five-state contract), confirm binding.
- `application/presets.py` — immutable revisions, get/list, portable JSON
  export/import (presets only; no paths or identities; imports create a new
  local identity).
- `application/inventory.py` — background full scans, status, paginated
  entries (default 200, max 1,000, stable cursor, server totals).
- `application/transfer_plan.py` — plan creation, paginated entries,
  approval.
- `service/protocol.py` + `service/wiring.py` + `desktop/shared/ipc-methods.ts`
  updated together per ADR-0002. New methods are discoverable through
  `app.getCapabilities`.

Evidence for the wire surface: `tests/test_destination_end_to_end.py` drives
scan → save preset → save destination → resolve → plan → approve through the
real wired sidecar, and `tests/test_service_wiring.py` pins handler/catalog
parity.

### What P2 does *not* do

- The rule engine is P4. Plans preserve the source relative path (applying a
  legacy root-only prefix where one exists) and record a warning saying so
  when a preset's rules are not applied.
- There is **no explicit exclusion workflow** yet. Every finding is therefore
  blocking; `excluded_by_user` is always 0.
- `transfer.start` is deliberately absent until P5.
- No CLI commands for destinations, presets, inventories, or plans exist. The
  earlier report's claim that `ferry destination …` etc. shipped was wrong;
  CLI parity is P6.

## P3 — volume identity, discovery, availability, rebinding

> An earlier report marked this PASS while none of it existed. What
> follows describes code that is now in the tree, with the tests that
> exercise it named.

### Identity evidence — `application/volume_identity.py`

The question this layer answers is deliberately narrow: *what durable
identifier can the platform tell us about this mount point right now?*
It answers with evidence and a confidence, never a decision.

- **macOS** — `diskutil info -plist <mount>` for local volumes;
  `VolumeUUID` is strong, `DiskUUID` only medium (a reformat keeps the
  media UUID, so a match proves the hardware returned, not the
  filesystem). Network shares are identified from the mount table's
  device string (`//user@server/share`, `server:/export`) for
  `smbfs`/`cifs`/`nfs`/`afpfs`/`webdav`.
- **Linux** — `/proc/self/mountinfo` joined to `/dev/disk/by-uuid`;
  octal escapes (`\040`) are decoded so spaced and Unicode mount paths
  parse correctly.
- **Windows / anything else** — `NullIdentityProbe`, which returns weak
  `path_only` evidence *and a warning saying so*. Ferry has no tested
  way to read a volume GUID there, and claiming weak evidence is strong
  would be worse than admitting the gap (spec §1.2).

Credentials are stripped before anything is stored: `//alice:hunter2@nas.local/media`
becomes `nas.local/media`, host lowercased (DNS is case-insensitive),
share name left alone (often it is not). Probes are bounded by
`PROBE_BUDGET_SECONDS` (5s); a timeout or error **keeps the previous
evidence and marks the observation degraded** rather than downgrading a
strong identity to a guess — a transient probe failure must not silently
stop a saved destination being recognized.

Evidence: `tests/test_volume_identity.py` (25 tests over captured
platform output plus probe-failure behavior).

### Discovery — `application/volumes.py`

`SystemVolumeAdapter` attaches identity to each `MountedVolume` and
exposes `last_warnings()`/`degraded`. `VolumeObserver` gained:

- **`initialized`, separate from an empty baseline.** The previous
  `if not self._last` conflated "has not observed" with "observed
  nothing", so on a machine with no external volumes the *first* drive
  plugged in was swallowed as a baseline instead of reported as a mount.
  That is the one machine where that event is the only one that happens.
- `observed_at` / `age_seconds()` / `last_volumes()` so a stale
  observation is visibly stale rather than confidently wrong, and a
  re-rendering UI can read the cache without re-probing.

There is still one discovery loop; nothing was added alongside it
(spec §5.2).

Evidence: `tests/test_volumes.py` (21 tests, including the empty-baseline
distinction, cached-identity retention across a probe failure, a probe
that raises not taking discovery down, and a vanished mount not leaving
its identity behind for the next thing mounted at that path).

### Resolution and rebinding — `application/destinations.py`

`DestinationObservation` now describes a **mount**, not a folder. The
resolver joins the saved `subfolder_path` to a mount whose identity
already matched — a saved folder is never searched for by path
(spec §5.1). Branch order, each for a real failure:

1. Strong identity match → resolve the subfolder inside that mount and
   check it exists, is a directory, and is writable.
2. More than one strong match → `ambiguous`. Two devices presenting one
   identifier is not a tie to break silently.
3. Weak or medium match only → `needs_confirmation`.
4. Same share name, different host → `needs_confirmation`, because the
   host may be an alias for the saved one or a different server that
   also exports `media`.
5. Something *is* mounted at the saved path but reports a different
   identity → `needs_confirmation` naming what it found (A14).
6. Nothing matched but the directory remains → `needs_confirmation`
   (A12: a share unmounts and leaves its mount point on the local disk;
   writing into it fills the boot drive while reporting success to the
   NAS).
7. Nothing there → `offline`.

A missing local folder is `offline` and is **never recreated** — the new
one could be on a different disk (spec §5.1). `resolve` is an
observation and never writes a binding; only `confirmBinding` rebinds,
and it invalidates unexecuted approvals in the same transaction.

`ApplicationService.destination_resolve` now feeds the resolver real
observations from the one observer, with `refresh: false` to reuse the
last one. New method `destination.discovery` returns volumes,
`observedAt`, `ageSeconds`, `stale`, and `warnings` so a degraded probe
surfaces as a recoverable warning with manual folder selection still
usable.

Evidence: `tests/test_destinations.py` (22 tests) and
`tests/test_destination_end_to_end.py` (10 tests through the real wired
sidecar).

### Live check on real hardware

Run once against this workstation's actual mounts, read-only, in a
throwaway database — no transfer, no writes to the share (per §12,
private addresses are not recorded here):

- The boot volume resolved a strong `volume_uuid` from `diskutil`.
- A mounted SMB share resolved a strong `server_share` identity with the
  server credentials stripped, and a destination saved against it
  resolved **available**.
- Substituting an observation for the same share name on a different
  host returned **needs_confirmation**, naming the host mismatch.
- Removing the share from the observations returned
  **needs_confirmation** with `bindingPath` `None` — it did not fall
  back to the still-present local mount directory.

This is a single-machine sanity check, not the §12.2 matrix. It is not
evidence for any production claim.

### What P3 does not do

- **No automatic mounting**, no remote host discovery, no credential
  storage. Only already-mounted storage is discovered (spec §1.2).
- **No periodic observation loop is started.** `destination.discovery`
  and `resolve` observe on demand; the desktop's refresh cadence is P6.
- **Windows has no identity.** Destinations there can only be recognized
  by explicit confirmation, and the probe says so.
- Binding validation immediately before each file publication (§5.2) is
  specified for the execution runner and belongs to **P5**; the resolver
  and `approve` provide the check it will call.

## Automated acceptance matrix (§10)

Only IDs with observed evidence are listed. Everything else is `NOT RUN`.

| ID | Status | Evidence |
| --- | --- | --- |
| A01 (no silent cap) | PASS (service layer) | `test_organize_safety.py` inspect cases; `test_inventory_service.py` pagination; `test_transfer_plan.py::test_plan_entries_paginate_without_gaps_or_duplicates` |
| A03 (identical requires checksum) | PASS (planner refuses to claim it) | `test_transfer_plan.py` R03 section |
| A04 (two drives, same names) | PASS (planner layer) | `test_transfer_plan.py::test_two_sources_with_the_same_name_both_survive` |
| A06 (traversal/symlink escape) | PASS (planner + preflight) | `test_organize_safety.py` for rendered paths; R16 closed — `test_transfer_plan.py::test_a_directory_symlink_at_the_destination_blocks_the_plan` and `::test_a_symlink_pointing_inside_the_destination_blocks_too`, `test_preflight.py::test_a_symlink_appearing_at_a_planned_path_fails_preflight`. No component of a planned destination path may be a link; an ordinary directory still merges |
| A07 (unreadable/unsupported visible **and blocking**) | PASS (scan + planner + legacy entry points) | `test_inventory_service.py`, `test_organize_safety.py::TestScanErrorsFailClosed`, `desktop/tests/r08-scan-gate.test.ts` |
| A08 (stale approval rejected) | PASS (server side) | `test_transfer_plan.py` R04 section; `test_destination_end_to_end.py`. UI side is P6 |
| A20 (preset edit/export/import, old DB upgrade) | PASS (service layer) | `test_presets.py`, `test_preset_compat.py`, `test_destination_end_to_end.py::test_preset_export_carries_no_local_paths`; R14 closed — `test_transfer_plan.py::test_a_preset_needing_review_refuses_approval_and_names_the_item` and `::test_a_corrected_revision_makes_the_same_plan_approvable` |
| A12 (share unmounted, mount dir remains) | PASS (resolver layer, fakes + one live check) | `test_destinations.py::test_a12_unmounted_share_leaves_its_directory_and_must_not_be_used` |
| A13 (same volume remounted at a new path) | PASS (resolver layer) | `test_destinations.py::test_a13_same_volume_remounted_at_a_new_path_resolves` |
| A14 (different drive reuses label/path; duplicate identity) | PASS (resolver layer) | `test_destinations.py::test_a14_*` (two cases) |
| A25 (spaces/Unicode, empty baseline, slow probe) | PASS (adapter + observer + resolver) | `test_volume_identity.py` (mount-path parsing), `test_volumes.py` (empty baseline, probe timeout), `test_destinations.py::test_a25_*` |
| A26 (unknown capacity needs recorded override) | PASS (planner/approval) | `test_transfer_plan.py::test_unknown_capacity_requires_a_recorded_override` |
| A02 (existing same-name, different content) | PASS (planner layer) | `test_conflicts.py::test_existing_destination_content_is_reserved_against`, `test_transfer_plan.py` |
| A05 (case/Unicode aliases, file/dir ancestor conflict) | PASS (planner layer) | `test_conflicts.py::TestDistinctConflictKinds`, `test_transfer_plan.py::test_a05_*` |
| A17 (preserved group with mixed file types) | PASS (planner layer) | `test_rules.py::TestGroups` and `::TestGroupRootRouting`; R17 closed — `test_transfer_plan.py::test_the_group_root_lands_under_the_group_not_the_fallback`, `::test_a_colliding_group_moves_whole_and_keeps_its_internal_paths`, `::test_a_group_collision_blocks_whole_under_a_review_policy`. The group root is a group member; a collision moves the whole group or blocks it, never a member |
| A18 (unknown extension, extensionless, empty directory) | PASS (planner layer) | `test_transfer_plan.py::test_a18_*`; R15 closed — the exclusion tests in `test_transfer_plan.py`/`test_presets.py`/`test_rules.py`; R18 closed — `::test_a_parent_of_routed_files_gets_no_empty_fallback_folder` and `::test_a_genuinely_empty_directory_keeps_its_entry` |
| A09–A11, A15–A16, A19, A21–A24 | NOT RUN | Belong to P5–P7 |

A12/A13/A14/A25 were claimed `PASS` before any of the code existed. They
are now genuinely covered at the resolver and adapter layers against fake
observations, plus one live read-only check described under P3. They are
**not** covered against real disconnect/reconnect of physical hardware —
that is the §12.2 gate and remains `NOT RUN`.

## Blockers / unresolved

- **Approval is now gated on a preflight, which is a workflow change.**
  Any caller that approved a plan directly must first run
  `transfer.preflightStart` and wait for it to pass. The desktop does not
  consume these methods yet (P6).
- **P3 is implemented but not operationally validated.** The identity
  probes are exercised against captured platform output and one live
  read-only check on a single macOS workstation. No physical
  disconnect/reconnect, no second machine, no Linux or Windows run, no
  real remount-at-a-new-path. Those are §12.2 gates.
- **Windows destinations cannot be recognized automatically.** The null
  probe reports weak `path_only` evidence and a warning; every rebinding
  there needs explicit confirmation. This is a real capability gap, stated
  rather than papered over.
- **No exclusion workflow.** Until P4, any scan error, symlink, unsupported
  object, or existing destination file blocks approval outright. Retained by
  reviewer decision as correct for P2: P4 is to make conflicts practical
  through reviewed keep-both decisions and checksum-proven identical reuse,
  not by loosening this gate. It will feel strict on real sources until then.
- **Legacy `organize.*` and `plan.build` now fail closed** on sources that do
  not scan cleanly, and the restriction is retained by reviewer decision. This
  is a visible behavior change to existing commands: a source containing a
  symlink can no longer be organized through the legacy path. The refusal
  names every offending path and states explicitly that the restriction is
  about symlinks *inside* the tree — a source path that is itself an alias for
  a mount point is ordinary and is not what blocks (regression-tested both
  ways). P3 may distinguish a confirmed root mount alias from in-tree
  symlinks; blanket dereferencing is out of bounds.
- Real-storage gates (§12.2) unrun by definition; no production claim is made.
- The desktop renderer does not consume the new methods (P6); the protocol and
  TS types are in place so that work is additive.
- **`destination.save` is a full upsert, not a patch.** Omitting
  `defaultPresetId` clears the preset and its pin, exactly as omitting
  `conflictPolicy` resets it to the default. That is internally consistent,
  but it is a sharp edge for a P6 UI that wants to rename a destination
  without touching its preset. Either the UI must round-trip every field or
  a separate patch method is needed; flagged rather than silently shipped.
- **Startup scan recovery is process-wide.** `bootstrap` fails every
  inventory still marked `scanning`, which is correct for a fresh process but
  would be wrong if two `ApplicationService` instances ever shared a database
  concurrently. The sidecar bootstraps once per process, so this holds today;
  it stops holding if that changes.
- **The SQLite backup flake (R13) is unresolved.** Two contributing
  defects were fixed and full diagnostics added, but the cause is not
  demonstrated and it did not reproduce across 27 full runs plus targeted
  stress. P0 is therefore not signed off. Do not read the green runs
  recorded above as closure.

## Second review pass — R09–R11

Three integration defects, each reproduced before being fixed and
re-run afterwards. The common shape: unit-level logic was right and the
*seams between* components were not.

### R09 — approval validated records, not the world

Reproduction: build a clean plan, change the source bytes, delete the
destination directory. The resolver correctly said `offline`; approval
returned `approved`. Every check read a stored row, and a stored row does
not move when a file is edited or a drive is unplugged.

New `application/preflight.py` and a `transfer_plan_preflights` table. A
preflight:

- re-walks each source root and recomputes the **same** manifest hash the
  inventory stored, catching files added, removed, resized, or re-saved;
- confirms every planned source file still exists;
- resolves the destination through the real resolver with **fresh
  observations**, refusing unavailable, ambiguous, or rebound storage;
- refuses any planned target that has acquired content since planning
  (§6.4) — including a broken symlink, which `exists()` misses but which
  still occupies the name;
- recomputes capacity against live free space plus the reserve.

`approve` now requires a preflight that is passing, bound to the exact
fingerprint, not superseded by a later failure, and newer than
`PREFLIGHT_TTL_SECONDS` (300s). Otherwise it refuses and quotes the
findings.

It runs on a background thread with a persisted progress counter, exposed
as `transfer.preflightStart` / `transfer.preflightStatus`, so a
100,000-entry plan never blocks the IPC handler (§12). `run_blocking`
exists for CLI and tests and is deliberately not on the RPC surface.

**Known limitation, stated rather than hidden:** a same-size, same-mtime
content change is not detected. Only checksums can, and those belong to
the P5 runner — whose publication-time revalidation this does not
replace. Preflight bounds the window between review and execution; it
does not close it.

Evidence: `tests/test_preflight.py` (16 tests) drives the real
`ApplicationService` and mutates actual files and directories rather than
editing rows — the shortcut that let the defect through in the first
place.

### R10 — cached identity could authorize recognition

Reproduction: a successful probe, then a failed probe at the same path.
`degraded` was `True` and resolution was still `available`.

The original reasoning was wrong in a specific way: retaining cached
evidence was right; treating it as *current* was not; the two were
conflated. `DestinationIdentity` gained `observed_at` and `stale`.
Unrefreshed evidence is kept — "this looked like your Backup drive" is
useful — but returned marked stale, and `_classify_match` never rates
stale evidence `strong`, so the resolver answers `needs_confirmation`
explaining that a drive can be swapped between observations. Cache
pruning moved *before* the probe so it runs on every exit path including
a raised exception. `destination.discovery.stale` is no longer purely
time-based: a one-second-old snapshot that reused remembered identity is
stale, and the response names which mounts.

Evidence: `tests/test_destinations.py::TestStaleEvidenceIsNotAuthority`,
`tests/test_volumes.py` (retention, raised probe, pruning).

### R11 — subfolder resolution could escape the recognized volume

Reproduction: a recognized mount with `folder` symlinked outside it
resolved `available`.

`_resolve_within` now requires the resolved subfolder to be inside the
*resolved* mount and on the same `st_dev`. Comparing resolved forms is
what preserves an intentional root alias while still rejecting an
escaping subfolder — the rule is containment, not a ban on symlinks. The
device comparison catches a different filesystem mounted inside the
volume, which a path cannot reveal. `_resolve_local_folder` now takes
observations and validates backing evidence, so a local folder whose disk
reports a different identity needs confirmation. `confirm_binding`
refuses a path/identity pair that current observations contradict,
derives `subfolder_path` from the mount it was confirmed on, and records
the platform's own evidence when the caller supplies none.

Evidence: `tests/test_destinations.py::TestSubfolderContainment` and
`::TestConfirmBindingConsistency`, plus
`tests/test_destination_end_to_end.py::test_confirm_binding_refuses_a_contradictory_identity`.

### Retained scope notes, also addressed

- **Concurrent startup no longer terminates a live scan.** Recovery fails
  only inventories whose `owner_pid` is gone (`signal 0`; anything
  undeterminable counts as alive, since wrongly failing a live scan is
  worse than leaving a dead one for the next startup).
- **Filesystem metadata calls are bounded.** `disk_usage` runs on a
  daemon thread with a 5s budget; an unresponsive share degrades to
  "capacity unknown" with a warning instead of hanging discovery. The
  syscall cannot be cancelled, so the thread stays blocked until the
  mount answers or the process exits — what this buys is that discovery
  returns and manual selection stays usable.

## Third review pass — R12–R13

### R12 — local folders now get the same evidence rules (fixed)

`local_folder` is the **default** destination kind, and it was the one
with the weakest rules. `_backing_failure` treated absence of
contradiction as confirmation, and accepted every `_classify_match`
result other than `none` — which swallowed precisely the stale and weak
evidence R10 had just established as non-authoritative. Reproduced:
with a strong volume UUID confirmed, resolving with no observations,
with an unknown owner, with the UUID marked stale, and with weak
evidence all returned `available`.

Now: once identity evidence has been recorded, recognition requires
**fresh, strong, matching** evidence, and each failing case returns
`needs_confirmation` with a reason naming which one it was.

Two cases still pass, both deliberate and both explicit:

- **No identity was ever recorded** — the user saved a path and never
  confirmed storage for it. The explicit path binding is the whole of
  what they asked for; ordinary local-folder usage keeps working without
  a confirmation dance.
- **A recorded `path_only` identity** — §5.1's escape hatch for storage
  the platform cannot identify. It is *scoped, not permanent*: it
  expires the moment the platform can identify that storage, so a prior
  path confirmation never becomes standing authority over replacement
  storage.

Evidence: `tests/test_destinations.py::TestLocalFolderBackingEvidence`
(all six enumerated cases plus both permitted ones) and
`tests/test_preflight.py` (through preflight and approval, not only the
resolver).

### R13 — SQLite backup flake: NOT CLOSED

**Status: unresolved nondeterminism. This gate is not PASS.**

What was done:

1. **The required diagnostics are in.** `_backup_failure` wraps
   `source.backup(dest)` and re-raises naming both paths, each file's
   size and mode, which `-wal`/`-shm`/`-journal` sidecars exist, the
   target directory's existence/writability/entry count, and the SQLite
   version. File metadata only — no database content, since this text
   reaches logs and reports. Regression:
   `test_backup_failure_names_both_databases_and_their_state`, which
   also asserts no schema text leaks.

2. **Two real lifecycle defects found and fixed** while investigating —
   contributing factors, *not* a proven cause:
   - **Background threads outlived shutdown.** Inventory scans and
     preflights run on daemon threads that `shutdown()` did not stop, so
     they kept opening connections against a database their owner
     believed it had released — including while a later bootstrap of the
     same path took migration backups. Both services now cancel and join
     with a bounded wait (a walk blocked in the kernel cannot be
     interrupted, so shutdown waits and moves on rather than hanging).
   - **A test left directories permanently unreadable.**
     `test_sources.py`'s `chmod(0o000)` restore sat in a `finally`
     covering only the last assertion, so an earlier failure left an
     undeletable directory and every later run accumulated another temp
     root pytest could not clean.

3. **The root cause was not demonstrated.** It did not reproduce here
   across:
   - 27 full-suite runs (the one failure observed was a test of mine
     mid-edit, not a SQLite failure);
   - 60 iterations of the migration/bootstrap-heavy modules;
   - 300 direct `write_backup` iterations holding an open WAL connection
     on the source under concurrent subprocess pressure;
   - 2 full-suite runs with undeletable temp roots artificially
     recreated to match the condition the old `chmod` leak produced.

Isolated rerun success is explicitly **not** being treated as closure,
and no test was relaxed. If it recurs, the exception now names the file
that could not be opened — which is what the next diagnosis needs.
Please re-run on your machine; if you can capture one failure with the
new message, that should identify it.

## P4 — rule engine, groups, conflicts, exclusions

Built on the agreed direction: saved destinations lead, the user picks
between preserving structure and organizing by reusable rules,
"keep selected folders intact" is a general rule rather than a
project-specific feature, and every conflict is reviewed — nothing
silently overwrites and nothing disappears.

### The rule engine — `application/rules.py`

Order is the contract: **groups first, then ordered rules, first match
wins, then the fallback.** Groups run first because that is what stops
an extension rule pulling the `.xml` sidecar out of a camera card while
its `.mov` goes elsewhere. Nothing reaches the end without a
destination — an unrecognized file goes to the fallback, never nowhere
(§6.2).

- **Conditions are AND within a rule, OR within a condition.** A rule
  with no conditions matches nothing and is rejected at save time, so it
  cannot become an invisible catch-all above everything below it.
- **Path globs** always use `/` and match case-insensitively: sources are
  removable media formatted exFAT/FAT/HFS+ as often as not, and a
  pattern that silently stopped matching because a camera wrote `DCIM`
  instead of `dcim` would be a quiet routing bug rather than an error.
- **Extensions** normalize case and support matching extensionless files
  explicitly — otherwise "no extensions listed" and "files without one"
  are indistinguishable in the editor.
- **Categories** come from an explicit, versioned extension map
  (`CATEGORY_MAP_VERSION`, recorded on every plan). This is extension
  classification, never content verification, and it is described that
  way everywhere it surfaces — including in the built-in preset's own
  description.
- **`{year}`/`{month}` are source mtime in UTC**, never a capture date.
  A file with no usable mtime routes to the fallback *with a warning*
  rather than to an invented "now", which would file last year's footage
  under this year forever.
- **Rendered paths are validated, never silently repaired.** Control
  characters, over-long components, over-long total paths, and names
  with trailing dots or spaces (which Windows and some shares rewrite)
  are rejected — because a receipt naming a path that was not what got
  written is worse than a refusal.

### Groups — "keep selected folders intact"

A general rule, not a project feature: it applies equally to camera
cards, application bundles, client folders, albums, or edit projects. The
**outermost** matching group wins, so a group nested inside another
cannot split the parent apart. Descendants keep their internal structure
beneath the group's destination.

### Conflicts — `application/conflicts.py`

Keep-both is the default and resolves collisions deterministically:
`name (2).ext`, reserved against **both** the other planned entries and
the existing destination contents, so two sources cannot each pick the
same "free" suffix. The same plan produces the same names every time.

The conflict kinds are kept distinct because they mean different things
to whoever reviews them:

| Kind | Why it is its own finding |
| --- | --- |
| `same_name_different_content` | The common case; keep-both resolves it |
| `case_only` | One file on a case-insensitive target, two on a case-sensitive one |
| `unicode_normalization` | Visually identical; macOS and Linux disagree by default |
| `file_vs_directory` | No suffix fixes it; needs a decision |
| `ancestor_path` | One destination is inside another entry's file |
| `existing_destination` / `_symlink` / `_special` / `_unreadable` | Something is already there that this plan did not put |

Comparison is Unicode-normalized and case-folded — conservative on
purpose, because Ferry frequently cannot know what the target does, and
treating two names as *possibly* the same file is the answer that cannot
lose data. Actual filenames are never altered; only the comparison is
normalized.

**`skip_identical` is still never issued.** It requires proof of full
content equality (§6.4), and the checksums that prove it belong to the
P5 runner. A plan records the conflict so the decision can be made later
rather than asserting an identity nothing has verified.

### The exclusion workflow — what unblocks P2's strictness

Until now every finding blocked approval with no way through, which made
a plan containing one symlink permanently unusable. `transfer.planResolve`
is the way through, and it does **not** edit the reviewed plan: it
produces a new plan revision with the decision carried in and records
which plan it came from (§8). Decisions are keyed by
`(inventory, source-relative path)` so they survive the rebuild that
reassigns entry ids, and they accumulate — working through several
findings does not mean re-deciding the earlier ones each round.

An exclusion always records that a person chose it (`excluded_by_user`),
is counted separately from successful copies (§7.3), and is part of the
approved substance the fingerprint covers.

### Built-in starting presets (§6.2)

Two, both general, neither encoding a NAS layout or anyone's taxonomy:
**Preserve source structure** (the safe default — a transfer rearranges
nothing) and **Sort loose files by category**. They are handed to the
editor as starting points the user owns, not installed as magic presets
they cannot see inside.

### Evidence

`tests/test_rules.py` (47), `tests/test_conflicts.py` (18),
`tests/test_transfer_plan.py::TestExclusionWorkflow` and
`::TestAcceptanceMatrixP4`, `tests/test_presets.py::TestBuiltInPresets`.

### What P4 does not do

- **No repeated-transfer reuse.** §6.4's "consult prior completed
  mappings … reuse that mapped output only after checksum validation"
  needs receipts and checksums from P5; without them, keep-both remains
  the default on a re-run, as the spec says it should.
- **No cross-job path reservation.** §6.4 also requires serializing
  reservations across concurrent Ferry jobs; that belongs with the
  execution runner.
- **No preset editor UI.** P4 is the engine; the editor is P6.

## Reviewer verification — P4 (2026-09-11)

Independent checks on the same tree: Python **931 passed / 0 failed**
(once, then three further full runs, all green); Ruff check and format
clean (141 files); mypy clean (80 files); desktop typecheck, lint, Vitest
(**259 passed**) and build clean. Four green full runs are recorded as
observations, not as R13 closure; the flake did not appear on this
machine and the gate stays open.

**R09–R12 accepted** after independent reproduction (R09, R12) and
regression-class runs (R10, R11). **R13 unchanged: open.**

**P4: NEEDS CHANGES.** Every finding below was reproduced against a
disposable database through the real services; full text and required
changes are in the spec's §13.1 appendix.

| ID | Severity | Finding |
| --- | --- | --- |
| R14 | Major | A revision with non-empty review evidence approves; it only warns |
| R15 | Major | Preset-level `exclusions` are stored and hashed but never applied |
| R16 | Major | A directory symlink at the destination is accepted as a directory by planner and preflight |
| R17 | Major | Group root directory routes via the fallback; keep-both renames a group member individually (E16) |
| R18 | Moderate | Built-in category preset uses `{year}` and drops `{source_label}/{relative_dir}`, contrary to the examples; parents of routed files are recreated as empty fallback dirs |
| R19 | Moderate | `planResolve` on an approved plan leaves the parent approved |
| R20 | Minor | Glob dialect (`*` spans `/`) and keep-both suffix style are undocumented |

P5 must not begin against this tree until R14–R17 are closed. This
section is a review record, not a status claim by the implementer; the
"Completion statement" below is left as written and should be re-read
against it.

## R14–R20 — the P4 review pass

All seven addressed. Each was reproduced first, through the real
services against a disposable database and temporary directories, and
each reproduction is now a regression asserting the corrected behavior.
Full per-finding responses are in the spec's §13.1 appendix; what
follows is what a reader of this report needs to know.

**R14 — review-required revisions now block approval.** The plan carries
the evidence (`preset_review_json`, surfaced as `presetReviewRequired`),
`_assert_approvable` refuses before every other check, and the message
names the items and the way through: pin a corrected revision. Nothing
clears it on the user's behalf. Worth noting that the preflight *passes*
in this case — the world is fine, the preset is not — which is why the
regression asserts that too.

**R15 — preset exclusions are applied.** Excluded entries get
`action = exclude`, `matched_rule = "exclusion:<id>"`, and a reason
quoting the rule's own words; `excluded_by_user` stays 0 and a new
`rule_exclusion_count` keeps the two origins apart per §7.3.

The cause turned out to be upstream of where the finding pointed:
`_effective_content` rebuilt preset content from the fallback template
alone whenever a revision had no rules or groups, discarding the
exclusions *and* the review evidence on the way — so the exclusion-only
preset, the one most likely to exist in practice, was exactly where the
field disappeared. Excluding a directory now also excludes its
descendants; copying the contents of a folder the plan says it will skip
is incoherent, and the files would land under a parent the plan never
said it would create.

**R16 — no component of a planned destination path may be a symlink.**
This is wider than the finding asked, and had to be. Fixing only the
planned `dir` entry would have left the reproduced case open, because
R18's implied-directory rule means the symlinked parent has no plan entry
at all. The planner and preflight both walk the ancestor chain with
`lstat` — `is_dir()` follows links — each with a per-directory cache, so
a plan with a hundred thousand files pays for the depth of the tree
rather than its size. Where the link points is not the question: one
inside the destination root blocks too. An ordinary existing directory
still merges, and that is covered, so the fix cannot quietly turn re-use
of a destination into a blocker.

**R17 — a group's collision is resolved at its root.** Two fixes. The
group's own root directory is now a member of its group rather than
falling through to the fallback. And groups are allocated first, as whole
subtrees: under `keep_both` the entire group moves to a suffixed root
with every internal path unchanged; under any other policy the entire
group blocks. No member is ever suffixed — the internal names are
precisely what "keep together" protects. The relocation is recorded on
the group root entry, and `group_id` is on every plan entry so review can
show the containment. Group destinations are now restricted to
`{source_label}`, `{relative_dir}` and `{filename}` at save time, per the
examples' §4.

**R18 — the examples were right; the code was changed to match.** The
category preset routes `Video/{source_label}/{relative_dir}/{filename}`
and the same shape for the other four categories, with no date token in
either starter preset. A source directory holding entries this plan
copies gets no entry of its own — its contents create it — while a
genuinely empty directory keeps its entry and is preserved. The
end-to-end test's entry count went from 5 to 3 and now asserts the reason
rather than the number.

**R19 — resolving a plan invalidates it.** The parent goes
`invalidated`, its `approved_fingerprint` is cleared (leaving it set
would let a later reader conclude the plan was approved in the shape it
now has), and `superseded_by` records the successor. The invalidation
happens after the successor exists rather than in one transaction with
it: the consequence is the safe one, since a failed rebuild leaves the
reviewed plan exactly as it was.

**R20 — documented and pinned.** The glob dialect is written out in spec
§6.1 and in `path_glob_matches`, with `TestGlobDialect` pinning all six
behaviors. The keep-both suffix was reconciled in favor of the
implementation — `name (n).ext` from 2 — and the examples updated to
match, because that document explicitly left the punctuation open and the
parenthesised form does not collide with filenames legitimately ending in
`-1`.

### Two defects found while fixing these, neither filed

- `tests/test_presets.py` used `{filename}{ext}` in every fixture.
  `{filename}` is the complete basename per §6.2, so those templates
  rendered `a.mov.mov`. Nothing asserted a rendered result, so it had
  gone unnoticed. Fixture-only; corrected, and the examples' §2 table is
  now checked verbatim.
- `resolve` accepted a plan that had already been superseded, which would
  have produced two sibling plans each holding half of one review. It now
  refuses and names the successor.

### How R17 and R18 interact

They pull in opposite directions on the same entries, so the resolution
is stated in the spec (§6.2, §6.3) rather than left implicit: directories
route group-aware (R17), and a directory whose contents this plan writes
is then implied by them and gets no entry (R18) — **except** a relocated
group root, which is retained because it is where the relocation decision
is recorded.

### Schema

Migration 004 amended in place again: `transfer_plans` gained
`preset_review_json`, `rule_exclusion_count` and `superseded_by`;
`transfer_plan_entries` gained `group_id`. All four are registered in
`_AMENDED_V4_COLUMNS`, so a development database already stamped v4 fails
`assert_v4_shape` with one actionable error. See the next section — the
same instruction applies: rebuild disposable test databases, preserve or
explicitly migrate anything holding useful records.

### Evidence

976 Python tests (931 before this pass), Ruff check and format clean over
141 files, mypy clean over 80 source files; desktop typecheck, lint, 259
Vitest tests and build clean.

**No stress runs were made this pass**, per the standing instruction.
Nothing in it bears on R13 either way; that gate is exactly where it was.

## Development-schema incompatibility (migration 004)

Migration 004 was amended in place during this pass. It has never been
committed or shipped, so **no released or user database can carry the
superseded shape** — but uncommitted is not unapplied: the earlier round of
tests applied the first revision of it, so **development and test databases
do carry it**.

Why it does not self-correct: the DDL is `CREATE TABLE IF NOT EXISTS`, and
the runner keys migrations by version number, so a database already stamped
`schema_version = 4` skips 004 entirely and keeps the old columns forever.
Left alone that surfaces as `no such column: review_json` somewhere deep in a
service, far from the cause.

Guard: `004_destination_presets.assert_v4_shape`, called from
`ApplicationService.bootstrap` via `_assert_schema_shape`, raises
`IncompatibleDevelopmentSchemaError` at startup naming every missing column
across `source_inventories`, `organization_profile_revisions`,
`transfer_plans`, and `transfer_plan_entries`.

Recovery, per reviewer direction:

- **Disposable test/scratch databases:** delete and recreate. The suite
  builds its own per-test databases, so nothing in `tests/` is affected.
- **Any database holding records worth keeping:** do **not** delete it.
  Export the records first, or write a follow-up migration (005) that adds
  the missing columns. No automatic destructive path is provided and none
  should be added.

The columns the guard checks are listed in `_AMENDED_V4_COLUMNS` in the
migration, which is the authoritative list.

## Session log — 2026-09-13 (commit series landed; P5 begins)

Step 0 of the 2026-09-13 handoff: the 47-file working tree (all P2–P4
work and R01–R20 responses) is committed as the eight-commit series in
"Committed vs working tree", every boundary verified green in a detached
worktree as recorded there. Validation re-run on the final tree by this
session, output read directly: `.venv/bin/python -m pytest` **976 passed**,
`.venv/bin/ruff check .` all checks passed, `.venv/bin/ruff format --check .`
141 files already formatted, `.venv/bin/mypy src` success (80 source
files), desktop `npm run typecheck`/`lint`/`test` (**259 passed**)/`build`
all clean. R13 did not fire in any of this session's runs (one full-suite
run per boundary plus the final-tree run above); the gate remains open
exactly as before — no closure is claimed.

One incidental observation from the boundary runs, recorded for the R13
file and not treated as progress on it: the *old* `test_sources.py`
(baseline `9d0d460` through boundary `867bf05`) still carries the
`chmod(0o000)` restore gap fixed in `77e470f`, and its runs leave
undeletable pytest garbage directories with `Directory not empty`
warnings — the same environmental residue the R13 investigation
artificially recreated without reproducing the failure.

## Completion statement

**Implemented** (spec §1.1) for P0, P1, P2, P3, and P4 — meaning the phased
changes and their automated acceptance tests pass, and that R01–R12 and
R14–R20 are addressed with regressions. That is explicitly not
integration sign-off, which is the reviewer's to give after inspecting
this tree and rerunning the checks; R14–R20 in particular are
"implementer addressed; reviewer verification pending". **P0–P3 are not
signed off as a completed foundation** while R13 remains open: an intermittent failure
nobody has explained is not a green baseline, whatever a given run
prints. Not pilot-ready and not
production-validated: no packaged artifact was built, no desktop UI consumes
the new surface, and the §12.2 real-storage matrix is unrun. P3's identity
work is validated against captured platform output and one live read-only
check on a single macOS machine — which is evidence that the code works, not
evidence that the configuration is supported.
