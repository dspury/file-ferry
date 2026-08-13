"""Verified offload engine (plan §4.2, §7.2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from media_mate.application.offload import copy_file_atomic, verify_copy
from media_mate.application.service import ApplicationService
from media_mate.service.protocol import (
    AddDestinationParams,
    CancelJobParams,
    CreateIntakeSessionParams,
    CreateJobParams,
    CreateProjectParams,
    JobTransitionParams,
    ListAssetsParams,
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


def _setup(tmp_path: Path):
    svc = ApplicationService(db_path=tmp_path / "media-mate.db", app_data_dir=tmp_path / "app")
    svc.bootstrap()
    working = tmp_path / "proj" / "working"
    backup = tmp_path / "proj" / "backup"
    working.mkdir(parents=True)
    backup.mkdir(parents=True)
    pid = svc.create_project(
        CreateProjectParams(
            name="Offload-Project",
            workingRoot=str(working),
            backupRoot=str(backup),
            storagePolicy=SAME_VOLUME_POLICY,
            acknowledgeWeaker=True,
        )
    )
    src = tmp_path / "card" / "DCIM" / "100MEDIA"
    src.mkdir(parents=True)
    (src / "A001.mov").write_bytes(b"the-media-content")
    inspected = svc.source_inspect(SourceInspectParams(path=str(tmp_path / "card"), kind="card"))

    session = svc.intake_create_session(
        CreateIntakeSessionParams(projectId=pid, sourceId=inspected.source_id, kind="offload")
    )
    svc.intake_add_destination(
        AddDestinationParams(intakeSessionId=session.id, kind="working", rootPath=str(working))
    )
    svc.intake_add_destination(
        AddDestinationParams(intakeSessionId=session.id, kind="backup", rootPath=str(backup))
    )
    svc.intake_adopt_source(session.id, inspected.source_id, inspected.entries, str(working))

    job = svc.job_create(
        CreateJobParams(projectId=pid, command="offload", sessionId=session.id, totalSteps=1)
    )
    svc.job_transition(
        JobTransitionParams(id=job.id, fromState="planned", toState="awaiting_review")
    )
    svc.job_transition(
        JobTransitionParams(id=job.id, fromState="awaiting_review", toState="queued")
    )
    return svc, pid, inspected, working, backup, session, job.id


# ---- pure copy/verify -----------------------------------------------


def test_copy_file_atomic_writes_and_replaces(tmp_path: Path) -> None:
    src = tmp_path / "src.bin"
    src.write_bytes(b"hello")
    dest = tmp_path / "sub" / "dest.bin"
    n = copy_file_atomic(src, dest)
    assert dest.read_bytes() == b"hello"
    assert n == 5
    # Overwrite works.
    src.write_bytes(b"longer-content")
    copy_file_atomic(src, dest)
    assert dest.read_bytes() == b"longer-content"
    # No .part leftovers.
    assert not list(tmp_path.rglob("*.part"))


def test_copy_file_atomic_leaves_no_partial_on_error(tmp_path: Path) -> None:
    missing = tmp_path / "missing.bin"
    dest = tmp_path / "out.bin"
    with pytest.raises(OSError):
        copy_file_atomic(missing, dest)
    assert not dest.exists()


def test_verify_copy_matches(tmp_path: Path) -> None:
    src = tmp_path / "a.bin"
    dest = tmp_path / "b.bin"
    src.write_bytes(b"same")
    dest.write_bytes(b"same")
    scs, rcs, match = verify_copy(src, dest, "xxhash64")
    assert match is True
    assert scs == rcs


def test_verify_copy_mismatch(tmp_path: Path) -> None:
    src = tmp_path / "a.bin"
    dest = tmp_path / "b.bin"
    src.write_bytes(b"AAA")
    dest.write_bytes(b"BBB")
    scs, rcs, match = verify_copy(src, dest, "xxhash64")
    assert match is False
    assert scs != rcs


# ---- offload runner (scheduler) -------------------------------------


def test_offload_succeeds_and_verifies_both_destinations(tmp_path: Path) -> None:
    svc, pid, inspected, working, backup, session, job_id = _setup(tmp_path)
    result = svc.scheduler().dispatch(job_id)
    assert result.state == "succeeded"

    rel = inspected.entries[0].path
    assert (working / rel).exists()
    assert (backup / rel).exists()
    assert (working / rel).read_bytes() == b"the-media-content"
    assert (backup / rel).read_bytes() == b"the-media-content"

    # Replicas recorded verified in both destinations.
    replicas = svc.replica_list(svc.asset_list(ListAssetsParams(projectId=pid))[0].id)
    assert len(replicas) == 2
    assert all(r.verified for r in replicas)

    # The safe-to-format gate is now satisfied.
    eval_result = svc.intake_evaluate(session.id)
    assert eval_result.safe is True, eval_result.unmet


def test_offload_cancel_is_cooperative(tmp_path: Path) -> None:
    svc, _pid, _inspected, _working, _backup, _session, job_id = _setup(tmp_path)
    svc.job_cancel(CancelJobParams(id=job_id))
    result = svc.scheduler().dispatch(job_id)
    assert result.state == "cancelled"


def test_offload_fails_on_unavailable_destination(tmp_path: Path) -> None:
    svc, _pid, _inspected, _working, _backup, session, job_id = _setup(tmp_path)
    # A destination that is a plain file (not a writable dir) fails the plan.
    badfile = tmp_path / "not-a-dir"
    badfile.write_text("x")
    svc.intake_add_destination(
        AddDestinationParams(intakeSessionId=session.id, kind="organization", rootPath=str(badfile))
    )
    result = svc.scheduler().dispatch(job_id)
    assert result.state == "failed"
