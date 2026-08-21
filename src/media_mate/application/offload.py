"""Verified offload engine (plan §4.2, §7.2).

Implements the source-preserving offload core:

- Each copy is written to an application-owned temporary name in the
  final parent directory, flushed, then atomically renamed only after the
  transfer succeeds (plan §7.2). A failed copy leaves no partial file at
  the destination.
- Each replica is checksum-verified against its source after copy; a
  mismatch fails that replica and keeps the card unsafe (ADR-0004).
- Completed verified copies are preserved when a later destination
  fails; the receipt explains the partial state.
- :class:`OffloadRunner` is a scheduler runner that drives a plan for an
  intake session, recording replicas and per-file progress.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path
from typing import Literal, cast

from media_mate.application.assets import AssetService
from media_mate.application.intake import IntakeService
from media_mate.application.jobs import JobService
from media_mate.application.plan import IntakePlanner
from media_mate.application.replicas import ReplicaService, compute_checksum
from media_mate.application.scheduler import JobScheduler
from media_mate.service.protocol import (
    BuildPlanParams,
    JobDetail,
    PlanDestination,
)


def copy_file_atomic(source: Path, dest: Path) -> int:
    """Copy ``source`` to ``dest`` atomically.

    Writes to a temporary sibling, fsyncs, then renames over ``dest``.
    On any failure the temporary file is removed and ``dest`` is left
    untouched. Returns the number of bytes copied.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{dest.name}.", suffix=".part", dir=dest.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as out:
            with open(source, "rb") as src:
                total = 0
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    total += len(chunk)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, dest)
        return total
    except Exception:
        with __import__("contextlib").suppress(OSError):
            tmp.unlink()
        raise


def verify_copy(source: Path, dest: Path, algo: str) -> tuple[str, str, bool]:
    """Verify ``dest`` against ``source``.

    Returns ``(source_checksum, replica_checksum, match)`` under the
    configured algorithm.
    """
    source_checksum = compute_checksum(source, algo)
    replica_checksum = compute_checksum(dest, algo)
    return source_checksum, replica_checksum, source_checksum == replica_checksum


class OffloadRunner:
    """A scheduler runner that executes a verified offload for a session."""

    def __init__(
        self,
        planner: IntakePlanner,
        intake: IntakeService,
        replicas: ReplicaService,
        assets: AssetService,
        jobs: JobService,
        *,
        algo: str = "xxhash64",
    ) -> None:
        self._planner = planner
        self._intake = intake
        self._replicas = replicas
        self._assets = assets
        self._jobs = jobs
        self._algo = algo

    def __call__(self, job: JobDetail, scheduler: JobScheduler) -> str:
        if job.session_id is None:
            return "failed"
        session = self._intake.get_session(job.session_id)
        if session.source_id is None:
            return "failed"
        dests = self._intake.get_destinations(job.session_id)
        if not dests:
            return "failed"

        plan = self._planner.build(
            BuildPlanParams(
                projectId=session.project_id,
                sourceId=session.source_id,
                destinations=[
                    PlanDestination(
                        kind=cast(Literal["working", "backup", "organization"], d.kind),
                        rootPath=d.root_path,
                        required=d.required,
                    )
                    for d in dests
                ],
            )
        )
        if plan.collisions or not plan.capacity_ok:
            return "failed"

        source_root = Path(plan.source_root)
        project_id = session.project_id
        source_id = session.source_id

        for entry in plan.entries:
            if scheduler.should_cancel(job.id):
                return "cancelled"
            asset = self._assets.get_by_path(source_id, entry.rel_path)
            if asset is None:
                return "failed"
            src = source_root / entry.rel_path
            self._add_item(job.id, asset.id, entry.rel_path, entry.size)
            for dest in plan.destinations:
                if scheduler.should_cancel(job.id):
                    return "cancelled"
                dest_file = Path(dest.root_path) / entry.rel_path
                try:
                    copy_file_atomic(src, dest_file)
                except OSError:
                    self._mark_item_failed(job.id, asset.id)
                    return "failed"
                try:
                    scs, rcs, match = verify_copy(src, dest_file, self._algo)
                except OSError:
                    self._mark_item_failed(job.id, asset.id)
                    return "failed"
                if not match:
                    # Keep the replica recorded but unverified; card stays unsafe.
                    self._replicas.record(
                        asset.id,
                        project_id,
                        str(dest_file),
                        checksum=rcs,
                        algo=self._algo,
                        source_checksum=scs,
                        verified=False,
                    )
                    self._mark_item_failed(job.id, asset.id)
                    return "failed"
                self._replicas.record_verified(
                    asset.id,
                    project_id,
                    str(dest_file),
                    checksum=rcs,
                    algo=self._algo,
                    source_checksum=scs,
                )
                self._mark_item_done(job.id, asset.id)
        return "succeeded"

    # ---- progress helpers (best-effort; never fail the offload) -----

    def _add_item(self, job_id: str, asset_id: str, rel_path: str, size: int) -> None:
        with contextlib.suppress(Exception):  # pragma: no cover - progress is best-effort
            self._jobs.add_item(
                job_id,
                step="copy",
                asset_id=asset_id,
                source_path=rel_path,
                dest_path=rel_path,
                total_bytes=size,
            )

    def _mark_item_done(self, job_id: str, asset_id: str) -> None:
        with contextlib.suppress(Exception):  # pragma: no cover
            self._jobs.update_item_progress(job_id, asset_id, byte_progress=1, state="succeeded")

    def _mark_item_failed(self, job_id: str, asset_id: str) -> None:
        with contextlib.suppress(Exception):  # pragma: no cover
            self._jobs.update_item_progress(
                job_id, asset_id, state="failed", error="copy or verification failed"
            )
