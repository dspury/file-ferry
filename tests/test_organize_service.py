"""vNext organization service (plan §4.3, §7.3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ferry.application.organize import OrganizeError, OrganizeService
from ferry.service.protocol import (
    OrganizeApplyParams,
    OrganizePreviewParams,
    SourceInventoryEntry,
)

ENTRIES = [
    SourceInventoryEntry(path="Interview/A001.mov", size=3, mtime=1.0),
    SourceInventoryEntry(path="Interview/A002.mov", size=4, mtime=2.0),
]


def _svc() -> OrganizeService:
    return OrganizeService()


def _make_source(tmp_path: Path) -> Path:
    root = tmp_path / "editor-drive"
    (root / "Interview").mkdir(parents=True)
    (root / "Interview" / "A001.mov").write_bytes(b"123")
    (root / "Interview" / "A002.mov").write_bytes(b"1234")
    return root


def test_preview_builds_tree(tmp_path: Path) -> None:
    src = _make_source(tmp_path)
    dest = tmp_path / "project" / "org"
    dest.mkdir(parents=True)
    preview = _svc().preview(
        OrganizePreviewParams(sourceRoot=str(src), destRoot=str(dest), entries=ENTRIES, mode="copy")
    )
    assert len(preview.entries) == 2
    assert preview.total_bytes == 7
    assert preview.collisions == []
    paths = {e.dest_path for e in preview.entries}
    assert paths == {
        str(dest / "Interview/A001.mov"),
        str(dest / "Interview/A002.mov"),
    }


def test_apply_copy_default(tmp_path: Path) -> None:
    src = _make_source(tmp_path)
    dest = tmp_path / "project" / "org"
    dest.mkdir(parents=True)
    result = _svc().apply(
        OrganizeApplyParams(sourceRoot=str(src), destRoot=str(dest), entries=ENTRIES, mode="copy")
    )
    assert all(e.ok for e in result.entries)
    assert (src / "Interview/A001.mov").exists()
    assert (dest / "Interview/A001.mov").read_bytes() == b"123"


def test_move_requires_confirmation(tmp_path: Path) -> None:
    src = _make_source(tmp_path)
    dest = tmp_path / "project" / "org"
    dest.mkdir(parents=True)
    with pytest.raises(OrganizeError, match="confirm_move"):
        _svc().apply(
            OrganizeApplyParams(
                sourceRoot=str(src), destRoot=str(dest), entries=ENTRIES, mode="move"
            )
        )


def test_apply_move_with_confirmation(tmp_path: Path) -> None:
    src = _make_source(tmp_path)
    dest = tmp_path / "project" / "org"
    dest.mkdir(parents=True)
    result = _svc().apply(
        OrganizeApplyParams(
            sourceRoot=str(src),
            destRoot=str(dest),
            entries=ENTRIES,
            mode="move",
            confirmMove=True,
        )
    )
    assert all(e.ok for e in result.entries)
    assert (dest / "Interview/A001.mov").exists()
    assert not (src / "Interview/A001.mov").exists()


def test_apply_link_same_volume(tmp_path: Path) -> None:
    src = _make_source(tmp_path)
    dest = tmp_path / "project" / "org"
    dest.mkdir(parents=True)
    result = _svc().apply(
        OrganizeApplyParams(sourceRoot=str(src), destRoot=str(dest), entries=ENTRIES, mode="link")
    )
    assert all(e.ok for e in result.entries)
    assert (dest / "Interview/A001.mov").read_bytes() == b"123"
    assert (src / "Interview/A001.mov").stat().st_ino == (dest / "Interview/A001.mov").stat().st_ino
