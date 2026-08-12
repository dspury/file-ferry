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
npm run package:mac    # macOS DMG (arm64 + x64)
npm run package:win    # Windows NSIS (x64)
npm run package:linux  # Linux AppImage (x64)
```

The packaged sidecar lives at `release/{app}/media-mate-desktop.app/
Contents/Resources/sidecar/{arch}/media-mate-service` and is supervised
by `electron/main.ts` at runtime.

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
