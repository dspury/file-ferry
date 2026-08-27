"""Ledger location resolution (file_ferry.paths).

The CLI, the TUI, the vNext verbs, and the desktop sidecar must all resolve
to one database file. They did not before this module existed: the sidecar
used the platform app-data dir while the CLI used ``~/.ferry``, so desktop
work was invisible to ``ferry project list`` and vice versa.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from file_ferry.paths import (
    app_data_dir,
    canonical_db_path,
    default_db_path,
    legacy_db_is_shadowed,
    legacy_db_path,
)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``Path.home()`` at a scratch directory."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Windows
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    return tmp_path


@pytest.mark.parametrize(
    ("system", "expected"),
    [
        ("Darwin", ("Library", "Application Support", "ferry")),
        ("Windows", ("AppData", "Local", "ferry")),
        ("Linux", (".local", "share", "ferry")),
        ("FreeBSD", (".local", "share", "ferry")),  # POSIX default
    ],
)
def test_app_data_dir_per_platform(
    home: Path,
    monkeypatch: pytest.MonkeyPatch,
    system: str,
    expected: tuple[str, ...],
) -> None:
    monkeypatch.setattr("platform.system", lambda: system)
    assert app_data_dir() == home.joinpath(*expected)


def test_canonical_and_legacy_are_distinct(home: Path) -> None:
    assert canonical_db_path() != legacy_db_path()
    assert canonical_db_path().name == "ferry.db"
    assert legacy_db_path() == home / ".ferry" / "ferry.db"
    # The Electron shell derives the same parent from its userData dir,
    # which electron-builder takes from productName (`ferry`).
    assert canonical_db_path().parent.name == "ferry"


def test_prefers_the_app_data_ledger_on_a_fresh_install(home: Path) -> None:
    """Neither file exists: a new install gets the canonical location."""
    assert default_db_path() == canonical_db_path()


def test_prefers_the_app_data_ledger_when_it_exists(home: Path) -> None:
    canonical_db_path().parent.mkdir(parents=True)
    canonical_db_path().touch()
    assert default_db_path() == canonical_db_path()


def test_redirects_to_the_legacy_ledger_when_only_it_exists(home: Path) -> None:
    """A CLI-only install keeps its existing audit log.

    The regression this guards against is handing such an operator a
    fresh, empty database and calling it their history.
    """
    legacy_db_path().parent.mkdir(parents=True)
    legacy_db_path().touch()
    assert default_db_path() == legacy_db_path()


def test_app_data_wins_when_both_exist(home: Path) -> None:
    for p in (canonical_db_path(), legacy_db_path()):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch()
    assert default_db_path() == canonical_db_path()


def test_shadowing_is_only_reported_when_both_exist(home: Path) -> None:
    assert legacy_db_is_shadowed() is False

    legacy_db_path().parent.mkdir(parents=True)
    legacy_db_path().touch()
    assert legacy_db_is_shadowed() is False  # legacy alone is not shadowed

    canonical_db_path().parent.mkdir(parents=True)
    canonical_db_path().touch()
    assert legacy_db_is_shadowed() is True


def test_resolution_is_not_frozen_at_import(home: Path) -> None:
    """The answer follows the filesystem, not import order."""
    legacy_db_path().parent.mkdir(parents=True)
    legacy_db_path().touch()
    assert default_db_path() == legacy_db_path()

    canonical_db_path().parent.mkdir(parents=True)
    canonical_db_path().touch()
    assert default_db_path() == canonical_db_path()


def test_every_entry_point_resolves_to_the_same_ledger(home: Path) -> None:
    """The whole point: one store for all four surfaces.

    ``service/cli.py`` is what the desktop app spawns; if it disagrees with
    the CLI, the desktop and the terminal are two separate products.
    """
    from file_ferry.service.cli import default_db_path as sidecar_default

    assert sidecar_default() == default_db_path()
