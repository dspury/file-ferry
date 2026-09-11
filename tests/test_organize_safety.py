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
    OrganizeApplyParams,
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

    def test_apply_refuses_and_keeps_existing_content(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        _make_tree(src, 2)
        dest = tmp_path / "dest"
        _make_tree(dest, 1, content=b"different-owner")
        with pytest.raises(OrganizeError, match="collisions detected"):
            OrganizeService().apply(
                OrganizeApplyParams(
                    sourceRoot=str(src),
                    destRoot=str(dest),
                    entries=_entries_for(src, 2),
                    mode="copy",
                )
            )
        # The pre-existing file was not replaced and nothing else landed.
        assert (dest / "CL000/A0000.mov").read_bytes() == b"different-owner"
        assert not (dest / "CL000/A0001.mov").exists()

    def test_apply_never_replaces_even_without_preview(self, tmp_path: Path) -> None:
        # Direct primitive-level guarantee: publication is exclusive no
        # matter what the caller did between preview and apply (A09).
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
