"""Intake service — session, adoption, and the safe-to-format gate."""

from __future__ import annotations

import shutil
from pathlib import Path

from media_mate.application.service import ApplicationService
from media_mate.service.protocol import (
    AddDestinationParams,
    CreateIntakeSessionParams,
    CreateProjectParams,
    SourceInspectParams,
    StoragePolicy,
    VerifyReplicaParams,
)

# tmp_path shares one device -> relax the same-volume rule for the project.
SAME_VOLUME_POLICY = StoragePolicy(
    requiredReplicas=2,
    backupOnDifferentVolume=False,
    checksumAlgo="xxhash64",
    safetyReserveBytes=0,
    requireSourceFingerprint=True,
)


def _bootstrapped(tmp_path: Path) -> ApplicationService:
    svc = ApplicationService(db_path=tmp_path / "media-mate.db", app_data_dir=tmp_path / "app")
    svc.bootstrap()
    return svc


def _setup(tmp_path: Path):
    svc = _bootstrapped(tmp_path)

    # A project with relaxed same-volume policy.
    working = tmp_path / "project" / "working"
    backup = tmp_path / "project" / "backup"
    working.mkdir(parents=True)
    backup.mkdir(parents=True)
    pid = svc.create_project(
        CreateProjectParams(
            name="Episode-2",
            workingRoot=str(working),
            backupRoot=str(backup),
            storagePolicy=SAME_VOLUME_POLICY,
            acknowledgeWeaker=True,
        )
    )

    # A source with one media file.
    src = tmp_path / "card" / "DCIM"
    src.mkdir(parents=True)
    (src / "A001.mov").write_bytes(b"the-media-bytes")
    inspected = svc.source_inspect(SourceInspectParams(path=str(src.parent), kind="card"))

    return svc, pid, inspected, working, backup


def test_gate_not_safe_until_all_destinations_verified(tmp_path: Path) -> None:
    svc, pid, inspected, working, backup = _setup(tmp_path)

    session = svc.intake_create_session(
        CreateIntakeSessionParams(projectId=pid, sourceId=inspected.source_id, kind="offload")
    )
    svc.intake_add_destination(
        AddDestinationParams(intakeSessionId=session.id, kind="working", rootPath=str(working))
    )
    svc.intake_add_destination(
        AddDestinationParams(intakeSessionId=session.id, kind="backup", rootPath=str(backup))
    )

    # Adopt the source into the working destination (replicas recorded unverified).
    asset_ids = svc.intake_adopt_source(
        session.id, inspected.source_id, inspected.entries, str(working)
    )
    assert len(asset_ids) == 1
    asset_id = asset_ids[0]

    # Not safe: working replica unverified, backup has no replica.
    eval1 = svc.intake_evaluate(session.id)
    assert eval1.safe is False
    assert any("backup" in u for u in eval1.unmet)

    # Copy the file into both destinations and verify both replicas.
    rel = inspected.entries[0].path
    source_file = Path(inspected.root_path) / rel
    (working / rel).parent.mkdir(parents=True, exist_ok=True)
    (backup / rel).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_file, working / rel)
    shutil.copy2(source_file, backup / rel)

    replicas = svc.replica_list(asset_id)
    assert len(replicas) == 1  # only the working one from adopt

    working_replica = replicas[0]
    svc.replica_verify(
        VerifyReplicaParams(
            replicaId=working_replica.id,
            sourcePath=str(source_file),
            checksumAlgo="xxhash64",
        )
    )

    backup_replica_id = svc.replica_record(
        asset_id,
        pid,
        str(backup / rel),
        checksum="",
        algo="xxhash64",
        source_checksum="",
        verified=False,
    )
    svc.replica_verify(
        VerifyReplicaParams(
            replicaId=backup_replica_id,
            sourcePath=str(source_file),
            checksumAlgo="xxhash64",
        )
    )

    eval2 = svc.intake_evaluate(session.id)
    assert eval2.safe is True, eval2.unmet
    assert eval2.unmet == []
