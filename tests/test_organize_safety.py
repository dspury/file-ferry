"""P1 safety regressions for the destination-presets spec (§2, §9-P1).

Each test reproduces a confirmed baseline defect and pins the safe
behavior:

- overwrite: organize replaced an existing destination file silently.
- truncation: source.inspect reported 5,001 files but returned 5,000.
- traversal: a template root of ``../outside`` escaped the destination.
- false verification: move unlinked without comparing; copy reported ok
  without reading anything back.

These are behavior tests against the shared application layer; the
desktop UI is downstream of it.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from file_ferry.application.organize import OrganizeError, OrganizeService
from file_ferry.application.sources import SourceService
from file_ferry.application.transfer_safety import (
    DestinationExistsError,
    SourceChangedError,
    UnsafeDestinationError,
    copy_file_verified,
    existing_destination_collisions,
    publish_exclusive,
    render_destination,
    validate_relpath,
)
from file_ferry.service.protocol import (
    OrganizePreviewParams,
    SourceInspectParams,
    SourceInventoryEntry,
)


def _make_tree(root: Path, count: int, *, content: bytes = b"x") -> None:
    root.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        sub = root / f"CL{i // 50:03d}"
        sub.mkdir(exist_ok=True)
        (sub / f"A{i % 50:04d}.mov").write_bytes(content)


def _entries_for(root: Path, count: int) -> list[SourceInventoryEntry]:
    return [
        SourceInventoryEntry(path=f"CL{i // 50:03d}/A{i % 50:04d}.mov", size=1, mtime=1.0)
        for i in range(count)
    ]


# ---- overwrite (A02-shaped) ------------------------------------------


class TestOverwriteRefused:
    def test_preview_reports_existing_destination_file(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        _make_tree(src, 2)
        dest = tmp_path / "dest"
        _make_tree(dest, 1, content=b"different-owner")
        preview = OrganizeService().preview(
            OrganizePreviewParams(
                sourceRoot=str(src),
                destRoot=str(dest),
                entries=_entries_for(src, 2),
                mode="copy",
            )
        )
        reasons = {c.reason for c in preview.collisions}
        assert "existing_file" in reasons

    def test_copy_never_replaces_an_existing_destination(self, tmp_path: Path) -> None:
        # Direct primitive-level guarantee: publication is exclusive no
        # matter what a caller did between planning and copying (A09). This
        # is the guarantee TransferRunner relies on at execute time; the
        # `organize.apply` RPC path that also relied on it was withdrawn in
        # R-3, but the primitive is unchanged and still the one under test.
        src = tmp_path / "src.bin"
        src.write_bytes(b"new-content")
        dest = tmp_path / "dest.bin"
        dest.write_bytes(b"pre-existing")
        with pytest.raises(DestinationExistsError):
            copy_file_verified(src, dest)
        assert dest.read_bytes() == b"pre-existing"
        assert not list(tmp_path.glob("*.ferry-part"))

    def test_ancestor_file_conflict_detected(self, tmp_path: Path) -> None:
        dest = tmp_path / "dest"
        dest.mkdir()
        (dest / "A").write_bytes(b"file-where-dir-should-go")
        collisions = existing_destination_collisions(dest, [str(dest / "A" / "B.mov")])
        assert collisions == {str(dest / "A"): "ancestor_is_file"}

    def test_existing_directory_conflict_detected(self, tmp_path: Path) -> None:
        dest = tmp_path / "dest"
        (dest / "A.mov").mkdir(parents=True)
        collisions = existing_destination_collisions(dest, [str(dest / "A.mov")])
        assert collisions == {str(dest / "A.mov"): "existing_directory"}


# ---- truncation (A01-shaped) -----------------------------------------


class TestNoSilentCap:
    def _svc(self, tmp_path: Path) -> SourceService:
        from file_ferry.application.service import ApplicationService

        db_path = tmp_path / "ferry.db"
        boot = ApplicationService(db_path=db_path, app_data_dir=tmp_path / "app")
        boot.bootstrap()
        boot.close()
        return SourceService(db_path=db_path)

    def test_inspect_returns_every_entry(self, tmp_path: Path) -> None:
        root = tmp_path / "big"
        _make_tree(root, 5_001)
        svc = self._svc(tmp_path)
        result = svc.inspect(SourceInspectParams(path=str(root)))
        assert result.file_count == 5_001
        assert len(result.entries) == 5_001
        assert result.truncated is False

    def test_explicit_cap_is_flagged_and_counted(self, tmp_path: Path) -> None:
        root = tmp_path / "big"
        _make_tree(root, 10)
        svc = self._svc(tmp_path)
        result = svc.inspect(SourceInspectParams(path=str(root)), max_entries=4)
        assert result.file_count == 10
        assert len(result.entries) == 4
        assert result.truncated is True


# ---- traversal (A06-shaped) ------------------------------------------


class TestTraversalRejected:
    def test_template_root_dotdot_rejected(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        _make_tree(src, 1)
        dest = tmp_path / "dest"
        dest.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        with pytest.raises((UnsafeDestinationError, OrganizeError)):
            OrganizeService().preview(
                OrganizePreviewParams(
                    sourceRoot=str(src),
                    destRoot=str(dest),
                    entries=_entries_for(src, 1),
                    template={"root": "../outside"},
                    mode="copy",
                )
            )
        assert list(outside.iterdir()) == []

    def test_absolute_template_root_rejected(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        _make_tree(src, 1)
        dest = tmp_path / "dest"
        dest.mkdir()
        with pytest.raises((UnsafeDestinationError, OrganizeError)):
            OrganizeService().preview(
                OrganizePreviewParams(
                    sourceRoot=str(src),
                    destRoot=str(dest),
                    entries=_entries_for(src, 1),
                    template={"root": str(tmp_path)},
                    mode="copy",
                )
            )

    def test_relpath_validation_rejects_bad_paths(self) -> None:
        for bad in ("../escape", "/abs", "a/../../b", "C:\\win", "nul\x00byte"):
            with pytest.raises(UnsafeDestinationError):
                validate_relpath(bad)

    def test_render_destination_rejects_symlink_escape(self, tmp_path: Path) -> None:
        root = tmp_path / "root"
        (root / "sub").mkdir(parents=True)
        outside = tmp_path / "outside"
        outside.mkdir()
        (root / "link").symlink_to(outside)
        with pytest.raises(UnsafeDestinationError):
            render_destination(root, "link/escaped.txt")
        assert list(outside.iterdir()) == []

    def test_render_destination_allows_symlink_inside_root(self, tmp_path: Path) -> None:
        root = tmp_path / "root"
        (root / "real").mkdir(parents=True)
        (root / "link").symlink_to(root / "real", target_is_directory=True)
        dest = render_destination(root, "link/file.txt")
        assert dest == root / "link" / "file.txt"


# ---- false verification ----------------------------------------------


class TestVerifiedCopy:
    def test_success_carries_checksums(self, tmp_path: Path) -> None:
        src = tmp_path / "src.bin"
        src.write_bytes(b"payload")
        dest = tmp_path / "dest.bin"
        verification = copy_file_verified(src, dest)
        assert verification.bytes_copied == 7
        assert verification.source_checksum == verification.dest_checksum
        assert verification.mtime_preserved

    def test_source_changed_during_copy_fails(self, tmp_path: Path) -> None:
        src = tmp_path / "src.bin"
        src.write_bytes(b"a" * (1024 * 1024 * 2))
        dest = tmp_path / "dest.bin"
        state = {"calls": 0}

        def mutate_then_report_false() -> bool:
            state["calls"] += 1
            if state["calls"] == 1:
                # Simulate an external edit mid-copy: mtime moves.
                os.utime(src, ns=(0, 0))
            return False

        with pytest.raises(SourceChangedError):
            copy_file_verified(src, dest, cancel_check=mutate_then_report_false)
        assert not dest.exists()

    def test_cancellation_leaves_nothing_behind(self, tmp_path: Path) -> None:
        src = tmp_path / "src.bin"
        src.write_bytes(b"a" * (1024 * 1024 * 3))
        dest = tmp_path / "dest.bin"
        from file_ferry.application.transfer_safety import _Cancelled

        with pytest.raises(_Cancelled):
            copy_file_verified(src, dest, cancel_check=lambda: True)
        assert not dest.exists()
        assert not list(tmp_path.glob("*.ferry-part"))
        assert src.read_bytes() == b"a" * (1024 * 1024 * 3)

    def test_publish_exclusive_cleans_temp_on_conflict(self, tmp_path: Path) -> None:
        tmp = tmp_path / "tmp.ferry-part"
        tmp.write_bytes(b"data")
        dest = tmp_path / "dest.bin"
        dest.write_bytes(b"existing")
        with pytest.raises(DestinationExistsError):
            publish_exclusive(tmp, dest)
        assert dest.read_bytes() == b"existing"
        # The temp sibling is cleaned up either way.
        assert not tmp.exists()


class TestScanErrorsFailClosed:
    """R08: recording scan errors does not by itself stop a partial transfer.

    ``source.inspect`` grew an ``errorCount`` in P1, but ``organize.*``
    takes a caller-supplied entry list, so a client that forwards only
    ``inspected.entries`` hands over a silently partial set and gets a
    green result for a transfer that left files behind. The backend has
    to refuse; renderer validation alone is not the guarantee.
    """

    @staticmethod
    def _tree_with_unreadable_subdir(tmp_path: Path) -> tuple[Path, Path]:
        src = tmp_path / "src"
        src.mkdir()
        (src / "good.mov").write_bytes(b"x")
        locked = src / "locked"
        locked.mkdir()
        (locked / "deep.mov").write_bytes(b"x")
        locked.chmod(0o000)
        dest = tmp_path / "dest"
        dest.mkdir()
        return src, dest

    def test_preview_refuses_an_unreadable_source(self, tmp_path: Path) -> None:
        src, dest = self._tree_with_unreadable_subdir(tmp_path)
        try:
            with pytest.raises(OrganizeError, match="could not be fully accounted for"):
                OrganizeService().preview(
                    OrganizePreviewParams(
                        sourceRoot=str(src),
                        destRoot=str(dest),
                        entries=[SourceInventoryEntry(path="good.mov", size=1, mtime=0.0)],
                    )
                )
        finally:
            (src / "locked").chmod(0o755)

    def test_preview_refuses_unsupported_objects(self, tmp_path: Path) -> None:
        """§6.3: symlinks are flagged, never quietly skipped past.

        The refusal has to say *which* path stopped it — a message that
        only says "unsupported object" leaves the operator guessing at a
        tree of thousands.
        """
        src = tmp_path / "src"
        src.mkdir()
        (src / "real.mov").write_bytes(b"x")
        (src / "DCIM").mkdir()
        (src / "DCIM" / "link.mov").symlink_to(src / "real.mov")
        dest = tmp_path / "dest"
        dest.mkdir()
        with pytest.raises(OrganizeError) as caught:
            OrganizeService().preview(
                OrganizePreviewParams(
                    sourceRoot=str(src),
                    destRoot=str(dest),
                    entries=[SourceInventoryEntry(path="real.mov", size=1, mtime=0.0)],
                )
            )
        message = str(caught.value)
        assert "1 symlink inside the source tree" in message
        assert str(src / "DCIM" / "link.mov") in message, "the offending path is named"
        assert "alias for a mount point is fine" in message, (
            "the message distinguishes a symlinked source *root* from links inside it"
        )
        assert "Nothing was written" in message
        assert list(dest.iterdir()) == []

    def test_a_symlinked_source_root_is_not_a_finding(self, tmp_path: Path) -> None:
        """Selecting an alias for a mount is ordinary, not a finding.

        The restriction is about links *inside* the tree. P3 handles
        root-level mount aliases as an identity question; blanket
        dereferencing is never the answer to either.
        """
        real = tmp_path / "real_mount"
        real.mkdir()
        (real / "a.mov").write_bytes(b"a")
        alias = tmp_path / "alias"
        alias.symlink_to(real, target_is_directory=True)
        dest = tmp_path / "dest"
        dest.mkdir()
        preview = OrganizeService().preview(
            OrganizePreviewParams(
                sourceRoot=str(alias),
                destRoot=str(dest),
                entries=[SourceInventoryEntry(path="a.mov", size=1, mtime=0.0)],
            )
        )
        assert [e.dest_path for e in preview.entries] == [str(dest.resolve() / "a.mov")]

    def test_preview_refuses_a_partial_entry_list(self, tmp_path: Path) -> None:
        """A truncated or stale list must not narrow the operation silently."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.mov").write_bytes(b"a")
        (src / "b.mov").write_bytes(b"b")
        dest = tmp_path / "dest"
        dest.mkdir()
        with pytest.raises(OrganizeError, match="does not account for the whole source"):
            OrganizeService().preview(
                OrganizePreviewParams(
                    sourceRoot=str(src),
                    destRoot=str(dest),
                    entries=[SourceInventoryEntry(path="a.mov", size=1, mtime=0.0)],
                )
            )
        assert list(dest.iterdir()) == []

    def test_a_clean_source_previews(self, tmp_path: Path) -> None:
        """The gate must not block ordinary work."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.mov").write_bytes(b"a")
        dest = tmp_path / "dest"
        dest.mkdir()
        preview = OrganizeService().preview(
            OrganizePreviewParams(
                sourceRoot=str(src),
                destRoot=str(dest),
                entries=[SourceInventoryEntry(path="a.mov", size=1, mtime=0.0)],
            )
        )
        assert [e.dest_path for e in preview.entries] == [str(dest.resolve() / "a.mov")]

    def test_the_intake_planner_refuses_an_unaccounted_source(self, tmp_path: Path) -> None:
        """The compatibility planner used a files-only scan (R08)."""
        from file_ferry.application.plan import PlanError
        from file_ferry.application.service import ApplicationService
        from file_ferry.service.protocol import (
            BuildPlanParams,
            CreateProjectParams,
        )

        src = tmp_path / "card"
        src.mkdir()
        (src / "real.mov").write_bytes(b"x")
        (src / "link.mov").symlink_to(src / "real.mov")
        (tmp_path / "work").mkdir()

        service = ApplicationService(db_path=tmp_path / "ferry.db", app_data_dir=tmp_path / "app")
        service.bootstrap()
        try:
            project_id = service.create_project(
                CreateProjectParams(name="P", workingRoot=str(tmp_path / "work"))
            )
            inspected = service.source_inspect(SourceInspectParams(path=str(src), kind="card"))
            assert inspected.error_count == 0
            assert len(inspected.non_files) == 1, "the symlink is a finding, not a silence"
            with pytest.raises(PlanError, match="symlink inside the source tree"):
                service.plan_build(
                    BuildPlanParams(
                        projectId=project_id,
                        sourceId=inspected.source_id,
                        destinations=[
                            {"kind": "working", "rootPath": str(tmp_path / "work")}  # type: ignore[list-item]
                        ],
                    )
                )
        finally:
            service.shutdown()
            service.close()
