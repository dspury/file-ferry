"""vNext organization service (plan §4.3, §7.3).

Move/link apply modes are disabled pending the verified-transfer safety
contract (destination-presets spec §1.2); copy is exclusive and
checksum-verified. These tests pin that contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from file_ferry.application.organize import OrganizeError, OrganizeService
from file_ferry.service.protocol import (
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


def _dest(tmp_path: Path) -> Path:
    dest = tmp_path / "project" / "org"
    dest.mkdir(parents=True)
    return dest


def test_preview_builds_tree(tmp_path: Path) -> None:
    src = _make_source(tmp_path)
    dest = _dest(tmp_path)
    preview = _svc().preview(
        OrganizePreviewParams(sourceRoot=str(src), destRoot=str(dest), entries=ENTRIES, mode="copy")
    )
    assert len(preview.entries) == 2
    assert preview.total_bytes == 7
    assert preview.collisions == []
    # Destinations are reported against the resolved root: what the
    # preview shows is exactly where the bytes will go.
    resolved = dest.resolve()
    paths = {e.dest_path for e in preview.entries}
    assert paths == {
        str(resolved / "Interview/A001.mov"),
        str(resolved / "Interview/A002.mov"),
    }


def test_apply_copy_default(tmp_path: Path) -> None:
    src = _make_source(tmp_path)
    dest = _dest(tmp_path)
    result = _svc().apply(
        OrganizeApplyParams(sourceRoot=str(src), destRoot=str(dest), entries=ENTRIES, mode="copy")
    )
    assert all(e.ok for e in result.entries)
    assert (src / "Interview/A001.mov").exists()
    assert (dest / "Interview/A001.mov").read_bytes() == b"123"
    # Success without verification evidence is one of the confirmed
    # baseline defects; every ok outcome must now carry its checksums.
    for outcome in result.entries:
        assert outcome.ok
        assert outcome.verification is not None
        assert outcome.verification["sourceChecksum"] == outcome.verification["destChecksum"]
        assert outcome.verification["checksumAlgo"] in ("xxhash64", "sha256")


def test_move_is_disabled_with_actionable_error(tmp_path: Path) -> None:
    src = _make_source(tmp_path)
    dest = _dest(tmp_path)
    with pytest.raises(OrganizeError, match="organize move is disabled"):
        _svc().apply(
            OrganizeApplyParams(
                sourceRoot=str(src), destRoot=str(dest), entries=ENTRIES, mode="move"
            )
        )


def test_move_with_confirmation_is_still_disabled(tmp_path: Path) -> None:
    # The old confirm_move gate is not sufficient: move unlinked the
    # source without any checksum comparison (spec §2). Elevated
    # confirmation must not resurrect it.
    src = _make_source(tmp_path)
    dest = _dest(tmp_path)
    with pytest.raises(OrganizeError, match="organize move is disabled"):
        _svc().apply(
            OrganizeApplyParams(
                sourceRoot=str(src),
                destRoot=str(dest),
                entries=ENTRIES,
                mode="move",
                confirmMove=True,
            )
        )
    assert (src / "Interview/A001.mov").exists()
    assert not (dest / "Interview/A001.mov").exists()


def test_link_is_disabled_with_actionable_error(tmp_path: Path) -> None:
    src = _make_source(tmp_path)
    dest = _dest(tmp_path)
    with pytest.raises(OrganizeError, match="organize link is disabled"):
        _svc().apply(
            OrganizeApplyParams(
                sourceRoot=str(src), destRoot=str(dest), entries=ENTRIES, mode="link"
            )
        )
    assert not (dest / "Interview/A001.mov").exists()
