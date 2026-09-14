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

Execute in this order:

    #120  ->  A0  ->  B1  ->  B2  ->  BRAND  ->  B3  ->  A

The operator wants the **scoped build completed before packaging**, so full
packaging (A) moves to the end and the app is packaged once, with everything in
it. `A0` is a single cheap freeze smoke test kept near the front as insurance --
see "Why A moved, and what A0 is" below.

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

**Stage B is the agreed goal**, and full packaging happens once, at the end,
with the whole build in it.

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

## Stage A — package the completed build (runs LAST)

Everything below runs once, after B3 and BRAND are done. `A0` (the freeze smoke
test) has already run near the front; `A2` re-runs the same freeze against the
finished tree.

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

**Gated on BRAND landing** — see that section. Building these against tokens
that are about to be re-valued means building them twice.

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

## Why A moved, and what A0 is

Packaging-first would normally be the safer order: the PyInstaller freeze is
where a working source tree quietly stops being a working binary, and finding
that after all of B is expensive. Two facts specific to this repo make the
deferral acceptable:

1. **The migration-bundling trap is already solved.** `scripts/sidecar.spec`
   globs `NNN_*.py` at build time into `hiddenimports`, and
   `persistence/runner.py::discover_migrations` has an explicit frozen-bundle
   fallback for when `pkg.__path__` is not a real directory. Verified: all five
   migrations, `005_transfer_execution` included, are picked up. The spec even
   carries a comment about the past incident where a frozen build "knew about
   two migrations, computed `target 2`, and refused to open any".
2. **P2-P5 added no new third-party dependency.** `pyproject.toml` still lists
   exactly click, pydantic, rich, textual, tomlkit, xxhash. The transfer runner
   is stdlib-only (`hashlib`, `json`, `os`, `uuid`, `datetime`). New imports are
   the usual cause of a freeze that succeeds and then fails at runtime, and
   there are none.

So the freeze risk is low but not zero. **A0** buys down what remains, cheaply:

### A0. Freeze smoke test (do this early, once)

    scripts/build-sidecar.sh arm64
    desktop/sidecar/arm64/ferry-service --version

Then run the frozen binary against a scratch database and confirm it migrates
to **schema 5**. Do **not** package the app, sign anything, or touch
`electron-builder.yml` -- this is only asking "does the current tree still
freeze and still migrate".

**Acceptance:** the frozen sidecar reports the current version and creates a
v5 database. If it fails, stop and fix it before starting B -- that is the one
failure mode this ordering is exposed to.

**Add A0 to the definition of done for any B task that adds a Python import.**
Re-running it is under a minute and it is the whole cost of the reordering.

---

## BRAND — branding / style guide package

The operator is preparing a branding and style-guide package on a separate
branch. **It is not on the remote yet**, so this section states the integration
contract rather than the content; fill in specifics when the branch lands.

### Where it sits

Between **B2** and **B3**, and that position is deliberate: B3 builds seven or
eight new screens, and building them against tokens that are about to be
replaced means building them twice. **Do not start B3 before the branding
package has landed on `main`.**

If the branding branch is delayed, B1 and B2 are unaffected -- neither touches
presentation -- so continue with those and hold B3.

### What it lands on

`desktop/renderer/src/styles.css` already carries **80 CSS custom properties**
in a coherent scheme, from the CinePrompt reskin (`c774d36`, reviewed in
`docs/design/cineprompt-reskin-review.md`):

| Family | Count | What |
| --- | --- | --- |
| `--c-*` | 33 | colour |
| `--state-*` | 12 | job/entity state colours |
| `--sp-*` | 8 | spacing, `4px`..`44px` |
| `--fs-*` | 7 | font size, `10px`..`26px` |
| `--radius-*` | 4 | corner radii |
| `--tr-*` | 3 | transitions |
| other | 13 | shadow, scrim, nav, header, glow, control, fills, families |

This is a real system, not ad-hoc values. The branding package should **extend
or re-value these tokens**, not introduce a second parallel system beside them
-- two token systems disagreeing about a colour is precisely the cross-surface
divergence class this codebase has been bitten by before.

### Two things the branding pass should fix while it is in there

- **Issue #101 -- every `--fs-*` is an absolute `px`**, so OS text-only scaling
  has no effect. Confirmed: `--fs-2xs: 10px` through `--fs-2xl: 26px`. Convert
  the type scale to `rem` (or equivalent) as part of re-valuing it. Doing this
  during a branding pass is nearly free; doing it afterwards means re-touching
  every screen.
- **Contrast.** Re-valuing colour tokens can silently break WCAG contrast.
  Check the new palette against the text/background pairings before B3 consumes
  it, not after. Issue #95 (no screen-reader pass) and #148 (Windows-only a11y
  verification) are related open a11y work.

### Acceptance

- One token system; no duplicate or shadow set of values
- `--fs-*` scale is relative, and OS text scaling visibly changes rendered text
- Contrast checked for the text/background pairings the new palette introduces
- Existing screens still render correctly -- the reskin is not regressed
- The desktop suite stays green, and **#122's render tests exist by now** (see
  below), or the check is honestly recorded as "by eye only"

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
tests at all. Issues #97 and #110 were both found by hand.

This matters more under the new ordering than the old one. B3 now builds seven
or eight screens *and* consumes a re-valued token system, with full packaging
deferred to the very end — so the window between "UI regression introduced" and
"anyone launches the app" is at its widest. Add jsdom + render tests **before**
B3, not alongside it.

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
