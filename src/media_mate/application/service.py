"""The application service root.

The :class:`ApplicationService` is the assembly root. It owns the
SQLite connection, the migration runner, the repositories, and the
per-domain services. The CLI, the TUI, and the sidecar all instantiate
exactly one :class:`ApplicationService` per process.

The foundation cut is intentionally minimal: it boots, runs the
pending migrations, and serves the protocol-shaped methods that the
desktop shell and the in-process client both consume. The actual
business logic (intake planning, replica verification, job
execution) lands in subsequent packages per ADR-0005.
"""

from __future__ import annotations

import logging
import platform
from pathlib import Path

from media_mate.persistence import runner
from media_mate.service.protocol import (
    CreateProjectParams,
    JobSnapshot,
    MountedVolume,
    ProjectSummary,
)

LOGGER = logging.getLogger(__name__)

SIDECAR_VERSION = "0.0.0+foundation"

METHOD_NAMES: tuple[str, ...] = (
    "app.getStatus",
    "app.getCapabilities",
    "project.list",
    "project.create",
    "source.listVolumes",
    "job.subscribe",
    "job.unsubscribe",
)

EVENT_NAMES: tuple[str, ...] = (
    "job.updated",
    "sidecar.ready",
    "sidecar.crashed",
)


class ApplicationService:
    """The assembly root. One instance per process."""

    def __init__(self, db_path: Path, app_data_dir: Path | None = None) -> None:
        self._db_path = Path(db_path)
        self._app_data_dir = (
            Path(app_data_dir) if app_data_dir is not None else self._db_path.parent
        )
        self._bootstrapped = False

    # ---- lifecycle ----------------------------------------------------

    def bootstrap(self) -> None:
        """Prepare the database for use.

        Creates the schema_meta table if missing, runs all pending
        migrations, and verifies the connection is healthy. Idempotent;
        safe to call multiple times.
        """
        if self._bootstrapped:
            return
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        if not self._db_path.exists():
            self._db_path.touch()
        discovered = runner.discover_migrations()
        backups_dir = self._app_data_dir / "backups"
        applied = runner.apply_pending(self._db_path, discovered, backups_dir)
        if applied:
            LOGGER.info(
                "applied %d migrations; latest schema_version=%d", len(applied), applied[-1].version
            )
        self._bootstrapped = True

    def close(self) -> None:
        """Release any resources held by the service.

        The foundation cut holds no external resources beyond the
        database file; ``close`` is a no-op kept for symmetry.
        """
        self._bootstrapped = False

    # ---- introspection ------------------------------------------------

    def sidecar_version(self) -> str:
        return SIDECAR_VERSION

    def capabilities(self) -> tuple[str, ...]:
        return METHOD_NAMES

    def method_names(self) -> tuple[str, ...]:
        return METHOD_NAMES

    def event_names(self) -> tuple[str, ...]:
        return EVENT_NAMES

    # ---- placeholder methods (real implementations land in Package 2) -

    def list_projects(self) -> list[ProjectSummary]:
        """Return the list of projects. Empty in the foundation cut."""
        return []

    def create_project(self, params: CreateProjectParams) -> str:
        """Create a project. The foundation cut returns a stub id."""
        # The real implementation lands in Package 2.1 (project service).
        return "stub-project-id"

    def list_volumes(self) -> list[MountedVolume]:
        """Return the list of mounted volumes. Empty in the foundation cut."""
        # The real implementation lives in a platform adapter tested
        # on macOS, Linux, and Windows. The foundation cut returns
        # the root mount to prove the protocol shape round-trips.
        return [_root_volume()]

    def job_snapshot(self, job_id: str) -> JobSnapshot:
        """Return a snapshot of the named job. The foundation cut returns
        a placeholder."""
        return JobSnapshot(
            id=job_id,
            state="planned",
            currentStep="",
            completedSteps=[],
            totalSteps=0,
            startedAt="1970-01-01T00:00:00Z",
            updatedAt="1970-01-01T00:00:00Z",
        )

    def job_unsubscribe(self, job_id: str) -> None:
        """Idempotent unsubscribe for the named job. No-op in the foundation cut."""
        return None


def _root_volume() -> MountedVolume:
    """Return a single ``/`` mount as the boot-vol proof the protocol round-trips."""
    usage = _disk_usage(Path("/"))
    return MountedVolume(
        path="/",
        label="root",
        totalBytes=usage[0],
        freeBytes=usage[1],
        filesystem=platform.system(),
    )


def _disk_usage(path: Path) -> tuple[int, int]:
    """Return ``(total, free)`` bytes for the volume holding ``path``."""
    import shutil

    usage = shutil.disk_usage(path)
    return (usage.total, usage.free)
