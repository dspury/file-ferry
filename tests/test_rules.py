"""The organization rule engine (spec §6.1-6.3, P4).

These pin the decisions that determine where a file lands. They are unit
tests on purpose: routing is pure, and a bug here misfiles every file of
a given shape rather than failing loudly once.
"""

from __future__ import annotations

import pytest

from file_ferry.application.rules import (
    CATEGORY_MAP_VERSION,
    FileFacts,
    RuleError,
    TemplateDataMissingError,
    category_for,
    find_exclusion,
    find_group,
    matches,
    normalize_label,
    path_glob_matches,
    render_template,
    route,
    validate_rendered,
)
from file_ferry.service.protocol import (
    PresetContent,
    PresetExclusion,
    PresetGroup,
    PresetMatchConditions,
    PresetRule,
)

# 2026-03-04T05:06:07Z — a fixed instant so date tokens are deterministic.
MTIME = 1772600767.0


def _facts(
    rel: str,
    *,
    label: str = "Card A",
    mtime: float | None = MTIME,
    entry_type: str = "file",
) -> FileFacts:
    return FileFacts(rel_path=rel, source_label=label, size=10, mtime=mtime, entry_type=entry_type)


class TestCategories:
    """Extension classification, never content verification (spec §6.1)."""

    @pytest.mark.parametrize(
        ("ext", "expected"),
        [
            (".mov", "video"),
            (".MOV", "video"),
            (".r3d", "video"),
            (".wav", "audio"),
            (".cr3", "image"),
            (".pdf", "document"),
            (".zip", "archive"),
            (".zzz", "other"),
            ("", "other"),
        ],
    )
    def test_known_and_unknown_extensions(self, ext: str, expected: str) -> None:
        assert category_for(ext) == expected

    def test_a_mislabelled_file_is_classified_by_extension_only(self) -> None:
        """A text file named `.mov` is `video` here, and nothing claims otherwise."""
        assert category_for(".mov") == "video"

    def test_the_map_is_versioned(self) -> None:
        """Reclassifying files is a visible change, so plans record the version."""
        assert CATEGORY_MAP_VERSION >= 1


class TestConditionMatching:
    def test_conditions_are_and_values_are_or(self) -> None:
        """One rule is one idea: every condition must hold, any value may."""
        conditions = PresetMatchConditions(pathGlob="DCIM/*", extensions=[".mov", ".mp4"])
        assert matches(conditions, _facts("DCIM/A001.MOV"))
        assert matches(conditions, _facts("DCIM/A002.mp4"))
        assert not matches(conditions, _facts("DCIM/notes.txt")), "extension fails"
        assert not matches(conditions, _facts("Other/A001.MOV")), "glob fails"

    def test_extensions_are_case_insensitive_and_dot_optional(self) -> None:
        conditions = PresetMatchConditions(extensions=["MOV", ".Mp4"])
        assert matches(conditions, _facts("a.mov"))
        assert matches(conditions, _facts("a.MP4"))

    def test_extensionless_files_are_matchable_explicitly(self) -> None:
        """Otherwise "no extensions listed" and "files without one" collide."""
        conditions = PresetMatchConditions(extensions=[""])
        assert matches(conditions, _facts("README"))
        assert not matches(conditions, _facts("README.md"))

    def test_category_condition(self) -> None:
        conditions = PresetMatchConditions(categories=["video", "audio"])
        assert matches(conditions, _facts("a.mov"))
        assert matches(conditions, _facts("a.wav"))
        assert not matches(conditions, _facts("a.pdf"))

    def test_source_label_condition_uses_the_normalized_label(self) -> None:
        conditions = PresetMatchConditions(sourceLabel="Card A")
        assert matches(conditions, _facts("a.mov", label="Card A"))
        assert not matches(conditions, _facts("a.mov", label="Card B"))

    def test_a_condition_free_rule_matches_nothing(self) -> None:
        """It would otherwise be an invisible catch-all above every rule below."""
        assert not matches(PresetMatchConditions(), _facts("a.mov"))

    def test_globs_use_forward_slashes_and_ignore_case(self) -> None:
        """A preset written on one OS must behave the same on another."""
        assert path_glob_matches("DCIM/*", "dcim/a001.mov")
        assert path_glob_matches("dcim/*", "DCIM/A001.MOV")
        # Leading/trailing separators on the pattern are incidental.
        assert path_glob_matches("/DCIM/*/", "DCIM/x")
        # A pattern naming a directory matches that path, not its children —
        # subtree claiming is what groups do, not what globs do.
        assert not path_glob_matches("DCIM", "DCIM/x")


class TestTemplates:
    def test_every_token_renders(self) -> None:
        facts = _facts("Trip/Day 1/A001.MOV")
        rendered = render_template(
            "{source_label}/{category}/{year}/{month}/{relative_dir}/{stem}{ext}", facts
        )
        assert rendered == "Card A/video/2026/03/Trip/Day 1/A001.MOV"

    def test_filename_is_the_whole_basename_and_ext_carries_its_dot(self) -> None:
        facts = _facts("a/b.tar.gz")
        assert render_template("{filename}", facts) == "b.tar.gz"
        assert render_template("{stem}", facts) == "b.tar"
        assert render_template("{ext}", facts) == ".gz"

    def test_an_extensionless_file_renders_an_empty_ext(self) -> None:
        assert render_template("{stem}{ext}", _facts("README")) == "README"

    def test_empty_segments_collapse(self) -> None:
        """A file at the source root must not produce a doubled separator."""
        rendered = render_template(
            "Sources/{source_label}/{relative_dir}/{filename}", _facts("a.mov")
        )
        assert rendered == "Sources/Card A/a.mov"

    def test_dates_are_source_mtime_in_utc(self) -> None:
        """§6.2: explicitly modification time, never a capture date."""
        assert render_template("{year}-{month}", _facts("a.mov")) == "2026-03"

    def test_a_missing_date_never_becomes_today(self) -> None:
        """Substituting "now" would misfile last year's footage forever."""
        for bad in (None, 0.0, -1.0):
            with pytest.raises(TemplateDataMissingError):
                render_template("{year}/{filename}", _facts("a.mov", mtime=bad))

    def test_unknown_tokens_are_rejected(self) -> None:
        with pytest.raises(RuleError, match="unknown template token"):
            render_template("{made_up}/{filename}", _facts("a.mov"))


class TestLabelNormalization:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Card A", "Card A"),
            ("a/b", "a-b"),
            ("a\\b", "a-b"),
            ("C:drive", "C-drive"),
            ("  padded  ", "padded"),
            ("", "Source"),
            (None, "Source"),
            ("...", "Source"),
        ],
    )
    def test_labels_become_safe_path_components(self, raw: str | None, expected: str) -> None:
        assert normalize_label(raw) == expected

    def test_control_characters_are_removed(self) -> None:
        assert normalize_label("a\x00b\x1fc") == "abc"


class TestRenderedValidation:
    def test_control_characters_are_rejected_not_stripped(self) -> None:
        """Silently rewriting a name makes the receipt describe a path that
        was never written."""
        with pytest.raises(RuleError, match="control character"):
            validate_rendered("a/b\x01c")

    def test_overlong_components_are_rejected(self) -> None:
        with pytest.raises(RuleError, match="exceeds"):
            validate_rendered("a/" + "x" * 300)

    def test_overlong_total_paths_are_rejected(self) -> None:
        with pytest.raises(RuleError, match="exceed"):
            validate_rendered("/".join("x" * 200 for _ in range(30)), dest_root_len=100)

    def test_trailing_dots_and_spaces_are_rejected(self) -> None:
        """Legal on POSIX; silently trimmed on Windows and some shares."""
        with pytest.raises(RuleError, match="space or dot"):
            validate_rendered("a/b.")
        with pytest.raises(RuleError, match="space or dot"):
            validate_rendered("a/b ")

    def test_an_empty_render_is_rejected(self) -> None:
        with pytest.raises(RuleError, match="empty destination"):
            validate_rendered("")


def _content(**kwargs: object) -> PresetContent:
    base: dict[str, object] = {
        "fallbackTemplate": "Unsorted/{source_label}/{relative_dir}/{filename}"
    }
    base.update(kwargs)
    return PresetContent(**base)  # type: ignore[arg-type]


class TestRouting:
    def test_first_matching_rule_wins(self) -> None:
        content = _content(
            rules=[
                PresetRule(
                    id="first",
                    match=PresetMatchConditions(categories=["video"]),
                    destination="First/{filename}",
                ),
                PresetRule(
                    id="second",
                    match=PresetMatchConditions(extensions=[".mov"]),
                    destination="Second/{filename}",
                ),
            ]
        )
        routing = route(content, _facts("a.mov"))
        assert routing.dest_rel == "First/a.mov"
        assert routing.matched_rule == "rule:first"

    def test_an_unmatched_file_goes_to_the_fallback_never_nowhere(self) -> None:
        """§6.2: unknown files are copied to the fallback or explicitly
        excluded — never silently omitted."""
        routing = route(_content(), _facts("odd/thing.zzz"))
        assert routing.dest_rel == "Unsorted/Card A/odd/thing.zzz"
        assert routing.matched_rule == "fallback"

    def test_a_rule_needing_a_missing_date_falls_back_with_a_warning(self) -> None:
        content = _content(
            rules=[
                PresetRule(
                    id="dated",
                    match=PresetMatchConditions(categories=["video"]),
                    destination="{year}/{filename}",
                )
            ]
        )
        routing = route(content, _facts("a.mov", mtime=None))
        assert routing.matched_rule == "fallback"
        assert routing.warnings and "no usable modification time" in routing.warnings[0]

    def test_a_fallback_that_cannot_render_is_an_error_not_a_silent_drop(self) -> None:
        content = _content(fallbackTemplate="{year}/{filename}")
        with pytest.raises(RuleError, match="fallback must be renderable"):
            route(content, _facts("a.mov", mtime=None))


class TestGroups:
    """§6.3: a kept-together subtree routes as a unit."""

    @staticmethod
    def _grouped() -> PresetContent:
        return _content(
            rules=[
                PresetRule(
                    id="docs",
                    match=PresetMatchConditions(categories=["document"]),
                    destination="Docs/{filename}",
                ),
                PresetRule(
                    id="video",
                    match=PresetMatchConditions(categories=["video"]),
                    destination="Video/{filename}",
                ),
            ],
            groups=[
                PresetGroup(
                    id="cards",
                    match=PresetMatchConditions(pathGlob="DCIM"),
                    destination="Cards/{source_label}/{filename}",
                )
            ],
        )

    def test_a_group_beats_the_rules_that_would_split_it(self) -> None:
        """The sidecar must not be pulled out of the card by an extension rule."""
        content = self._grouped()
        movie = route(content, _facts("DCIM/100/A001.MOV"))
        sidecar = route(content, _facts("DCIM/100/A001.XML"))
        assert movie.dest_rel == "Cards/Card A/DCIM/100/A001.MOV"
        assert sidecar.dest_rel == "Cards/Card A/DCIM/100/A001.XML"
        assert sidecar.group_id == "cards"
        # Outside the group the ordinary rules still apply.
        assert route(content, _facts("loose.pdf")).dest_rel == "Docs/loose.pdf"

    def test_descendants_keep_their_internal_structure(self) -> None:
        routing = route(self._grouped(), _facts("DCIM/100/sub/deep/A.MOV"))
        assert routing.dest_rel == "Cards/Card A/DCIM/100/sub/deep/A.MOV"

    def test_the_outermost_group_wins(self) -> None:
        """A group inside a group must not split the parent apart."""
        content = _content(
            groups=[
                PresetGroup(
                    id="inner",
                    match=PresetMatchConditions(pathGlob="Project/Assets"),
                    destination="Inner/{filename}",
                ),
                PresetGroup(
                    id="outer",
                    match=PresetMatchConditions(pathGlob="Project"),
                    destination="Outer/{filename}",
                ),
            ]
        )
        routing = route(content, _facts("Project/Assets/a.mov"))
        assert routing.group_id == "outer"
        assert routing.dest_rel == "Outer/Project/Assets/a.mov"

    def test_a_group_glob_matches_directories_not_files(self) -> None:
        """A group claims a subtree; a file is claimed by being inside one."""
        assert (
            find_group(
                [
                    PresetGroup(
                        id="g",
                        match=PresetMatchConditions(pathGlob="Bundle.app"),
                        destination="X/{filename}",
                    )
                ],
                "Bundle.app/Contents/Info.plist",
            )
            is not None
        )
        assert (
            find_group(
                [
                    PresetGroup(
                        id="g",
                        match=PresetMatchConditions(pathGlob="Bundle.app"),
                        destination="X/{filename}",
                    )
                ],
                "Bundle.app",
            )
            is None
        ), "the group root itself is the folder, not an entry inside it"


class TestGlobDialect:
    """R20: the glob dialect is a contract, not an implementation detail.

    A preset author has to be able to predict which files a pattern
    claims. These pin the answers so a change to the matcher is a
    deliberate, visible decision rather than a silent re-routing of
    everybody's saved presets.
    """

    def test_separators_are_always_forward_slashes(self) -> None:
        assert path_glob_matches("DCIM/100", "DCIM/100")
        assert path_glob_matches("DCIM\\100", "DCIM/100"), "a backslash reads as a separator"
        assert path_glob_matches("/DCIM/", "DCIM"), "leading and trailing slashes are ignored"

    def test_matching_is_case_insensitive(self) -> None:
        assert path_glob_matches("dcim/*", "DCIM/A001.MOV")
        assert path_glob_matches("DCIM/*", "dcim/a001.mov")

    def test_star_spans_separators_and_there_is_no_double_star(self) -> None:
        """One wildcard means "anything, separators included"."""
        assert path_glob_matches("DCIM/*", "DCIM/100MEDIA/A001.MOV")
        assert path_glob_matches("*.mov", "a/b/c/deep.mov")
        assert path_glob_matches("**/x", "a/b/x"), "** is not a distinct construct"

    def test_question_mark_and_character_classes(self) -> None:
        assert path_glob_matches("IMG_00?.JPG", "IMG_001.JPG")
        assert path_glob_matches("IMG_00[12].JPG", "IMG_002.JPG")
        assert not path_glob_matches("IMG_00[12].JPG", "IMG_003.JPG")

    def test_a_pattern_naming_a_directory_does_not_claim_its_children(self) -> None:
        assert path_glob_matches("DCIM", "DCIM")
        assert not path_glob_matches("DCIM", "DCIM/A001.MOV")


class TestGroupRootRouting:
    """R17: the group's own root directory belongs to the group."""

    @staticmethod
    def _content() -> PresetContent:
        return _content(
            groups=[
                PresetGroup(
                    id="proj",
                    match=PresetMatchConditions(pathGlob="Proj"),
                    destination="Collections/{source_label}/{relative_dir}/{filename}",
                )
            ]
        )

    def test_the_group_root_directory_routes_via_the_group(self) -> None:
        """It used to go through the fallback and leave a stray folder."""
        routing = route(self._content(), _facts("Proj", entry_type="dir"))
        assert routing.dest_rel == "Collections/Card A/Proj"
        assert routing.group_id == "proj"
        assert routing.group_root == "Proj"
        assert routing.group_dest_root == "Collections/Card A/Proj"

    def test_a_directory_inside_the_group_still_routes_beneath_it(self) -> None:
        routing = route(self._content(), _facts("Proj/Media", entry_type="dir"))
        assert routing.dest_rel == "Collections/Card A/Proj/Media"
        assert routing.group_root == "Proj"

    def test_a_file_is_never_its_own_group_root(self) -> None:
        """A group claims a directory; a file is claimed by being inside one."""
        content = _content(
            groups=[
                PresetGroup(
                    id="g",
                    match=PresetMatchConditions(pathGlob="loose.mov"),
                    destination="X/{filename}",
                )
            ]
        )
        assert route(content, _facts("loose.mov")).matched_rule == "fallback"

    def test_every_member_shares_one_group_destination_root(self) -> None:
        """The template is evaluated once, for the root (examples §4)."""
        content = self._content()
        roots = {
            route(content, _facts(rel, entry_type=kind)).group_dest_root
            for rel, kind in (
                ("Proj", "dir"),
                ("Proj/Media", "dir"),
                ("Proj/Media/a.wav", "file"),
                ("Proj/edit.drp", "file"),
            )
        }
        assert roots == {"Collections/Card A/Proj"}


class TestPresetExclusions:
    """R15: an exclusion rule the user saved has to actually apply."""

    @staticmethod
    def _with(*exclusions: PresetExclusion) -> PresetContent:
        return _content(exclusions=list(exclusions))

    def test_an_extension_exclusion_claims_its_files(self) -> None:
        content = self._with(
            PresetExclusion(
                id="tmp", reason="scratch files", match=PresetMatchConditions(extensions=[".tmp"])
            )
        )
        assert find_exclusion(content, _facts("work/junk.tmp")) is not None
        assert find_exclusion(content, _facts("work/keep.mov")) is None

    def test_glob_and_category_exclusions_work_the_same_way(self) -> None:
        content = self._with(
            PresetExclusion(
                id="caches",
                reason="render caches",
                match=PresetMatchConditions(pathGlob="*/Cache/*"),
            ),
            PresetExclusion(
                id="archives",
                reason="not wanted on this destination",
                match=PresetMatchConditions(categories=["archive"]),
            ),
        )
        assert find_exclusion(content, _facts("a/Cache/b.dat")).id == "caches"
        assert find_exclusion(content, _facts("loose/backup.zip")).id == "archives"
        assert find_exclusion(content, _facts("loose/clip.mov")) is None

    def test_the_first_matching_exclusion_wins_and_carries_its_reason(self) -> None:
        content = self._with(
            PresetExclusion(
                id="first", reason="first reason", match=PresetMatchConditions(extensions=[".tmp"])
            ),
            PresetExclusion(
                id="second",
                reason="second reason",
                match=PresetMatchConditions(extensions=[".tmp"]),
            ),
        )
        found = find_exclusion(content, _facts("x.tmp"))
        assert found.id == "first" and found.reason == "first reason"

    def test_exclusions_apply_inside_preserved_groups_too(self) -> None:
        """An explicit rule does not stop at a group boundary.

        It is surfaced in review when it takes a member out of a group,
        which is the part that matters: losing a sidecar out of a
        preserved subtree should be visible before the transfer.
        """
        content = _content(
            groups=[
                PresetGroup(
                    id="proj",
                    match=PresetMatchConditions(pathGlob="Proj"),
                    destination="Collections/{filename}",
                )
            ],
            exclusions=[
                PresetExclusion(
                    id="tmp",
                    reason="scratch files",
                    match=PresetMatchConditions(extensions=[".tmp"]),
                )
            ],
        )
        assert find_exclusion(content, _facts("Proj/render.tmp")) is not None
