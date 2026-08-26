"""Wire the JSON-RPC server to the application services.

This module is the sidecar's dispatch table. It maps every method name
in the protocol catalog (``METHOD_NAMES`` in
``file_ferry.application.service``) to a handler that validates the
inbound params against the matching pydantic model and invokes the
corresponding ``ApplicationService`` method.

The server alone cannot do the work; without this wiring every request
would return ``method_not_found``. ``wire_server`` is the single entry
point the sidecar bootstrap calls once it has a bootstrapped
``ApplicationService``.

See ADR-0002 (IPC protocol) and ADR-0005 (application service module
structure).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from file_ferry.application.service import ApplicationService
from file_ferry.service.protocol import (
    PROTOCOL_VERSION,
    AcceptChangeParams,
    AddDestinationParams,
    AdoptSourceParams,
    AdoptSourceResult,
    AppSettings,
    AppStatus,
    ArchiveProjectParams,
    AssetSummary,
    BuildPlanParams,
    CancelJobParams,
    CreateIntakeSessionParams,
    CreateJobParams,
    CreateProjectParams,
    CreateProjectResult,
    DerivativeSummary,
    DetectClipsParams,
    DoctorResult,
    ExportReceiptParams,
    ExportReceiptResult,
    GetCapabilities,
    IntakeDestination,
    IntakePlan,
    IntakeSession,
    JobDetail,
    JobSnapshot,
    JobTransitionParams,
    ListAssetsParams,
    ListAssetsResult,
    ListAuditParams,
    ListAuditResult,
    ListJobsParams,
    ListJobsResult,
    ListProfilesResult,
    ListProjectsResult,
    ListReplicasResult,
    ListVolumesResult,
    LogicalClip,
    OrganizationProfile,
    OrganizeApplyParams,
    OrganizePreview,
    OrganizePreviewParams,
    OrganizeResult,
    ProfilePreviewParams,
    ProjectDetail,
    ProjectManifest,
    ReconcileAssetParams,
    ReconcileProjectParams,
    ReconcileReport,
    ResolveImportManifest,
    SafeToFormatEval,
    SaveProfileParams,
    SourceInspectParams,
    SourceInspectResult,
    UpdateProjectParams,
    UpdateSettingsParams,
    VerifyReplicaParams,
    VerifyReplicaResult,
)
from file_ferry.service.server import SidecarServer, rpc_error

# A handler validates params against a pydantic model, calls the
# service, and returns a pydantic model (or a plain value) that the
# server serializes into the response frame.
Handler = Callable[[dict[str, Any]], Any]


def wire_server(server: SidecarServer, service: ApplicationService) -> None:
    """Register every method in the catalog as a handler on ``server``.

    ``service`` must already be bootstrapped (``service.bootstrap()``
    called) so that the domain services exist.
    """
    # The service is built before the server, so the event transport is
    # attached here -- this is what turns `job.updated` from a declared
    # event into one that can actually reach the desktop.
    service.set_event_sink(server.send_event)
    handlers = _build_handlers(service)
    for method, handler in handlers.items():

        def dispatch(frame: object, h: Handler = handler) -> Any:
            # The server passes RequestFrame; extract params. Guard for
            # robustness against a non-request call.
            params = getattr(frame, "params", None)
            if not isinstance(params, dict):
                rpc_error("invalid_request", "expected a request frame")
            return h(params)

        server.register(method, dispatch)


def _validate(model: type[Any], params: dict[str, Any]) -> Any:
    """Validate inbound params against a pydantic model.

    Raises ``invalid_params`` via :func:`rpc_error` on failure so the
    caller sees a typed error rather than a 500.
    """
    try:
        return model.model_validate(params)
    except Exception as exc:  # pydantic.ValidationError
        rpc_error("invalid_params", f"invalid params for {model.__name__}: {exc}")


def _build_handlers(service: ApplicationService) -> dict[str, Handler]:
    """Build the method -> handler table for the current service."""

    def app_get_status(_: dict[str, Any]) -> AppStatus:
        return AppStatus(
            sidecarVersion=service.sidecar_version(),
            protocolVersion=PROTOCOL_VERSION,
            capabilities=list(service.capabilities()),
        )

    def app_get_capabilities(_: dict[str, Any]) -> GetCapabilities:
        return GetCapabilities(
            methods=list(service.method_names()),
            events=list(service.event_names()),
            version=PROTOCOL_VERSION,
        )

    def app_doctor(_: dict[str, Any]) -> DoctorResult:
        return service.app_doctor()

    def project_list(_: dict[str, Any]) -> ListProjectsResult:
        return ListProjectsResult(projects=service.list_projects())

    def project_create(params: dict[str, Any]) -> CreateProjectResult:
        p = _validate(CreateProjectParams, params)
        return CreateProjectResult(projectId=service.create_project(p))

    def project_get(params: dict[str, Any]) -> ProjectDetail:
        project_id = params.get("projectId")
        if not isinstance(project_id, str) or not project_id:
            rpc_error("invalid_params", "missing projectId")
        return service.get_project(project_id)

    def project_update(params: dict[str, Any]) -> ProjectDetail:
        p = _validate(UpdateProjectParams, params)
        return service.update_project(p)

    def project_archive(params: dict[str, Any]) -> ProjectDetail:
        p = _validate(ArchiveProjectParams, params)
        return service.archive_project(p)

    def source_list_volumes(_: dict[str, Any]) -> ListVolumesResult:
        return ListVolumesResult(volumes=service.list_volumes())

    def source_inspect(params: dict[str, Any]) -> SourceInspectResult:
        p = _validate(SourceInspectParams, params)
        return service.source_inspect(p)

    def profile_save(params: dict[str, Any]) -> OrganizationProfile:
        p = _validate(SaveProfileParams, params)
        return service.profile_save(p)

    def profile_list(_: dict[str, Any]) -> ListProfilesResult:
        return ListProfilesResult(profiles=service.profile_list())

    def profile_get(params: dict[str, Any]) -> OrganizationProfile:
        profile_id = params.get("id")
        if not isinstance(profile_id, int):
            rpc_error("invalid_params", "missing id")
        return service.profile_get(profile_id)

    def profile_preview(params: dict[str, Any]) -> OrganizePreview:
        p = _validate(ProfilePreviewParams, params)
        return service.profile_preview(p)

    def asset_list(params: dict[str, Any]) -> ListAssetsResult:
        p = _validate(ListAssetsParams, params)
        return ListAssetsResult(assets=service.asset_list(p))

    def asset_get(params: dict[str, Any]) -> AssetSummary:
        # asset.get uses assetId; validate the shape directly.
        asset_id = params.get("assetId")
        if not isinstance(asset_id, str) or not asset_id:
            rpc_error("invalid_params", "missing assetId")
        return service.asset_get(asset_id)

    def replica_verify(params: dict[str, Any]) -> VerifyReplicaResult:
        p = _validate(VerifyReplicaParams, params)
        return service.replica_verify(p)

    def replica_list(params: dict[str, Any]) -> ListReplicasResult:
        asset_id = params.get("assetId")
        if not isinstance(asset_id, str) or not asset_id:
            rpc_error("invalid_params", "missing assetId")
        return ListReplicasResult(replicas=service.replica_list(asset_id))

    def intake_create_session(params: dict[str, Any]) -> IntakeSession:
        p = _validate(CreateIntakeSessionParams, params)
        return service.intake_create_session(p)

    def intake_add_destination(params: dict[str, Any]) -> IntakeDestination:
        p = _validate(AddDestinationParams, params)
        return service.intake_add_destination(p)

    def intake_evaluate(params: dict[str, Any]) -> SafeToFormatEval:
        session_id = params.get("sessionId")
        if not isinstance(session_id, str) or not session_id:
            rpc_error("invalid_params", "missing sessionId")
        return service.intake_evaluate(session_id)

    def intake_adopt_source(params: dict[str, Any]) -> AdoptSourceResult:
        p = _validate(AdoptSourceParams, params)
        asset_ids = service.intake_adopt_source(
            p.session_id,
            p.source_id,
            p.entries,
            p.destination_root,
            project_id=p.project_id,
        )
        return AdoptSourceResult(assetIds=asset_ids)

    def job_create(params: dict[str, Any]) -> JobDetail:
        p = _validate(CreateJobParams, params)
        return service.job_create(p)

    def job_list(params: dict[str, Any]) -> ListJobsResult:
        p = _validate(ListJobsParams, params)
        return ListJobsResult(jobs=service.job_list(p.project_id))

    def job_get(params: dict[str, Any]) -> JobDetail:
        p = _validate(CancelJobParams, params)
        return service.job_get(p.id)

    def job_transition(params: dict[str, Any]) -> JobDetail:
        p = _validate(JobTransitionParams, params)
        return service.job_transition(p)

    def job_cancel(params: dict[str, Any]) -> dict[str, Any]:
        p = _validate(CancelJobParams, params)
        service.job_cancel(p)
        return {}

    def job_dispatch(params: dict[str, Any]) -> dict[str, Any]:
        job_id = params.get("id")
        if not isinstance(job_id, str) or not job_id:
            rpc_error("invalid_params", "missing id")
        service.job_dispatch(job_id)
        return {}

    def job_dispatch_next(_: dict[str, Any]) -> dict[str, Any]:
        service.job_dispatch_next()
        return {}

    def job_recover(_: dict[str, Any]) -> list[str]:
        return service.job_recover()

    def job_resume(params: dict[str, Any]) -> JobDetail:
        job_id = params.get("id")
        if not isinstance(job_id, str) or not job_id:
            rpc_error("invalid_params", "missing id")
        return service.job_resume(job_id)

    def job_retry(params: dict[str, Any]) -> JobDetail:
        job_id = params.get("id")
        if not isinstance(job_id, str) or not job_id:
            rpc_error("invalid_params", "missing id")
        return service.job_retry(job_id)

    def plan_build(params: dict[str, Any]) -> IntakePlan:
        p = _validate(BuildPlanParams, params)
        return service.plan_build(p)

    def receipt_export(params: dict[str, Any]) -> ExportReceiptResult:
        p = _validate(ExportReceiptParams, params)
        return service.receipt_export(p)

    def receipt_get(params: dict[str, Any]) -> dict[str, Any]:
        op_id = params.get("operationId")
        if not isinstance(op_id, str) or not op_id:
            rpc_error("invalid_params", "missing operationId")
        return service.receipt_get(op_id)

    def reconcile_asset(params: dict[str, Any]) -> ReconcileReport:
        p = _validate(ReconcileAssetParams, params)
        return service.reconcile_asset(p)

    def reconcile_project(params: dict[str, Any]) -> list[ReconcileReport]:
        p = _validate(ReconcileProjectParams, params)
        return service.reconcile_project(p)

    def reconcile_accept_change(params: dict[str, Any]) -> ReconcileReport:
        p = _validate(AcceptChangeParams, params)
        return service.reconcile_accept_change(p)

    def organize_preview(params: dict[str, Any]) -> OrganizePreview:
        p = _validate(OrganizePreviewParams, params)
        return service.organize_preview(p)

    def organize_apply(params: dict[str, Any]) -> OrganizeResult:
        p = _validate(OrganizeApplyParams, params)
        return service.organize_apply(p)

    def clips_detect(params: dict[str, Any]) -> list[LogicalClip]:
        p = _validate(DetectClipsParams, params)
        return service.clips_detect(p)

    def clips_list(params: dict[str, Any]) -> list[LogicalClip]:
        p = _validate(DetectClipsParams, params)
        return service.clips_list(p.source_id)

    def derivatives_list(params: dict[str, Any]) -> list[DerivativeSummary]:
        asset_id = params.get("assetId")
        if not isinstance(asset_id, str) or not asset_id:
            rpc_error("invalid_params", "missing assetId")
        return service.derivatives_list(asset_id)

    def _project_id(params: dict[str, Any]) -> str:
        project_id = params.get("projectId")
        if not isinstance(project_id, str) or not project_id:
            rpc_error("invalid_params", "missing projectId")
        return project_id

    def manifest_export(params: dict[str, Any]) -> ProjectManifest:
        return service.manifest_export(_project_id(params))

    def manifest_handoff(params: dict[str, Any]) -> str:
        return service.manifest_handoff(_project_id(params))

    def manifest_resolve(params: dict[str, Any]) -> ResolveImportManifest:
        return service.manifest_resolve(_project_id(params))

    def audit_list(params: dict[str, Any]) -> ListAuditResult:
        p = _validate(ListAuditParams, params)
        return ListAuditResult(events=service.audit_list(p))

    def audit_backfill(_: dict[str, Any]) -> int:
        return service.audit_backfill()

    def job_subscribe(params: dict[str, Any]) -> JobSnapshot:
        job_id = params.get("jobId")
        if not isinstance(job_id, str) or not job_id:
            rpc_error("invalid_params", "missing jobId")
        return service.job_subscribe(job_id)

    def job_unsubscribe(params: dict[str, Any]) -> dict[str, Any]:
        job_id = params.get("jobId")
        if not isinstance(job_id, str) or not job_id:
            rpc_error("invalid_params", "missing jobId")
        service.job_unsubscribe(job_id)
        return {}

    def settings_get(_: dict[str, Any]) -> AppSettings:
        return service.settings_get()

    def settings_update(params: dict[str, Any]) -> AppSettings:
        p = _validate(UpdateSettingsParams, params)
        return service.settings_update(p)

    handlers: dict[str, Handler] = {
        "app.getStatus": app_get_status,
        "app.getCapabilities": app_get_capabilities,
        "app.doctor": app_doctor,
        "project.list": project_list,
        "project.create": project_create,
        "project.get": project_get,
        "project.update": project_update,
        "project.archive": project_archive,
        "source.listVolumes": source_list_volumes,
        "source.inspect": source_inspect,
        "profile.save": profile_save,
        "profile.list": profile_list,
        "profile.get": profile_get,
        "profile.preview": profile_preview,
        "asset.list": asset_list,
        "asset.get": asset_get,
        "replica.verify": replica_verify,
        "replica.list": replica_list,
        "intake.createSession": intake_create_session,
        "intake.addDestination": intake_add_destination,
        "intake.evaluate": intake_evaluate,
        "intake.adoptSource": intake_adopt_source,
        "job.create": job_create,
        "job.list": job_list,
        "job.get": job_get,
        "job.transition": job_transition,
        "job.cancel": job_cancel,
        "job.dispatch": job_dispatch,
        "job.dispatchNext": job_dispatch_next,
        "job.recover": job_recover,
        "job.resume": job_resume,
        "job.retry": job_retry,
        "plan.build": plan_build,
        "receipt.export": receipt_export,
        "receipt.get": receipt_get,
        "reconcile.asset": reconcile_asset,
        "reconcile.project": reconcile_project,
        "reconcile.acceptChange": reconcile_accept_change,
        "organize.preview": organize_preview,
        "organize.apply": organize_apply,
        "clips.detect": clips_detect,
        "clips.list": clips_list,
        "derivatives.list": derivatives_list,
        "manifest.export": manifest_export,
        "manifest.handoff": manifest_handoff,
        "manifest.resolve": manifest_resolve,
        "audit.list": audit_list,
        "audit.backfill": audit_backfill,
        "job.subscribe": job_subscribe,
        "job.unsubscribe": job_unsubscribe,
        "settings.get": settings_get,
        "settings.update": settings_update,
    }
    return handlers
