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

    #120  ->  A0  ->  B1  ->  B2  ->  BRAND(§6 decision)  ->  B3  ->  A

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

**The §6 decision is made: migrate** (operator, 2026-09-14). The token
migration is fully specified — §3a, §6a and §6b of the style guide cover every
colour token in `styles.css`, contrast-checked, with no guesswork left.

B3 is now gated only on: the token migration having landed, and #122 render
tests existing.

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

**This has landed.** `55f5652 feat(brand): add file-ferry logo, icons, and
style guide` is on `branding/file-ferry-assets`, carrying
`docs/BRAND-STYLE-GUIDE.md` and five masters under `assets/brand/`. That branch
changes **no code** by design; turning it into product theme is this pass's job.

Read `docs/BRAND-STYLE-GUIDE.md` in full before touching tokens. Summary of
what constrains the build:

### The palette, and the decision it forces

| Token | Hex | Role |
| --- | --- | --- |
| `ink` | `#0E1219` | app background |
| `ink-raise` | `#171C26` | surfaces, cards |
| `bone` | `#F0ECE3` | primary text |
| `ferry` | `#7AA6C8` | lead accent |
| `steel` | `#33475E` | secondary / cargo bars |
| `mist` | `#D4DEE7` | highlights, dividers |

The guide's §6 is an explicit **open decision**: the brand contains no orange,
while the desktop leads with `--c-accent: #ff6a2c` on `--c-bg: #14100e` and the
TUI `ferry-studio` theme leads with `#ff7a45`. The guide proposes migrating
primary/accent to the `ferry`/`steel` family on `ink`, keeping bone text and the
existing ok/warn/danger ramps.

**That decision must be made before B3 starts.** It is a theme migration across
33 `--c-*` tokens plus 12 `--state-*`, not a swap of one accent.

### Contrast — checked, with one finding

Computed against the proposed backgrounds (WCAG 2.1: 4.5:1 normal text,
3.0:1 large text and UI components):

| on `ink #0E1219` | ratio | verdict |
| --- | --- | --- |
| bone `#F0ECE3` | 15.91:1 | AA text |
| mist `#D4DEE7` | 13.76:1 | AA text |
| ferry `#7AA6C8` | 7.25:1 | AA text |
| **steel `#33475E`** | **1.97:1** | **fails at every level** |

Same ordering on `ink-raise #171C26` (bone 14.48, mist 12.52, ferry 6.60,
steel 1.79).

Two consequences:

- **`steel` is decoration only.** Never text, never a control boundary that
  carries meaning, never a focus ring. That matches the role the guide gives it
  ("cargo bars, dark end"), but it must not drift into UI use during B3.
- **The migration improves accent contrast.** Ferry blue on ink is 7.25:1
  against the current orange-on-coal 6.62:1. This is not a trade-off against
  accessibility; it is an improvement.

### Verified claims

- §4's typography claim is correct — the shell already ships
  `@fontsource-variable/archivo` (^5.3.0) and `@fontsource/ibm-plex-mono`
  (^5.3.0), so no new font dependency is needed.
- The palette is **sampled from rasters and self-described as approximate**.
  Confirm exact values against `assets/brand/file-ferry-icon.ai` before
  hard-coding tokens, as the guide itself instructs.

### Still to fix during this pass

- **Issue #101 — every `--fs-*` is absolute `px`** (`--fs-2xs: 10px` through
  `--fs-2xl: 26px`), so OS text-only scaling does nothing. Convert the type
  scale to `rem` while re-valuing it. Nearly free now, expensive later.
- **Do not introduce a second token system.** Re-value the existing 80 custom
  properties in `styles.css`. Two systems disagreeing about a colour is the
  cross-surface divergence class this codebase has repeatedly been bitten by.

### Asset handling

- `ferry-logo-black.svg` carries no fill attributes and recolors via a single
  CSS `fill` — that is its purpose; do not bake colours into copies.
- `file-ferry-icon-gen.png` has a **baked light-grey surround**; do not use it
  in-app. Export a clean squircle from the `.ai` master.
- `file-ferry-icon-macOS-v1.png` is the mac packaging candidate. Wiring it in is
  explicitly *not* done on the branding branch — it belongs to **Stage A3**,
  since `desktop/build/` is already `buildResources` in
  `electron-builder.yml`.
- The `.ai` master is 6.7 MB and the gen PNGs are 2.6-2.8 MB. Keep large masters
  out of anything the app bundles; ship only derived, sized exports.

### Where it sits

Between **B2** and **B3**. B3 builds seven or eight new screens; building them
against tokens that are about to be re-valued means building them twice. **Do
not start B3 before the §6 decision is made and the tokens are migrated.**

B1 and B2 touch no presentation and are unaffected, so they can proceed in
parallel with the §6 call.

### Acceptance

- §6 decided and recorded, with the TUI theme's fate stated either way
- One token system; no duplicate or shadow set of values
- Exact hex values confirmed against the `.ai` master, not the raster samples
- `--fs-*` is relative, and OS text scaling visibly changes rendered text
- `steel` appears in no text or meaningful-boundary role
- Existing screens still render correctly — the reskin is not regressed
- Desktop suite green, and #122's render tests exist (see below)

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
