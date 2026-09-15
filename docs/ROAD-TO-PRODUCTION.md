# Road to production

What is left between `main` and a production-validated ferry, in order.
Written so a fresh session can pick it up without re-deriving anything.

**Baseline:** `main` @ `bd0e77f`. **Status:** implemented, not pilot-ready,
not production-validated — in the spec's own terms (§13.6).

---

## Where things actually stand

The phase table in `DESTINATION-PRESETS-EXECUTION-REPORT.md` is stale for
P6 and P7. Corrected:

| Phase | Real status |
| --- | --- |
| P0 cleanup/baseline | **Not signed off** — R13 open |
| P1 safety regressions | Tests pass; integration sign-off pending |
| P2 persistence | Tests pass; integration sign-off pending |
| P3 volume identity | Tests pass; integration sign-off pending (macOS/Linux) |
| P4 rule engine / planner | Tests pass; integration sign-off pending |
| P5 verified copy runner | Tests pass; integration sign-off pending |
| P6 desktop flow / CLI parity | **Landed** — B1 (#158), B2 (#161), B3 (#164) |
| P7 packaging / pilot / real storage | **In progress** — Stage A only |
| P8 final review handoff | NOT RUN |

The engine is complete and drivable from both the CLI and the UI. What
remains is almost entirely *evidence*, not code — plus the UI work below.

---

## 0. UI design — open, and ahead of everything else

The operator's read after driving the app: the colour scheme holds up,
the design needs a thorough rethink. **A dedicated UI conversation is
happening separately.**

- `docs/UI-REVISION-SPEC.md` holds the standing rules and the itemised
  revisions (`SR-1`…, `R-1`, `R-2`).
- That spec is the input to the restyling pass, and it will grow.

Everything below assumes the UI settles first. Packaging a shell that is
about to be redesigned means packaging twice — the same argument that put
the brand migration before B3.

**Exception:** Stage A (§1) touches build configuration, not the shell,
so it can finish in parallel.

---

## 1. Stage A — a packaged macOS app

In flight. Full detail in `docs/PACKAGING-HANDOFF.md`.

- **A1** unsigned local build path — `notarize: true` and
  `hardenedRuntime: true` block a build with no Apple credentials
- **A2** refreeze the sidecar — the current binary predates B1/B2/B3
- **A3** app icon — `assets/brand/file-ferry-icon-macOS-v1.png` to
  `desktop/build/icon.png` (confirmed final, not a candidate)
- **A4** produce and verify the bundle by booting it

**Exit:** a double-clickable `ferry.app` that starts its own frozen
sidecar, migrates to schema 5, and drives a transfer end to end.

---

## 2. §12.1 — disposable local pilot

The first real-data run. Not the storage matrix; a controlled rehearsal.

Requires, per spec:

- independent source and destination directories, isolated app data
- **mixed real files** — "not only tiny text renamed `.mov`": actual
  media, documents, archives, nested bundles, large files, empty folders,
  overlapping filenames
- known hashes going in
- **independent verification** — a separate checksum walk, not Ferry's own
  status
- every original accounted for as copied, verified-identical, explicitly
  excluded, or failed
- the **packaged** app and the CLI exercised against the same contracts
- proof that general transfer needs no FFmpeg
- provenance checked against the packaged release, not a source checkout

**Exit:** a run where Ferry's account of what happened matches an
independent checksum walk, file for file.

---

## 3. §12.2 — real storage matrix

The gate for a macOS production claim, and the biggest unknown. Entirely
`NOT RUN`. Everything verified so far is injected failures against a local
filesystem with byte-sized fixtures.

Required:

- external local drive → a separate local destination volume
- external local drive → an already-mounted network share
- a populated destination with overlaps, and two sequential source drives
- **≥10,001 entries and at least one ≥10 GiB file**
- **a ≥2-hour sustained transfer** (or a full representative drive
  offload), recording throughput, memory behaviour, DB/job state, and
  receipt integrity
- controlled cancellation, app/sidecar restart, and network
  disconnect/reconnect on disposable targets

> "Simulated adapters do not satisfy the real interruption gate."
> "Do not manufacture confidence from repeated tiny-file tests."

Record: OS, commit/package provenance, source and destination
filesystems, mount protocol, counts and bytes, duration, peak memory,
observed issues, independent hash comparison. Keep private paths out of
committed artifacts.

Also required separately: **100,000-entry synthetic planning**, measured
on its own, to expose memory and IPC growth.

**This is where the engine meets reality.** Throughput, memory under
100k entries, and interruption semantics on a live network mount are all
unmeasured. It is the step most likely to send work back to the engine,
which is why it should not be left until last.

**If hardware or permission is unavailable:** mark the exact gate
`NOT RUN`, provide a reproducible procedure, finish everything else, and
**do not** mark P7 production-validated.

---

## 4. §12.3 — operational documentation

Update the root and desktop READMEs, release instructions, and CLI/TUI
parity docs to final behaviour. Must cover: preset examples, supported
tokens and date semantics, destination recognition limits, recovery
steps, metadata limitations, exclusion behaviour, conflict policies, and
how to inspect and export receipts.

One distinction the spec calls out explicitly: **copies verified ≠ storage
redundancy ≠ backup guarantees.** Say so plainly.

---

## 5. Signing and notarization

Out of scope for the pilot; required for any real release.

- Needs an Apple Developer ID and notarization credentials in the
  environment. `electron-builder.yml` is already configured for it
  (`hardenedRuntime`, `notarize: true`, entitlements present).
- Per `docs/RELEASE.md`: an unsigned local build is a development
  artifact. **An unsigned local pilot is not a public stable release.**
- Auto-update stays disabled until update signing, rollback, and release
  verification exist.

---

## 6. §13 — final handoff

P8. The implementation agent must provide:

1. Execution report with P0–P8 and A01–A26 statuses, each linked to
   evidence
2. Files changed, architecture decisions, migration behaviour, explicit
   deviations
3. Exact validation commands and results — **including failed and flaky
   runs**
4. Fresh-user reproduction: save destination → create/import preset →
   inspect sources → review plan → execute → inspect receipt →
   reconnect/resume
5. Packaged artifact location and provenance; declared support boundary;
   unperformed gates named
6. Remaining risks, and a clear implemented / pilot-ready /
   production-validated statement

> "Do not publish, merge, upload user data, or perform the user's actual
> migration merely because implementation is complete."

---

## Standing blockers

**R13** — an unexplained intermittent SQLite backup failure. P0 has never
been signed off because of it. It has not fired in many consecutive runs,
which is **not** the same as being fixed. An intermittent nobody has
explained is not a green baseline.

**Acceptance coverage** — A09–A11, A15–A16, A21–A23 pass against injected
failures on a local filesystem. A01–A08, A12–A14, A17–A20, A24–A26 have
service- or planner-level coverage. None of it is hardware-validated;
that is §12.2.

---

## Open issues, and whether they gate

| Issue | Gates production? |
| --- | --- |
| #123 unpackaged Electron cannot load the built renderer | No — dev-mode only; packaged path differs |
| #101 absolute px type scale defeats text scaling | **Closed by #160** — verify and close the issue |
| #95 no screen-reader pass (macOS/VoiceOver) | Should gate a release; a11y is unverified |
| #148 Windows-only a11y verification | No — Windows is honestly unsupported |
| #138 `desktop/package.json` has no `"type": "module"` | No — a vite 8 warning |
| #121 dependabot grouping produces unmergeable PRs | No — process, not product |
| #149/#150/#151 typescript 7, eslint 10 | No — blocked on upstream peer deps |

---

## Shortest honest path

1. Settle the UI (separate conversation) → `UI-REVISION-SPEC.md`
2. Finish Stage A → a bundle that boots
3. §12.1 pilot on real mixed files, independently verified
4. §12.2 on real hardware — **do this before polishing anything else**,
   because it is the step that can invalidate the engine
5. §12.3 docs, then §13 handoff
6. Signing only when a real release is actually wanted

Steps 1–3 are work. Step 4 is evidence that cannot be shortcut, faked, or
inferred from green tests.
