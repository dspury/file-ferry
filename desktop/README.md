# file-ferry desktop

Electron desktop shell for file-ferry vNext: the security boundary,
the IPC contract, the sidecar supervisor, and the working screens
(Home, Ingest, Organize, Projects, Activity, Asset detail, Settings,
Onboarding) backed by the Python application services under
`src/file_ferry/application/`.

The desktop **Organize** flow's saved-destination and preset work is
being rebuilt per
[`docs/DESTINATION-PRESETS-PRODUCTION-SPEC.md`](../docs/DESTINATION-PRESETS-PRODUCTION-SPEC.md);
until that lands, its move/link actions are disabled and copies are
review-first. Treat that document, not this README, as the source of
truth for what has actually shipped.

See:

- `docs/adr/0001-desktop-shell-architecture.md` — why Electron
- `docs/adr/0002-ipc-protocol-stdio-json-rpc.md` — the wire format
- `docs/adr/0005-application-service-modules.md` — the Python side

## Layout

```
desktop/
├── electron/             main process, preload, sidecar supervisor
├── renderer/             React + TypeScript screens (Home/Ingest/Organize/…)
├── shared/               IPC protocol types (TS + matched by Python pydantic)
├── tests/                vitest contract + supervision tests
├── build/                electron-builder config + macOS entitlements
├── tsconfig*.json        project references for shared / electron / renderer
├── vite.config.ts        renderer build
├── vitest.config.ts      test runner
└── package.json          pinned dependency surface
```

## Development

Requires **Node 22+**. The floor is set by the anti-slop lint: oxlint loads
its plugin as a `.ts` file, which relies on Node's TypeScript
type-stripping, and Node 20 cannot import `.ts` at all. (This is the
toolchain requirement — unrelated to the Node that Electron bundles.)

```bash
npm install
npm run typecheck
npm test
npm run build
```

`npm run dev` runs the shared / electron / vite watcher together. The
development sidecar is launched by `electron/main.ts` as
`python -m file_ferry.service` against the workspace at `src/`.

## Build

```bash
npm run build:sidecar  # freeze the Python sidecar (needs PyInstaller in .venv)
npm run package:mac    # macOS DMG (arm64 + x64)
```

`package:*` runs `build:sidecar` first, so the frozen sidecar is always
present before electron-builder packages the app.

The packaged sidecar lives at `release/{app}/ferry.app/
Contents/Resources/sidecar/{arch}/ferry-service` and is supervised
by `electron/main.ts` at runtime.

## Sidecar freeze

`scripts/build-sidecar.sh` freezes the Python sidecar with PyInstaller
into `desktop/sidecar/{arch}/ferry-service` (a single onefile
executable). It requires the package installed in `.venv`
(`pip install -e .`) plus PyInstaller (`pip install pyinstaller`). The
spec (`scripts/sidecar.spec`) bundles the migration submodules so the
frozen app can discover them (see `persistence/runner.py`'s frozen
discovery fallback). FFmpeg/ffprobe/Resolve are NOT bundled — they
remain detected at runtime per the dependency policy.

Verify a frozen build:

```bash
echo '{"jsonrpc":"2.0","v":1,"kind":"request","id":"x","method":"app.getCapabilities","params":{}}' \
  | ./desktop/sidecar/arm64/ferry-service --once --db /tmp/x.db
```

## What is and is NOT implemented

- The screens listed above exist and drive the vNext application
  services over the IPC bridge.
- The saved-destination / organization-preset workflow from the
  destination-presets spec is in progress; see that spec's execution
  report for per-phase status.
- Live DaVinci Resolve project creation is NOT implemented — the
  Resolve handoff produces an import manifest, per plan §7.4.

## Security

The renderer has no node access, no filesystem access, no database
access. Its only window onto the host is the `window.ferry`
object exposed by `electron/preload.ts`. The schema is validated on
both sides of the IPC bridge. See `electron/security.ts` for the
frozen security configuration.
