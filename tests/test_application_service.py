"""ApplicationService wiring — real project + source methods."""

from __future__ import annotations

from pathlib import Path

import pytest

from file_ferry.application.service import ApplicationService
from file_ferry.service.protocol import (
    CreateProjectParams,
    SourceInspectParams,
    StoragePolicy,
)

SAME_VOLUME_POLICY = StoragePolicy(
    requiredReplicas=2,
    backupOnDifferentVolume=False,
    checksumAlgo="xxhash64",
    safetyReserveBytes=0,
    requireSourceFingerprint=True,
)


@pytest.fixture
def service(tmp_path: Path) -> ApplicationService:
    s = ApplicationService(db_path=tmp_path / "ferry.db", app_data_dir=tmp_path / "app")
    s.bootstrap()
    return s


def test_method_names_include_new_methods(service: ApplicationService) -> None:
    names = service.method_names()
    for expected in (
        "project.get",
        "project.update",
        "project.archive",
        "source.inspect",
    ):
        assert expected in names


def test_create_project_returns_real_id(service: ApplicationService, tmp_path: Path) -> None:
    working = tmp_path / "working"
    working.mkdir()
    pid = service.create_project(
        CreateProjectParams(
            name="Svc-Proj",
            workingRoot=str(working),
            backupRoot=None,
            storagePolicy=SAME_VOLUME_POLICY,
            acknowledgeWeaker=True,
        )
    )
    assert pid != "stub-project-id"
    assert len(pid) > 0

    projects = service.list_projects()
    assert [p.id for p in projects] == [pid]
    detail = service.get_project(pid)
    assert detail.name == "Svc-Proj"


def test_create_project_rejects_same_volume_default(
    service: ApplicationService, tmp_path: Path
) -> None:
    working = tmp_path / "working"
    backup = tmp_path / "backup"
    working.mkdir()
    backup.mkdir()
    with pytest.raises(Exception, match="different physical volume"):
        service.create_project(
            CreateProjectParams(
                name="Svc-SameVol",
                workingRoot=str(working),
                backupRoot=str(backup),
            )
        )


def test_source_inspect_via_service(service: ApplicationService, tmp_path: Path) -> None:
    root = tmp_path / "src"
    root.mkdir()
    (root / "clip.mov").write_bytes(b"clip")
    result = service.source_inspect(
        SourceInspectParams(path=str(root), kind="existing_media", label="EditorDrive")
    )
    assert result.kind == "existing_media"
    assert result.file_count == 1
    assert result.entries[0].path == "clip.mov"


def test_services_require_bootstrap(tmp_path: Path) -> None:
    svc = ApplicationService(db_path=tmp_path / "x.db", app_data_dir=tmp_path)
    with pytest.raises(RuntimeError, match="bootstrap"):
        svc.list_projects()
