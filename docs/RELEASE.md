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
2. Stamps release provenance (version, git commit, build time, arch) into
   `desktop/shared/release.ts` via `scripts/stamp-release.js`. The runtime
   surfaces it through `app.diagnostics`, so a diagnostic report identifies
   the exact build.
3. Builds the renderer/main/preload.
4. Packages with electron-builder (macOS DMG by default; `PLATFORM=win` /
   `PLATFORM=linux` for the others).

## Validate a packaged build

```bash
scripts/verify-packaged.sh release/mac-arm64/ferry.app
```

`scripts/verify-packaged.sh` asserts:
- the frozen sidecar exists at `Contents/Resources/sidecar/{arch}/`
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
app. See `docs/DEVELOPMENT.md` for the environment.

## Release gates (plan §11.3)

Do not call the app stable until all are true:

- Full automated matrix green on the supported macOS architectures
  (pytest, desktop typecheck/lint/tests/build, gitleaks).
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
| Sidecar frozen binary (packaged) | `Contents/Resources/sidecar/{arch}/ferry-service` |

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
