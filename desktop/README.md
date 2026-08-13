# media-mate desktop

Electron desktop shell for media-mate vNext. The foundation cut
contains the security boundary, the IPC contract, the sidecar
supervisor, and a minimal renderer — not the actual screens.

See:

- `docs/adr/0001-desktop-shell-architecture.md` — why Electron
- `docs/adr/0002-ipc-protocol-stdio-json-rpc.md` — the wire format
- `docs/adr/0005-application-service-modules.md` — the Python side

## Layout

```
desktop/
├── electron/             main process, preload, sidecar supervisor
├── renderer/             React + TypeScript shell (placeholder)
├── shared/               IPC protocol types (TS + matched by Python pydantic)
├── tests/                vitest contract + supervision tests
├── build/                electron-builder config + macOS entitlements
├── tsconfig*.json        project references for shared / electron / renderer
├── vite.config.ts        renderer build
├── vitest.config.ts      test runner
└── package.json          pinned dependency surface
```

## Development

```bash
npm install
npm run typecheck
npm test
npm run build
```

`npm run dev` runs the shared / electron / vite watcher together. The
development sidecar is launched by `electron/main.ts` as
`python -m media_mate.service` against the workspace at `src/`.

## Build

```bash
npm run build:sidecar  # freeze the Python sidecar (needs PyInstaller in .venv)
npm run package:mac    # macOS DMG (arm64 + x64)
npm run package:win    # Windows NSIS (x64)
npm run package:linux  # Linux AppImage (x64)
```

`package:*` runs `build:sidecar` first, so the frozen sidecar is always
present before electron-builder packages the app.

The packaged sidecar lives at `release/{app}/media-mate-desktop.app/
Contents/Resources/sidecar/{arch}/media-mate-service` and is supervised
by `electron/main.ts` at runtime.

## Sidecar freeze

`scripts/build-sidecar.sh` freezes the Python sidecar with PyInstaller
into `desktop/sidecar/{arch}/media-mate-service` (a single onefile
executable). It requires the package installed in `.venv`
(`pip install -e .`) plus PyInstaller (`pip install pyinstaller`). The
spec (`scripts/sidecar.spec`) bundles the migration submodules so the
frozen app can discover them (see `persistence/runner.py`'s frozen
discovery fallback). FFmpeg/ffprobe/Resolve are NOT bundled — they
remain detected at runtime per the dependency policy.

Verify a frozen build:

```bash
echo '{"jsonrpc":"2.0","v":1,"kind":"request","id":"x","method":"app.getCapabilities","params":{}}' \
  | ./desktop/sidecar/arm64/media-mate-service --once --db /tmp/x.db
```

## What's NOT in this foundation

- The actual screens (Home, Ingest, Organize, Projects, Activity).
  They land in Package 7 of the implementation plan.
- The actual application services (project, source, intake, jobs,
  replicas, assets, receipts). They land in
  `src/media_mate/application/` per ADR-0005.
- The renderer is a single placeholder that calls `app.getStatus`. It
  is a sanity check, not a UI.

## Security

The renderer has no node access, no filesystem access, no database
access. Its only window onto the host is the `window.mediaMate`
object exposed by `electron/preload.ts`. The schema is validated on
both sides of the IPC bridge. See `electron/security.ts` for the
frozen security configuration.
