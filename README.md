# file-ferry

[![Version](https://img.shields.io/badge/version-0.3.0-blue)](https://github.com/dspury/file-ferry)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/dspury/file-ferry/ci.yml?style=flat-square)](https://github.com/dspury/file-ferry/actions/workflows/ci.yml)

> A CLI + interactive TUI for the boring-but-critical infrastructure underneath video post-production: probe camera cards, organize them, generate proxies, spin up a DaVinci Resolve project, and verify backups — every step logged to a local SQLite audit trail.

No API keys. No cloud. Just FFmpeg, your local SQLite, and (optionally) DaVinci Resolve.

---

## Two ways to use it

**1. The interactive TUI** (the primary interface for most people)

```bash
ferry
```

Launches a full-screen Textual workstation with four screens: **Home** (dashboard), **Pipelines** (browse + queue + watch runs live), **Audit Log** (browse and search run history), and **Settings** (edit and persist config). See [The TUI](#the-tui) below for the full keymap.

**2. The CLI** (for scripts, cron, and quick one-offs)

```bash
ferry run ./raw/ --organize --proxy --resolve-project --verify --project-name "Episode-12"
```

Chains probe → organize → proxy → resolve-project → verify in one call. Each command also runs standalone — see [The CLI](#the-cli).

Prefer scripts and one-liners? Add `--no-tui` to skip the TUI auto-launch and stay in CLI mode:

```bash
ferry --no-tui run ./raw/
```

---

## Quick start

```bash
# 1. Get the code
git clone https://github.com/dspury/file-ferry.git
cd file-ferry

# 2. Install (use pipx for an isolated install, or pip if you don't have it)
pipx install .
#   — or —
pip install .

# 3. Make sure ffmpeg is on PATH (required)
brew install ffmpeg         # macOS
sudo apt install ffmpeg     # Debian/Ubuntu

# 4. Launch the TUI
ferry
```

Want to try it without your own media? Bundled sample footage is in [`examples/`](./examples/):

```bash
cd examples/
./run-demo.sh
```

A full walkthrough with screenshots and audit-log output is in [`examples/WALKTHROUGH.md`](./examples/WALKTHROUGH.md).

---

## The TUI

The TUI is a full-screen Textual workstation. It's keyboard-driven and lives inside your terminal — no browser, no separate window.

| Screen        | What it does                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| ------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Home**      | Dashboard with ffmpeg version, db path, and stat tiles (total / succeeded / failed / live runs)                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| **Pipelines** | Browse mounted folders, queue several sources, run all five capability steps, watch progress live. The MEDIA BROWSER pane surfaces connected external drives (camera cards, backup disks, USB sticks) at the top — each entry shows name and free/total space, click one to jump the tree straight to it. The drive list refreshes automatically when cards are plugged in or ejected, and system junk (`.Trashes`, `$RECYCLE.BIN`, AppleDouble `._*` sidecars, …) is hidden from the browser and skipped by every pipeline step. |
| **Audit Log** | Browse and search run history; runs are color-coded by status                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| **Settings**  | Edit and persist proxy codec/height, checksum algorithm, and binary paths                                                                                                                                                                                                                                                                                                                                                                                                                                                         |

**Keybindings** (all available without leaving the keyboard):

| Key             | Action                                                         |
| --------------- | -------------------------------------------------------------- |
| `R` / `L` / `S` | Jump to **P**ipelines / Audit **L**og / **S**ettings from Home |
| `A`             | Add a folder to the queue (in Pipelines)                       |
| `Ctrl+R`        | Run the queue                                                  |
| `Ctrl+C`        | Safely cancel the current run                                  |
| `/`             | Search the audit log                                           |
| `Ctrl+S`        | Save settings                                                  |
| `Q`             | Quit                                                           |

The TUI is optional — `ferry --no-tui` keeps you in CLI mode and prints command help.

---

## The CLI

Each capability runs standalone or as part of the `run` pipeline. Step order in `run` is fixed: probe (always) → organize → proxy → resolve-project → verify. Skip any combination you don't need.

| Command          | What it does                                                                                                        |
| ---------------- | ------------------------------------------------------------------------------------------------------------------- |
| `probe`          | Run `ffprobe` on every file in a folder; capture codec, resolution, frame rate, color, audio, duration, size, mtime |
| `organize`       | Re-arrange files into a structured layout, preserving the source's folder shape (cards/scenes/takes)                |
| `proxy`          | Generate ProRes 422 Proxy (or any ProRes variant) at 1080p via `ffmpeg`; aspect-preserving; skips non-video         |
| `resolve create` | Create a DaVinci Resolve project programmatically; falls back to a JSON manifest if Resolve isn't running           |
| `verify`         | Checksum a folder; on rerun, report what changed (added/modified/missing) — designed for cron                       |
| `log`            | Query the audit log (text or JSON)                                                                                  |
| `run`            | Orchestrate any combination of the above as a pipeline                                                              |

Run `ferry <command> --help` for the full flag list. Example output:

```
$ ferry run ./raw/ --organize --proxy --resolve-project --verify --project-name "Episode-12"

Step 1: probe
  Probed 4 file(s)
Step 2: organize
  Copied 4, skipped 0
Step 3: proxy
  Generated 4 proxy file(s)
Step 4: resolve-project
  Created Resolve project (v20.0)
Step 5: verify
  Clean: 4 file(s) verified

Done.
```

### A cron-ready verify

```cron
# Every night at 3am, verify the backup drive and alert on any change
0 3 * * * cd /path/to/workspace && ferry verify /Volumes/Backup/ || mail -s "Backup alert" me@example.com
```

Exit codes from `verify`: `0` = clean, `1` = missing, `2` = modified, `3` = added.

---

## Installation

**Requirements:**

- **Python 3.11+** (for `tomllib` stdlib)
- **FFmpeg** with `ffprobe` on `$PATH` (or pointed at via config)
- **DaVinci Resolve Studio** (free tier is fine) — only required for `resolve create`; everything else works without it

**Install:**

```bash
git clone https://github.com/dspury/file-ferry.git
cd file-ferry
pipx install .                # clean isolated install
#   — or —
pip install .                 # into your current environment
```

**From a working tree (development):**

```bash
git clone https://github.com/dspury/file-ferry.git
cd file-ferry
pip install -e ".[dev]"
```

**Verify:**

```bash
ferry --version
ferry --help
```

---

## Configuration (optional)

ferry works with sensible defaults. Drop a `ferry.toml` in your project root or `~/.ferry/` to override. Search order: `--config <path>` / `FERRY_CONFIG` env var → `./ferry.toml` → `~/.ferry/config.toml`.

```toml
# Proxy generation defaults (any ProRes variant)
proxy_codec = "ProRes422Proxy"
proxy_height = 1080

# Checksum algorithm: xxhash (default, ~10x faster) | sha256
checksum_algo = "xxhash"
```

See [`ferry.toml.example`](./ferry.toml.example) for the full reference.

### Upgrading from media-mate (v0.2.x)

v0.3.0 renamed the project, and with it every path it reads. Nothing is migrated
automatically — `ferry` looks only at the new locations, and your old data is
left untouched where it is. To carry it over:

```bash
mv ~/.media-mate ~/.ferry                      # config + audit log
mv ~/.ferry/media-mate.db ~/.ferry/ferry.db    # the database itself
mv ./media-mate.toml ./ferry.toml              # per-project config, if you have one
```

The desktop app keeps its data separately, under
`~/Library/Application Support/ferry/` (was `.../media-mate/`) on macOS. That
directory holds the vNext database, operation receipts and diagnostic logs, so
move it too — left behind, the app starts with an empty database and your
projects, jobs and receipts are not carried over.

The database schema did not change, so a moved `ferry.db` is read as-is.

---

## The audit log

Every operation writes to one local SQLite database, shared by the CLI, the TUI, and the desktop app. The schema covers runs, files, probes, proxies, projects, verifications, and organize operations.

The default location is your platform's application-data directory:

| Platform | Path |
| --- | --- |
| macOS | `~/Library/Application Support/ferry/ferry.db` |
| Windows | `~/AppData/Local/ferry/ferry.db` |
| Linux | `~/.local/share/ferry/ferry.db` |

Override it with `--db <path>` or the `FERRY_DB` environment variable.

If you have been using the CLI from a release before 0.3.1, your log is at `~/.ferry/ferry.db`. Ferry keeps reading it from there — nothing to migrate — as long as no application-data database exists yet. When both exist, the application-data one wins and `ferry` tells you which it picked. To adopt the old log deliberately, move it:

```bash
mv ~/.ferry/ferry.db "$HOME/Library/Application Support/ferry/ferry.db"   # macOS
```

Note that `ferry.toml` / `config.toml` resolution is unchanged and still looks in `~/.ferry/`.

The log answers questions like:

- _"When did this file get probed, and what was the result?"_
- _"What got copied during the last organize run?"_
- _"When was this Resolve project created, and from what source folder?"_
- _"What was the checksum of this file at the last verify?"_

It's the system of record — back it up, copy it between machines, trust it as ground truth. Query from the TUI's **Audit Log** screen or the CLI:

```bash
ferry log            # text table
ferry log --format json
ferry log --limit 5
```

---

## Roadmap

The next product direction is documented in
[`docs/FILE-FERRY-PRODUCT-DIRECTION.md`](./docs/FILE-FERRY-PRODUCT-DIRECTION.md):
a local-first desktop workstation for verified card offload, existing-folder
adoption, project reconciliation, and a retained CLI/TUI.

The full build plan is in
[`docs/FILE-FERRY-FULL-APP-IMPLEMENTATION-PLAN.md`](./docs/FILE-FERRY-FULL-APP-IMPLEMENTATION-PLAN.md).
**All nine implementation packages are landed** (see its §0 progress table):
Electron shell + secure bridge, the complete desktop experience, TUI/CLI
parity, and packaged-release hardening. The remaining items are operator-owned
release gates (signing/notarization, real-media suite, soak, security review)
— see §16 of the plan.

Longer-term ideas (not yet scheduled):

- Scene detection (PySceneDetect)
- Audio loudness analysis
- Watch-folder mode
- Cloud-storage adapters

---

## Contributing

Open source under the MIT license. Issues and PRs welcome on [GitHub](https://github.com/dspury/file-ferry).

Development setup:

```bash
git clone https://github.com/dspury/file-ferry.git
cd file-ferry
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

pytest
ruff check . && ruff format --check .
mypy src
```

Full specification: [`SPEC.md`](./SPEC.md).

---

## License

MIT — see [`LICENSE`](./LICENSE).
