"""Asset service tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from file_ferry.application.assets import AssetNotFoundError, AssetService
from file_ferry.service.protocol import SourceInventoryEntry

ENTRIES = [
    SourceInventoryEntry(path="DCIM/A001.mov", size=100, mtime=1.0),
    SourceInventoryEntry(path="DCIM/A002.mov", size=200, mtime=2.0),
]


@pytest.fixture
def service(tmp_path: Path) -> AssetService:
    from file_ferry.application.service import ApplicationService

    db = tmp_path / "ferry.db"
    boot = ApplicationService(db_path=db, app_data_dir=tmp_path / "app")
    boot.bootstrap()
    boot.close()
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO sources (kind, root_path, status, captured_at) "
            "VALUES ('card', '/tmp', 'scanned', 'now')"
        )
        conn.commit()
    return AssetService(db_path=db)


def test_adopt_creates_assets(service: AssetService) -> None:
    ids = service.adopt_source(source_id=1, entries=ENTRIES)
    assert len(ids) == 2
    assets = service.list()
    assert {a.source_relative_path for a in assets} == {"DCIM/A001.mov", "DCIM/A002.mov"}
    assert {a.source_id for a in assets} == {1}
    assert all(a.lifecycle_state == "discovered" for a in assets)


def test_adopt_is_idempotent(service: AssetService) -> None:
    ids1 = service.adopt_source(source_id=1, entries=ENTRIES)
    ids2 = service.adopt_source(source_id=1, entries=ENTRIES)
    assert ids1 == ids2
    assert len(service.list()) == 2


def test_get(service: AssetService) -> None:
    ids = service.adopt_source(source_id=1, entries=ENTRIES)
    asset = service.get(ids[0])
    assert asset.id == ids[0]
    assert asset.observed_size == 100


def test_get_missing_raises(service: AssetService) -> None:
    with pytest.raises(AssetNotFoundError):
        service.get("no-such-asset")
