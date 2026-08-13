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

from media_mate.application.assets import AssetService
from media_mate.application.audit import AuditService
from media_mate.application.clips import ClipService
from media_mate.application.intake import IntakeService
from media_mate.application.jobs import JobService
from media_mate.application.offload import OffloadRunner
from media_mate.application.organize import OrganizeService
from media_mate.application.plan import IntakePlanner
from media_mate.application.profiles import ProfileService
from media_mate.application.projects import ProjectService
from media_mate.application.receipts import ReceiptStore, export_html, export_markdown
from media_mate.application.reconcile import ReconcileService
from media_mate.application.replicas import ReplicaService
from media_mate.application.scheduler import JobScheduler
from media_mate.application.sources import SourceService
from media_mate.persistence import runner
from media_mate.persistence.connection import transaction
from media_mate.service.protocol import (
    PROTOCOL_VERSION,
    AcceptChangeParams,
    AddDestinationParams,
    ArchiveProjectParams,
    AssetSummary,
    AuditEvent,
    BuildPlanParams,
    CancelJobParams,
    CreateIntakeSessionParams,
    CreateJobParams,
    CreateProjectParams,
    DetectClipsParams,
    ExportReceiptParams,
    ExportReceiptResult,
    IntakeDestination,
    IntakePlan,
    IntakeSession,
    JobDetail,
    JobSnapshot,
    JobTransitionParams,
    ListAssetsParams,
    ListAuditParams,
    LogicalClip,
    MountedVolume,
    OrganizationProfile,
    OrganizeApplyParams,
    OrganizePreview,
    OrganizePreviewParams,
    OrganizeResult,
    ProjectDetail,
    ProjectSummary,
    ReconcileAssetParams,
    ReconcileProjectParams,
    ReconcileReport,
    ReplicaSummary,
    SafeToFormatEval,
    SaveProfileParams,
    SourceInspectParams,
    SourceInspectResult,
    SourceInventoryEntry,
    UpdateProjectParams,
    VerifyReplicaParams,
    VerifyReplicaResult,
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
    "profile.save",
    "profile.list",
    "profile.get",
    "asset.list",
    "asset.get",
    "replica.verify",
    "replica.list",
    "intake.createSession",
    "intake.addDestination",
    "intake.evaluate",
    "plan.build",
    "receipt.export",
    "reconcile.asset",
    "reconcile.project",
    "reconcile.acceptChange",
    "organize.preview",
    "organize.apply",
    "clips.detect",
    "clips.list",
    "job.create",
    "job.list",
    "job.get",
    "job.transition",
    "job.cancel",
    "job.recover",
    "audit.list",
    "audit.backfill",
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
        self._profiles: ProfileService | None = None
        self._assets: AssetService | None = None
        self._replicas: ReplicaService | None = None
        self._intake: IntakeService | None = None
        self._jobs: JobService | None = None
        self._audit: AuditService | None = None
        self._planner: IntakePlanner | None = None
        self._scheduler: JobScheduler | None = None
        self._reconcile: ReconcileService | None = None
        self._organize: OrganizeService | None = None
        self._clips: ClipService | None = None

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
        self._profiles = ProfileService(self._db_path)
        self._assets = AssetService(self._db_path)
        self._replicas = ReplicaService(self._db_path)
        self._intake = IntakeService(self._db_path, self._assets, self._replicas)
        self._jobs = JobService(self._db_path)
        self._audit = AuditService(self._db_path)
        self._planner = IntakePlanner(self._db_path)
        self._scheduler = JobScheduler(self._db_path, self._jobs)
        self._receipts = ReceiptStore(self._app_data_dir)
        self._reconcile = ReconcileService(self._db_path)
        self._organize = OrganizeService()
        self._clips = ClipService(self._db_path)
        self._register_scheduler_runners()
        self._bootstrapped = True

    def close(self) -> None:
        """Release any resources held by the service.

        Services open short-lived connections per operation; ``close``
        only clears the bootstrapped services.
        """
        self._projects = None
        self._sources = None
        self._profiles = None
        self._assets = None
        self._replicas = None
        self._intake = None
        self._jobs = None
        self._audit = None
        self._planner = None
        self._scheduler = None
        self._reconcile = None
        self._organize = None
        self._clips = None
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

    # ---- profile methods ---------------------------------------------

    def profile_save(self, params: SaveProfileParams) -> OrganizationProfile:
        return self._profile_service().save(params)

    def profile_list(self) -> list[OrganizationProfile]:
        return self._profile_service().list()

    def profile_get(self, profile_id: int) -> OrganizationProfile:
        return self._profile_service().get(profile_id)

    # ---- asset methods -----------------------------------------------

    def asset_list(self, params: ListAssetsParams) -> list[AssetSummary]:
        return self._asset_service().list(params.project_id)

    def asset_get(self, asset_id: str) -> AssetSummary:
        return self._asset_service().get(asset_id)

    def asset_adopt_source(self, source_id: int, entries: list[SourceInventoryEntry]) -> list[str]:
        return self._asset_service().adopt_source(source_id, entries)

    # ---- replica methods ---------------------------------------------

    def replica_verify(self, params: VerifyReplicaParams) -> VerifyReplicaResult:
        from pathlib import Path

        return self._replica_service().verify(
            params.replica_id, Path(params.source_path), params.checksum_algo
        )

    def replica_list(self, asset_id: str) -> list[ReplicaSummary]:
        return self._replica_service().list(asset_id)

    def replica_record(
        self,
        asset_id: str,
        project_id: str,
        path: str,
        *,
        checksum: str,
        algo: str,
        source_checksum: str,
        verified: bool,
    ) -> int:
        return self._replica_service().record(
            asset_id,
            project_id,
            path,
            checksum=checksum,
            algo=algo,
            source_checksum=source_checksum,
            verified=verified,
        )

    # ---- intake methods ----------------------------------------------

    def intake_create_session(self, params: CreateIntakeSessionParams) -> IntakeSession:
        return self._intake_service().create_session(params)

    def intake_add_destination(self, params: AddDestinationParams) -> IntakeDestination:
        return self._intake_service().add_destination(params)

    def intake_evaluate(self, session_id: str) -> SafeToFormatEval:
        return self._intake_service().evaluate(session_id)

    def intake_adopt_source(
        self,
        session_id: str,
        source_id: int,
        entries: list[SourceInventoryEntry],
        destination_root: str,
        *,
        project_id: str | None = None,
    ) -> list[str]:
        return self._intake_service().adopt_source(
            session_id, source_id, entries, destination_root, project_id=project_id
        )

    # ---- job methods -------------------------------------------------

    def job_create(self, params: CreateJobParams) -> JobDetail:
        return self._job_service().create(params)

    def job_list(self, project_id: str | None = None) -> list[JobDetail]:
        return self._job_service().list(project_id)

    def job_get(self, job_id: str) -> JobDetail:
        return self._job_service().get(job_id)

    def job_transition(self, params: JobTransitionParams) -> JobDetail:
        return self._job_service().transition(params)

    def job_cancel(self, params: CancelJobParams) -> None:
        """Request cooperative cancellation of a running job."""
        return self._scheduler_service().request_cancel(params.id)

    def job_dispatch(self, job_id: str) -> JobDetail:
        """Run one queued job through its registered runner."""
        return self._scheduler_service().dispatch(job_id)

    def job_recover(self) -> list[str]:
        """Mark jobs interrupted by a restart as needs_attention."""
        return self._scheduler_service().recover()

    # ---- plan / receipt ----------------------------------------------

    def plan_build(self, params: BuildPlanParams) -> IntakePlan:
        return self._planner_service().build(params)

    def receipt_export(self, params: ExportReceiptParams) -> ExportReceiptResult:
        with transaction(self._db_path) as conn:
            row = conn.execute(
                "SELECT receipt_json FROM operation_receipts WHERE operation_id = ? LIMIT 1",
                (params.operation_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"no receipt for operation {params.operation_id}")
        from media_mate.application.receipts import OperationReceipt

        receipt = OperationReceipt.model_validate_json(row["receipt_json"])
        content = export_html(receipt) if params.format == "html" else export_markdown(receipt)
        return ExportReceiptResult(content=content)

    # ---- reconcile / organize / clips --------------------------------

    def reconcile_asset(self, params: ReconcileAssetParams) -> ReconcileReport:
        return self._reconcile_service().reconcile_asset(params.asset_id, algo=params.checksum_algo)

    def reconcile_project(self, params: ReconcileProjectParams) -> list[ReconcileReport]:
        return self._reconcile_service().reconcile_project(
            params.project_id, algo=params.checksum_algo
        )

    def reconcile_accept_change(self, params: AcceptChangeParams) -> ReconcileReport:
        return self._reconcile_service().accept_change(
            params.asset_id, params.replica_id, algo=params.checksum_algo
        )

    def organize_preview(self, params: OrganizePreviewParams) -> OrganizePreview:
        return self._organize_service().preview(params)

    def organize_apply(self, params: OrganizeApplyParams) -> OrganizeResult:
        return self._organize_service().apply(params)

    def clips_detect(self, params: DetectClipsParams) -> list[LogicalClip]:
        return self._clips_service().detect(params.source_id)

    def clips_list(self, source_id: int) -> list[LogicalClip]:
        return self._clips_service().list(source_id)

    # ---- scheduler wiring --------------------------------------------

    def _register_scheduler_runners(self) -> None:
        """Wire the durable runners (offload) into the scheduler."""
        runner = OffloadRunner(
            self._planner_service(),
            self._intake_service(),
            self._replica_service(),
            self._asset_service(),
            self._job_service(),
        )
        self._scheduler_service().register_runner("offload", runner)

    # ---- audit methods -----------------------------------------------

    def audit_list(self, params: ListAuditParams) -> list[AuditEvent]:
        return self._audit_service().list(params)

    def audit_backfill(self) -> int:
        return self._audit_service().backfill_legacy()

    # ---- getters -----------------------------------------------------

    def _project_service(self) -> ProjectService:
        if self._projects is None:
            raise RuntimeError("ApplicationService.bootstrap() must be called first")
        return self._projects

    def _source_service(self) -> SourceService:
        if self._sources is None:
            raise RuntimeError("ApplicationService.bootstrap() must be called first")
        return self._sources

    def _profile_service(self) -> ProfileService:
        if self._profiles is None:
            raise RuntimeError("ApplicationService.bootstrap() must be called first")
        return self._profiles

    def _asset_service(self) -> AssetService:
        if self._assets is None:
            raise RuntimeError("ApplicationService.bootstrap() must be called first")
        return self._assets

    def _replica_service(self) -> ReplicaService:
        if self._replicas is None:
            raise RuntimeError("ApplicationService.bootstrap() must be called first")
        return self._replicas

    def _intake_service(self) -> IntakeService:
        if self._intake is None:
            raise RuntimeError("ApplicationService.bootstrap() must be called first")
        return self._intake

    def _job_service(self) -> JobService:
        if self._jobs is None:
            raise RuntimeError("ApplicationService.bootstrap() must be called first")
        return self._jobs

    def _planner_service(self) -> IntakePlanner:
        if self._planner is None:
            raise RuntimeError("ApplicationService.bootstrap() must be called first")
        return self._planner

    def _scheduler_service(self) -> JobScheduler:
        if self._scheduler is None:
            raise RuntimeError("ApplicationService.bootstrap() must be called first")
        return self._scheduler

    def _reconcile_service(self) -> ReconcileService:
        if self._reconcile is None:
            raise RuntimeError("ApplicationService.bootstrap() must be called first")
        return self._reconcile

    def _organize_service(self) -> OrganizeService:
        if self._organize is None:
            raise RuntimeError("ApplicationService.bootstrap() must be called first")
        return self._organize

    def _clips_service(self) -> ClipService:
        if self._clips is None:
            raise RuntimeError("ApplicationService.bootstrap() must be called first")
        return self._clips

    def scheduler(self) -> JobScheduler:
        """Expose the scheduler so runners can be registered at startup."""
        return self._scheduler_service()

    def _audit_service(self) -> AuditService:
        if self._audit is None:
            raise RuntimeError("ApplicationService.bootstrap() must be called first")
        return self._audit

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
