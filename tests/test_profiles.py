"""Organization-profile service tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from ferry.application.profiles import ProfileNotFoundError, ProfileService
from ferry.service.protocol import SaveProfileParams


@pytest.fixture
def service(tmp_path: Path) -> ProfileService:
    from ferry.application.service import ApplicationService

    db = tmp_path / "ferry.db"
    boot = ApplicationService(db_path=db, app_data_dir=tmp_path / "app")
    boot.bootstrap()
    boot.close()
    return ProfileService(db_path=db)


def test_save_and_get(service: ProfileService) -> None:
    profile = service.save(
        SaveProfileParams(
            name="Editor-Default",
            template={"date_bucket": "%Y/%m", "camera": "keep"},
            conflictPolicy="rename",
            mutationPolicy="copy",
        )
    )
    assert profile.version == 1
    assert profile.conflict_policy == "rename"
    assert profile.template["camera"] == "keep"

    fetched = service.get(profile.id)
    assert fetched.name == "Editor-Default"
    assert fetched.id == profile.id


def test_save_bumps_version_on_same_name(service: ProfileService) -> None:
    service.save(SaveProfileParams(name="Profile", template={"a": 1}))
    v2 = service.save(SaveProfileParams(name="Profile", template={"a": 2}))
    assert v2.version == 2
    assert v2.id == service.list()[0].id  # same row, bumped version


def test_list_returns_all(service: ProfileService) -> None:
    service.save(SaveProfileParams(name="P1", template={"x": 1}))
    service.save(SaveProfileParams(name="P2", template={"y": 2}))
    names = {p.name for p in service.list()}
    assert names == {"P1", "P2"}


def test_get_missing_raises(service: ProfileService) -> None:
    with pytest.raises(ProfileNotFoundError):
        service.get(9999)
