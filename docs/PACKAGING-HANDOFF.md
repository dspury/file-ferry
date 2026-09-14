# Work order — packaged macOS app for sample-file testing

**Goal:** a double-clickable `ferry.app` bundling the Electron shell and the
frozen Python sidecar, which the operator can launch and drive against
prepared sample files.

**Audience:** a builder agent working in this repository.

**Baseline:** `main` at `fe132c2`. CI green (8/8). 993 pytest, mypy clean,
ruff clean, desktop format/lint/typecheck/259 tests/build all pass.

---

## Scope decision — made, do not re-litigate

**The operator has chosen Stage A + Stage B: the new transfer engine.** The
packaged app must be able to drive destination -> plan -> preflight -> approve
-> verified transfer -> receipt against real sample files. Stage A still ships
first, because it is cheap and proves the pipeline, but it is not the
destination.

Execute in this order: **A -> #120 -> B1 -> B2 -> B3.**

The reasoning behind that choice is below; it is recorded so the constraint is
understood, not so it can be reopened.

## The fork, and why it mattered

A packaged app built from `main` today presents these screens:

    Activity  AssetDetail  Home  Ingest  Onboarding  Organize  Projects  Settings

There is **no destinations, presets, plan, preflight, or transfer screen**, and
the preload bridge exposes `plan.build` (the *old* intake planner) and
`profile.save` (the *old* profiles) — not `transfer.*`, `destination.*`, or
`inventory.*`.

So the P2–P5 engine — destinations, preset revisions, inventories, plans,
preflight, approval, and the verified transfer runner — **is not reachable from
the UI**. It is reachable only over raw JSON-RPC.

That produces two possible readings of "test on sample files":

| | What the operator can exercise | Work |
| --- | --- | --- |
| **Stage A only** | The legacy offload / organize / proxy flows | Small — the pipeline already works |
| **Stage A + B** | The new destination -> plan -> approve -> transfer -> receipt flow | Substantial — this is P6 |

**Stage A first, then Stage B.** Stage A is cheap, proves the packaging
pipeline against current `main`, and gives the operator something to launch
while Stage B proceeds. Do not skip it in order to start Stage B, and do not
stop at it — Stage B is the agreed goal.

---

## What already works (do not rebuild)

The packaging pipeline exists and has succeeded before —
`desktop/release/mac-arm64/ferry.app` was produced on 2026-08-28, and the frozen
sidecar at `desktop/sidecar/arm64/ferry-service` (17 MB) still runs and responds
to `--help`.

- `desktop/build/electron-builder.yml` — appId, dmg targets for arm64 + x64,
  hardened runtime, entitlements, `asarUnpack` for the renderer,
  `extraResources` copying the sidecar
- `scripts/build-sidecar.sh` + `scripts/sidecar.spec` — PyInstaller freeze
- `desktop/electron/sidecar-command.ts` — resolves
  `resourcesPath/sidecar/ferry-service` when packaged
- PyInstaller 6.22.0 is installed in `.venv`

Both artifacts predate P2–P5 and are stale. They are evidence the path works,
not something to ship.

---

## Stage A — packaged app from current `main`

### A1. Make an unsigned local build possible

`electron-builder.yml` sets `notarize: true` and `hardenedRuntime: true`.
Notarization requires an Apple Developer ID and credentials in the environment;
without them the build will fail or hang.

`docs/RELEASE.md` already states the intent: *"local builds run unsigned for
development."* The config does not yet express it.

Add a local build path that does not sign or notarize — a separate script or
config overlay, **not** by editing the release config's defaults, so the signed
release path stays intact. `CSC_IDENTITY_AUTO_DISCOVERY=false` plus a notarize
override is the usual shape.

**Acceptance:** `npm run package:mac:local` (or equivalent) completes on a
machine with no Apple credentials, and `npm run package:mac` is unchanged.

### A2. Rebuild the sidecar against current `main`

    scripts/build-sidecar.sh arm64

The existing binary predates migration 005 and the transfer runner.

**Acceptance:** `desktop/sidecar/arm64/ferry-service --version` reports the
current version; the binary is newer than `fe132c2`.

### A3. Produce and verify the bundle

**Acceptance — all of these, verified by running, not by inspection:**

1. `ferry.app` launches by double-click from Finder
2. The sidecar starts and is reachable — `app.getStatus` returns, and the
   Environment screen shows a sidecar version that is **not**
   `0.0.0+foundation` (see issue #119's regression)
3. The vNext database migrates to **schema version 5** in
   `~/Library/Application Support/ferry/`, and `transfer_executions`,
   `transfer_execution_items`, `transfer_path_reservations` and
   `transfer_receipts` all exist
4. No unhandled error dialog; `~/Library/Application Support/ferry/logs/` has
   no fatal entries
5. `app.getCapabilities` lists `transfer.start`, `transfer.receipt`,
   `transfer.receiptExport` — proving the packaged sidecar carries P5 even
   though no screen calls it

### A4. Legacy-flow smoke test on real sample files

Drive offload / organize / proxy from the packaged app against the operator's
sample files. Record what worked and what did not. This is the first time this
code meets real files rather than byte-sized fixtures.

---

## Stage B — make the P2–P5 engine reachable (P6)

This is the agreed destination, not an optional extension. Ordered
cheapest-first. **B1 is the highest value per unit of work**: it makes the new
engine drivable against real sample files without building any UI, so the
operator can start testing the real pipeline before B3 lands.

### B1. CLI parity

`ferry --help` currently lists `intake, jobs, log, organize, probe, project,
proxy, receipt, reconcile, resolve, run, source, tui, verify` — none of the new
surface.

Add commands covering: save/list/resolve a destination; save/list a preset
revision; create/inspect an inventory; create/inspect/resolve/approve a plan;
run preflight; start a transfer; read and export a receipt.

**Acceptance:** a scripted end-to-end run — scan -> destination -> preset ->
plan -> preflight -> approve -> transfer -> receipt — completes from the CLI
against real files on two physical volumes, and the receipt's
`actual.committed` matches the file count. `tests/test_transfer_runner_e2e.py`
is the reference for the call sequence.

### B2. Preload bridge + IPC

Extend `desktop/shared/preload-api.ts` and `desktop/electron/preload.ts` with
`destination.*`, `inventory.*`, and `transfer.*`, mirroring the existing
namespaces. The typed contract in `desktop/shared/ipc-methods.ts` is already
complete for all three — it was finished in P5 and needs no changes.

**Acceptance:** `window.ferry.transfer.start` exists in the running app; the
bridge namespace list includes `destination`, `inventory`, `transfer`.

### B3. UI screens

Destination manager, preset editor, inventory/scan view, plan review with the
conflict and exclusion workflow, preflight status, approval, transfer progress,
and receipt view.

**Read `docs/DESTINATION-PRESETS-PRODUCTION-SPEC.md` §8 before starting.** The
server-side gates are already enforced and the UI must not fight them: approval
requires a *current passing* preflight; a plan whose fingerprint moved is
refused; `needs_review` items block approval.

**Acceptance:** the whole flow is drivable from the packaged app with no raw
RPC, and a stale approval is refused in the UI as well as server-side (A08).

---

## Fix regardless of stage

### #120 — mismatched checksum labels (do this first; it is small)

Confirmed live on `main`:

    'xxhash64': OK
    'xxhash':   ValueError: unsupported checksum algorithm: xxhash

`_normalize_checksum_algo` is applied at exactly one call site
(`application/service.py:1199`, `settings.get`). Any other path handed a legacy
`"xxhash"` label raises. For a tool whose value is checksum-verified transfer,
this is a correctness bug, not cosmetic.

### Stale doc — packaged sidecar path

`docs/RELEASE.md` documents `Contents/Resources/sidecar/{arch}/ferry-service`.
The config (`extraResources: to: 'sidecar'`) and the code
(`sidecar-command.ts`) both use `Resources/sidecar/ferry-service`, with **no
arch subdirectory**. The doc is wrong; fix the doc.

### #122 — no desktop render tests (blocks Stage B3 safely)

`vitest` runs with `environment: 'node'` and no DOM, so there are no render
tests at all. Issues #97 and #110 were both found by hand. Starting B3 without
this means UI regressions are invisible. Add jsdom + render tests before or
alongside B3.

---

## Traps — read before starting

**The desktop CI job gates on formatting before anything else.**
`npm run format:check` runs ahead of typecheck, test, and build. A formatting
drift turns the whole job red while nothing downstream is exercised — this is
exactly what kept `main` red from `e7ba274` until `fe132c2`. Run
`format:check` locally before pushing.

**CI never loads Electron.** `ci.yml` sets `ELECTRON_SKIP_BINARY_DOWNLOAD: '1'`,
deliberately — *"The suite never loads Electron (no test imports it)."* A green
`desktop (node22)` check proves the TypeScript types fit and nothing about the
runtime. For packaging work, CI cannot verify your change. Boot the app.

**Green suites have hidden boot-breaking defects in this repo before.** Nine of
them, in one prior instance. Verify by launching the real app, not by reading
test output.

**Branch protection requires a PR and 8 status checks.** It is bypassable by an
admin push; do not rely on that. Open a PR.

**`main` is the only worktree and the only branch.** If you create a worktree,
remove it when done.

**R13 is open** — an unexplained intermittent SQLite backup failure. It has not
fired in recent runs. It is not closed by runs that happen to pass; do not claim
it is.

---

## What this work order does *not* cover

Spec §12.2 — the real-storage matrix — remains `NOT RUN` and is **not** in scope
here. It requires external drives, a network share, at least 10,001 entries, a
file of at least 10 GiB, a sustained transfer of at least two hours, and real
cancellation / restart / network disconnection (the spec explicitly rules out
simulated adapters). A packaged app the operator can drive is a prerequisite for
that campaign, not a substitute for it.

Signing and notarization are likewise out of scope. Per `docs/RELEASE.md`, an
unsigned local build is a development artifact; a stable release requires the
signed and notarized path with its own verification gates.
