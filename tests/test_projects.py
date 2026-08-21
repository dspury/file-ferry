"""Project service — CRUD, validation, receipts."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from file_ferry.application.policies import PolicyValidationError
from file_ferry.application.projects import (
    ProjectNotFoundError,
    ProjectService,
    ProjectValidationError,
)
from file_ferry.service.protocol import (
    CreateProjectParams,
    StoragePolicy,
    UpdateProjectParams,
)

# tmp_path dirs all live on the same filesystem, so the default
# same-volume-backup rule would reject any backup_root under tmp_path.
# Tests that supply both roots use a policy with backup_on_different_volume
# relaxed and acknowledge_weaker=True, except where the rule itself is
# under test.
SAME_VOLUME_POLICY = StoragePolicy(
    requiredReplicas=2,
    backupOnDifferentVolume=False,
    checksumAlgo="xxhash64",
    safetyReserveBytes=0,
    requireSourceFingerprint=True,
)


@pytest.fixture
def service(tmp_path: Path) -> ProjectService:
    db_path = tmp_path / "ferry.db"
    from file_ferry.application.service import ApplicationService

    boot = ApplicationService(db_path=db_path, app_data_dir=tmp_path / "app_data")
    boot.bootstrap()
    boot.close()
    return ProjectService(
        db_path=db_path,
        app_data_dir=tmp_path / "app_data",
        protocol_version=1,
    )


def _params(
    name: str,
    working: Path,
    backup: Path | None = None,
    *,
    policy: StoragePolicy | None = None,
    ack: bool = True,
) -> CreateProjectParams:
    return CreateProjectParams(
        name=name,
        workingRoot=str(working),
        backupRoot=str(backup) if backup else None,
        storagePolicy=policy or SAME_VOLUME_POLICY,
        acknowledgeWeaker=ack,
    )


def test_create_round_trips(service: ProjectService, tmp_path: Path) -> None:
    working = tmp_path / "working"
    backup = tmp_path / "backup"
    working.mkdir()
    backup.mkdir()
    detail = service.create(_params("Episode-1", working, backup))
    assert detail.status == "active"
    assert detail.name == "Episode-1"
    assert detail.storage_policy.required_replicas == 2

    listed = service.list()
    assert [p.id for p in listed] == [detail.id]
    fetched = service.get(detail.id)
    assert fetched.id == detail.id
    assert fetched.backup_root == str(backup)


def test_create_writes_receipt(service: ProjectService, tmp_path: Path) -> None:
    working = tmp_path / "working"
    working.mkdir()
    detail = service.create(_params("Receipted", working))

    receipts_dir = tmp_path / "app_data" / "receipts"
    files = list(receipts_dir.glob("*.json"))
    assert len(files) == 1
    import json as _json

    on_disk = _json.loads(files[0].read_text(encoding="utf-8"))
    assert on_disk["finalState"] == "created"
    assert on_disk["actual"][0]["project_id"] == detail.id

    with sqlite3.connect(tmp_path / "ferry.db") as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT kind, receipt_hash, export_version FROM operation_receipts "
            "WHERE kind = 'project'"
        ).fetchone()
        assert row is not None
        assert row["kind"] == "project"
        assert row["export_version"] == 1
        assert len(row["receipt_hash"]) == 64  # sha256


def test_create_rejects_nonexistent_working_root(service: ProjectService, tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    with pytest.raises(ProjectValidationError, match="does not exist"):
        service.create(_params("Bad", missing))


def test_create_default_policy_rejects_same_volume_backup(
    service: ProjectService, tmp_path: Path
) -> None:
    working = tmp_path / "working"
    backup = tmp_path / "backup"
    working.mkdir()
    backup.mkdir()
    # No storagePolicy supplied => the default policy applies, which
    # forbids a same-volume backup (tmp_path shares one device).
    params = CreateProjectParams(name="SameVol", workingRoot=str(working), backupRoot=str(backup))
    with pytest.raises(ProjectValidationError, match="different physical volume"):
        service.create(params)


def test_create_rejects_unacknowledged_weaker_policy(
    service: ProjectService, tmp_path: Path
) -> None:
    working = tmp_path / "working"
    working.mkdir()
    weaker = StoragePolicy(
        requiredReplicas=1,
        backupOnDifferentVolume=True,
        checksumAlgo="xxhash64",
        safetyReserveBytes=0,
        requireSourceFingerprint=True,
    )
    with pytest.raises(PolicyValidationError):
        service.create(_params("Weak", working, policy=weaker, ack=False))


def test_create_acknowledged_weaker_succeeds(service: ProjectService, tmp_path: Path) -> None:
    working = tmp_path / "working"
    working.mkdir()
    weaker = StoragePolicy(
        requiredReplicas=1,
        backupOnDifferentVolume=True,
        checksumAlgo="xxhash64",
        safetyReserveBytes=0,
        requireSourceFingerprint=True,
    )
    detail = service.create(_params("WeakAck", working, policy=weaker, ack=True))
    assert detail.storage_policy.required_replicas == 1


def test_duplicate_name_rejected(service: ProjectService, tmp_path: Path) -> None:
    working = tmp_path / "working"
    working.mkdir()
    service.create(_params("Dup", working))
    with pytest.raises(ProjectValidationError, match="already exists"):
        service.create(_params("Dup", working))


def test_get_missing_raises(service: ProjectService) -> None:
    with pytest.raises(ProjectNotFoundError):
        service.get("does-not-exist")


def test_update_changes_fields(service: ProjectService, tmp_path: Path) -> None:
    working = tmp_path / "working"
    new_working = tmp_path / "new_working"
    working.mkdir()
    new_working.mkdir()
    detail = service.create(_params("Edit", working))
    updated = service.update(
        UpdateProjectParams(
            id=detail.id,
            name="Edited",
            workingRoot=str(new_working),
            storagePolicy=SAME_VOLUME_POLICY,
            acknowledgeWeaker=True,
        )
    )
    assert updated.name == "Edited"
    assert updated.working_root == str(new_working)
    assert updated.id == detail.id


def test_archive_sets_status(service: ProjectService, tmp_path: Path) -> None:
    working = tmp_path / "working"
    working.mkdir()
    detail = service.create(_params("ArchiveMe", working))
    archived = service.archive(detail.id)
    assert archived.status == "archived"
    assert archived.archived_at is not None
