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

from media_mate.application.projects import ProjectService
from media_mate.application.sources import SourceService
from media_mate.persistence import runner
from media_mate.service.protocol import (
    PROTOCOL_VERSION,
    ArchiveProjectParams,
    CreateProjectParams,
    JobSnapshot,
    MountedVolume,
    ProjectDetail,
    ProjectSummary,
    SourceInspectParams,
    SourceInspectResult,
    UpdateProjectParams,
)

LOGGER = logging.getLogger(__name__)

SIDECAR_VERSION = "0.0.0+foundation"

METHOD_NAMES: tuple[str, ...] = (
    "app.getStatus",
    "app.getCapabilities",
    "project.list",
    "project.create",
    "project.get",
    "project.update",
    "project.archive",
    "source.listVolumes",
    "source.inspect",
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
        self._projects: ProjectService | None = None
        self._sources: SourceService | None = None

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
        self._projects = ProjectService(
            self._db_path, self._app_data_dir, protocol_version=PROTOCOL_VERSION
        )
        self._sources = SourceService(self._db_path)
        self._bootstrapped = True

    def close(self) -> None:
        """Release any resources held by the service.

        Services open short-lived connections per operation; ``close``
        only clears the bootstrapped services.
        """
        self._projects = None
        self._sources = None
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

    # ---- project methods ---------------------------------------------

    def list_projects(self) -> list[ProjectSummary]:
        """Return the list of projects."""
        return self._project_service().list()

    def create_project(self, params: CreateProjectParams) -> str:
        """Create a project and return its durable id."""
        return self._project_service().create(params).id

    def get_project(self, project_id: str) -> ProjectDetail:
        """Return the detail for one project."""
        return self._project_service().get(project_id)

    def update_project(self, params: UpdateProjectParams) -> ProjectDetail:
        """Update the mutable fields of one project."""
        return self._project_service().update(params)

    def archive_project(self, params: ArchiveProjectParams) -> ProjectDetail:
        """Archive (soft-delete) one project."""
        return self._project_service().archive(params.id)

    # ---- source methods ----------------------------------------------

    def source_inspect(self, params: SourceInspectParams) -> SourceInspectResult:
        """Identify a source and scan it read-only."""
        return self._source_service().inspect(params)

    def _project_service(self) -> ProjectService:
        if self._projects is None:
            raise RuntimeError("ApplicationService.bootstrap() must be called first")
        return self._projects

    def _source_service(self) -> SourceService:
        if self._sources is None:
            raise RuntimeError("ApplicationService.bootstrap() must be called first")
        return self._sources

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
