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
from collections.abc import Callable
from pathlib import Path

from file_ferry.application.assets import AssetService
from file_ferry.application.audit import AuditService
from file_ferry.application.clips import ClipService
from file_ferry.application.derivatives import DerivativeService
from file_ferry.application.dispatcher import JobDispatcher
from file_ferry.application.intake import IntakeService
from file_ferry.application.jobs import JobService
from file_ferry.application.manifest import ManifestService
from file_ferry.application.offload import OffloadRunner
from file_ferry.application.organize import OrganizeService
from file_ferry.application.plan import IntakePlanner
from file_ferry.application.policies import StoragePolicy
from file_ferry.application.profiles import ProfileService
from file_ferry.application.projects import ProjectService
from file_ferry.application.proxy_runner import ProxyRunner
from file_ferry.application.receipts import (
    OperationReceipt,
    ReceiptStore,
    export_html,
    export_markdown,
)
from file_ferry.application.reconcile import ReconcileService
from file_ferry.application.replicas import ReplicaService
from file_ferry.application.scheduler import JobScheduler
from file_ferry.application.sources import SourceService
from file_ferry.application.volumes import SystemVolumeAdapter, VolumeChange, VolumeObserver
from file_ferry.persistence import runner
from file_ferry.persistence.connection import transaction
from file_ferry.service.protocol import (
    PROTOCOL_VERSION,
    AcceptChangeParams,
    AddDestinationParams,
    AppSettings,
    ArchiveProjectParams,
    AssetSummary,
    AuditEvent,
    BuildPlanParams,
    CancelJobParams,
    CreateIntakeSessionParams,
    CreateJobParams,
    CreateProjectParams,
    DerivativeSummary,
    DetectClipsParams,
    DoctorResult,
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
    ProfilePreviewParams,
    ProjectDetail,
    ProjectManifest,
    ProjectSummary,
    ReconcileAssetParams,
    ReconcileProjectParams,
    ReconcileReport,
    ReplicaSummary,
    ResolveImportManifest,
    SafeToFormatEval,
    SaveProfileParams,
    SourceInspectParams,
    SourceInspectResult,
    SourceInventoryEntry,
    UpdateProjectParams,
    UpdateSettingsParams,
    VerifyReplicaParams,
    VerifyReplicaResult,
)

LOGGER = logging.getLogger(__name__)

SIDECAR_VERSION = "0.0.0+foundation"

METHOD_NAMES: tuple[str, ...] = (
    "app.getStatus",
    "app.getCapabilities",
    "app.doctor",
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
    "profile.preview",
    "asset.list",
    "asset.get",
    "replica.verify",
    "replica.list",
    "intake.createSession",
    "intake.addDestination",
    "intake.evaluate",
    "intake.adoptSource",
    "plan.build",
    "receipt.export",
    "receipt.get",
    "reconcile.asset",
    "reconcile.project",
    "reconcile.acceptChange",
    "organize.preview",
    "organize.apply",
    "clips.detect",
    "clips.list",
    "derivatives.list",
    "manifest.export",
    "manifest.handoff",
    "manifest.resolve",
    "job.create",
    "job.list",
    "job.get",
    "job.transition",
    "job.cancel",
    "job.dispatch",
    "job.dispatchNext",
    "job.recover",
    "job.resume",
    "job.retry",
    "audit.list",
    "audit.backfill",
    "job.subscribe",
    "job.unsubscribe",
    "settings.get",
    "settings.update",
)

EVENT_NAMES: tuple[str, ...] = (
    "job.updated",
    "sidecar.ready",
    "sidecar.crashed",
)


class ApplicationService:
    """The assembly root. One instance per process."""

    def __init__(
        self,
        db_path: Path,
        app_data_dir: Path | None = None,
        *,
        config_path: Path | None = None,
    ) -> None:
        self._db_path = Path(db_path)
        self._app_data_dir = (
            Path(app_data_dir) if app_data_dir is not None else self._db_path.parent
        )
        self._config_path = Path(config_path) if config_path is not None else None
        self._bootstrapped = False
        # Set by ``wire_server`` to the sidecar server's ``send_event``. It
        # stays None for in-process users (the CLI, tests), which simply do
        # not get events.
        self._event_sink: Callable[[str, dict[str, object]], None] | None = None
        # Only jobs a client has asked for are published, so an idle window
        # does not pay for every job in the database.
        self._job_subscriptions: set[str] = set()
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
        self._derivatives: DerivativeService | None = None
        self._manifest: ManifestService | None = None
        self._volume_adapter: SystemVolumeAdapter | None = None
        self._volume_observer: VolumeObserver | None = None
        self._dispatcher: JobDispatcher | None = None

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
        # The scheduler has always published every transition to its
        # listeners and nothing ever subscribed, so `job.updated` was a
        # declared event that could not fire. This is the missing edge.
        self._scheduler.subscribe(lambda job: self._publish_job_updated(job.id))
        self._receipts = ReceiptStore(self._app_data_dir)
        self._reconcile = ReconcileService(self._db_path)
        self._organize = OrganizeService()
        self._clips = ClipService(self._db_path)
        self._derivatives = DerivativeService(self._db_path)
        self._manifest = ManifestService(self._db_path)
        self._volume_adapter = SystemVolumeAdapter()
        self._volume_observer = VolumeObserver(self._volume_adapter)
        self._register_scheduler_runners()
        # Plan §6.4 / §5.1: a sidecar-internal dispatcher picks up
        # jobs that have moved into the queued state. Without this,
        # nothing triggers the registered runners -- the renderer can
        # see queued jobs but never the result. The dispatcher's loop
        # blocks on a wake event so it costs nothing between jobs.
        self._dispatcher = JobDispatcher(self._scheduler)
        self._dispatcher.start()
        self._bootstrapped = True

    def shutdown(self) -> None:
        """Stop the background dispatcher and release resources.

        Called on sidecar shutdown. Idempotent; safe to call multiple
        times. Does NOT close the database connection -- callers that
        want that should follow up with ``close``.
        """
        if self._dispatcher is not None:
            self._dispatcher.stop()
            self._dispatcher = None

    def close(self) -> None:
        """Release any resources held by the service.

        Services open short-lived connections per operation; ``close``
        only clears the bootstrapped services. Stops the dispatcher
        first to avoid in-flight jobs using cleared services.
        """
        self.shutdown()
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
        self._derivatives = None
        self._manifest = None
        self._volume_adapter = None
        self._volume_observer = None
        self._bootstrapped = False
        # Drop the transport and the watch list together: publishing into a
        # torn-down server, or replaying a previous session's subscriptions
        # after a re-bootstrap, are both wrong.
        self._event_sink = None
        self._job_subscriptions.clear()

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

    def profile_preview(self, params: ProfilePreviewParams) -> OrganizePreview:
        """Preview how an organization profile maps a source tree (plan §8.3)."""
        from file_ferry.service.protocol import OrganizePreviewParams

        return self._organize_service().preview(
            OrganizePreviewParams(
                sourceRoot=params.source_root,
                destRoot=params.dest_root,
                entries=params.entries,
                template=params.template,
                mode="copy",  # preview never mutates
            )
        )

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
        """Create a job, and queue it when the plan has already been reviewed.

        A new job starts in ``planned``. The §6.4 machine holds it at
        ``awaiting_review`` until somebody approves the plan, and only a
        ``queued`` job is something the dispatcher will run -- so creating
        a job is not, on its own, starting one.

        That distinction was invisible for as long as nothing acted on it:
        the Offload screen called this method and stopped, so every offload
        anyone ever ran from the desktop sat in ``planned`` forever. The
        screen does review the plan -- that is its Review step -- so it now
        says so, and the gate opens here rather than through three separate
        transition calls that could half-fail.
        """
        job = self._job_service().create(params)
        # Announced even though nobody can be subscribed yet: a subscription
        # is per job id, so a client watching the job list has no way to ask
        # for a job that does not exist. Without this one unsolicited event a
        # job created while Activity is open stays invisible until something
        # else reloads the list -- the client uses it as "reload, then
        # subscribe".
        self._publish_job_updated(job.id, force=True)
        if params.reviewed:
            job = self._queue_reviewed(job.id)
        self._dispatcher_service().kick()
        return job

    def _queue_reviewed(self, job_id: str) -> JobDetail:
        """Walk a freshly created job through the review gate to ``queued``."""
        self.job_transition(
            JobTransitionParams(id=job_id, fromState="planned", toState="awaiting_review")
        )
        return self.job_transition(
            JobTransitionParams(id=job_id, fromState="awaiting_review", toState="queued")
        )

    def job_list(self, project_id: str | None = None) -> list[JobDetail]:
        return self._job_service().list(project_id)

    def job_get(self, job_id: str) -> JobDetail:
        return self._job_service().get(job_id)

    def job_transition(self, params: JobTransitionParams) -> JobDetail:
        # A transition driven straight from IPC does not go through the
        # scheduler, so it would otherwise be the one state change that
        # subscribers never hear about.
        job = self._job_service().transition(params)
        self._publish_job_updated(job.id)
        if job.state == "queued":
            # Reaching `queued` is the whole trigger condition for the
            # background dispatcher, and this is the one path that can put a
            # job there without waking it. `job.create` kicks, but a job is
            # never queued at creation -- so a job queued by transition sat
            # until some unrelated event happened to wake the loop.
            self._dispatcher_service().kick()
        return job

    def job_cancel(self, params: CancelJobParams) -> None:
        """Request cooperative cancellation of a running job."""
        return self._scheduler_service().request_cancel(params.id)

    def job_dispatch(self, job_id: str) -> JobDetail:
        """Synchronously dispatch one queued job through the scheduler.

        Provided as an IPC method (``job.dispatch``) for clients that
        want a "kick this specific job" affordance. The background
        :class:`JobDispatcher` will also run the job on its next tick,
        so this is a safety net rather than the primary path.
        """
        return self._scheduler_service().dispatch(job_id)

    def job_dispatch_next(self) -> dict[str, object]:
        """Kick the background dispatcher.

        Returns a status dict describing the dispatcher state. Matches
        the ``job.dispatchNext`` IPC method.
        """
        self._dispatcher_service().kick()
        return {"kicked": True}

    def job_recover(self) -> list[str]:
        """Mark jobs interrupted by a restart as needs_attention."""
        recovered = self._scheduler_service().recover()
        # Recovering a job does not put it back in queued; the operator
        # must explicitly ``resume`` it. No kick here on purpose.
        return recovered

    def job_resume(self, job_id: str) -> JobDetail:
        """Resume an attention job at a safe boundary (plan §6.4)."""
        job = self._scheduler_service().resume(job_id)
        # resume transitions the job back into "running" inside the
        # scheduler, but a future resume from a fresh state will land
        # in queued; either way, a kick is harmless and idempotent.
        self._dispatcher_service().kick()
        return job

    def job_retry(self, job_id: str) -> JobDetail:
        """Retry a failed job with a fresh attempt (plan §6.4)."""
        job = self._scheduler_service().retry(job_id)
        # retry creates a brand-new queued job; kick so the new attempt
        # does not have to wait for the next event.
        self._dispatcher_service().kick()
        return job

    # ---- plan / receipt ----------------------------------------------

    def plan_build(self, params: BuildPlanParams) -> IntakePlan:
        return self._planner_service().build(params)

    def receipt_export(self, params: ExportReceiptParams) -> ExportReceiptResult:

        receipt = self._load_receipt(params.operation_id)
        content = export_html(receipt) if params.format == "html" else export_markdown(receipt)
        return ExportReceiptResult(content=content)

    def receipt_get(self, operation_id: str) -> dict[str, object]:
        """Return the stored receipt as a dict (plan §8.3 receipt.get)."""
        receipt = self._load_receipt(operation_id)
        dumped = receipt.model_dump(by_alias=True)
        return {k: v for k, v in dumped.items()}

    def _load_receipt(self, operation_id: str) -> OperationReceipt:
        """Load an OperationReceipt by id, raising KeyError if absent."""
        with transaction(self._db_path) as conn:
            row = conn.execute(
                "SELECT receipt_json FROM operation_receipts WHERE operation_id = ? LIMIT 1",
                (operation_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"no receipt for operation {operation_id}")
        return OperationReceipt.model_validate_json(row["receipt_json"])

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
        """Wire the durable runners (offload, proxy) into the scheduler."""
        offload = OffloadRunner(
            self._planner_service(),
            self._intake_service(),
            self._replica_service(),
            self._asset_service(),
            self._job_service(),
            receipt_writer=self._write_job_receipt,
            policy_resolver=self._policy_for_project,
        )
        self._scheduler_service().register_runner("offload", offload)
        proxy = ProxyRunner(
            self._asset_service(),
            self._derivative_service(),
            self._intake_service(),
            self._job_service(),
            receipt_writer=self._write_job_receipt,
        )
        self._scheduler_service().register_runner("proxy", proxy)

    def _write_job_receipt(self, receipt: OperationReceipt) -> None:
        """Persist a runner's receipt, superseding a previous attempt's.

        The runners hold services, not a database connection, so this is
        the seam that gives them one. It is also where the supersede rule
        lives, because only something holding the connection can see what
        it is about to replace: :meth:`JobScheduler.resume` re-runs one job
        id, and a receipt keyed by that id would otherwise collide with the
        abandoned attempt's under ``UNIQUE(operation_id, kind)``.
        """
        store = self._receipts
        with transaction(self._db_path) as conn:
            prior = store.prior_hash(conn, receipt.operation_id, receipt.kind)
            if prior is not None:
                # The superseded attempt's substance is not recoverable from
                # the row that replaces it, so its hash is carried forward.
                # A receipt that silently forgot an earlier attempt existed
                # would be a worse record than none.
                receipt = receipt.model_copy(
                    update={"warnings": [*receipt.warnings, f"supersedes receipt {prior}"]}
                )
            store.write(conn, receipt, replace=True)

    def _policy_for_project(self, project_id: str) -> StoragePolicy | None:
        """The storage policy a receipt is judged against, or None."""
        try:
            return self._project_service().get(project_id).storage_policy
        except KeyError:
            return None

    # ---- derivatives / manifest --------------------------------------

    def derivatives_list(self, asset_id: str) -> list[DerivativeSummary]:
        return self._derivative_service().list(asset_id)

    def manifest_export(self, project_id: str) -> ProjectManifest:
        return self._manifest_service().export_project(project_id)

    def manifest_handoff(self, project_id: str) -> str:
        return self._manifest_service().export_handoff(project_id)

    def manifest_resolve(self, project_id: str) -> ResolveImportManifest:
        return self._manifest_service().export_resolve_manifest(project_id)

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

    def _dispatcher_service(self) -> JobDispatcher:
        if self._dispatcher is None:
            raise RuntimeError("ApplicationService.bootstrap() must be called first")
        return self._dispatcher

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

    def _derivative_service(self) -> DerivativeService:
        if self._derivatives is None:
            raise RuntimeError("ApplicationService.bootstrap() must be called first")
        return self._derivatives

    def _manifest_service(self) -> ManifestService:
        if self._manifest is None:
            raise RuntimeError("ApplicationService.bootstrap() must be called first")
        return self._manifest

    def scheduler(self) -> JobScheduler:
        """Expose the scheduler so runners can be registered at startup."""
        return self._scheduler_service()

    def dispatcher(self) -> JobDispatcher:
        """Expose the background dispatcher.

        Mostly useful for tests and tooling (e.g. ``svc.dispatcher().kick()``
        from a repl). Production code should rely on the implicit kicks
        from ``job.create`` / ``job.retry`` / ``job.resume``.
        """
        return self._dispatcher_service()

    def _audit_service(self) -> AuditService:
        if self._audit is None:
            raise RuntimeError("ApplicationService.bootstrap() must be called first")
        return self._audit

    def list_volumes(self) -> list[MountedVolume]:
        """Return the currently mounted volumes (observations only)."""
        if self._volume_adapter is None:
            raise RuntimeError("ApplicationService.bootstrap() must be called first")
        return self._volume_adapter.list_volumes()

    def volume_poll(self) -> VolumeChange:
        """Return the mount/unmount observations since the last call."""
        if self._volume_observer is None:
            raise RuntimeError("ApplicationService.bootstrap() must be called first")
        return self._volume_observer.poll()

    # ---- settings / doctor (plan §8.3) -------------------------------

    def settings_get(self) -> AppSettings:
        """Return the current application settings from the config file."""
        from file_ferry.config import load_config

        cfg = load_config(self._config_path)
        raw_algo = cfg.checksum_algo.value if cfg.checksum_algo else "xxhash"
        return AppSettings(
            proxyCodec=cfg.proxy_codec,
            proxyHeight=cfg.proxy_height,
            # Legacy config enum uses "xxhash"; the vNext protocol uses
            # "xxhash64". Normalize so the renderer sees a stable value.
            checksumAlgo=_normalize_checksum_algo(raw_algo),
            resolvePath=cfg.resolve_path,
            ffmpegPath=cfg.ffmpeg_path,
            organizeTemplate=cfg.organize.template,
            organizeMode=cfg.organize.mode,
            organizeOnConflict=cfg.organize.on_conflict,
        )

    def settings_update(self, params: UpdateSettingsParams) -> AppSettings:
        """Apply present settings fields and persist, then return the result."""
        from file_ferry.config import config_target, load_config, save_config

        current = load_config(self._config_path)
        updates: dict[tuple[str, str], str] = {}
        if params.proxy_codec is not None:
            current.proxy_codec = params.proxy_codec
            updates[("", "proxy_codec")] = params.proxy_codec
        if params.proxy_height is not None:
            current.proxy_height = params.proxy_height
            updates[("", "proxy_height")] = str(params.proxy_height)
        if params.checksum_algo is not None:
            current.checksum_algo = params.checksum_algo  # type: ignore[assignment]
            updates[("", "checksum_algo")] = params.checksum_algo
        if params.resolve_path is not None:
            current.resolve_path = params.resolve_path
            updates[("", "resolve_path")] = params.resolve_path
        if params.ffmpeg_path is not None:
            current.ffmpeg_path = params.ffmpeg_path
            updates[("", "ffmpeg_path")] = params.ffmpeg_path
        if params.organize_template is not None:
            current.organize.template = params.organize_template
            updates[("organize", "template")] = params.organize_template
        if params.organize_mode is not None:
            current.organize.mode = params.organize_mode  # type: ignore[assignment]
            updates[("organize", "mode")] = params.organize_mode
        if params.organize_on_conflict is not None:
            current.organize.on_conflict = params.organize_on_conflict  # type: ignore[assignment]
            updates[("organize", "on_conflict")] = params.organize_on_conflict

        path = config_target(self._config_path)
        if updates:
            save_config(current, path)
        return self.settings_get()

    def app_doctor(self) -> DoctorResult:
        """Return dependency + storage health for the Onboarding/Doctor screen."""

        from file_ferry.config import config_target, load_config
        from file_ferry.service.protocol import ToolCheck

        cfg = load_config(self._config_path)
        ffmpeg = _locate_binary(cfg.ffmpeg_path, "ffmpeg")
        ffprobe = _locate_binary(cfg.ffmpeg_path, "ffprobe")
        resolve = cfg.resolve_path if cfg.resolve_path and Path(cfg.resolve_path).exists() else None
        db_path = self._db_path
        return DoctorResult(
            version=self.sidecar_version(),
            protocolVersion=PROTOCOL_VERSION,
            tools=[
                ToolCheck(name="ffmpeg", present=ffmpeg is not None, path=ffmpeg),
                ToolCheck(name="ffprobe", present=ffprobe is not None, path=ffprobe),
                ToolCheck(name="resolve", present=resolve is not None, path=resolve),
                ToolCheck(
                    name="config",
                    present=True,
                    path=str(config_target(self._config_path)),
                    message="settings loaded",
                ),
            ],
            appDataDir=str(self._app_data_dir),
            dbPath=str(db_path),
        )

    def set_event_sink(self, sink: Callable[[str, dict[str, object]], None] | None) -> None:
        """Install the transport that asynchronous events are written to.

        ``wire_server`` passes the sidecar server's ``send_event``. Kept as a
        setter rather than a constructor argument because the service is
        built before the server it will emit through.
        """
        self._event_sink = sink

    def job_subscribe(self, job_id: str) -> JobSnapshot:
        """Start publishing ``job.updated`` for a job, and return its state now.

        Returning the current snapshot closes the race between subscribing
        and the first event: a job that changes between the two is still
        reflected, because the caller already holds where it started.
        """
        snapshot = self._job_service().snapshot(job_id)
        self._job_subscriptions.add(job_id)
        return snapshot

    def job_snapshot(self, job_id: str) -> JobSnapshot:
        """Return the current state of the named job."""
        return self._job_service().snapshot(job_id)

    def job_unsubscribe(self, job_id: str) -> None:
        """Stop publishing for the named job. Idempotent."""
        self._job_subscriptions.discard(job_id)

    def _publish_job_updated(self, job_id: str, *, force: bool = False) -> None:
        """Emit ``job.updated`` for a subscribed job.

        ``force`` publishes regardless of subscription, for the one case a
        client cannot subscribe to in advance: a job that has just been
        created.

        Never raises: an event is a courtesy to the UI, and a broken pipe or
        a job deleted mid-flight must not fail the operation that triggered
        it. A terminal job also drops its own subscription -- it can never
        emit again, so holding it would leak one entry per completed job.
        """
        if self._event_sink is None:
            return
        if not force and job_id not in self._job_subscriptions:
            return
        try:
            snapshot = self._job_service().snapshot(job_id)
        except Exception:
            return
        if snapshot.state in {"succeeded", "failed", "cancelled"}:
            self._job_subscriptions.discard(job_id)
        try:
            self._event_sink(
                "job.updated",
                {"jobId": job_id, "snapshot": snapshot.model_dump(by_alias=True)},
            )
        except Exception:
            return


def _locate_binary(configured: str | None, name: str) -> str | None:
    """Locate a binary from a configured path or PATH lookup."""
    import shutil

    if configured:
        candidate = Path(configured).expanduser()
        # config.ffmpeg_path may point at ffmpeg itself or its dir.
        if candidate.is_dir():
            candidate = candidate / name
        if candidate.exists() and candidate.is_file():
            return str(candidate)
        if candidate.name == name and candidate.exists():
            return str(candidate)
    found = shutil.which(name)
    return found


def _normalize_checksum_algo(algo: str) -> str:
    """Map the legacy config enum value to the vNext protocol value."""
    if algo == "xxhash":
        return "xxhash64"
    return algo
