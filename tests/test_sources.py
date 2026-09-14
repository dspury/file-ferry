"""Source service — read-only intake scanning."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from file_ferry.application.sources import SourceService
from file_ferry.service.protocol import SourceInspectParams


@pytest.fixture
def source_tree(tmp_path: Path) -> Path:
    root = tmp_path / "card"
    (root / "DCIM").mkdir(parents=True)
    (root / "DCIM" / "100MEDIA").mkdir()
    (root / "DCIM" / "100MEDIA" / "A001.mov").write_bytes(b"video-bytes")
    (root / "DCIM" / "100MEDIA" / "A002.mov").write_bytes(b"more-video")
    # System artifacts must be excluded.
    (root / ".DS_Store").write_bytes(b"junk")
    (root / "DCIM" / "100MEDIA" / "._A001.mov").write_bytes(b"appledouble")
    (root / "__MACOSX").mkdir()
    (root / "__MACOSX" / "._A001.mov").write_bytes(b"junk")
    return root


def _svc(tmp_path: Path) -> SourceService:
    db_path = tmp_path / "ferry.db"
    # Bootstrap the schema (migration 001 + 002) before using the source repo.
    from file_ferry.application.service import ApplicationService

    boot = ApplicationService(db_path=db_path, app_data_dir=tmp_path / "app")
    boot.bootstrap()
    boot.close()
    return SourceService(db_path=db_path)


def test_inspect_scans_without_writing(tmp_path: Path, source_tree: Path) -> None:
    svc = _svc(tmp_path)
    result = svc.inspect(SourceInspectParams(path=str(source_tree), kind="card", label="CFExpress"))
    assert result.kind == "card"
    assert result.label == "CFExpress"
    assert result.file_count == 2  # only the two .mov files
    assert result.total_bytes == len(b"video-bytes") + len(b"more-video")
    paths = {e.path for e in result.entries}
    assert paths == {"DCIM/100MEDIA/A001.mov", "DCIM/100MEDIA/A002.mov"}
    assert len(result.manifest_hash) == 64


def test_inspect_persists_source_row(tmp_path: Path, source_tree: Path) -> None:
    svc = _svc(tmp_path)
    result = svc.inspect(SourceInspectParams(path=str(source_tree), kind="card"))
    with sqlite3.connect(tmp_path / "ferry.db") as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM sources WHERE id = ?", (result.source_id,)).fetchone()
        assert row is not None
        assert row["kind"] == "card"
        assert row["status"] == "scanned"
        assert row["manifest_hash"] == result.manifest_hash
        assert row["file_count"] == 2


def test_inspect_is_idempotent_per_path(tmp_path: Path, source_tree: Path) -> None:
    svc = _svc(tmp_path)
    a = svc.inspect(SourceInspectParams(path=str(source_tree), kind="card"))
    b = svc.inspect(SourceInspectParams(path=str(source_tree), kind="card"))
    assert a.source_id == b.source_id
    assert a.manifest_hash == b.manifest_hash


def test_inspect_missing_path_raises(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    with pytest.raises(FileNotFoundError):
        svc.inspect(SourceInspectParams(path=str(tmp_path / "nope"), kind="card"))


def test_inspect_rejects_non_directory(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    f = tmp_path / "file.txt"
    f.write_text("hi")
    with pytest.raises(NotADirectoryError):
        svc.inspect(SourceInspectParams(path=str(f), kind="card"))


# ---- A07: scan failures + unsupported objects are visible, not hidden ---


def test_scan_flags_symlink_entries(tmp_path: Path) -> None:
    root = tmp_path / "media"
    root.mkdir()
    (root / "A.mov").write_bytes(b"video")
    (root / "link.mov").symlink_to(root / "A.mov")
    svc = _svc(tmp_path)
    result = svc.inspect(SourceInspectParams(path=str(root)))
    by_path = {e.path: e.entry_type for e in result.entries}
    assert by_path["A.mov"] == "file"
    non_by_path = {e.path: e.entry_type for e in result.non_files}
    assert non_by_path["link.mov"] == "symlink"
    # The file count does not silently include the symlink.
    assert result.file_count == 1


def test_scan_flags_unsupported_objects(tmp_path: Path) -> None:
    root = tmp_path / "media"
    root.mkdir()
    (root / "A.mov").write_bytes(b"video")
    fifo = root / "fifo"
    os.mkfifo(str(fifo))
    svc = _svc(tmp_path)
    result = svc.inspect(SourceInspectParams(path=str(root)))
    non_by_path = {e.path: e.entry_type for e in result.non_files}
    assert non_by_path["fifo"] == "other"


def test_scan_flags_broken_symlinks_as_symlinks(tmp_path: Path) -> None:
    # A broken symlink lstats successfully and is reported as a symlink
    # entry — never silently skipped, never counted as a regular file.
    root = tmp_path / "media"
    root.mkdir()
    (root / "A.mov").write_bytes(b"v")
    broken = root / "broken_link.mov"
    broken.symlink_to(root / "nope.mov")
    svc = _svc(tmp_path)
    result = svc.inspect(SourceInspectParams(path=str(root)))
    by_path = {e.path: e.entry_type for e in result.non_files}
    assert by_path["broken_link.mov"] == "symlink"
    assert result.file_count == 1
    assert result.error_count == 0


def test_scan_records_unreadable_subtree(tmp_path: Path) -> None:
    # Removing execute permission on a child directory causes os.walk to
    # fail with EACCES when it tries to descend. The scanner records the
    # failure as a scan error rather than reporting a zero-error scan.
    root = tmp_path / "media"
    root.mkdir()
    (root / "A.mov").write_bytes(b"v")
    locked = root / "locked"
    locked.mkdir()
    (locked / "inside.mov").write_bytes(b"deep")
    locked.chmod(0o000)
    try:
        svc = _svc(tmp_path)
        result = svc.inspect(SourceInspectParams(path=str(root)))
        # The accessible file is still inventoried; the inaccessible subtree
        # contributes at least one error finding (file count, not strictly
        # errorCount, because chmod only denies descent in some configurations).
        assert result.file_count == 1
        assert result.error_count >= 1
        assert any("locked" in s for s in result.scan_errors)
    finally:
        # Restoring must cover *every* assertion, not just the last one.
        # A failure before the old try-block left the directory
        # unreadable, so pytest could not clean up its temp root and each
        # run accumulated another undeletable copy.
        locked.chmod(0o755)
