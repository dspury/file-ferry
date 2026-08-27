"""Canonical filesystem locations for ferry's local state.

One resolver, imported by every entry point — the CLI, the TUI, the vNext
verbs, and the desktop sidecar — so all four read and write **one** ledger.

They did not, before this module existed. ``service/cli.py`` (the sidecar
the desktop app spawns) defaulted to the platform app-data dir while
``cli.py`` / ``tui.py`` / ``cli_vnext.py`` defaulted to ``~/.ferry``, so
work done in the desktop app was invisible to ``ferry project list`` and
vice versa — even though ``docs/CLI-TUI-PARITY.md`` promises a single store
and migration 001 exists precisely so the legacy and vNext schemas can
share one file.

The app-data dir wins as the canonical location: it is where a packaged
desktop app is supposed to keep user data on each platform, and it is where
the existing real ledger already lives. ``~/.ferry`` is not abandoned — see
:func:`default_db_path` for the redirect that keeps a CLI-only install
working untouched.

Note that ``~/.ferry/config.toml`` is a separate question and is **not**
moved here: config resolution lives in :mod:`file_ferry.config` and already
agrees across all four entry points.
"""

from __future__ import annotations

import platform
from pathlib import Path

_DB_NAME = "ferry.db"


def app_data_dir() -> Path:
    """Return the per-platform application-data directory for ferry.

    Matches the location the Electron shell derives from its ``userData``
    dir, which electron-builder takes from ``productName`` (``ferry``).
    """
    home = Path.home()
    base = {
        "Darwin": home / "Library" / "Application Support",
        "Windows": home / "AppData" / "Local",
    }.get(platform.system(), home / ".local" / "share")
    return base / "ferry"


def canonical_db_path() -> Path:
    """Return the app-data ledger path, whether or not it exists yet."""
    return app_data_dir() / _DB_NAME


def legacy_db_path() -> Path:
    """Return the pre-unification ``~/.ferry`` ledger path.

    Documented as the default in the README and ``CLI-TUI-PARITY.md`` for
    every release up to 0.3.0, so an existing CLI/TUI install has its only
    ledger here.
    """
    return Path.home() / ".ferry" / _DB_NAME


def default_db_path() -> Path:
    """Resolve the ledger to use when the operator named none.

    Prefers :func:`canonical_db_path`. Redirects to
    :func:`legacy_db_path` only when the canonical file does not exist and
    the legacy one does — so an install that has only ever used the CLI
    keeps reading and writing its existing audit log instead of silently
    being handed a fresh, empty database.

    Deliberately resolved on each call rather than frozen into a module
    constant at import time: the answer depends on the filesystem, and a
    constant would also bake one user's ``$HOME`` into ``--help`` output.
    """
    canonical = canonical_db_path()
    if not canonical.exists() and legacy_db_path().exists():
        return legacy_db_path()
    return canonical


def legacy_db_is_shadowed() -> bool:
    """True when both ledgers exist, so one of them is being ignored.

    The ambiguous case: whichever file loses is invisible to every
    surface. Callers should say so rather than pick in silence.
    """
    return canonical_db_path().exists() and legacy_db_path().exists()
