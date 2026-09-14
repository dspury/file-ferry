"""The application service root.

The :class:`ApplicationService` is the assembly root. It owns the
SQLite connection, the migration runner, the repositories, and the
per-domain services. The CLI, the TUI, and the sidecar all instantiate
exactly one :class:`ApplicationService` per process.

It boots, runs the pending migrations, and serves the protocol-shaped
methods that the desktop shell and the in-process client both consume.
The domain work it delegates to -- intake planning, replica
verification, organization, reconciliation, and job execution -- lives
in the per-domain services under ``file_ferry.application`` per
ADR-0005; this module wires them together and owns nothing else.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from file_ferry import APP_VERSION
from file_ferry.application.assets import AssetService
from file_ferry.application.audit import AuditService
from file_ferry.application.clips import ClipService
from file_ferry.application.derivatives import DerivativeService
from file_ferry.application.destinations import DestinationObservation, DestinationService
from file_ferry.application.dispatcher import JobDispatcher
from file_ferry.application.intake import IntakeService
from file_ferry.application.inventory import InventoryService, recover_abandoned_scans
from file_ferry.application.jobs import JobService
from file_ferry.application.manifest import ManifestService
from file_ferry.application.offload import OffloadRunner
from file_ferry.application.organize import OrganizeService
from file_ferry.application.plan import IntakePlanner
from file_ferry.application.policies import StoragePolicy
from file_ferry.application.preflight import PreflightService, recover_abandoned_preflights
from file_ferry.application.presets import PresetRevisionService
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
from file_ferry.application.transfer_plan import TransferPlanService
from file_ferry.application.transfer_runner import TRANSFER_COMMAND, TransferRunner
from file_ferry.application.volumes import SystemVolumeAdapter, VolumeChange, VolumeObserver
from file_ferry.persistence import runner
from file_ferry.persistence.connection import transaction
from file_ferry.service.protocol import (
    PROTOCOL_VERSION,
    AcceptChangeParams,
    AddDestinationParams,
    AppSettings,
    ArchiveDestinationParams,
    ArchiveProjectParams,
    AssetSummary,
    AuditEvent,
    BuildPlanParams,
    CancelJobParams,
    ConfirmBindingParams,
    CreateIntakeSessionParams,
    CreateJobParams,
    CreateProjectParams,
    DerivativeSummary,
    DestinationSummary,
    DetectClipsParams,
    DiscoveryStatus,
    DoctorResult,
    ExportReceiptParams,
    ExportReceiptResult,
    IntakeDestination,
    IntakePlan,
    IntakeSession,
    InventoryCreateParams,
    InventoryCreateResult,
    InventoryEntriesPage,
    InventoryEntriesParams,
    InventoryStatus,
    InventoryStatusParams,
    JobDetail,
    JobSnapshot,
    JobTransitionParams,
    ListAssetsParams,
    ListAuditParams,
    ListDestinationsResult,
    ListPresetRevisionsResult,
    LogicalClip,
    MountedVolume,
    OrganizationProfile,
    OrganizeApplyParams,
    OrganizePreview,
    OrganizePreviewParams,
    OrganizeResult,
    PlanApproveParams,
    PlanCreateParams,
    PlanEntriesPage,
    PlanEntriesParams,
    PlanIdParams,
    PlanResolveParams,
    PreflightStartParams,
    PreflightStatus,
    PreflightStatusParams,
    PresetExportResult,
    PresetImportParams,
    PresetRevisionDetail,
    PresetRevisionSummary,
    ProfilePreviewParams,
    ProjectDetail,
    ProjectManifest,
    ProjectSummary,
    ReconcileAssetParams,
    ReconcileProjectParams,
    ReconcileReport,
    ReplicaSummary,
    ResolveDestinationParams,
    ResolveDestinationsResult,
    ResolveImportManifest,
    SafeToFormatEval,
    SaveDestinationParams,
    SavePresetRevisionParams,
    SaveProfileParams,
    SourceInspectParams,
    SourceInspectResult,
    SourceInventoryEntry,
    TransferPlanStatusModel,
    TransferReceiptParams,
    TransferReceiptStatus,
    TransferStartParams,
    TransferStartResult,
    UpdateProjectParams,
    UpdateSettingsParams,
    VerifyReplicaParams,
    VerifyReplicaResult,
)

LOGGER = logging.getLogger(__name__)

# The version the sidecar reports over `app.getStatus` / `app.doctor`.
# Derived rather than declared: it was a separate literal
# ("0.0.0+foundation") through 0.3.0, so the desktop Environment screen
# told the operator they were running 0.0.0 while the same run stamped
# 0.3.0 into its receipts. Two version strings describing one operation
# undercut both surfaces, so there is now one source.
SIDECAR_VERSION = APP_VERSION

METHOD_NAMES: tuple[str, ...] = (
    "destination.save",
    "destination.list",
    "destination.get",
    "destination.archive",
    "destination.resolve",
    "destination.confirmBinding",
    "profile.saveRevision",
    "profile.getRevision",
    "profile.listRevisions",
    "profile.export",
    "profile.import",
    "inventory.create",
    "inventory.status",
    "inventory.entries",
    "transfer.planCreate",
    "transfer.planGet",
    "transfer.planEntries",
    "transfer.planResolve",
    "transfer.planApprove",
    "transfer.preflightStart",
    "transfer.preflightStatus",
    "transfer.start",
    "transfer.receipt",
    "transfer.receiptExport",
    "destination.discovery",
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
#: An observation older than this is shown as stale rather than current.
#: Mount tables change when hardware changes, not on a clock, so this is
#: about honesty in the UI, not a cache expiry (spec §5.2).
STALE_OBSERVATION_SECONDS = 30.0

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
        self._destinations: DestinationService | None = None
        self._preset_revisions: PresetRevisionService | None = None
        self._inventory: InventoryService | None = None
        self._transfer_plans: TransferPlanService | None = None
        self._transfer_runner: TransferRunner | None = None
        self._preflight: PreflightService | None = None

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
        _assert_schema_shape(self._db_path)
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
        self._destinations = DestinationService(self._db_path)
        self._preset_revisions = PresetRevisionService(self._db_path)
        self._inventory = InventoryService(self._db_path)
        self._transfer_plans = TransferPlanService(self._db_path)
        self._preflight = PreflightService(
            self._db_path,
            destinations=self._destinations,
            observations=self._destination_observations,
        )
        # Spec §7.3: a scan abandoned by a previous process would stay
        # ``scanning`` forever, and a planner reading it would treat a
        # partial entry set as the whole source. Fail those on startup,
        # keeping their partial entries as evidence.
        abandoned = recover_abandoned_scans(self._db_path)
        if abandoned:
            LOGGER.warning(
                "marked %d abandoned inventory scan(s) failed: %s",
                len(abandoned),
                abandoned,
            )
        stale_preflights = recover_abandoned_preflights(self._db_path)
        if stale_preflights:
            LOGGER.warning(
                "marked %d abandoned preflight(s) failed: %s",
                len(stale_preflights),
                stale_preflights,
            )
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

        Stops every background worker, not only the dispatcher: an
        inventory scan or a preflight that outlives shutdown keeps
        writing to the database, which surfaces later as an unrelated
        flake rather than as the lifecycle bug it is.
        """
        if self._dispatcher is not None:
            self._dispatcher.stop()
            self._dispatcher = None
        # Background scans and preflights hold the database too. Leaving
        # them running past shutdown means writes continue against a
        # database the caller believes it has released.
        if self._inventory is not None:
            self._inventory.shutdown()
        if self._preflight is not None:
            self._preflight.shutdown()

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
        self._destinations = None
        self._preset_revisions = None
        self._inventory = None
        self._transfer_plans = None
        self._transfer_runner = None
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

    # ---- destination methods ----------------------------------------

    def destination_save(self, params: SaveDestinationParams) -> DestinationSummary:
        return self._destination_service().save(params)

    def destination_list(self, *, include_archived: bool = False) -> ListDestinationsResult:
        return self._destination_service().list_destinations(include_archived=include_archived)

    def destination_get(self, destination_id: int) -> DestinationSummary:
        return self._destination_service().get(destination_id)

    def destination_archive(self, params: ArchiveDestinationParams) -> DestinationSummary:
        return self._destination_service().archive(params.id)

    def destination_resolve(self, params: ResolveDestinationParams) -> ResolveDestinationsResult:
        """Match saved destinations against what is actually mounted.

        The observations come from the one volume observer (spec §5.2
        forbids a second discovery loop). ``refresh=False`` reuses the
        last observation rather than probing again, which is what a
        rapidly re-rendering UI should ask for; the observation's age is
        reported so a stale answer is visibly stale rather than
        confidently wrong.
        """
        observations = self._destination_observations(refresh=params.refresh)
        return self._destination_service().resolve(
            destination_id=params.id, observations=observations
        )

    def _destination_observations(self, *, refresh: bool = True) -> list[DestinationObservation]:
        """Adapt the current volume observation into resolver inputs."""
        if self._volume_observer is None:
            raise RuntimeError("ApplicationService.bootstrap() must be called first")
        if refresh or not self._volume_observer.initialized:
            volumes = self._volume_observer.snapshot()
        else:
            volumes = self._volume_observer.last_volumes()
        return [DestinationObservation.from_volume(v) for v in volumes]

    def destination_discovery(self) -> DiscoveryStatus:
        """What discovery currently knows, and what it could not learn.

        Surfaced so the UI can show a recoverable warning and keep manual
        folder selection usable, instead of a spinner that never resolves
        (spec §5.2).
        """
        if self._volume_observer is None:
            raise RuntimeError("ApplicationService.bootstrap() must be called first")
        observer = self._volume_observer
        if not observer.initialized:
            observer.snapshot()
        age = observer.age_seconds()
        volumes = observer.last_volumes()
        # Stale is not only about the clock: a snapshot taken one second
        # ago that *reused* remembered identity for some mount is stale
        # in the way that matters, because that evidence is not about
        # what is mounted now (R10).
        reused = [v.path for v in volumes if v.identity is not None and v.identity.stale]
        warnings = list(observer.warnings())
        if reused:
            warnings.append(
                "identity for "
                + ", ".join(sorted(reused))
                + " was remembered from an earlier observation, not read now; those "
                "destinations need explicit confirmation before use"
            )
        return DiscoveryStatus(
            volumes=volumes,
            observedAt=observer.observed_at,
            ageSeconds=age,
            stale=bool(reused) or (age is not None and age > STALE_OBSERVATION_SECONDS),
            warnings=warnings,
        )

    def destination_confirm_binding(self, params: ConfirmBindingParams) -> DestinationSummary:
        """Rebind a destination to a user-chosen location.

        Fresh observations are passed so the service can refuse a
        path/identity pair that contradicts what is actually mounted
        there (R11) and derive a consistent mount/subfolder/binding.
        """
        return self._destination_service().confirm_binding(
            params.destination_id,
            path=params.path,
            identity=params.identity,
            observations=self._destination_observations(),
        )

    # ---- preset revision methods ------------------------------------

    def profile_save_revision(self, params: SavePresetRevisionParams) -> PresetRevisionSummary:
        return self._preset_revision_service().save_revision(params)

    def profile_get_revision(
        self, preset_id: int, revision: int | None = None
    ) -> PresetRevisionDetail:
        # The pydantic model PresetRevisionDetail returns content too;
        # the existing typed wrapper keeps the round-trip shape simple.

        row, content = self._preset_revision_service().get_revision(preset_id, revision)
        return PresetRevisionDetail(
            presetId=row.preset_id,
            revision=row.revision,
            createdAt=row.created_at,
            contentHash=row.content_hash,
            content=content,
            legacySnapshot=row.description is not None
            and "legacy snapshot" in row.description.lower(),
        )

    def profile_list_revisions(
        self, preset_id: int, *, limit: int = 50, after_id: int = 0
    ) -> ListPresetRevisionsResult:
        from file_ferry.service.protocol import ListPresetRevisionsResult

        rows, total = self._preset_revision_service().list_revisions(
            preset_id, limit=limit, after_id=after_id
        )
        return ListPresetRevisionsResult(revisions=rows, total=total)

    def profile_export(self, preset_id: int, revision: int | None = None) -> PresetExportResult:
        return self._preset_revision_service().export_preset(preset_id, revision)

    def profile_import(self, params: PresetImportParams) -> PresetRevisionSummary:
        return self._preset_revision_service().import_preset(
            params.payload, new_name=params.new_name
        )

    # ---- inventory methods ------------------------------------------

    def inventory_create(self, params: InventoryCreateParams) -> InventoryCreateResult:
        status = self._inventory_service().create(params.path, params.label)
        return InventoryCreateResult(inventoryId=status.id)

    def inventory_status(self, params: InventoryStatusParams) -> InventoryStatus:
        return self._inventory_service().get(params.id)

    def inventory_entries(self, params: InventoryEntriesParams) -> InventoryEntriesPage:
        return self._inventory_service().entries(params.id, limit=params.limit, after=params.after)

    # ---- transfer plan methods --------------------------------------

    def transfer_plan_create(self, params: PlanCreateParams) -> TransferPlanStatusModel:
        return self._transfer_plan_service().create(
            destination_id=params.destination_id,
            inventory_ids=params.inventory_ids,
            binding_path=params.binding_path,
            preset_id=params.preset_id,
            preset_revision=params.preset_revision,
            project_id=params.project_id,
            capacity_override_reason=params.capacity_override_reason,
        )

    def transfer_plan_get(self, params: PlanIdParams) -> TransferPlanStatusModel:
        return self._transfer_plan_service().get(params.id)

    def transfer_plan_entries(self, params: PlanEntriesParams) -> PlanEntriesPage:
        return self._transfer_plan_service().entries(
            params.id, limit=params.limit, after=params.after
        )

    def transfer_plan_resolve(self, params: PlanResolveParams) -> TransferPlanStatusModel:
        """Apply reviewed decisions, returning the new plan (spec §8).

        Plans are immutable, so this never edits one: it produces the
        next revision with the decisions carried in and records which
        plan it came from. The reviewed original is left exactly as it
        was.
        """
        return self._transfer_plan_service().resolve(
            params.id,
            entry_ids=params.entry_ids,
            decisions=params.decisions,
            reason=params.reason,
        )

    def transfer_plan_approve(self, params: PlanApproveParams) -> TransferPlanStatusModel:
        """Approve a plan, which requires a current passing preflight.

        See :meth:`TransferPlanService.approve`: stored rows cannot tell
        you that a drive was unplugged, so approval will refuse until a
        preflight has gone and looked.
        """
        return self._transfer_plan_service().approve(params.id, params.fingerprint)

    def transfer_preflight_start(self, params: PreflightStartParams) -> PreflightStatus:
        """Begin validating a plan against the live filesystem and storage.

        Returns immediately with the run's id; a large plan is hundreds
        of thousands of stat calls and must not block the IPC handler
        (spec §12). Poll ``transfer.preflightStatus`` for progress.
        """
        return self._preflight_service().start(params.plan_id)

    def transfer_preflight_status(self, params: PreflightStatusParams) -> PreflightStatus:
        return self._preflight_service().get(params.id)

    def transfer_start(self, params: TransferStartParams) -> TransferStartResult:
        """Queue an approved plan for execution (spec §7.2).

        Returns as soon as the durable job and execution exist; the
        dispatcher runs the copy. A kick is needed because nothing else
        wakes the dispatcher for a job queued outside ``job.create``.
        """
        result = self._transfer_runner_service().start(params)
        self._dispatcher_service().kick()
        return result

    def transfer_receipt(self, params: TransferReceiptParams) -> TransferReceiptStatus:
        """The durable receipt of a plan's latest execution (spec §7.3)."""
        return self._transfer_runner_service().receipt(params)

    def transfer_receipt_export(self, params: TransferReceiptParams) -> TransferReceiptStatus:
        """Re-attempt the JSON export of a receipt and report the outcome."""
        return self._transfer_runner_service().export_receipt(params)

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
        # Executions are a separate ledger from jobs, and a crash leaves
        # path reservations held by a job that will never run again. The
        # job ids are the wire contract here, so the released executions
        # are logged rather than mixed into the returned list (A21).
        released = self._transfer_runner_service().recover_executions()
        if released:
            LOGGER.warning(
                "reconciled %d abandoned transfer execution(s): %s", len(released), released
            )
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
        """Wire the durable runners (offload, proxy, transfer) into the scheduler."""
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
        # The transfer runner needs the live volume observations to prove a
        # destination is still the bound one before it publishes anything,
        # so it takes the same observation seam the resolver uses rather
        # than opening a second discovery loop (spec §5.2).
        transfer = TransferRunner(
            self._db_path,
            self._job_service(),
            self._destination_service(),
            self._destination_observations,
            app_data_dir=self._app_data_dir,
        )
        self._transfer_runner = transfer
        self._scheduler_service().register_runner(TRANSFER_COMMAND, transfer)
        # Per-destination serialization: two transfers writing the same
        # volume at once would race on path reservations and on capacity.
        self._scheduler_service().register_volume(TRANSFER_COMMAND, transfer.volume_of)

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

    def _destination_service(self) -> DestinationService:
        if self._destinations is None:
            raise RuntimeError("ApplicationService.bootstrap() must be called first")
        return self._destinations

    def _preset_revision_service(self) -> PresetRevisionService:
        if self._preset_revisions is None:
            raise RuntimeError("ApplicationService.bootstrap() must be called first")
        return self._preset_revisions

    def _inventory_service(self) -> InventoryService:
        if self._inventory is None:
            raise RuntimeError("ApplicationService.bootstrap() must be called first")
        return self._inventory

    def _preflight_service(self) -> PreflightService:
        if self._preflight is None:
            raise RuntimeError("ApplicationService.bootstrap() must be called first")
        return self._preflight

    def _transfer_plan_service(self) -> TransferPlanService:
        if self._transfer_plans is None:
            raise RuntimeError("ApplicationService.bootstrap() must be called first")
        return self._transfer_plans

    def _transfer_runner_service(self) -> TransferRunner:
        if self._transfer_runner is None:
            raise RuntimeError("ApplicationService.bootstrap() must be called first")
        return self._transfer_runner

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


def _assert_schema_shape(db_path: Path) -> None:
    """Verify the applied schema matches what this build expects.

    Migrations are keyed by version number alone, so a database stamped
    with a version whose migration has since been *amended* is skipped
    silently and then fails somewhere far away. Migration 004 is the one
    case in this tree (amended before it was ever committed, so only
    development databases can be affected); the check lives here rather
    than in the runner because the runner's job is to apply pending
    migrations, and there are none pending in this situation.
    """
    import importlib

    from file_ferry.persistence.connection import open_connection

    # The module name starts with a digit, so it is not importable by
    # ordinary syntax; the migration runner reaches it the same way.
    v4 = importlib.import_module("file_ferry.persistence.migrations.004_destination_presets")
    conn = open_connection(db_path)
    try:
        v4.assert_v4_shape(conn)
    finally:
        conn.close()
