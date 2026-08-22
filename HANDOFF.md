# Handoff: media-mate → file-ferry Rename

> **Closed — 2026-08-22. Kept as a historical record; do not action it.**
>
> Every task in the brief below has landed. The rename shipped on branch
> `rename/ferry` (PRs #61, #62, #63) and is merged to `main`. The only item
> still open anywhere is **RENAME.md §1.4 (PyPI)**, which is D's to run.
>
> **The paths and repo names in the brief below are stale by design** — they
> describe the world as it was when the work was handed off. Current values:
>
> | | Then (brief below) | Now |
> |---|---|---|
> | Local directory | `~/Lunar-Park/media-mate/` | `~/Lunar-Park/ferry/` |
> | GitHub repo | `dspury/media-mate` | `dspury/file-ferry` |
> | Python package | `media_mate` | `file_ferry` |
> | CLI command | `media-mate` | `ferry` |
>
> The old GitHub names (`dspury/media-mate`, `dspury/ferry`) are now private
> archived placeholders, so they no longer redirect — see RENAME.md §1.3.

---

Paste this into the agent session:

---

## Task

Rename the `media-mate` project to `file-ferry`. A full plan with checkboxes lives at the repo root.

## Context

- **Repo:** `~/Lunar-Park/media-mate/` (GitHub: `dspury/media-mate`)
- **Plan:** Read `RENAME.md` at the repo root first — it has every step with checkboxes
- **Decisions already made:**
  - Version: v0.3.0
  - GitHub org: `dspury/file-ferry`
  - CLI command: `ferry`
  - Python package: `file_ferry`
  - Resolve stays bundled but documented as optional (lazy import in CLI, TUI already lazy)

## What's already done

- KB docs updated (all active references point to file-ferry now)
- Cron jobs updated (PR sync, issue pipeline owner review, PR merged notifier)
- RENAME.md written with full checklist

## What you need to do

Work through RENAME.md Phase 1, 2, and 3:

1. **Phase 1 (Rename):** Rename `src/media_mate/` → `src/file_ferry/`, update all imports, update pyproject.toml (name, version 0.3.0, scripts entry `ferry`), update README.md, update CI workflow, update tests, update examples
2. **Phase 2 (Optional resolve):** Move the resolve import in cli.py from top-level to inside the function (TUI already lazy-imports it). Add docs noting resolve requires DaVinci Resolve installed separately.
3. **Phase 3 (Cleanup):** Ruff format pass, ensure all tests pass, update `__init__.py`

## Important

- Don't create a new repo — just prepare the code. D will handle the GitHub rename/push.
- The local directory stays at `~/Lunar-Park/media-mate/` for now (D will rename it)
- Run tests after changes: `cd ~/Lunar-Park/media-mate && python -m pytest`
- Run ruff after changes: `cd ~/Lunar-Park/media-mate && ruff format src/ tests/`

---

Start by reading RENAME.md, then work through the phases in order.

---

## Outcome

**Status: done.** Phases 1.1/1.2, 2 and 3 landed on branch `rename/ferry` and
are merged to `main`. The naming changed twice mid-pass and settled on
`file-ferry` for the project with `ferry` as the typed command; see the
execution notes at the bottom of `RENAME.md`.

- **§1.3 (GitHub) — done.** The repo was *renamed* rather than forked, keeping
  all issues, PRs, tags and CI history. Both freed names were re-created as
  private archived placeholders.
- **§1.4 (PyPI) — still open.** `file-ferry` has not been registered yet.
  (`ferry` was already taken on PyPI, which is why the project is `file-ferry`.)
- **Local directory — done, 2026-08-22.** Renamed `~/Lunar-Park/media-mate/` →
  `~/Lunar-Park/file-ferry/`, then shortened again the same day to
  `~/Lunar-Park/ferry/` — the local checkout is just `ferry`, while the project
  and the GitHub repo stay `file-ferry`. Both times the in-repo `.venv` had the
  old absolute path baked into 48 files (every `bin/` shebang, `pyvenv.cfg`,
  `activate*`, and the editable-install `.pth`), so it was repointed and stale
  caches purged; if you ever move this checkout again, either redo that rewrite
  or just rebuild the venv. Verified afterwards: `ferry --version` → 0.3.0,
  541 tests passing.

The remaining `media-mate` mentions in `README.md` and `SPEC.md` are deliberate
upgrade/migration notes for existing users and should stay.
