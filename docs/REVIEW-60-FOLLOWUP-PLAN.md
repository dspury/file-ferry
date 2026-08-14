# PR #60 Review Follow-up — Implementation Plan

Status: PLAN (not yet executed)
Created: 2026-08-14
Scope: Address the findings from the code review of PR #60 (vNext desktop
implementation) and land the follow-up work in the correct order.

---

## 1. Background

PR #60 (`vnext-desktop-implementation` → `main`) shipped all nine work
packages of the vNext desktop build. A code review of the PR surfaced six
inline findings (2 structural/"headline", 1 TypeScript bug, 3 non-blocking)
plus a documentation note.

Two follow-up PRs already address the top three findings:

- **PR #61** — `fix(desktop): distinguish unsolicited request vs response in
  protocol errors` (ternary bug + missing union member).
- **PR #62** — `fix(sidecar): wire ADR-0004 fingerprint comparison + background
  job dispatcher` (the two headline structural items).

Both branch off `vnext-desktop-implementation` (PR #60's head). Neither is
merged yet.

This document maps every finding to its resolution and lays out the remaining
work that is **not** yet covered by #61/#62, plus the correct merge sequence.

---

## 2. Findings → resolution matrix

| # | Finding | Severity | Resolution | Status |
|---|---------|----------|------------|--------|
| 1 | `job.dispatch` missing from IPC catalog → queued jobs never run in the desktop flow | 🔴 Critical | PR #62: `JobDispatcher` daemon thread drains the queued queue; `job.dispatch` / `job.dispatchNext` wired through `wiring.py`, `METHOD_NAMES`, `ipc-methods.ts`, `preload.ts` | ✅ In #62 |
| 2 | ADR-0004 condition (4) hardcoded off — no volume-fingerprint comparison | 🔴 Critical | PR #62: migration `003` adds `intake_sessions.volume_fingerprint_at_scan`; `intake.py` captures at scan, recomputes on evaluate, handles baseline-missing / source-row-missing paths | ✅ In #62 |
| 3 | `'unsolicited_response'` in both ternary branches + missing `'unsolicited_request'` union member | 🐛 TS bug | PR #61: `classifyUnexpectedFrame()` pure helper, union extended, `handleLine` rewired, 3 regression tests | ✅ In #61 |
| 4 | `sidecar:request` IPC handler does not validate the envelope (no `METHOD_NAMES` allowlist cross-check, no per-call protocol-version check, typed `RpcError.code`/`data` dropped) | ⚠️ Non-blocking | **Not yet implemented** — see Phase A, item A1 | ❌ |
| 5 | No automatic dispatcher in the sidecar (jobs stay `queued` unless something calls `dispatch`) | ⚠️ (tied to #1) | PR #62: `JobDispatcher` background task started by `service.bootstrap`, kicked by `job.create` / `job.retry` / `job.resume` | ✅ In #62 |
| 6 | Contract test gap: no invariant `set(METHOD_NAMES) == set(invokable in preload.ts)` | ⚠️ | Partial — PR #62 adds a targeted assertion that `job.dispatch` / `job.dispatchNext` are in `METHOD_NAMES`. The full cross-catalog invariant is **not** added | 🟡 Partial |
| 7 | Plan §16 lists "areas flagged for deeper review" but does not enumerate them in the doc (they live in the diff) | 📝 Doc | **Not done** — see Phase A, item A3 | ❌ |
| 8 | `sidecar.ts:187` spawns the sidecar with the full Electron env (keychain / AWS / 1Password tokens) — flagged for the §16.1 security review | 📝 Note | **Not done** — see Phase A, item A4 (explicit ADR note) | ❌ |

---

## 3. Merge sequence (must be in this order)

PRs #61 and #62 base off `vnext-desktop-implementation` (the head of #60).
Merging #60 to `main` first would strand the follow-ups. All three are
currently `MERGEABLE`.

1. Merge **PR #61** → `vnext-desktop-implementation`
2. Merge **PR #62** → `vnext-desktop-implementation`
3. Execute Phase A (below) on `vnext-desktop-implementation`
4. Merge **PR #60** → `main`

---

## 4. Remaining implementation (Phase A)

Executed on `vnext-desktop-implementation` after #61/#62 are merged.

### A1 — IPC envelope validation (#4)

File: `desktop/electron/main.ts` (`sidecar:request` handler, ~line 171).

- Cross-check the renderer-supplied `method` against an allowlist derived from
  the IPC catalog (`METHOD_NAMES` via `desktop/shared/ipc-methods.ts`). Reject
  unknown methods with a typed error frame instead of forwarding blindly.
- Enforce a per-call protocol-version check against `PROTOCOL_VERSION`
  (today it is only checked on the `ready` event).
- Preserve `RpcError.code` / `RpcError.data` on the renderer promise instead
  of collapsing everything to `new Error(message)`.

Justification: ADR-0002 declares the protocol a security boundary. Even though
the renderer is sandboxed and the Python side pydantically validates params,
the IPC handler should validate the method name and version at the boundary.

### A2 — Cross-catalog contract invariant (#6)

Add a test asserting the two method catalogs stay in sync, so drift like the
`job.dispatch` gap fails CI instead of passing silently.

- `tests/test_service_wiring.py`: assert `set(METHOD_NAMES) ==` the set of
  invokable methods the desktop preload advertises.
- Mirror or complement in `desktop/tests/ipc-contract.test.ts` if the
  server-side test cannot read the preload surface.

### A3 — Plan §16 doc enumeration (#7)

File: `docs/MEDIA-MATE-FULL-APP-IMPLEMENTATION-PLAN.md` §16.2.

The §16.2 section already lists the flagged review areas; confirm it remains
the single source of truth and that any review areas that currently live only
in the diff are moved into the doc (the current §16.2 was written to cover
this, so this is a verification/backfill pass rather than new authoring).

### A4 — Sidecar env-inheritance note (#8)

- Add an explicit note to ADR-0002 that the sidecar inherits the full Electron
  process env (keychain tokens, 1Password CLI session, AWS env, etc.) and that
  env scrubbing is deferred to the §16.1 security review.
- This is a documentation/decision capture, not a behavior change — the
  current single-user desktop design is defensible without scrubbing.

---

## 5. Verification (Phase B)

After A1–A4, rerun the full green set before merging #60 → main:

- **Python:** 534/534 (pytest)
- **Desktop:** 104/104 (vitest)
- **Lint/format/typecheck:** ruff, mypy strict, eslint, prettier, `tsc`
- **Security:** gitleaks scan clean

---

## 6. Operator-owned gates (outside this plan's scope)

From plan §16.1 — require a human + hardware, not a repo change:

- Real macOS signing / notarization (Apple Developer ID + credentials)
- Real-media acceptance suite (§11.2)
- Prolonged offload/proxy soak
- Security review (confirm renderer isolation, no unintended listener /
  privileged IPC surface)
- Signed install + update/rollback proof

---

## 7. Definition of done

- [ ] PR #61 merged into `vnext-desktop-implementation`
- [ ] PR #62 merged into `vnext-desktop-implementation`
- [ ] A1: `sidecar:request` validates method allowlist + version; typed errors preserved
- [ ] A2: cross-catalog invariant test present and passing
- [ ] A3: plan §16.2 fully enumerates flagged review areas
- [ ] A4: ADR-0002 documents sidecar env-inheritance decision
- [ ] Phase B verification green (534 Python / 104 desktop / lint / typecheck / gitleaks)
- [ ] PR #60 merged into `main`
