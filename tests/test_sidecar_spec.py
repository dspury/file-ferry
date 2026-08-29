"""The PyInstaller spec must bundle every migration (#139).

Migrations are discovered at runtime with ``pkgutil.iter_modules``, which
PyInstaller's static analysis cannot follow -- nothing imports them by name.
They therefore have to be named as hidden imports in ``scripts/sidecar.spec``.

That list was hand-maintained and went stale: it named 001 and 002, 003 was
added without it, and the frozen sidecar consequently knew about two
migrations, computed ``target 2``, and refused to open any database at
schema_version 3. Every real database is at 3, so the packaged app died on
launch with "sidecar exited before announcing readiness".

These tests guard the fix -- that the spec derives the list from disk rather
than restating it -- because the failure is invisible to every other check:
it needs a PyInstaller build and a packaged launch to show up.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = REPO_ROOT / "scripts" / "sidecar.spec"
MIGRATIONS_DIR = REPO_ROOT / "src" / "file_ferry" / "persistence" / "migrations"

_MIGRATION_FILE = re.compile(r"^(\d{3})_.+\.py$")


def _migration_modules_on_disk() -> list[str]:
    return sorted(
        f"file_ferry.persistence.migrations.{path.stem}"
        for path in MIGRATIONS_DIR.iterdir()
        if _MIGRATION_FILE.match(path.name)
    )


def test_the_spec_exists_where_the_build_script_expects_it() -> None:
    assert SPEC_PATH.is_file()


def test_there_is_at_least_one_migration_to_bundle() -> None:
    """Guards the test itself: an empty glob must not read as success."""
    assert len(_migration_modules_on_disk()) >= 3


def test_the_spec_does_not_hardcode_migration_module_names() -> None:
    """The regression, stated directly.

    A literal ``"file_ferry.persistence.migrations.NNN_..."`` in the spec is
    a list someone has to remember to update, and #139 is what happens when
    they do not.
    """
    source = SPEC_PATH.read_text(encoding="utf-8")
    hardcoded = re.findall(
        r"""["']file_ferry\.persistence\.migrations\.\d{3}_[^"']*["']""",
        source,
    )
    assert hardcoded == [], (
        "sidecar.spec names migration modules literally: "
        f"{hardcoded}. Derive them from the migrations directory instead, so "
        "adding a migration cannot silently break the packaged sidecar."
    )


def test_the_spec_derives_the_list_from_the_migrations_directory() -> None:
    source = SPEC_PATH.read_text(encoding="utf-8")
    assert "MIGRATIONS_DIR" in source
    assert "glob.glob" in source
    assert "hiddenimports=MIGRATION_MODULES" in source


def test_the_specs_glob_resolves_to_every_migration_on_disk() -> None:
    """Run the spec's own globbing logic and compare it to the package.

    Mirrors the spec rather than importing it -- a ``.spec`` file is
    executed by PyInstaller with injected globals (``SPEC``) and is not
    importable here.
    """
    import glob
    import os

    pattern = os.path.join(str(MIGRATIONS_DIR), "[0-9][0-9][0-9]_*.py")
    resolved = sorted(
        "file_ferry.persistence.migrations." + os.path.splitext(os.path.basename(p))[0]
        for p in glob.glob(pattern)
    )
    assert resolved == _migration_modules_on_disk()


def test_the_bundled_modules_match_what_the_runner_discovers() -> None:
    """The spec and the runner must agree on what a migration is.

    If the runner's pattern and the spec's glob ever diverge, the frozen
    sidecar bundles a different set than it looks for -- which is the same
    class of failure as #139, just from the other side.
    """
    from file_ferry.persistence.runner import discover_migrations

    discovered = sorted(
        f"file_ferry.persistence.migrations.{m.module.__name__.rsplit('.', 1)[-1]}"
        for m in discover_migrations()
    )
    assert discovered == _migration_modules_on_disk()


def test_the_highest_migration_is_the_target_version() -> None:
    """A frozen bundle missing the newest migration lowers the target.

    That is exactly how #139 presented: target 2 against a schema_version 3
    database. Asserting the relationship here means a missing migration shows
    up as a failing test rather than a dead packaged app.
    """
    from file_ferry.persistence.runner import discover_migrations

    migrations = discover_migrations()
    highest_on_disk = max(
        int(_MIGRATION_FILE.match(p.name).group(1))  # type: ignore[union-attr]
        for p in MIGRATIONS_DIR.iterdir()
        if _MIGRATION_FILE.match(p.name)
    )
    assert max(m.version for m in migrations) == highest_on_disk
