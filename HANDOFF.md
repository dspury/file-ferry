# Handoff: media-mate → ferry Rename

Paste this into the agent session:

---

## Task

Rename the `media-mate` project to `ferry`. A full plan with checkboxes lives at the repo root.

## Context

- **Repo:** `~/Lunar-Park/media-mate/` (GitHub: `dspury/media-mate`)
- **Plan:** Read `RENAME.md` at the repo root first — it has every step with checkboxes
- **Decisions already made:**
  - Version: v0.3.0
  - GitHub org: `dspury/ferry`
  - CLI command: `ferry`
  - Python package: `ferry`
  - Resolve stays bundled but documented as optional (lazy import in CLI, TUI already lazy)

## What's already done

- KB docs updated (all active references point to ferry now)
- Cron jobs updated (PR sync, issue pipeline owner review, PR merged notifier)
- RENAME.md written with full checklist

## What you need to do

Work through RENAME.md Phase 1, 2, and 3:

1. **Phase 1 (Rename):** Rename `src/media_mate/` → `src/ferry/`, update all imports, update pyproject.toml (name, version 0.3.0, scripts entry `ferry`), update README.md, update CI workflow, update tests, update examples
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

**Status: done.** Phases 1.1/1.2, 2 and 3 are landed on branch `rename/ferry`.
The naming was unified on a single name (`ferry`, not `ferry-media`) mid-pass;
see the execution notes at the bottom of `RENAME.md`. §1.3 (GitHub) and §1.4
(PyPI) are still open and are D's to run.
