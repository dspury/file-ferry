"""Proxy generation as a durable job (plan §7.4)."""

from __future__ import annotations

from pathlib import Path

from media_mate.application.service import ApplicationService
from media_mate.service.protocol import (
    AddDestinationParams,
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


def _setup(tmp_path: Path, *, proxy_fn=None):
    svc = ApplicationService(db_path=tmp_path / "media-mate.db", app_data_dir=tmp_path / "app")
    svc.bootstrap()
    working = tmp_path / "proj" / "working"
    backup = tmp_path / "proj" / "backup"
    working.mkdir(parents=True)
    backup.mkdir(parents=True)
    pid = svc.create_project(
        CreateProjectParams(
            name="Proxy-Project",
            workingRoot=str(working),
            backupRoot=str(backup),
            storagePolicy=SAME_VOLUME_POLICY,
            acknowledgeWeaker=True,
        )
    )
    src = tmp_path / "card" / "DCIM"
    src.mkdir(parents=True)
    (src / "A001.mov").write_bytes(b"media-content")
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
    # Copy the source into the working replica so proxies have a source.
    rel = inspected.entries[0].path
    (working / rel).parent.mkdir(parents=True, exist_ok=True)
    (working / rel).write_bytes((Path(inspected.root_path) / rel).read_bytes())

    # Register a fake proxy fn so no ffmpeg is required.
    if proxy_fn is not None:
        svc.scheduler().register_runner("proxy", _wrap_proxy(svc, proxy_fn))

    job = svc.job_create(
        CreateJobParams(projectId=pid, command="proxy", sessionId=session.id, totalSteps=1)
    )
    svc.job_transition(
        JobTransitionParams(id=job.id, fromState="planned", toState="awaiting_review")
    )
    svc.job_transition(
        JobTransitionParams(id=job.id, fromState="awaiting_review", toState="queued")
    )
    return svc, pid, inspected, working, backup, session, job.id


def _wrap_proxy(svc, fn):
    """Replace the registered ProxyRunner with one using ``fn``."""
    from media_mate.application.proxy_runner import ProxyRunner

    return ProxyRunner(
        svc._asset_service(),
        svc._derivative_service(),
        svc._intake_service(),
        svc._job_service(),
        proxy_fn=fn,
    )


def test_proxy_runner_records_ready_derivative(tmp_path: Path) -> None:
    made: list[str] = []

    def fake_proxy(source: str, output: str) -> object:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_bytes(b"proxy")
        made.append(output)
        return None

    svc, _pid, _inspected, _working, _backup, _session, job_id = _setup(
        tmp_path, proxy_fn=fake_proxy
    )
    result = svc.scheduler().dispatch(job_id)
    assert result.state == "succeeded"
    assert len(made) == 1

    # Find the adopted asset and check its derivative is ready.
    assets = svc.asset_list(ListAssetsParams())
    assert assets
    derivs = svc.derivatives_list(assets[0].id)
    assert derivs
    assert derivs[0].kind == "proxy"
    assert derivs[0].status == "ready"
    assert derivs[0].readiness == 1.0
    assert Path(derivs[0].output_path).exists()


def test_proxy_runner_failure_marks_derivative_failed(tmp_path: Path) -> None:
    def failing_proxy(source: str, output: str) -> object:
        raise RuntimeError("ffmpeg failed")

    svc, _pid, _inspected, _working, _backup, _session, job_id = _setup(
        tmp_path, proxy_fn=failing_proxy
    )
    result = svc.scheduler().dispatch(job_id)
    assert result.state == "failed"

    assets = svc.asset_list(ListAssetsParams())
    derivs = svc.derivatives_list(assets[0].id)
    assert derivs
    assert derivs[0].status == "failed"
    assert derivs[0].readiness == 0.0
