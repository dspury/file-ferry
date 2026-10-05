# Release — packaged build, signing, and operational policy (Package 9)

This document captures the packaged-release and operational-hardening
decisions for the desktop application (plan §10 Pkg9, §11.3).

## Build a release

```bash
# freeze the sidecar + stamp provenance + build + package
ARCH=arm64 PLATFORM=mac scripts/package-release.sh
```

`scripts/package-release.sh`:
1. Freezes the Python sidecar into `desktop/sidecar/{arch}/ferry-service`
   (PyInstaller onefile) — the same `build:sidecar` used by `package:*`.
2. Checks that **every** arch `build/electron-builder.yml` declares has a
   usable sidecar of that architecture (`node scripts/check-sidecars.ts`).
3. Stamps release provenance (version, git commit, build time, arch) into
   `desktop/shared/release.ts` via `scripts/stamp-release.js`. The runtime
   surfaces it through `app.diagnostics`, so a diagnostic report identifies
   the exact build.
4. Builds the renderer/main/preload.
5. Packages with electron-builder (macOS DMG by default; `PLATFORM=win` /
   `PLATFORM=linux` for the others).

## The sidecar guard

`scripts/check-sidecars.ts` runs on every packaging path and **fails the
build** when a declared arch has no usable sidecar. It is not optional, and it
exists because the alternative is silent:

`extraResources.from: 'sidecar/${arch}'` does not fail when that directory is
missing. electron-builder logs one informational line and exits 0:

```
• file source doesn't exist  from=.../desktop/sidecar/x64
=== PACKAGE EXIT 0 ===
```

The bundle it produces has no `Contents/Resources/sidecar/` at all, and
`electron/sidecar-command.ts` throws `sidecar executable not found in packaged
resources` on first launch. It installs, it opens, it is dead. Reproduced
2026-10-05; an engine-less `ferry-0.0.0.dmg` (x64) had already been produced
this way on 2026-09-18.

The guard also reads the Mach-O header and rejects a sidecar frozen for the
wrong architecture, which is the failure `ARCH=x64` used to produce: the stamp
recorded x64 while `build:sidecar` defaulted to `$(uname -m)`. `ARCH` is now
threaded through, and a build that reports the wrong arch in its own
diagnostics fails instead.

The same "declared but never built" class of defect is why Windows and Linux
were removed as targets in #203. `scripts/verify-packaged.sh` checks the same
property after the fact, on a path you pass by hand; the guard is the
pre-flight half. Run both.

## Validate a packaged build

```bash
scripts/verify-packaged.sh release/mac-arm64/ferry.app
```

`scripts/verify-packaged.sh` asserts:
- the frozen sidecar exists at `Contents/Resources/sidecar/`
  (the resource that must live **outside** `app.asar`),
- the frozen sidecar launches and serves the JSON-RPC protocol
  (`app.getCapabilities` round-trip),
- `app.asar` is present for main/preload/renderer.

The renderer build is unpacked via `asarUnpack: dist/renderer/**` so the
`file://` load path resolves outside the archive (plan §10 Pkg9 step 1).

## Clean-machine / clean-app-data procedure (plan §10 Pkg9 step 3)

Repeatable first-run verification:

```bash
scripts/clean-app-data.sh            # dry run: what would be removed
scripts/clean-app-data.sh --apply    # actually clear app data
```

This removes the legacy config/audit db (`~/.ferry`) and the Electron
userData dir (`~/Library/Application Support/ferry`, where receipts,
logs, and the vNext db live). After it, the next launch is a pristine first
run that exercises fresh migrations from an empty store.

For a true **clean machine** (no build artifacts): clone the repo fresh,
`pip install -e .` into a new venv, `cd desktop && npm ci && npm run build`,
then run the clean-app-data procedure and verify-packaged against the built
app. See the root `README.md` development-setup section for the environment.

## Release gates (plan §11.3)

Do not call the app stable until all are true:

- Full automated matrix green on the supported macOS architectures
  (pytest, desktop typecheck/lint/tests/build, gitleaks).
- `node scripts/check-sidecars.ts` passes: every arch the release config
  declares has a matching frozen sidecar. It runs automatically in
  `package:mac`, `package:mac:local` and `package-release.sh`; a green
  package step implies it, but it is listed because "every declared arch was
  actually built" is exactly the claim a green build has been getting wrong.
- Migration, package, and clean-app-data tests pass from a released prior DB.
- Real-media suite passes on at least two storage configurations.
- A prolonged offload/proxy soak completes with no orphaned jobs, stale
  sidecars, locked database, or incorrect safety state.
- A reviewer can inspect receipts and reproduce the claimed result.
- Security review confirms renderer isolation and no unintended listener or
  privileged IPC surface.
- Signed/notarized package installation and update/rollback policy are proven.

## macOS signing & notarization

`desktop/build/electron-builder.yml` already sets:
- `hardenedRuntime: true`, `gatekeeperAssess: false`
- `entitlements` / `entitlementsInherit`: `build/entitlements.mac.plist`
- `notarize: true`, `dmg.sign: true`

The entitlements allow JIT/unsigned-executable-memory/library-validation
(needed for the Electron runtime) and grant user-selected + Downloads
read-write (for choosing media roots); camera/microphone are explicitly
disabled.

**Operator prerequisite:** signing/notarization require an Apple Developer
ID + notarization credentials in the CI/environment. The config is present;
a real signed/notarized build must be produced and verified (gate list
above) before a stable release. Until then, local builds run unsigned for
development.

## App data locations

| Surface | Location |
| --- | --- |
| Legacy config + audit db | `~/.ferry/` |
| Electron userData (receipts, logs, vNext db) | `~/Library/Application Support/ferry/` (macOS) |
| Diagnostic logs | `~/Library/Application Support/ferry/logs/` |
| Sidecar frozen binary (packaged) | `Contents/Resources/sidecar/ferry-service` |

## Release / update policy (plan §10 Pkg9 step 4)

**Auto-update is disabled.** There is no `publish` block in
`electron-builder.yml` and no updater dependency, so a packaged app never
self-updates. This is deliberate:

> Auto-update must be disabled until update signing, rollback, and release
> verification are proved.

Until then, updates are distributed as signed artifacts and installed
manually, with the provenance stamp in each build's diagnostics identifying
the exact source. When auto-update is later enabled, it must first satisfy:
signed update artifacts, a proven rollback path, and release verification.

## Release provenance

Every packaged build carries `version`, `commit`, `buildTime`, and `arch`
in `desktop/shared/release.ts` (stamped at build time). The runtime prepends
these to the `app.diagnostics` summary, so a diagnostic report from any
installed build identifies exactly what shipped and from which commit.
