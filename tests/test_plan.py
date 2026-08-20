"""Intake planner tests (plan §7.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ferry.application.plan import IntakePlanner, PlanError, detect_collisions
from ferry.application.service import ApplicationService
from ferry.service.protocol import (
    BuildPlanParams,
    CreateProjectParams,
    PlanDestination,
    PlanEntry,
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
    svc = ApplicationService(db_path=tmp_path / "ferry.db", app_data_dir=tmp_path / "app")
    svc.bootstrap()
    working = tmp_path / "proj" / "working"
    backup = tmp_path / "proj" / "backup"
    working.mkdir(parents=True)
    backup.mkdir(parents=True)
    pid = svc.create_project(
        CreateProjectParams(
            name="Plan-Project",
            workingRoot=str(working),
            backupRoot=str(backup),
            storagePolicy=SAME_VOLUME_POLICY,
            acknowledgeWeaker=True,
        )
    )
    src = tmp_path / "card" / "DCIM" / "100MEDIA"
    src.mkdir(parents=True)
    (src / "A001.mov").write_bytes(b"media-bytes")
    (src / "sub" / "A002.mov").parent.mkdir(parents=True)
    (src / "sub" / "A002.mov").write_bytes(b"more")
    inspected = svc.source_inspect(SourceInspectParams(path=str(tmp_path / "card"), kind="card"))
    planner = IntakePlanner(db_path=tmp_path / "ferry.db")
    return svc, planner, pid, inspected, working, backup


def test_build_preserves_source_hierarchy(tmp_path: Path) -> None:
    _svc, planner, pid, inspected, working, backup = _setup(tmp_path)
    plan = planner.build(
        BuildPlanParams(
            projectId=pid,
            sourceId=inspected.source_id,
            destinations=[
                PlanDestination(kind="working", rootPath=str(working)),
                PlanDestination(kind="backup", rootPath=str(backup)),
            ],
        )
    )
    rels = {e.rel_path for e in plan.entries}
    assert rels == {"DCIM/100MEDIA/A001.mov", "DCIM/100MEDIA/sub/A002.mov"}
    # Source-preserving: dest path = dest root + source-relative path.
    a001 = next(e for e in plan.entries if e.rel_path == "DCIM/100MEDIA/A001.mov")
    assert a001.dest_path == str(working / "DCIM/100MEDIA/A001.mov")
    assert plan.total_bytes == len(b"media-bytes") + len(b"more")
    assert plan.capacity_ok is True
    assert plan.collisions == []


def test_fingerprint_is_deterministic(tmp_path: Path) -> None:
    _svc, planner, pid, inspected, working, _backup = _setup(tmp_path)
    params = BuildPlanParams(
        projectId=pid,
        sourceId=inspected.source_id,
        destinations=[PlanDestination(kind="working", rootPath=str(working))],
    )
    assert planner.build(params).fingerprint == planner.build(params).fingerprint


def test_source_equals_destination_rejected(tmp_path: Path) -> None:
    _svc, planner, pid, inspected, _working, _backup = _setup(tmp_path)
    with pytest.raises(PlanError, match="in-place"):
        planner.build(
            BuildPlanParams(
                projectId=pid,
                sourceId=inspected.source_id,
                destinations=[PlanDestination(kind="working", rootPath=str(tmp_path / "card"))],
            )
        )


def test_missing_destination_rejected(tmp_path: Path) -> None:
    _svc, planner, pid, inspected, _working, _backup = _setup(tmp_path)
    with pytest.raises(PlanError, match="does not exist"):
        planner.build(
            BuildPlanParams(
                projectId=pid,
                sourceId=inspected.source_id,
                destinations=[PlanDestination(kind="working", rootPath=str(tmp_path / "nope"))],
            )
        )


def test_no_destinations_rejected(tmp_path: Path) -> None:
    _svc, planner, pid, inspected, _working, _backup = _setup(tmp_path)
    with pytest.raises(PlanError, match="at least one destination"):
        planner.build(BuildPlanParams(projectId=pid, sourceId=inspected.source_id, destinations=[]))


def test_detect_case_only_collision() -> None:
    planned = [
        PlanEntry(relPath="clip.mov", destPath="/d/clip.mov", size=1),
        PlanEntry(relPath="CLIP.mov", destPath="/d/CLIP.mov", size=2),
    ]
    issues = detect_collisions(planned)
    assert any(i.reason == "case_only" for i in issues)


def test_detect_duplicate_destination() -> None:
    planned = [
        PlanEntry(relPath="a.mov", destPath="/d/a.mov", size=1),
        PlanEntry(relPath="b.mov", destPath="/d/a.mov", size=2),
    ]
    issues = detect_collisions(planned)
    assert any(i.reason == "duplicate_destination" for i in issues)
