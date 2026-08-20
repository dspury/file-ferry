# Rename & Cleanup Plan: media-mate → ferry-media

## Overview

Rename the project from `media-mate` to `ferry-media` and make the DaVinci Resolve integration an optional dependency. TUI stays bundled. No feature removal — just cleaner packaging.

---

## Phase 1: Rename

### 1.1 Package identity

| What | Old | New |
|------|-----|-----|
| PyPI name | `media-mate` | `ferry-media` |
| GitHub repo | `dspury/media-mate` | `dspury/ferry-media` |
| Python package | `media_mate` | `ferry_media` |
| CLI command | `media-mate` | `ferry` |
| Import | `from media_mate import ...` | `from ferry_media import ...` |

### 1.2 Files to update

- [ ] `pyproject.toml` — name, version → 0.3.0, scripts entry point
- [ ] `src/media_mate/` → `src/ferry_media/` (rename directory)
- [ ] All internal imports (`from media_mate.X` → `from ferry_media.X`)
- [ ] `README.md` — all references, install instructions, badges, CLI examples
- [ ] `CHANGELOG.md` (if exists) — note the rename
- [ ] CI workflow (`.github/workflows/ci.yml`) — any hardcoded paths or package names
- [ ] Tests — all imports and references
- [ ] `LICENSE` — check if name is referenced
- [ ] Examples (`examples/`) — any scripts or docs referencing the old name

### 1.3 GitHub

- [ ] Create new repo `dspury/ferry-media`
- [ ] Push code to new repo
- [ ] Archive `dspury/media-mate` with redirect notice
- [ ] Update any KB docs pointing to old repo

### 1.4 PyPI

- [ ] Register `ferry-media` on PyPI (first publish)
- [ ] Optionally yank or deprecate `media-mate` if it was ever published

---

## Phase 2: Optional Resolve Dependency

### 2.1 Current state

Resolve is already well-structured:
- `resolve.py` has a **manifest-first** architecture — pure functions (`build_project_manifest`, `write_manifest`) need no Resolve runtime
- The Resolve API adapter (`find_resolve`, `create_resolve_project`) is best-effort and already handles "Resolve not installed" gracefully
- TUI already lazy-imports resolve inside `_run_resolve_step()`
- CLI imports at top level — needs to become lazy

### 2.2 Changes

**pyproject.toml:**
```toml
[project.optional-dependencies]
resolve = []  # No extra deps — Resolve is detected at runtime via DaVinciResolveScript
tui = []      # Textual stays in core deps for now; placeholder if split later
```

Actually — Resolve has no pip dependency. It's detected at runtime. So `optional-dependencies` for resolve is really about documentation and intent, not pip packages. The real change is:

**cli.py:**
- [ ] Move `from media_mate.resolve import create_resolve_project` from top-level to inside `resolve_create()` function
- [ ] Add a helpful error message if resolve module fails to import (shouldn't happen since it's in-package, but good practice)

**tui.py:**
- [ ] Already lazy — no change needed. Just verify the import guard is clean.

**The actual isolation is about making the resolve step skippable and clearly optional in docs/UI, not about removing code.**

### 2.3 Documentation

- [ ] README: mark Resolve as optional ("requires DaVinci Resolve installed separately")
- [ ] CLI help text: note that `--resolve-project` requires DaVinci Resolve
- [ ] TUI: the Resolve checkbox already exists — add tooltip or note that it's optional

---

## Phase 3: Cleanup (while we're in here)

### 3.1 Minor cleanup

- [ ] Version: v0.3.0 (new name, continuous from media-mate)
- [ ] `__init__.py` — update `__version__` and any public API exports
- [ ] Ruff format pass after all renames
- [ ] Ensure all tests pass with new package name

### 3.2 KB updates

- [ ] `lunar-park-kb/projects/open-source-projects/media-mate/README.md` → rename folder + update all refs
- [ ] Issue pipeline assignment table — update repo name
- [ ] Any other KB docs referencing `media-mate`

---

## What stays the same

- All features — probe, organize, proxy, resolve, verify, log, TUI, CLI
- All tests (just import paths change)
- TUI stays bundled (not split out)
- Resolve stays in-package, just documented as optional
- Same repo history (rename, don't fork)

---

## Decisions

- [x] **Version number** — v0.3.0 (continuity from media-mate)
- [x] **GitHub org** — `dspury/ferry-media` (personal)
- [x] **CLI command** — `ferry`
