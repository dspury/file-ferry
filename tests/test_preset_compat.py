"""Legacy profiles and immutable revisions must not diverge (spec §4.2).

Two writers reach the same presets — legacy ``profile.save`` and the new
``profile.saveRevision``. When they disagree about what version N holds,
a destination pinned to a revision routes files through content that no
longer describes the profile, and nobody can tell from either side.

These tests cover the conversion itself, both writers interleaved, and
an actual pre-v4 database upgrading with awkward legacy content in it.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from file_ferry.application.preset_compat import (
    DEFAULT_FALLBACK_TEMPLATE,
    convert_legacy_template,
    legacy_root_prefix,
)
from file_ferry.application.presets import PresetRevisionService
from file_ferry.application.profiles import ProfileService
from file_ferry.persistence import runner
from file_ferry.persistence.connection import transaction
from file_ferry.persistence.repositories import preset_revisions as revision_repo
from file_ferry.service.protocol import (
    PresetContent,
    SavePresetRevisionParams,
    SaveProfileParams,
)


def _boot(tmp_path: Path) -> Path:
    from file_ferry.application.service import ApplicationService

    db_path = tmp_path / "ferry.db"
    boot = ApplicationService(db_path=db_path, app_data_dir=tmp_path / "app")
    boot.bootstrap()
    boot.close()
    return db_path


# --- the conversion itself -------------------------------------------------


def test_root_only_template_becomes_an_equivalent_preserve_relative_rule() -> None:
    fallback, policy, review = convert_legacy_template({"root": "Archive/2026"}, "rename")
    assert fallback == "Archive/2026/{relative_dir}/{filename}"
    assert policy == "keep_both"
    assert review == []


def test_unknown_keys_become_blocking_review_evidence_not_silence() -> None:
    fallback, _policy, review = convert_legacy_template(
        {"root": "Archive", "byCamera": True, "weird": {"a": 1}}, "rename"
    )
    assert fallback.startswith("Archive/")
    joined = " ".join(review)
    assert "byCamera" in joined and "weird" in joined
    assert "True" in joined, "the value is preserved, not just the key name"


def test_token_bearing_root_is_not_reinterpreted_as_a_literal_folder() -> None:
    """A template root was never an advanced token template; don't guess."""
    assert legacy_root_prefix({"root": "{year}/{month}"}) is None
    fallback, _policy, review = convert_legacy_template({"root": "{year}/{month}"}, "rename")
    assert fallback == DEFAULT_FALLBACK_TEMPLATE
    assert any("not a plain relative prefix" in r for r in review)


def test_escaping_root_is_refused_rather_than_sanitized() -> None:
    assert legacy_root_prefix({"root": "../outside"}) is None
    assert legacy_root_prefix({"root": "/absolute"}) is None
    _fallback, _policy, review = convert_legacy_template({"root": "../outside"}, "rename")
    assert review and "../outside" in review[0]


@pytest.mark.parametrize(
    ("legacy", "expected", "needs_review"),
    [
        ("rename", "keep_both", False),
        ("skip", "needs_review", True),
        ("overwrite", "needs_review", True),
        ("made_up", "needs_review", True),
    ],
)
def test_legacy_conflict_policies_map_deliberately(
    legacy: str, expected: str, needs_review: bool
) -> None:
    """``skip`` and ``overwrite`` have no safe equivalent (§6.4)."""
    _fallback, policy, review = convert_legacy_template({"root": "A"}, legacy)
    assert policy == expected
    assert bool(review) is needs_review


# --- both writers on the same preset --------------------------------------


def test_a_legacy_save_writes_its_matching_revision(tmp_path: Path) -> None:
    """R07: a version bump without its revision leaves the two diverged."""
    db = _boot(tmp_path)
    profiles = ProfileService(db)
    saved = profiles.save(SaveProfileParams(name="P", template={"root": "A"}))
    with transaction(db) as conn:
        rev = revision_repo.get_revision(conn, saved.id, saved.version)
    assert rev is not None, "the legacy save must produce its revision"
    assert rev.fallback_template == "A/{relative_dir}/{filename}"
    assert json.loads(rev.legacy_template_json or "{}") == {"root": "A"}


def test_versions_stay_monotonic_across_both_writers(tmp_path: Path) -> None:
    db = _boot(tmp_path)
    profiles = ProfileService(db)
    presets = PresetRevisionService(db)

    v1 = profiles.save(SaveProfileParams(name="Mixed", template={"root": "A"}))
    assert v1.version == 1
    r2 = presets.save_revision(
        SavePresetRevisionParams(
            name="Mixed", content=PresetContent(fallbackTemplate="B/{filename}")
        )
    )
    assert r2.revision == 2
    v3 = profiles.save(SaveProfileParams(name="Mixed", template={"root": "C"}))
    assert v3.version == 3, "a legacy save after a new-style save keeps counting up"
    r4 = presets.save_revision(
        SavePresetRevisionParams(
            name="Mixed", content=PresetContent(fallbackTemplate="D/{filename}")
        )
    )
    assert r4.revision == 4

    with transaction(db) as conn:
        revisions = {r.revision: r for r in revision_repo.list_revisions(conn, v1.id, limit=50)[0]}
    assert sorted(revisions) == [1, 2, 3, 4], "every version has exactly one revision"
    # Earlier revisions are immutable: revision 1 still describes root A.
    assert revisions[1].fallback_template == "A/{relative_dir}/{filename}"
    assert revisions[3].fallback_template == "C/{relative_dir}/{filename}"


def test_reading_a_legacy_revision_surfaces_what_needs_review(tmp_path: Path) -> None:
    db = _boot(tmp_path)
    profiles = ProfileService(db)
    presets = PresetRevisionService(db)
    saved = profiles.save(
        SaveProfileParams(name="Odd", template={"root": "A", "mystery": 1}, conflictPolicy="skip")
    )
    _row, content = presets.get_revision(saved.id, saved.version)
    joined = " ".join(content.review_required)
    assert "mystery" in joined
    assert "skip" in joined
    assert content.conflict_policy == "needs_review"


# --- a real pre-v4 database ------------------------------------------------


def _pre_v4_db(tmp_path: Path, profiles: list[tuple[str, dict[str, object], str]]) -> Path:
    """A database at schema v3 carrying the given legacy profiles."""
    db = tmp_path / "pre_v4.db"
    sqlite3.connect(str(db)).close()
    discovered = runner.discover_migrations()
    backups = tmp_path / "backups"
    runner.apply_pending(db, discovered, backups, target_version=3)
    with sqlite3.connect(db) as conn:
        for name, template, policy in profiles:
            conn.execute(
                "INSERT INTO organization_profiles "
                "(name, version, template, conflict_policy, mutation_policy, "
                " created_at, updated_at) VALUES (?, ?, ?, ?, 'copy', 'then', 'then')",
                (name, 3, json.dumps(template), policy),
            )
        conn.commit()
    return db


def test_upgrade_converts_awkward_legacy_profiles_without_losing_anything(
    tmp_path: Path,
) -> None:
    db = _pre_v4_db(
        tmp_path,
        [
            ("RootOnly", {"root": "Archive/2026"}, "rename"),
            ("UnknownKeys", {"root": "A", "byCamera": True}, "skip"),
            ("TokenRoot", {"root": "{year}/{month}"}, "overwrite"),
        ],
    )
    applied = runner.apply_pending(db, runner.discover_migrations(), tmp_path / "backups")
    assert applied and applied[-1].version == 4

    with transaction(db) as conn:
        rows = {
            r["name"]: r
            for r in conn.execute(
                "SELECT p.name AS name, r.fallback_template AS fallback, "
                "r.conflict_policy AS policy, r.review_json AS review, "
                "r.legacy_template_json AS legacy, r.revision AS revision "
                "FROM organization_profiles p "
                "JOIN organization_profile_revisions r ON r.preset_id = p.id"
            ).fetchall()
        }
    assert set(rows) == {"RootOnly", "UnknownKeys", "TokenRoot"}

    # Existing version numbers are preserved, not renumbered.
    assert all(r["revision"] == 3 for r in rows.values())

    root_only = rows["RootOnly"]
    assert root_only["fallback"] == "Archive/2026/{relative_dir}/{filename}"
    assert root_only["policy"] == "keep_both"
    assert json.loads(root_only["review"]) == []

    unknown = rows["UnknownKeys"]
    assert "byCamera" in unknown["review"]
    assert unknown["policy"] == "needs_review", "legacy 'skip' has no safe equivalent"

    token = rows["TokenRoot"]
    assert token["fallback"] == DEFAULT_FALLBACK_TEMPLATE
    assert "not a plain relative prefix" in token["review"]

    # The original template survives verbatim in every case.
    assert json.loads(token["legacy"]) == {"root": "{year}/{month}"}


def test_upgraded_database_has_clean_foreign_keys_and_keeps_dependent_rows(
    tmp_path: Path,
) -> None:
    db = _pre_v4_db(tmp_path, [("P", {"root": "A"}, "rename")])
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO projects (id, name, status, working_root, storage_policy, "
            "created_at, updated_at) "
            "VALUES ('p1', 'P', 'active', '/tmp/w', 'single_copy', 'then', 'then')"
        )
        conn.execute(
            "INSERT INTO jobs (id, project_id, command, state, total_steps, updated_at) "
            "VALUES ('j1', 'p1', 'offload', 'succeeded', 1, 'then')"
        )
        conn.commit()

    runner.apply_pending(db, runner.discover_migrations(), tmp_path / "backups")

    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        job = conn.execute("SELECT project_id FROM jobs WHERE id = 'j1'").fetchone()
        assert job is not None and job["project_id"] == "p1", "dependent rows survive"


def test_a_legacy_save_after_upgrade_continues_the_history(tmp_path: Path) -> None:
    """The upgraded profile is at version 3; the next save must be 4."""
    db = _pre_v4_db(tmp_path, [("P", {"root": "A"}, "rename")])
    runner.apply_pending(db, runner.discover_migrations(), tmp_path / "backups")
    saved = ProfileService(db).save(SaveProfileParams(name="P", template={"root": "B"}))
    assert saved.version == 4
    with transaction(db) as conn:
        assert revision_repo.get_revision(conn, saved.id, 4) is not None
        # The pre-migration snapshot is untouched.
        old = revision_repo.get_revision(conn, saved.id, 3)
        assert old is not None
        assert old.fallback_template == "A/{relative_dir}/{filename}"
