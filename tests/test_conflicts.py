"""The conflict matrix and keep-both allocation (spec §6.4, A02/A05).

One rule underneath all of these: nothing is overwritten and nothing
disappears. Each conflict kind is kept distinct because they mean
different things to the person reviewing them — and because collapsing
them into "name taken" is how a case-only collision on a
case-insensitive share silently becomes one file instead of two.
"""

from __future__ import annotations

from pathlib import Path

from file_ferry.application.conflicts import (
    ANCESTOR_PATH,
    CASE_ONLY,
    EXISTING_DESTINATION,
    EXISTING_SYMLINK,
    FILE_VS_DIRECTORY,
    SAME_NAME_DIFFERENT_CONTENT,
    UNICODE_NORMALIZATION,
    Reservations,
    allocate,
    comparison_key,
    distinguish,
)


def _reservations(tmp_path: Path) -> Reservations:
    root = tmp_path / "dest"
    root.mkdir(exist_ok=True)
    return Reservations(dest_root=root)


class TestComparison:
    def test_case_and_normalization_fold_together(self) -> None:
        """Conservative by design: Ferry often cannot know what the target does."""
        assert comparison_key("IMG_001.JPG") == comparison_key("img_001.jpg")
        assert comparison_key("café.mov") == comparison_key("café.mov")

    def test_distinguish_names_the_difference(self) -> None:
        assert distinguish("a.mov", "a.mov") is None
        assert distinguish("A.mov", "a.mov") == CASE_ONLY
        assert distinguish("café.mov", "café.mov") == UNICODE_NORMALIZATION
        assert distinguish("a.mov", "b.mov") == SAME_NAME_DIFFERENT_CONTENT


class TestKeepBoth:
    def test_a_free_name_is_used_as_is(self, tmp_path: Path) -> None:
        result = allocate("Video/a.mov", _reservations(tmp_path), policy="keep_both")
        assert result.dest_rel == "Video/a.mov"
        assert result.conflict is None

    def test_a_second_claim_is_suffixed_deterministically(self, tmp_path: Path) -> None:
        reservations = _reservations(tmp_path)
        first = allocate("Video/a.mov", reservations, policy="keep_both")
        second = allocate("Video/a.mov", reservations, policy="keep_both")
        third = allocate("Video/a.mov", reservations, policy="keep_both")
        assert first.dest_rel == "Video/a.mov"
        assert second.dest_rel == "Video/a (2).mov"
        assert third.dest_rel == "Video/a (3).mov"
        assert second.renamed_from == "Video/a.mov"
        assert second.conflict == SAME_NAME_DIFFERENT_CONTENT

    def test_allocation_is_reproducible(self, tmp_path: Path) -> None:
        """The same plan must produce the same names every time."""

        def run() -> list[str]:
            reservations = _reservations(tmp_path)
            return [allocate("a.mov", reservations, policy="keep_both").dest_rel for _ in range(4)]

        assert run() == run()

    def test_existing_destination_content_is_reserved_against(self, tmp_path: Path) -> None:
        """A02: an existing file is never replaced, and never ignored."""
        reservations = _reservations(tmp_path)
        (reservations.dest_root / "a.mov").write_bytes(b"already here")
        result = allocate("a.mov", reservations, policy="keep_both")
        assert result.dest_rel == "a (2).mov"
        assert result.conflict == EXISTING_DESTINATION
        assert (reservations.dest_root / "a.mov").read_bytes() == b"already here"

    def test_keep_both_skips_over_existing_suffixed_names(self, tmp_path: Path) -> None:
        reservations = _reservations(tmp_path)
        (reservations.dest_root / "a.mov").write_bytes(b"1")
        (reservations.dest_root / "a (2).mov").write_bytes(b"2")
        assert allocate("a.mov", reservations, policy="keep_both").dest_rel == "a (3).mov"

    def test_a_broken_symlink_still_occupies_the_name(self, tmp_path: Path) -> None:
        """`exists()` says no; publication would still fail on it."""
        reservations = _reservations(tmp_path)
        (reservations.dest_root / "a.mov").symlink_to(tmp_path / "nothing")
        result = allocate("a.mov", reservations, policy="keep_both")
        assert result.dest_rel == "a (2).mov"
        assert result.conflict == EXISTING_SYMLINK

    def test_extensionless_names_suffix_correctly(self, tmp_path: Path) -> None:
        reservations = _reservations(tmp_path)
        allocate("README", reservations, policy="keep_both")
        assert allocate("README", reservations, policy="keep_both").dest_rel == "README (2)"


class TestDistinctConflictKinds:
    """A05: each of these is a different problem with a different answer."""

    def test_case_only_collision_is_reported_as_such(self, tmp_path: Path) -> None:
        reservations = _reservations(tmp_path)
        allocate("IMG_001.JPG", reservations, policy="keep_both")
        result = allocate("img_001.jpg", reservations, policy="keep_both")
        assert result.conflict == CASE_ONLY
        assert result.dest_rel != "img_001.jpg"
        assert result.detail is not None and "letter case" in result.detail

    def test_unicode_normalization_collision_is_reported_as_such(self, tmp_path: Path) -> None:
        reservations = _reservations(tmp_path)
        allocate("café.mov", reservations, policy="keep_both")
        result = allocate("café.mov", reservations, policy="keep_both")
        assert result.conflict == UNICODE_NORMALIZATION
        assert result.detail is not None and "normal forms" in result.detail

    def test_a_file_wanting_a_planned_directorys_name(self, tmp_path: Path) -> None:
        reservations = _reservations(tmp_path)
        allocate("Media", reservations, policy="keep_both", entry_type="dir")
        result = allocate("Media", reservations, policy="keep_both")
        assert result.conflict == FILE_VS_DIRECTORY

    def test_a_directory_wanting_an_existing_files_name(self, tmp_path: Path) -> None:
        reservations = _reservations(tmp_path)
        (reservations.dest_root / "Media").write_bytes(b"a file, not a folder")
        result = allocate("Media", reservations, policy="keep_both", entry_type="dir")
        assert result.conflict == FILE_VS_DIRECTORY

    def test_an_existing_destination_directory(self, tmp_path: Path) -> None:
        reservations = _reservations(tmp_path)
        (reservations.dest_root / "Media").mkdir()
        result = allocate("Media", reservations, policy="keep_both")
        assert result.conflict == FILE_VS_DIRECTORY

    def test_an_ancestor_path_conflict_cannot_be_suffixed_away(self, tmp_path: Path) -> None:
        """One entry's destination is inside another entry's file."""
        reservations = _reservations(tmp_path)
        allocate("Media/report.pdf", reservations, policy="keep_both")
        result = allocate("Media/report.pdf/page1.png", reservations, policy="keep_both")
        assert result.conflict == ANCESTOR_PATH
        assert result.renamed_from is None, "no suffix resolves this; it needs a decision"

    def test_several_sources_may_contribute_the_same_directory(self, tmp_path: Path) -> None:
        """Directories are created, not written over one another."""
        reservations = _reservations(tmp_path)
        first = allocate("Media", reservations, policy="keep_both", entry_type="dir")
        second = allocate("Media", reservations, policy="keep_both", entry_type="dir")
        assert first.conflict is None and second.conflict is None
        assert first.dest_rel == second.dest_rel == "Media"


class TestNonKeepBothPolicies:
    def test_needs_review_blocks_instead_of_allocating(self, tmp_path: Path) -> None:
        reservations = _reservations(tmp_path)
        allocate("a.mov", reservations, policy="needs_review")
        result = allocate("a.mov", reservations, policy="needs_review")
        assert result.conflict == SAME_NAME_DIFFERENT_CONTENT
        assert result.renamed_from is None
        assert result.dest_rel == "a.mov", "the name is not reassigned without a decision"

    def test_skip_identical_never_silently_skips(self, tmp_path: Path) -> None:
        """It needs checksum proof this layer does not have (§6.4)."""
        reservations = _reservations(tmp_path)
        (reservations.dest_root / "a.mov").write_bytes(b"same")
        result = allocate("a.mov", reservations, policy="skip_identical")
        assert result.conflict == EXISTING_DESTINATION
        assert result.renamed_from is None
