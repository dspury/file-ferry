"""Preset revision service tests (destination-presets spec §4.2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from file_ferry.application.presets import PRESET_SCHEMA_VERSION, PresetError, PresetRevisionService
from file_ferry.service.protocol import (
    PresetContent,
    PresetExclusion,
    PresetGroup,
    PresetMatchConditions,
    PresetRule,
    SavePresetRevisionParams,
)


def _boot(tmp_path: Path) -> PresetRevisionService:
    from file_ferry.application.service import ApplicationService

    db_path = tmp_path / "ferry.db"
    boot = ApplicationService(db_path=db_path, app_data_dir=tmp_path / "app")
    boot.bootstrap()
    boot.close()
    return PresetRevisionService(db_path)


def _basic_content() -> PresetContent:
    return PresetContent(
        fallbackTemplate="Sources/{source_label}/{relative_dir}/{filename}",
        rules=[
            PresetRule(
                id="video",
                match=PresetMatchConditions(extensions=[".mov", ".mp4"]),
                destination="Video/{filename}",
            ),
        ],
        groups=[
            PresetGroup(
                id="camera-card",
                match=PresetMatchConditions(pathGlob="DCIM/*"),
                destination="Camera/{relative_dir}/{filename}",
            ),
        ],
        exclusions=[
            PresetExclusion(
                id="system",
                reason="macOS system artifacts",
                match=PresetMatchConditions(extensions=[".DS_Store"]),
            ),
        ],
        conflictPolicy="keep_both",
    )


def test_first_save_creates_preset_and_revision(tmp_path: Path) -> None:
    svc = _boot(tmp_path)
    summary = svc.save_revision(
        SavePresetRevisionParams(name="Camera default", content=_basic_content())
    )
    assert summary.preset_id > 0
    assert summary.revision == 1
    assert len(summary.content_hash) == 64


def test_second_save_bumps_revision(tmp_path: Path) -> None:
    svc = _boot(tmp_path)
    first = svc.save_revision(
        SavePresetRevisionParams(name="Camera default", content=_basic_content())
    )
    modified = _basic_content().model_copy(update={"rules": []})
    second = svc.save_revision(SavePresetRevisionParams(name="Camera default", content=modified))
    assert second.preset_id == first.preset_id
    assert second.revision == 2
    assert second.content_hash != first.content_hash


def test_get_revision_returns_content(tmp_path: Path) -> None:
    svc = _boot(tmp_path)
    saved = svc.save_revision(SavePresetRevisionParams(name="P", content=_basic_content()))
    row, content = svc.get_revision(saved.preset_id)
    assert row.revision == 1
    assert content.fallback_template.startswith("Sources/")
    assert content.rules[0].id == "video"


def test_get_revision_specific_version(tmp_path: Path) -> None:
    svc = _boot(tmp_path)
    first = svc.save_revision(SavePresetRevisionParams(name="P", content=_basic_content()))
    second = svc.save_revision(SavePresetRevisionParams(name="P", content=_basic_content()))
    row1, _ = svc.get_revision(first.preset_id, revision=1)
    row2, _ = svc.get_revision(first.preset_id, revision=2)
    assert row1.revision == 1
    assert row2.revision == 2
    assert second.revision == 2


def test_list_revisions_paginated(tmp_path: Path) -> None:
    svc = _boot(tmp_path)
    summaries = []
    for _ in range(7):
        summaries.append(
            svc.save_revision(SavePresetRevisionParams(name="P", content=_basic_content()))
        )
    rows, total = svc.list_revisions(summaries[0].preset_id, limit=3, after_id=0)
    assert total == 7
    assert len(rows) == 3
    page2, _ = svc.list_revisions(summaries[0].preset_id, limit=3, after_id=rows[-1].id)
    assert len(page2) == 3
    page3, _ = svc.list_revisions(summaries[0].preset_id, limit=3, after_id=page2[-1].id)
    assert len(page3) == 1


def test_rejects_unknown_template_token(tmp_path: Path) -> None:
    svc = _boot(tmp_path)
    bad = PresetContent(fallbackTemplate="{made_up_token}/{filename}")
    with pytest.raises(PresetError, match="unknown template token"):
        svc.save_revision(SavePresetRevisionParams(name="Bad", content=bad))


def test_rejects_rule_without_conditions(tmp_path: Path) -> None:
    svc = _boot(tmp_path)
    bad = PresetContent(
        fallbackTemplate="{filename}",
        rules=[PresetRule(id="empty", match=PresetMatchConditions(), destination="{filename}")],
    )
    with pytest.raises(PresetError, match="match: at least one condition"):
        svc.save_revision(SavePresetRevisionParams(name="Bad", content=bad))


def test_rejects_duplicate_rule_ids(tmp_path: Path) -> None:
    svc = _boot(tmp_path)
    bad = PresetContent(
        fallbackTemplate="{filename}",
        rules=[
            PresetRule(
                id="dup",
                match=PresetMatchConditions(extensions=[".mov"]),
                destination="{filename}",
            ),
            PresetRule(
                id="dup",
                match=PresetMatchConditions(extensions=[".mp4"]),
                destination="{filename}",
            ),
        ],
    )
    with pytest.raises(PresetError, match="duplicate rule id"):
        svc.save_revision(SavePresetRevisionParams(name="Bad", content=bad))


def test_export_payload_round_trip(tmp_path: Path) -> None:
    svc = _boot(tmp_path)
    saved = svc.save_revision(SavePresetRevisionParams(name="Trip", content=_basic_content()))
    exported = svc.export_preset(saved.preset_id)
    assert exported.payload.startswith("{")
    parsed = json.loads(exported.payload)
    assert parsed["format"] == "ferry-preset"
    assert parsed["formatVersion"] == PRESET_SCHEMA_VERSION
    preset_block = json.loads(parsed["preset"])
    assert preset_block["fallbackTemplate"].startswith("Sources/")
    # Imported preset has the same content hash as the source.
    summary = svc.import_preset(exported.payload, new_name="Trip-restored")
    original_row, _ = svc.get_revision(saved.preset_id)
    imported_row, _ = svc.get_revision(summary.preset_id)
    assert imported_row.content_hash == original_row.content_hash


def test_import_name_collision_suffixed(tmp_path: Path) -> None:
    svc = _boot(tmp_path)
    a = svc.save_revision(SavePresetRevisionParams(name="Shared", content=_basic_content()))
    b = svc.save_revision(SavePresetRevisionParams(name="Source", content=_basic_content()))
    exported = svc.export_preset(b.preset_id)
    summary = svc.import_preset(exported.payload, new_name="Shared")
    assert summary.preset_id is not None
    assert summary.preset_id != a.preset_id
    row, _ = svc.get_revision(summary.preset_id)
    assert row.name.startswith("Shared (")


class TestBuiltInPresets:
    """§6.2: two general starting points, no personal taxonomy."""

    def test_both_starting_presets_are_offered(self, tmp_path: Path) -> None:
        from file_ferry.application.presets import BUILTIN_PRESETS

        assert set(BUILTIN_PRESETS) == {"preserve-source-structure", "sort-by-category"}

    def test_preserve_keeps_the_source_layout_untouched(self, tmp_path: Path) -> None:
        """The safe default: a transfer rearranges nothing."""
        from file_ferry.application.rules import FileFacts, route

        content = _boot(tmp_path).builtin_content("preserve-source-structure")
        facts = FileFacts(rel_path="DCIM/100/A001.MOV", source_label="Card A", mtime=1.0)
        assert route(content, facts).dest_rel == "Sources/Card A/DCIM/100/A001.MOV"
        assert content.rules == [], "preserving means no routing rules at all"

    def test_category_preset_sorts_by_extension_and_says_so(self, tmp_path: Path) -> None:
        from file_ferry.application.rules import FileFacts, route

        content = _boot(tmp_path).builtin_content("sort-by-category")
        assert content.description is not None
        assert "not content inspection" in content.description, (
            "the description must not imply Ferry inspects file contents"
        )
        # The examples document's §2 table, verbatim. Source-relative
        # structure is preserved inside each category so a card's files
        # stay traceable and every IMG_0001.JPG does not collide in one
        # folder; no date routing in a starter preset (examples §2, §5).
        for rel, expected in (
            ("Exports/trailer.mov", "Video/Drive-A/Exports/trailer.mov"),
            ("Recordings/interview.wav", "Audio/Drive-A/Recordings/interview.wav"),
            ("Photos/Trip/IMG_001.JPG", "Images/Drive-A/Photos/Trip/IMG_001.JPG"),
            ("Admin/notes.pdf", "Documents/Drive-A/Admin/notes.pdf"),
            ("Backups/export.zip", "Archives/Drive-A/Backups/export.zip"),
            ("misc/file.custom", "Unsorted/Drive-A/misc/file.custom"),
            ("misc/README", "Unsorted/Drive-A/misc/README"),
        ):
            facts = FileFacts(rel_path=rel, source_label="Drive-A", mtime=1772600767.0)
            assert route(content, facts).dest_rel == expected

    def test_the_starter_presets_do_not_route_by_date(self, tmp_path: Path) -> None:
        """§5: users expect capture dates; {year} is modification time.

        Keeping it out of the starters means nobody inherits a filing
        scheme based on a timestamp that is usually not what they think
        it is. It stays available for a preset they write deliberately.
        """
        svc = _boot(tmp_path)
        for key in ("preserve-source-structure", "sort-by-category"):
            content = svc.builtin_content(key)
            templates = [r.destination for r in content.rules] + [content.fallback_template]
            for template in templates:
                assert "{year}" not in template and "{month}" not in template, template

    def test_unrecognized_files_go_to_unsorted_never_nowhere(self, tmp_path: Path) -> None:
        from file_ferry.application.rules import FileFacts, route

        content = _boot(tmp_path).builtin_content("sort-by-category")
        facts = FileFacts(rel_path="odd/mystery.zzz", source_label="Card A", mtime=1.0)
        routing = route(content, facts)
        assert routing.dest_rel == "Unsorted/Card A/odd/mystery.zzz"
        assert routing.matched_rule == "fallback"

    def test_the_built_ins_validate_as_saveable_presets(self, tmp_path: Path) -> None:
        """They are starting points the user owns, not hidden magic."""
        svc = _boot(tmp_path)
        for key in ("preserve-source-structure", "sort-by-category"):
            saved = svc.save_revision(
                SavePresetRevisionParams(name=key, content=svc.builtin_content(key))
            )
            assert saved.revision == 1

    def test_an_unknown_built_in_is_an_error(self, tmp_path: Path) -> None:
        with pytest.raises(PresetError, match="unknown built-in preset"):
            _boot(tmp_path).builtin_content("someones-personal-nas-layout")


class TestGroupDestinationTokens:
    """R20/examples §4: a group destination names a directory."""

    @staticmethod
    def _with_group(destination: str) -> PresetContent:
        return PresetContent(
            fallbackTemplate="Unsorted/{source_label}/{relative_dir}/{filename}",
            groups=[
                PresetGroup(
                    id="proj",
                    match=PresetMatchConditions(pathGlob="Proj"),
                    destination=destination,
                )
            ],
        )

    def test_directory_tokens_are_accepted(self, tmp_path: Path) -> None:
        svc = _boot(tmp_path)
        saved = svc.save_revision(
            SavePresetRevisionParams(
                name="G",
                content=self._with_group("Collections/{source_label}/{relative_dir}/{filename}"),
            )
        )
        assert saved.revision == 1

    @pytest.mark.parametrize("token", ["ext", "stem", "category", "year", "month"])
    def test_file_oriented_tokens_are_rejected_with_a_reason(
        self, tmp_path: Path, token: str
    ) -> None:
        """A group is evaluated once for its root directory.

        `{ext}` and `{stem}` are meaningless there, and `{year}` would
        make a preserved subtree's location depend on metadata a
        directory may not have — relocating or splitting the very thing
        the user marked "keep together".
        """
        svc = _boot(tmp_path)
        with pytest.raises(PresetError) as excinfo:
            svc.save_revision(
                SavePresetRevisionParams(
                    name="G",
                    content=self._with_group(f"Collections/{{{token}}}/{{filename}}"),
                )
            )
        message = str(excinfo.value)
        assert f"{{{token}}} is not available here" in message
        assert "evaluated once for the group root" in message

    def test_the_same_token_is_still_fine_in_an_ordinary_rule(self, tmp_path: Path) -> None:
        svc = _boot(tmp_path)
        content = PresetContent(
            fallbackTemplate="Unsorted/{filename}",
            rules=[
                PresetRule(
                    id="by-year",
                    match=PresetMatchConditions(categories=["image"]),
                    destination="Images/{year}/{source_label}/{relative_dir}/{filename}",
                )
            ],
        )
        assert svc.save_revision(SavePresetRevisionParams(name="R", content=content)).revision == 1


class TestExclusionValidation:
    """R15: an accepted field has to mean something, or be refused."""

    @staticmethod
    def _with(*exclusions: PresetExclusion) -> PresetContent:
        return PresetContent(
            fallbackTemplate="Sources/{source_label}/{relative_dir}/{filename}",
            exclusions=list(exclusions),
        )

    def test_a_condition_free_exclusion_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(PresetError, match=r"exclusions\[0\].match: at least one condition"):
            _boot(tmp_path).save_revision(
                SavePresetRevisionParams(
                    name="X",
                    content=self._with(
                        PresetExclusion(id="all", reason="all", match=PresetMatchConditions())
                    ),
                )
            )

    def test_duplicate_exclusion_ids_are_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(PresetError, match="duplicate exclusion id"):
            _boot(tmp_path).save_revision(
                SavePresetRevisionParams(
                    name="X",
                    content=self._with(
                        PresetExclusion(
                            id="dup",
                            reason="a",
                            match=PresetMatchConditions(extensions=[".tmp"]),
                        ),
                        PresetExclusion(
                            id="dup",
                            reason="b",
                            match=PresetMatchConditions(extensions=[".bak"]),
                        ),
                    ),
                )
            )

    def test_a_blank_reason_is_rejected(self, tmp_path: Path) -> None:
        """It is the whole account a receipt gives for every skipped file."""
        with pytest.raises(PresetError, match=r"exclusions\[0\].reason"):
            _boot(tmp_path).save_revision(
                SavePresetRevisionParams(
                    name="X",
                    content=self._with(
                        PresetExclusion(
                            id="tmp", reason="", match=PresetMatchConditions(extensions=[".tmp"])
                        )
                    ),
                )
            )

    def test_a_valid_exclusion_survives_an_export_import_round_trip(self, tmp_path: Path) -> None:
        svc = _boot(tmp_path)
        saved = svc.save_revision(
            SavePresetRevisionParams(
                name="X",
                content=self._with(
                    PresetExclusion(
                        id="tmp",
                        reason="editor scratch files",
                        match=PresetMatchConditions(extensions=[".tmp"]),
                    )
                ),
            )
        )
        imported = svc.import_preset(svc.export_preset(saved.preset_id).payload, new_name="Y")
        _, content = svc.get_revision(imported.preset_id)
        assert [e.id for e in content.exclusions] == ["tmp"]
        assert content.exclusions[0].reason == "editor scratch files"
