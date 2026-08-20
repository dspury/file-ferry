"""Source service — read-only intake scanning."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ferry.application.sources import SourceService
from ferry.service.protocol import SourceInspectParams


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
    from ferry.application.service import ApplicationService

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
