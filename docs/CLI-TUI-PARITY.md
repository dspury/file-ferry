# CLI & TUI parity — vNext application-service verbs (Package 8)

This document records the Package 8 transition (plan §9, ADR-0005): the
CLI and TUI now reach the same application services the desktop sidecar
uses, instead of composing the capability modules directly.

## Compatibility promise

The **legacy standalone verbs are preserved and unchanged**: `probe`,
`organize`, `proxy`, `resolve create`, `verify`, `log`, and `run`. Existing
automation that calls these does **not** need to change and is **not**
forced to launch Electron. The existing CLI/TUI behavior is untouched, and
an existing audit log at `~/.ferry/ferry.db` keeps being read from there
(see the ledger note below).

The **vNext verbs are additive**. They call the same
`file_ferry.application.service.ApplicationService` the sidecar uses, so
the CLI and desktop are behaviorally identical — the CLI is not a second
implementation.

## New vNext CLI verbs

All accept `--json` for machine-readable output unless noted.

| Command | Purpose |
| --- | --- |
| `ferry project list` | List projects (rich table or `--json`) |
| `ferry project create NAME --working DIR [--backup DIR]` | Create a project |
| `ferry project get ID` | Show one project |
| `ferry source inspect PATH [--kind card\|existing_media]` | Read-only source scan |
| `ferry source list-volumes` | List mounted volumes |
| `ferry intake plan PROJECT SOURCE --working DIR [--backup DIR]` | Build a reviewable plan (no writes) |
| `ferry jobs list [--project ID]` | List durable jobs |
| `ferry jobs resume ID` | Resume an attention job |
| `ferry jobs retry ID` | Retry a failed job (fresh attempt) |
| `ferry receipt export OPERATION [--format markdown\|html]` | Export a receipt |
| `ferry reconcile project ID` | Reconcile a project's replicas |

> The vNext verbs read/write the same SQLite database the legacy CLI uses,
> so legacy and vNext surfaces coexist on one store. The vNext database
> schema is created and migrated on first use by the application-service
> bootstrap.

### Which database, exactly

This promise was only half-true until 0.3.1. The CLI, TUI, and vNext verbs
defaulted to `~/.ferry/ferry.db` while `service/cli.py` — the sidecar the
desktop app spawns — defaulted to the platform application-data directory.
The two surfaces were therefore **two separate ledgers**: an offload run in
the desktop app was invisible to `ferry project list`, and vice versa.

All four entry points now resolve through
`file_ferry.paths.default_db_path`:

1. `--db <path>` or `FERRY_DB`, when given.
2. Otherwise the platform application-data database —
   `~/Library/Application Support/ferry/ferry.db` (macOS),
   `~/AppData/Local/ferry/ferry.db` (Windows),
   `~/.local/share/ferry/ferry.db` (otherwise).
3. Except when that file does not exist and `~/.ferry/ferry.db` does, in
   which case the older log is used — so a CLI-only install is not handed a
   fresh, empty database in place of its history.

When both files exist the application-data one wins and the CLI prints
which it chose, because the loser is invisible to every surface.

Config resolution is a separate question and is unchanged: `ferry.toml` /
`~/.ferry/config.toml` already agreed across all four entry points.

## TUI

The Textual TUI remains a terminal workstation. A new **DURABLE JOBS**
screen (`J` from Home, or the "DURABLE JOBS" button) lists the vNext
durable jobs from the same `ApplicationService` the sidecar uses. It is a
read-only recovery/activity surface; the full pipeline workspace,
audit-log, and settings screens are unchanged.

`ferry --no-tui` remains the stable escape hatch that keeps you in
CLI mode and prints help instead of launching the TUI.

## Migration behavior

- Both the legacy audit log and the vNext application schema live in the
  same SQLite file. The application-service bootstrap runs numbered,
  transactional, idempotent migrations (see `persistence/runner.py` and
  `docs/adr/0003`). Databases created by prior releases are migrated, not
  recreated; a backup is taken before each migration.
- Legacy history is preserved: the vNext model does not manufacture
  project facts from legacy audit rows. Unambiguous evidence may be linked
  later; all other history stays legacy.

## Recovery operations

- **Resume** a `needs_attention` job at a safe boundary (the runner
  validates source/destination state and the original plan fingerprint
  before reusing partial output). Never blindly appends to an arbitrary
  file.
- **Retry** a `failed` job: `failed` is a terminal state, so a retry
  creates a **fresh job** (new attempt); the prior failure is preserved in
  history.
- **Cancel** is cooperative: copy/FFmpeg work stops at documented safe
  boundaries; incomplete files stay marked partial or are cleaned only
  when a receipt proves they are owned temporary outputs.
- The `--db` flag points both legacy and vNext surfaces at the same store;
  a backup clone of the DB is taken before any migration runs.

## Why both paths exist

The CLI and desktop are two surfaces over **one** application layer
(ADR-0005). Keeping the legacy verbs stable means existing automation and
the Textual TUI keep working unchanged while the vNext model lands. The
`ApplicationService` is the single boundary between "ways of invoking"
and "the actual work."
