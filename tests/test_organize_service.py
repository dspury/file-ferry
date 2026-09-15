"""vNext organization preview (plan §4.3, §7.3).

R-3 withdrew the Organize screen and the ``organize.preview`` /
``organize.apply`` RPC methods. The previewer survives because
``profile.preview`` reuses it, and the exclusive, checksum-verified copy
contract moved wholly to ``transfer_safety`` / ``TransferRunner`` (see
``test_organize_safety.py`` and the transfer-runner suite for that half).
These tests pin the preview tree and destination rendering.
"""

from __future__ import annotations

from pathlib import Path

from file_ferry.application.organize import OrganizeService
from file_ferry.service.protocol import (
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
