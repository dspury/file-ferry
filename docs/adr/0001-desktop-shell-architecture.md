# ADR-0001 — Desktop shell architecture

- **Status:** Accepted
- **Date:** 2026-08-12
- **Supersedes:** v0.2.4 SPEC.md §6 architecture sketch (CLI + TUI only)

## Context

file-ferry v0.2.4 is a Python CLI + Textual TUI. The vNext direction
(`docs/FILE-FERRY-PRODUCT-DIRECTION.md`) calls for a local-first
desktop application for verified card offload, existing-folder
adoption, and project reconciliation. The CLI and TUI remain
first-class interfaces on their existing supported platforms. The
desktop application is the new daily-use surface.

The plan §5.1 lists architectural constraints: the renderer must not
own file mutations; the desktop database writer must be a single
process; the renderer must be sandboxed; an open platform must be
preserved.

We need a desktop shell that:

1. Survives renderer reload and sidecar restart without losing job state.
2. Exposes a narrow, schema-validated IPC bridge to the renderer.
3. Owns the desktop lifecycle (single instance, native dialogs, tray,
   sidecar supervision).
4. Does not freeze us out of Windows or Linux packaging later.
5. Packages the Python sidecar deterministically per architecture.

## Decision

**Electron is the desktop shell.** The renderer is React + TypeScript;
Electron main owns the desktop lifecycle and the Python sidecar; the
Python sidecar (run as `python -m file_ferry.service` in development,
as a frozen platform-matched executable outside `app.asar` in
packaged builds) is the source of media-operation behavior.

**Process boundary:**

```text
React renderer              Electron main                Python sidecar
views and local UI state -> typed IPC bridge ---------> application commands
job/event subscription  <- typed event bridge <--------- durable job events
                                     |
                                     v
                          native dialogs, volume watch,
                          single-instance lock, tray,
                          sidecar supervision, packaging
```

**Security model (hard requirements):**

- `contextIsolation: true`
- `nodeIntegration: false`
- `sandbox: true`
- `webSecurity: true`
- No `webview` tag, no `remote` module, no arbitrary external
  navigation, no `shell.openExternal` from the renderer.
- Renderer never sees a path it did not request via a typed command.
- Native dialogs and volume observation are owned by Electron main,
  exposed only through the schema-validated `contextBridge` API.

**Single-instance lock.** A second launch forwards its request to the
existing process instead of opening a second writer against the
project database.

**Renderer reload and sidecar restart.** A renderer reload may lose
its subscription but cannot lose job state; main replays a current
job snapshot on reconnect. If a sidecar exits, Electron main records
the condition, restarts only when safe, and never marks interrupted
work successful.

**Tauri and a native Swift shell are deferred alternatives, not
parallel implementation targets.** They are not being built; the plan
§8 names Electron as the choice. If Electron proves unsatisfactory
during Package 9 (packaged release), the architecture is small enough
that the sidecar can be reused with a different shell.

## Consequences

Positive:

- React + TS is the most-hired skill in the desktop-renderer space;
  recruiting and library ecosystem are both wider than Tauri or
  native Swift.
- Electron + Node ecosystem gives us cross-platform packaging
  (electron-builder), a stable single-instance lock story, and
  automatic code signing / notarization pipelines.
- The renderer stays narrow enough that a Tauri rewrite is plausible
  without touching the sidecar or the application services.

Negative:

- Electron ships a Chromium runtime (~150 MB per platform). The
  package is bigger than a Tauri build.
- The Electron security model requires discipline; the loadable
  preload surface is a security boundary that must be reviewed.
- We now depend on Node + npm for the desktop build, in addition to
  Python. This is a second dependency surface to maintain.

Neutral:

- The CLI and TUI remain supported on their existing platforms. They
  do not depend on the desktop shell.
- The Python sidecar is a single internal contract; replacing
  Electron with a different shell would not require rewriting the
  sidecar.

## References

- `docs/FILE-FERRY-FULL-APP-IMPLEMENTATION-PLAN.md` §5.1, §5.2, §8
- `docs/FILE-FERRY-PRODUCT-DIRECTION.md` §7, §8
- v0.2.4 `SPEC.md` §6 (existing CLI + TUI architecture, unaffected)
