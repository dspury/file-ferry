"""JSON-RPC protocol types for the vNext IPC.

These pydantic models mirror the TypeScript types in
``desktop/shared/ipc-schema.ts`` and ``desktop/shared/ipc-methods.ts``.
The two sides are the contract; the matching tests in
``tests/test_service_protocol.py`` and ``desktop/tests/ipc-contract.test.ts``
must be updated in the same commit when the protocol changes.

See ADR-0002 (IPC protocol) and ADR-0005 (application service module
structure).
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel

# Frozen protocol version. Must match desktop/shared/version.ts.
PROTOCOL_VERSION: Literal[1] = 1


class FrozenModel(BaseModel):
    """Base model with strict fields and no implicit mutation."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        use_attribute_docstrings=True,
        ser_json_inf_nan="constants",
    )


# ---------------------------------------------------------------------------
# JSON-RPC envelope
# ---------------------------------------------------------------------------

RpcErrorCode = Literal[
    "parse_error",
    "invalid_request",
    "method_not_found",
    "invalid_params",
    "schema_invalid",
    "version_mismatch",
    "internal_error",
    "cancelled",
    "needs_attention",
    "unsafe_state",
]


class RpcError(FrozenModel):
    """A typed error returned over the IPC."""

    code: RpcErrorCode
    message: str
    data: dict[str, Any] | None = None


class RequestFrame(FrozenModel):
    """A request sent from the desktop to the sidecar."""

    jsonrpc: Literal["2.0"]
    v: Literal[1]
    kind: Literal["request"]
    id: str
    method: str
    params: dict[str, Any]


class ResponseFrame(FrozenModel):
    """A successful response from the sidecar to the desktop."""

    jsonrpc: Literal["2.0"]
    v: Literal[1]
    kind: Literal["response"]
    id: str
    result: Any


class EventFrame(FrozenModel):
    """An asynchronous event from the sidecar to the desktop."""

    jsonrpc: Literal["2.0"]
    v: Literal[1]
    kind: Literal["event"]
    method: str
    params: dict[str, Any]


class ErrorFrame(FrozenModel):
    """An error response from the sidecar to the desktop."""

    jsonrpc: Literal["2.0"]
    v: Literal[1]
    kind: Literal["error"]
    id: str
    error: RpcError


Frame = Annotated[
    RequestFrame | ResponseFrame | EventFrame | ErrorFrame,
    Field(discriminator="kind"),
]


class FrameRoot(RootModel[Frame]):
    """Root model for decoding frames from a JSON line."""

    root: Frame


# ---------------------------------------------------------------------------
# Method catalog
# ---------------------------------------------------------------------------


class AppStatus(FrozenModel):
    """The result of ``app.getStatus``."""

    sidecar_version: str = Field(alias="sidecarVersion")
    protocol_version: Literal[1] = Field(alias="protocolVersion")
    capabilities: list[str]


class GetCapabilities(FrozenModel):
    """The result of ``app.getCapabilities``."""

    methods: list[str]
    events: list[str]
    version: Literal[1]


class StoragePolicy(FrozenModel):
    """The storage-policy shape shared by the IPC and receipts (ADR-0004)."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        populate_by_name=True,
        use_attribute_docstrings=True,
        ser_json_inf_nan="constants",
    )

    required_replicas: int = Field(default=2, ge=1, alias="requiredReplicas")
    backup_on_different_volume: bool = Field(default=True, alias="backupOnDifferentVolume")
    checksum_algo: Literal["xxhash64", "sha256"] = Field(default="xxhash64", alias="checksumAlgo")
    safety_reserve_bytes: int = Field(default=0, ge=0, alias="safetyReserveBytes")
    require_source_fingerprint: bool = Field(default=True, alias="requireSourceFingerprint")


class CreateProjectParams(FrozenModel):
    """The params for ``project.create``."""

    name: str
    working_root: str = Field(alias="workingRoot")
    backup_root: str | None = Field(default=None, alias="backupRoot")
    storage_policy: StoragePolicy | None = Field(default=None, alias="storagePolicy")
    acknowledge_weaker: bool = Field(default=False, alias="acknowledgeWeaker")


class CreateProjectResult(FrozenModel):
    """The result of ``project.create``."""

    project_id: str = Field(alias="projectId")


class ProjectSummary(FrozenModel):
    """One row in the ``project.list`` result."""

    id: str
    name: str
    working_root: str = Field(alias="workingRoot")
    backup_root: str | None = Field(alias="backupRoot")
    status: str
    storage_policy: StoragePolicy = Field(alias="storagePolicy")
    created_at: str = Field(alias="createdAt")
    updated_at: str = Field(alias="updatedAt")
    archived_at: str | None = Field(alias="archivedAt")


class ListProjectsResult(FrozenModel):
    """The result of ``project.list``."""

    projects: list[ProjectSummary]


class ProjectDetail(ProjectSummary):
    """The result of ``project.get`` — the summary plus defaults."""

    organization_profile_id: int | None = Field(alias="organizationProfileId")
    proxy_defaults: dict[str, object] | None = Field(alias="proxyDefaults")
    resolve_defaults: dict[str, object] | None = Field(alias="resolveDefaults")


class UpdateProjectParams(FrozenModel):
    """The params for ``project.update``. Only present fields change."""

    id: str
    name: str | None = None
    working_root: str | None = Field(default=None, alias="workingRoot")
    backup_root: str | None = Field(default=None, alias="backupRoot")
    storage_policy: StoragePolicy | None = Field(default=None, alias="storagePolicy")
    acknowledge_weaker: bool = Field(default=False, alias="acknowledgeWeaker")


class ArchiveProjectParams(FrozenModel):
    """The params for ``project.archive``."""

    id: str


# ---------------------------------------------------------------------------
# organization profiles
# ---------------------------------------------------------------------------


class OrganizationProfile(FrozenModel):
    """A versioned source-to-destination template."""

    id: int
    name: str
    version: int
    template: dict[str, Any]
    conflict_policy: str = Field(alias="conflictPolicy")
    mutation_policy: str = Field(alias="mutationPolicy")
    created_at: str = Field(alias="createdAt")
    updated_at: str = Field(alias="updatedAt")


class SaveProfileParams(FrozenModel):
    """The params for ``profile.save``."""

    name: str
    template: dict[str, Any]
    conflict_policy: str = Field(default="skip", alias="conflictPolicy")
    mutation_policy: str = Field(default="copy", alias="mutationPolicy")


class ListProfilesResult(FrozenModel):
    """The result of ``profile.list``."""

    profiles: list[OrganizationProfile]


# ---------------------------------------------------------------------------
# assets
# ---------------------------------------------------------------------------


class AssetSummary(FrozenModel):
    """One asset identity."""

    id: str
    source_id: int | None = Field(alias="sourceId")
    source_relative_path: str = Field(alias="sourceRelativePath")
    observed_size: int | None = Field(alias="observedSize")
    observed_mtime: float | None = Field(alias="observedMtime")
    lifecycle_state: str = Field(alias="lifecycleState")
    media_kind: str | None = Field(alias="mediaKind")
    first_seen_at: str = Field(alias="firstSeenAt")


class ListAssetsParams(FrozenModel):
    """The params for ``asset.list``."""

    project_id: str | None = Field(default=None, alias="projectId")


class ListAssetsResult(FrozenModel):
    """The result of ``asset.list``."""

    assets: list[AssetSummary]


# ---------------------------------------------------------------------------
# replicas + safe-to-format
# ---------------------------------------------------------------------------


class ReplicaSummary(FrozenModel):
    """One physical location of one asset."""

    id: int
    asset_id: str = Field(alias="assetId")
    project_id: str = Field(alias="projectId")
    path: str
    checksum: str | None
    checksum_algo: str | None = Field(alias="checksumAlgo")
    verified: bool
    verified_at: str | None = Field(alias="verifiedAt")
    availability: str


class VerifyReplicaParams(FrozenModel):
    """The params for ``replica.verify``."""

    replica_id: int = Field(alias="replicaId")
    source_path: str = Field(alias="sourcePath")
    checksum_algo: str = Field(alias="checksumAlgo")


class VerifyReplicaResult(FrozenModel):
    """The result of ``replica.verify``."""

    replica_id: int = Field(alias="replicaId")
    verified: bool
    checksum_algo: str = Field(alias="checksumAlgo")
    source_checksum: str = Field(alias="sourceChecksum")
    replica_checksum: str = Field(alias="replicaChecksum")


class ListReplicasResult(FrozenModel):
    """The result of ``replica.list``."""

    replicas: list[ReplicaSummary]


# ---------------------------------------------------------------------------
# intake sessions
# ---------------------------------------------------------------------------


class IntakeSession(FrozenModel):
    """An intake session (offload or adoption intent)."""

    id: str
    project_id: str = Field(alias="projectId")
    source_id: int | None = Field(alias="sourceId")
    kind: str
    status: str
    safe_to_format: bool = Field(alias="safeToFormat")
    created_at: str = Field(alias="createdAt")
    updated_at: str = Field(alias="updatedAt")


class IntakeDestination(FrozenModel):
    """A required/optional destination on an intake session."""

    id: int
    intake_session_id: str = Field(alias="intakeSessionId")
    kind: str
    root_path: str = Field(alias="rootPath")
    role: str | None = None
    required: bool
    verified: bool


class CreateIntakeSessionParams(FrozenModel):
    """The params for ``intake.createSession``."""

    project_id: str = Field(alias="projectId")
    source_id: int = Field(alias="sourceId")
    kind: Literal["offload", "existing_folder"] = "offload"


class AddDestinationParams(FrozenModel):
    """The params for ``intake.addDestination``."""

    intake_session_id: str = Field(alias="intakeSessionId")
    kind: Literal["working", "backup", "organization"]
    root_path: str = Field(alias="rootPath")
    role: str | None = None
    required: bool = True


class SafeToFormatEval(FrozenModel):
    """The result of ``intake.evaluate`` — the ADR-0004 gate outcome."""

    session_id: str = Field(alias="sessionId")
    safe: bool
    unmet: list[str]


class AdoptSourceParams(FrozenModel):
    """The params for ``intake.adoptSource`` — adopt a scanned source."""

    session_id: str = Field(alias="sessionId")
    source_id: int = Field(alias="sourceId")
    entries: list[SourceInventoryEntry]
    destination_root: str = Field(alias="destinationRoot")
    project_id: str | None = Field(default=None, alias="projectId")


class AdoptSourceResult(FrozenModel):
    """The result of ``intake.adoptSource`` — adopted asset ids."""

    asset_ids: list[str] = Field(alias="assetIds")


# ---------------------------------------------------------------------------
# jobs
# ---------------------------------------------------------------------------


class JobDetail(FrozenModel):
    """A durable job row."""

    id: str
    # Nullable since migration 004 made ``jobs.project_id`` nullable: a
    # general transfer is not part of a project (spec §4.1). The column
    # is a foreign key, so the empty string is not a stand-in for "none".
    project_id: str | None = Field(default=None, alias="projectId")
    session_id: str | None = Field(alias="sessionId")
    command: str
    # The plan fingerprint the job was created against. A retry creates a
    # new job row for the same fingerprint, and that is the only handle a
    # runner has for adopting the prior attempt's execution ledger, so the
    # read model has to carry it and not just ``CreateJobParams``.
    args_fingerprint: str | None = Field(default=None, alias="argsFingerprint")
    state: str
    current_step: str | None = Field(alias="currentStep")
    total_steps: int = Field(alias="totalSteps")
    started_at: str | None = Field(alias="startedAt")
    updated_at: str = Field(alias="updatedAt")
    finished_at: str | None = Field(alias="finishedAt")
    error: str | None = None
    resumable: bool = False


class CreateJobParams(FrozenModel):
    """The params for ``job.create``."""

    project_id: str | None = Field(default=None, alias="projectId")
    command: str
    args_fingerprint: str | None = Field(default=None, alias="argsFingerprint")
    session_id: str | None = Field(default=None, alias="sessionId")
    total_steps: int = Field(default=0, alias="totalSteps")
    # The operator has already reviewed the plan, so the job should pass
    # through the §6.4 review gate instead of stopping at it. A caller that
    # wants the gate to hold -- a scripted or scheduled job with nobody
    # watching -- leaves this false and approves later.
    reviewed: bool = Field(default=False)


class JobTransitionParams(FrozenModel):
    """The params for ``job.transition``."""

    id: str
    from_state: str = Field(alias="fromState")
    to_state: str = Field(alias="toState")


class ListJobsParams(FrozenModel):
    """The params for ``job.list``.

    A dedicated model rather than a reuse of ``ListAssetsParams``: the two
    happen to share a ``projectId`` filter today, but each method's params
    are its own contract, and a future field on either (pagination, state
    filters) would otherwise silently change what the other accepts.
    """

    project_id: str | None = Field(default=None, alias="projectId")


class ListJobsResult(FrozenModel):
    """The result of ``job.list``."""

    jobs: list[JobDetail]


# ---------------------------------------------------------------------------
# audit
# ---------------------------------------------------------------------------


class AuditEvent(FrozenModel):
    """One append-only audit event."""

    id: int
    occurred_at: str = Field(alias="occurredAt")
    event_type: str = Field(alias="eventType")
    entity_type: str | None = Field(alias="entityType")
    entity_id: str | None = Field(alias="entityId")
    data: dict[str, Any] | None = None
    run_id: int | None = Field(alias="runId")


class ListAuditParams(FrozenModel):
    """The params for ``audit.list``."""

    entity_id: str | None = Field(default=None, alias="entityId")
    limit: int = Field(default=200, ge=1, le=5000)


class ListAuditResult(FrozenModel):
    """The result of ``audit.list``."""

    events: list[AuditEvent]


# ---------------------------------------------------------------------------
# intake planning
# ---------------------------------------------------------------------------


class PlanDestination(FrozenModel):
    """One destination requested for an intake plan."""

    kind: Literal["working", "backup", "organization"]
    root_path: str = Field(alias="rootPath")
    required: bool = True


class PlanEntry(FrozenModel):
    """One planned source->destination copy."""

    rel_path: str = Field(alias="relPath")
    dest_path: str = Field(alias="destPath")
    size: int


class CollisionIssue(FrozenModel):
    """A detected plan collision (duplicate destination or case-only)."""

    path: str
    reason: str
    count: int


class IntakePlan(FrozenModel):
    """An immutable intake plan built before any write."""

    fingerprint: str
    project_id: str = Field(alias="projectId")
    source_id: int = Field(alias="sourceId")
    source_root: str = Field(alias="sourceRoot")
    destinations: list[PlanDestination]
    entries: list[PlanEntry]
    total_bytes: int = Field(alias="totalBytes")
    capacity_ok: bool = Field(alias="capacityOk")
    needed_bytes: int = Field(alias="neededBytes")
    warnings: list[str]
    collisions: list[CollisionIssue]


class BuildPlanParams(FrozenModel):
    """The params for ``plan.build``."""

    project_id: str = Field(alias="projectId")
    source_id: int = Field(alias="sourceId")
    destinations: list[PlanDestination]


# ---------------------------------------------------------------------------
# receipt export
# ---------------------------------------------------------------------------


class ExportReceiptParams(FrozenModel):
    """The params for ``receipt.export``."""

    operation_id: str = Field(alias="operationId")
    format: Literal["markdown", "html"] = "markdown"


class ExportReceiptResult(FrozenModel):
    """The result of ``receipt.export``."""

    content: str


# ---------------------------------------------------------------------------
# job cancellation
# ---------------------------------------------------------------------------


class CancelJobParams(FrozenModel):
    """The params for ``job.cancel``."""

    id: str


# ---------------------------------------------------------------------------
# reconciliation
# ---------------------------------------------------------------------------


class ReconcileEntry(FrozenModel):
    """The state of one replica after a reconciliation check."""

    replica_id: int = Field(alias="replicaId")
    path: str
    availability: str  # present | missing | inaccessible
    status: str  # verified | changed | missing | inaccessible
    expected_checksum: str | None = Field(alias="expectedChecksum")
    actual_checksum: str | None = Field(alias="actualChecksum")


class ReconcileReport(FrozenModel):
    """The reconciliation result for one asset."""

    asset_id: str = Field(alias="assetId")
    entries: list[ReconcileEntry]


class ReconcileAssetParams(FrozenModel):
    """The params for ``reconcile.asset``."""

    asset_id: str = Field(alias="assetId")
    checksum_algo: str = Field(default="xxhash64", alias="checksumAlgo")


class ReconcileProjectParams(FrozenModel):
    """The params for ``reconcile.project``."""

    project_id: str = Field(alias="projectId")
    checksum_algo: str = Field(default="xxhash64", alias="checksumAlgo")


class AcceptChangeParams(FrozenModel):
    """The params for ``reconcile.acceptChange``."""

    asset_id: str = Field(alias="assetId")
    replica_id: int = Field(alias="replicaId")
    checksum_algo: str = Field(alias="checksumAlgo")


# ---------------------------------------------------------------------------
# organization
# ---------------------------------------------------------------------------


class OrganizeEntry(FrozenModel):
    """One planned source->destination organize copy."""

    source_path: str = Field(alias="sourcePath")
    dest_path: str = Field(alias="destPath")
    size: int


class OrganizePreview(FrozenModel):
    """A complete source-to-destination tree + collision report."""

    source_root: str = Field(alias="sourceRoot")
    dest_root: str = Field(alias="destRoot")
    entries: list[OrganizeEntry]
    collisions: list[CollisionIssue]
    total_bytes: int = Field(alias="totalBytes")
    mode: str


class OrganizePreviewParams(FrozenModel):
    """The params ``profile.preview`` builds to reuse the organize previewer.

    R-3 withdrew the ``organize.*`` RPC methods; this shape survives because
    ``profile.preview`` still returns an :class:`OrganizePreview`.
    """

    source_root: str = Field(alias="sourceRoot")
    dest_root: str = Field(alias="destRoot")
    entries: list[SourceInventoryEntry]
    template: dict[str, Any] = Field(default_factory=dict)
    mode: Literal["copy", "move", "link"] = "copy"


# ---------------------------------------------------------------------------
# logical clips
# ---------------------------------------------------------------------------


class ClipMember(FrozenModel):
    """One asset in a logical clip."""

    asset_id: str = Field(alias="assetId")
    role: str  # primary | sidecar


class LogicalClip(FrozenModel):
    """A detected logical (multi-file / spanned) clip."""

    id: int
    source_id: int = Field(alias="sourceId")
    clip_name: str = Field(alias="clipName")
    confidence: float
    resolved: bool
    members: list[ClipMember]


class DetectClipsParams(FrozenModel):
    """The params for ``clips.detect``."""

    source_id: int = Field(alias="sourceId")


# ---------------------------------------------------------------------------
# derivatives
# ---------------------------------------------------------------------------


class DerivativeSummary(FrozenModel):
    """Per-asset proxy / derived output state."""

    id: int
    asset_id: str = Field(alias="assetId")
    kind: str
    output_path: str = Field(alias="outputPath")
    settings_fingerprint: str | None = Field(alias="settingsFingerprint")
    status: str
    readiness: float


# ---------------------------------------------------------------------------
# project manifest / handoff export
# ---------------------------------------------------------------------------


class ManifestAsset(FrozenModel):
    """One asset in a portable project manifest."""

    id: str
    source_relative_path: str = Field(alias="sourceRelativePath")
    observed_size: int | None = Field(alias="observedSize")
    lifecycle_state: str = Field(alias="lifecycleState")
    media_kind: str | None = Field(alias="mediaKind")


class ManifestReplica(FrozenModel):
    """One replica in a portable project manifest."""

    asset_id: str = Field(alias="assetId")
    path: str
    checksum: str | None
    checksum_algo: str | None = Field(alias="checksumAlgo")
    verified: bool
    availability: str


class ProjectManifest(FrozenModel):
    """A portable, reviewable JSON manifest for a project (§4.5, §7.4)."""

    project_id: str = Field(alias="projectId")
    project_name: str = Field(alias="projectName")
    status: str
    exported_at: str = Field(alias="exportedAt")
    manifest_version: int = Field(alias="manifestVersion")
    assets: list[ManifestAsset]
    replicas: list[ManifestReplica]
    warnings: list[str]


class ResolveClip(FrozenModel):
    """One clip in a Resolve import manifest."""

    name: str
    path: str
    proxy_path: str | None = Field(alias="proxyPath")


class ResolveImportManifest(FrozenModel):
    """A clearly-labeled manifest for Resolve import — NOT a created project.

    Per plan §7.4: until live Resolve integration is proven, the output is
    a manifest for import, never a claim of a created Resolve project.
    """

    label: str
    project_id: str = Field(alias="projectId")
    clips: list[ResolveClip]


class SourceInventoryEntry(FrozenModel):
    """One file found by a read-only source scan.

    ``entry_type`` flags non-regular findings (``dir``, ``symlink``,
    ``other``); regular files keep the default and old payloads stay
    valid.
    """

    path: str
    size: int
    mtime: float
    entry_type: Literal["file", "dir", "symlink", "other"] = Field(
        default="file", alias="entryType"
    )


class SourceInspectParams(FrozenModel):
    """The params for ``source.inspect``."""

    path: str
    kind: Literal["card", "existing_media"] = "existing_media"
    label: str | None = None


class SourceInspectResult(FrozenModel):
    """The result of ``source.inspect`` — a read-only scan summary.

    ``truncated`` is true only when the caller supplied an explicit
    ``max_entries`` bound (the default is unbounded; the baseline's
    silent 5,000-entry cap was a confirmed defect). ``error_count`` /
    ``scan_errors`` surface scan failures that approval must account
    for; ``scan_errors`` is bounded for wire size while ``error_count``
    is exact. ``non_files`` carries symlinks and unsupported objects
    that the user must explicitly exclude (spec §6.3) — they are not
    hidden inside the file count.
    """

    source_id: int = Field(alias="sourceId")
    root_path: str = Field(alias="rootPath")
    kind: str
    label: str | None = None
    file_count: int = Field(alias="fileCount")
    total_bytes: int = Field(alias="totalBytes")
    manifest_hash: str = Field(alias="manifestHash")
    entries: list[SourceInventoryEntry]
    truncated: bool = False
    error_count: int = Field(default=0, alias="errorCount")
    scan_errors: list[str] = Field(default_factory=list, alias="scanErrors")
    non_files: list[SourceInventoryEntry] = Field(default_factory=list, alias="nonFiles")
    dir_count: int = Field(default=0, alias="dirCount")


class JobSnapshot(FrozenModel):
    """The state of a single job at one point in time."""

    id: str
    state: Literal[
        "planned",
        "awaiting_review",
        "queued",
        "running",
        "verifying",
        "succeeded",
        "failed",
        "cancelled",
        "needs_attention",
        "resumable",
    ]
    current_step: str = Field(alias="currentStep")
    completed_steps: list[str] = Field(alias="completedSteps")
    total_steps: int = Field(alias="totalSteps")
    started_at: str = Field(alias="startedAt")
    updated_at: str = Field(alias="updatedAt")
    # Per-file progress. Steps describe *which phase* a job is in and there
    # are only a handful of them; these describe how far through the work it
    # is, which for an offload is thousands of files and terabytes. A UI that
    # divided completed steps by a file count -- which is what `totalSteps`
    # on the job row holds -- could never show anything meaningful.
    completed_items: int = Field(default=0, alias="completedItems")
    total_items: int = Field(default=0, alias="totalItems")
    bytes_copied: int = Field(default=0, alias="bytesCopied")
    total_bytes: int = Field(default=0, alias="totalBytes")


class JobEvent(FrozenModel):
    """The payload of a ``job.updated`` event."""

    job_id: str = Field(alias="jobId")
    snapshot: JobSnapshot


class DestinationIdentity(FrozenModel):
    """Identity evidence for saved storage (spec §5.1).

    ``value`` is normalized and never contains credentials. Confidence
    levels: strong identity may authorize rebinding; weak evidence must
    not (a label, st_dev, size, or mount path alone is weak).
    """

    kind: Literal["volume_uuid", "disk_uuid", "server_share", "path_only"]
    value: str
    confidence: Literal["strong", "medium", "weak"]
    provenance: str
    # When this evidence was actually observed, and whether it was
    # re-observed on the latest pass. Stale evidence is kept for display
    # — "this looked like your Backup drive" is useful — but it is never
    # recognition authority: a drive can be swapped between two
    # observations, so not having witnessed an unmount proves nothing
    # about continuity (spec §5.1).
    observed_at: str | None = Field(default=None, alias="observedAt")
    stale: bool = False


class MountedVolume(FrozenModel):
    """One volume on the host filesystem.

    ``identity`` is the best evidence the platform could provide within
    its probe budget; ``None`` means not probed. It is evidence, not a
    promise — a weak or stale identity must never authorize rebinding.
    ``device_id`` is the filesystem's ``st_dev``: useless as identity
    (it is reassigned across boots) but exactly right for answering "is
    this path still on the volume we matched?".
    """

    path: str
    label: str
    total_bytes: int = Field(alias="totalBytes")
    free_bytes: int = Field(alias="freeBytes")
    filesystem: str
    identity: DestinationIdentity | None = None
    device_id: int | None = Field(default=None, alias="deviceId")


class ListVolumesResult(FrozenModel):
    """The result of ``source.listVolumes``."""

    volumes: list[MountedVolume]


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# presets — immutable revisions (destination-presets spec §4.2)
# ---------------------------------------------------------------------------


class PresetMatchConditions(FrozenModel):
    path_glob: str | None = Field(default=None, alias="pathGlob")
    extensions: list[str] | None = None
    categories: list[str] | None = None
    source_label: str | None = Field(default=None, alias="sourceLabel")


class PresetRule(FrozenModel):
    id: str
    match: PresetMatchConditions
    destination: str


class PresetGroup(FrozenModel):
    id: str
    match: PresetMatchConditions
    destination: str


class PresetExclusion(FrozenModel):
    id: str
    reason: str
    match: PresetMatchConditions


class PresetContent(FrozenModel):
    name: str = ""
    description: str | None = None
    rules: list[PresetRule] = Field(default_factory=list)
    groups: list[PresetGroup] = Field(default_factory=list)
    fallback_template: str = Field(alias="fallbackTemplate")
    conflict_policy: Literal["keep_both", "skip_identical", "needs_review"] = Field(
        default="keep_both", alias="conflictPolicy"
    )
    exclusions: list[PresetExclusion] = Field(default_factory=list)
    # Content that still needs a human decision before this revision may
    # be transferred with — unknown legacy template keys, legacy conflict
    # policies with no safe equivalent. Non-empty blocks plan approval
    # (spec §4.2: unsupported legacy keys are never silently ignored).
    review_required: list[str] = Field(default_factory=list, alias="reviewRequired")


class SavePresetRevisionParams(FrozenModel):
    name: str
    content: PresetContent


class PresetRevisionSummary(FrozenModel):
    preset_id: int = Field(alias="presetId")
    revision: int
    content_hash: str = Field(alias="contentHash")
    created_at: str = Field(alias="createdAt")
    # The repo row id used for pagination cursors (newest-first id > ?).
    id: int


class ListPresetRevisionsResult(FrozenModel):
    revisions: list[PresetRevisionSummary]
    total: int


class PresetExportResult(FrozenModel):
    preset_id: int = Field(alias="presetId")
    revision: int
    payload: str


class PresetImportParams(FrozenModel):
    payload: str
    new_name: str | None = Field(default=None, alias="newName")


class PresetRevisionDetail(FrozenModel):
    preset_id: int = Field(alias="presetId")
    revision: int
    created_at: str = Field(alias="createdAt")
    content_hash: str = Field(alias="contentHash")
    content: PresetContent
    legacy_snapshot: bool = Field(default=False, alias="legacySnapshot")
    # The legacy profile template this revision was converted from, kept
    # verbatim so a conversion can always be audited against its input.
    legacy_template: dict[str, Any] | None = Field(default=None, alias="legacyTemplate")


# ---------------------------------------------------------------------------
# inventories (spec §4.3)
# ---------------------------------------------------------------------------


class InventoryEntry(FrozenModel):
    """One inventory entry (spec §4.3).

    ``entry_type`` is the kind of filesystem object; ``scan_status`` is
    orthogonal. A read failure is ``scan_status="error"`` carrying the
    diagnostic in ``error`` — with ``entry_type="unknown"`` when the
    object could not be stat'd at all, rather than a fifth object type
    the schema does not model.
    """

    id: int
    rel_path: str = Field(alias="relPath")
    entry_type: Literal["file", "dir", "symlink", "other", "unknown"] = Field(alias="entryType")
    size: int
    mtime: float | None = None
    scan_status: Literal["ok", "error"] = Field(default="ok", alias="scanStatus")
    error: str | None = None


class InventoryStatus(FrozenModel):
    id: int
    root_path: str = Field(alias="rootPath")
    label: str | None = None
    status: Literal["scanning", "complete", "failed"]
    # Why a scan failed. A failed inventory keeps the partial counts it
    # actually reached; this says what stopped it (spec §4.3).
    error: str | None = None
    file_count: int = Field(alias="fileCount")
    dir_count: int = Field(alias="dirCount")
    total_bytes: int = Field(alias="totalBytes")
    error_count: int = Field(alias="errorCount")
    excluded_count: int = Field(alias="excludedCount")
    manifest_hash: str | None = Field(default=None, alias="manifestHash")
    started_at: str = Field(alias="startedAt")
    finished_at: str | None = Field(default=None, alias="finishedAt")


class InventoryCreateParams(FrozenModel):
    path: str
    label: str | None = None


class InventoryCreateResult(FrozenModel):
    inventory_id: int = Field(alias="inventoryId")


class InventoryEntriesParams(FrozenModel):
    id: int
    limit: int = Field(default=200, ge=1, le=1000)
    after: int = Field(default=0, ge=0)


class InventoryStatusParams(FrozenModel):
    id: int


class InventoryEntriesPage(FrozenModel):
    entries: list[InventoryEntry]
    total: int
    next_cursor: int | None = Field(default=None, alias="nextCursor")


# ---------------------------------------------------------------------------
# saved destinations (spec §4.1)
# ---------------------------------------------------------------------------


class SaveDestinationParams(FrozenModel):
    name: str
    path: str
    subfolder_path: str | None = Field(default=None, alias="subfolderPath")
    location_kind: Literal["local_folder", "volume_folder", "mounted_share_folder"] | None = Field(
        default=None, alias="locationKind"
    )
    default_preset_id: int | None = Field(default=None, alias="defaultPresetId")
    # The preset revision this destination is pinned to. Omitted on a
    # save that names a preset, the *current* revision is resolved and
    # pinned — a later revision of the same preset never re-routes this
    # destination on its own (spec §4.2).
    pinned_revision: int | None = Field(default=None, alias="pinnedRevision")
    conflict_policy: Literal["keep_both", "skip_identical", "needs_review"] = Field(
        default="keep_both", alias="conflictPolicy"
    )
    checksum_algo: Literal["xxhash64", "sha256"] = Field(default="xxhash64", alias="checksumAlgo")
    free_space_reserve: int = Field(default=0, ge=0, alias="freeSpaceReserve")


class DestinationSummary(FrozenModel):
    id: int
    name: str
    location_kind: str = Field(alias="locationKind")
    last_root_path: str = Field(alias="lastRootPath")
    subfolder_path: str | None = Field(default=None, alias="subfolderPath")
    identity: DestinationIdentity | None = None
    default_preset_id: int | None = Field(default=None, alias="defaultPresetId")
    pinned_revision: int | None = Field(default=None, alias="pinnedRevision")
    conflict_policy: str = Field(alias="conflictPolicy")
    checksum_algo: str = Field(alias="checksumAlgo")
    free_space_reserve: int = Field(default=0, alias="freeSpaceReserve")
    last_binding_path: str | None = Field(default=None, alias="lastBindingPath")
    last_seen_at: str | None = Field(default=None, alias="lastSeenAt")
    created_at: str = Field(alias="createdAt")
    updated_at: str = Field(alias="updatedAt")
    archived_at: str | None = Field(default=None, alias="archivedAt")


class ListDestinationsResult(FrozenModel):
    destinations: list[DestinationSummary]


DestinationAvailability = Literal[
    "available",
    "offline",
    "needs_confirmation",
    "ambiguous",
    "unwritable",
]


class DestinationResolution(FrozenModel):
    destination_id: int = Field(alias="destinationId")
    name: str
    status: DestinationAvailability
    reason: str
    candidate_paths: list[str] = Field(default_factory=list, alias="candidatePaths")
    binding_path: str | None = Field(default=None, alias="bindingPath")


class ResolveDestinationsResult(FrozenModel):
    resolutions: list[DestinationResolution]


class ResolveDestinationParams(FrozenModel):
    id: int | None = None
    # Re-probe the platform, or reuse the last observation. A UI that
    # re-renders often should pass false and read ``discovery.status``
    # for the observation's age (spec §5.2: do not block on slow mount
    # metadata calls).
    refresh: bool = True


class DiscoveryStatus(FrozenModel):
    """What storage discovery currently knows (spec §5.2).

    ``stale`` and ``warnings`` exist so a degraded probe shows as a
    recoverable warning with manual folder selection still usable,
    rather than as confident but wrong availability. ``observed_at`` of
    ``None`` means discovery has not run — which is not the same as
    having observed nothing.
    """

    volumes: list[MountedVolume]
    observed_at: str | None = Field(default=None, alias="observedAt")
    age_seconds: float | None = Field(default=None, alias="ageSeconds")
    stale: bool = False
    warnings: list[str] = Field(default_factory=list)


class ConfirmBindingParams(FrozenModel):
    destination_id: int = Field(alias="destinationId")
    path: str
    identity: DestinationIdentity | None = None


class ArchiveDestinationParams(FrozenModel):
    id: int


# ---------------------------------------------------------------------------
# transfer plans (spec §4.3, §7.1)
# ---------------------------------------------------------------------------


class PlanCreateParams(FrozenModel):
    """Params for ``transfer.planCreate``.

    ``preset_revision`` is a deliberate per-transfer override. Without
    it the plan uses the destination's *pinned* revision — never
    whatever revision happens to be newest (spec §4.2).
    """

    destination_id: int = Field(alias="destinationId")
    inventory_ids: list[int] = Field(alias="inventoryIds")
    preset_id: int | None = Field(default=None, alias="presetId")
    preset_revision: int | None = Field(default=None, alias="presetRevision")
    project_id: str | None = Field(default=None, alias="projectId")
    binding_path: str | None = Field(default=None, alias="bindingPath")
    capacity_override_reason: str | None = Field(default=None, alias="capacityOverrideReason")


class TransferPlanStatusModel(FrozenModel):
    id: str
    destination_id: int | None = Field(default=None, alias="destinationId")
    destination_binding_path: str = Field(alias="destinationBindingPath")
    preset_id: int | None = Field(default=None, alias="presetId")
    preset_revision: int | None = Field(default=None, alias="presetRevision")
    preset_content_hash: str | None = Field(default=None, alias="presetContentHash")
    project_id: str | None = Field(default=None, alias="projectId")
    fingerprint: str
    status: Literal["draft", "approved", "invalidated", "executing", "executed"]
    approved_fingerprint: str | None = Field(default=None, alias="approvedFingerprint")
    capacity_ok: bool = Field(alias="capacityOk")
    capacity_unknown: bool = Field(alias="capacityUnknown")
    capacity_override_reason: str | None = Field(default=None, alias="capacityOverrideReason")
    needed_bytes: int = Field(alias="neededBytes")
    total_bytes: int = Field(alias="totalBytes")
    total_files: int = Field(alias="totalFiles")
    conflict_count: int = Field(alias="conflictCount")
    exclusion_count: int = Field(alias="exclusionCount")
    # How many of ``exclusion_count`` came from the preset's own
    # exclusion rules rather than a decision this reviewer made. Both are
    # explicit; §7.3 needs a receipt to tell them apart.
    rule_exclusion_count: int = Field(default=0, alias="ruleExclusionCount")
    # Entries that still need a human decision. Non-zero means approval
    # is refused (spec §7.1) — distinct from ``conflict_count``, which
    # counts findings whether or not they still block.
    blocking_count: int = Field(default=0, alias="blockingCount")
    # Review evidence carried by the pinned preset revision. Non-empty
    # blocks approval (spec §4.2): the revision contains something Ferry
    # could not convert safely, and warning about it while approving
    # anyway is the silent ignore the spec forbids.
    preset_review_required: list[str] = Field(default_factory=list, alias="presetReviewRequired")
    free_bytes: int | None = Field(default=None, alias="freeBytes")
    free_space_reserve: int = Field(default=0, alias="freeSpaceReserve")
    conflict_policy: str = Field(default="keep_both", alias="conflictPolicy")
    checksum_algo: str = Field(default="xxhash64", alias="checksumAlgo")
    inventory_ids: list[int] = Field(default_factory=list, alias="inventoryIds")
    # The plan this one was derived from by resolving decisions, and the
    # decisions carried into it.
    derived_from: str | None = Field(default=None, alias="derivedFrom")
    # The plan that superseded this one. Resolving a finding produces a
    # new plan and invalidates its parent, so an approved plan can never
    # coexist with the revision that replaced it (spec §8).
    superseded_by: str | None = Field(default=None, alias="supersededBy")
    decisions: list[PlanDecision] = Field(default_factory=list)
    category_map_version: int = Field(default=1, alias="categoryMapVersion")
    warnings: list[str] = Field(default_factory=list)
    created_at: str = Field(alias="createdAt")
    approved_at: str | None = Field(default=None, alias="approvedAt")


class TransferPlanEntryModel(FrozenModel):
    """One planned mapping (spec §4.3, §6.4).

    The source is identified by ``inventory_id`` + ``inventory_entry_id``
    — never by ``rel_path`` alone, which two different sources can share.
    ``excluded_by_user`` distinguishes a decision somebody made from a
    finding that merely has not been decided yet.
    """

    id: int
    inventory_id: int | None = Field(default=None, alias="inventoryId")
    inventory_entry_id: int | None = Field(default=None, alias="inventoryEntryId")
    source_path: str = Field(alias="sourcePath")
    rel_path: str = Field(default="", alias="relPath")
    entry_type: str = Field(default="file", alias="entryType")
    dest_rel_path: str = Field(alias="destRelPath")
    matched_rule: str | None = Field(default=None, alias="matchedRule")
    size: int
    mtime: float | None = None
    action: Literal["copy", "skip_identical", "exclude", "needs_review", "dir"]
    conflict: str | None = None
    exclusion_reason: str | None = Field(default=None, alias="exclusionReason")
    excluded_by_user: bool = Field(default=False, alias="excludedByUser")
    # Set when keep-both moved this copy off its natural name. The review
    # screen shows the rename rather than letting it be discovered in the
    # receipt afterwards (spec §6.4).
    renamed_from: str | None = Field(default=None, alias="renamedFrom")
    # The keep-together group that claimed this entry. A group's
    # collision is resolved at its root, never by renaming a member, so
    # review has to be able to show the containment (spec §6.3).
    group_id: str | None = Field(default=None, alias="groupId")


class PlanEntriesParams(FrozenModel):
    id: str
    limit: int = Field(default=200, ge=1, le=1000)
    after: int = Field(default=0, ge=0)


class PlanEntriesPage(FrozenModel):
    entries: list[TransferPlanEntryModel]
    total: int
    next_cursor: int | None = Field(default=None, alias="nextCursor")


class PlanDecision(FrozenModel):
    """One reviewed decision about a plan finding (spec §6.4, §8).

    Keyed by ``(inventory_id, rel_path)`` rather than a plan entry id:
    resolving decisions produces a *new* plan, which reassigns entry
    ids, and a decision that did not survive that would have to be made
    again every round.
    """

    inventory_id: int = Field(alias="inventoryId")
    rel_path: str = Field(alias="relPath")
    # Exclusion removes an entry from the transfer outright.
    # ``skip_identical`` resolves an existing-destination conflict by
    # asking the runner to prove full content equality at execution
    # time (spec §6.4): if the checksums disagree the item fails
    # visibly and needs a new decision — never an overwrite, never a
    # silent skip.
    action: Literal["exclude", "skip_identical"] = "exclude"
    reason: str | None = None


class PlanResolveParams(FrozenModel):
    """Params for ``transfer.planResolve``.

    ``entry_ids`` is what a review screen has to hand; the service
    translates them to the stable ``(inventory, relPath)`` key. Decisions
    accumulate across rounds — resolving one finding does not discard
    the decisions already made about others.
    """

    id: str
    entry_ids: list[int] = Field(default_factory=list, alias="entryIds")
    decisions: list[PlanDecision] = Field(default_factory=list)
    reason: str | None = None


class PreflightStatus(FrozenModel):
    """A preflight run's state and findings (spec §7.1).

    ``findings`` is empty exactly when the run passed. Each entry is a
    sentence an operator can act on, because a refusal that does not say
    what changed is indistinguishable from a bug.
    """

    id: int
    plan_id: str = Field(alias="planId")
    fingerprint: str
    status: Literal["running", "passed", "failed"]
    findings: list[str] = Field(default_factory=list)
    checked_entries: int = Field(default=0, alias="checkedEntries")
    total_entries: int = Field(default=0, alias="totalEntries")
    resolved_binding_path: str | None = Field(default=None, alias="resolvedBindingPath")
    destination_status: str | None = Field(default=None, alias="destinationStatus")
    free_bytes: int | None = Field(default=None, alias="freeBytes")
    started_at: str = Field(alias="startedAt")
    finished_at: str | None = Field(default=None, alias="finishedAt")


class PreflightStartParams(FrozenModel):
    plan_id: str = Field(alias="planId")


class PreflightStatusParams(FrozenModel):
    id: int


class PlanApproveParams(FrozenModel):
    id: str
    fingerprint: str


class PlanIdParams(FrozenModel):
    id: str


# ---------------------------------------------------------------------------
# transfer execution (spec §7.2/§7.3 — the P5 runner)
# ---------------------------------------------------------------------------


class TransferStartParams(FrozenModel):
    """Params for ``transfer.start``.

    Takes the approved plan id **and** the fingerprint it was approved
    under (spec §8): starting a plan whose substance moved is refused,
    and a caller never supplies paths — the plan is the only source of
    what gets written.
    """

    id: str
    fingerprint: str


class TransferStartResult(FrozenModel):
    """The result of ``transfer.start``.

    Returns the durable job promptly (spec §8): creation never waits
    for the copy. Starting the same approved plan twice returns the
    same execution.
    """

    job: JobDetail
    execution_id: str = Field(alias="executionId")


class TransferReceiptParams(FrozenModel):
    """Params for ``transfer.receipt`` / ``transfer.receiptExport``.

    Keyed by plan: a plan's receipt is its latest execution's. The
    execution id is returned so a lineage can be followed.
    """

    plan_id: str = Field(alias="planId")


class TransferReceiptStatus(FrozenModel):
    """The durable receipt of a transfer, and its export state.

    ``exportError`` non-empty means the JSON export failed and is
    retriable; the database receipt itself is the audit record and was
    written first (spec §7.3).
    """

    execution_id: str = Field(alias="executionId")
    plan_id: str = Field(alias="planId")
    fingerprint: str
    final_state: str = Field(alias="finalState")
    written_at: str = Field(alias="writtenAt")
    exported_path: str | None = Field(default=None, alias="exportedPath")
    export_error: str | None = Field(default=None, alias="exportError")
    receipt: dict[str, Any]


# ---------------------------------------------------------------------------
# profile.preview (plan §8.3)
# ---------------------------------------------------------------------------


class ProfilePreviewParams(FrozenModel):
    """The params for ``profile.preview`` — a profile template + inputs."""

    name: str = ""
    template: dict[str, Any] = Field(default_factory=dict)
    source_root: str = Field(alias="sourceRoot")
    dest_root: str = Field(alias="destRoot")
    entries: list[SourceInventoryEntry]
    conflict_policy: str = Field(default="skip", alias="conflictPolicy")
    mutation_policy: str = Field(default="copy", alias="mutationPolicy")


# ---------------------------------------------------------------------------
# settings (plan §8.3)
# ---------------------------------------------------------------------------


class AppSettings(FrozenModel):
    """The application settings exposed to the renderer (Settings screen)."""

    proxy_codec: str = Field(default="ProRes422Proxy", alias="proxyCodec")
    proxy_height: int = Field(default=1080, alias="proxyHeight")
    checksum_algo: str = Field(default="xxhash64", alias="checksumAlgo")
    resolve_path: str | None = Field(default=None, alias="resolvePath")
    ffmpeg_path: str | None = Field(default=None, alias="ffmpegPath")
    organize_template: str = Field(
        default="{root}/{source_relpath}/{filename}{ext}", alias="organizeTemplate"
    )
    organize_mode: str = Field(default="copy", alias="organizeMode")
    organize_on_conflict: str = Field(default="skip", alias="organizeOnConflict")


class UpdateSettingsParams(FrozenModel):
    """The params for ``settings.update``. Only present fields change."""

    proxy_codec: str | None = Field(default=None, alias="proxyCodec")
    proxy_height: int | None = Field(default=None, alias="proxyHeight")
    checksum_algo: str | None = Field(default=None, alias="checksumAlgo")
    resolve_path: str | None = Field(default=None, alias="resolvePath")
    ffmpeg_path: str | None = Field(default=None, alias="ffmpegPath")
    organize_template: str | None = Field(default=None, alias="organizeTemplate")
    organize_mode: str | None = Field(default=None, alias="organizeMode")
    organize_on_conflict: str | None = Field(default=None, alias="organizeOnConflict")


# ---------------------------------------------------------------------------
# app.doctor (plan §8.3, onboarding/doctor screen)
# ---------------------------------------------------------------------------


class ToolCheck(FrozenModel):
    """One dependency check on the Doctor screen."""

    name: str
    present: bool
    path: str | None = None
    message: str | None = None


class DoctorResult(FrozenModel):
    """The result of ``app.doctor`` — dependency + storage health."""

    version: str
    protocol_version: int = Field(alias="protocolVersion")
    tools: list[ToolCheck]
    app_data_dir: str = Field(alias="appDataDir")
    db_path: str = Field(alias="dbPath")


# ---------------------------------------------------------------------------
# Wire format helpers
# ---------------------------------------------------------------------------


def encode_frame(frame: Frame) -> str:
    """Encode a frame as a single newline-terminated JSON line."""
    return frame.model_dump_json(by_alias=True) + "\n"


def decode_frame(line: str) -> Frame | None:
    """Decode a single frame from a JSON line. Returns ``None`` on parse
    failure or schema mismatch — the caller should emit a ``parse_error``
    frame rather than crashing the stream.
    """
    stripped = line.strip()
    if not stripped:
        return None
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    if parsed.get("jsonrpc") != "2.0" or parsed.get("v") != PROTOCOL_VERSION:
        return None
    try:
        return FrameRoot.model_validate(parsed).root
    except ValueError:
        return None


# Re-export the catalog names so the rest of the service package can
# import them from a single namespace.
__all__ = [
    "PROTOCOL_VERSION",
    "AcceptChangeParams",
    "AddDestinationParams",
    "AdoptSourceParams",
    "AdoptSourceResult",
    "AppSettings",
    "AppStatus",
    "ArchiveDestinationParams",
    "ArchiveProjectParams",
    "AssetSummary",
    "AuditEvent",
    "BuildPlanParams",
    "CancelJobParams",
    "ClipMember",
    "CollisionIssue",
    "ConfirmBindingParams",
    "CreateIntakeSessionParams",
    "CreateJobParams",
    "CreateProjectParams",
    "CreateProjectResult",
    "DerivativeSummary",
    "DestinationAvailability",
    "DestinationIdentity",
    "DestinationResolution",
    "DestinationSummary",
    "DetectClipsParams",
    "DoctorResult",
    "ErrorFrame",
    "EventFrame",
    "ExportReceiptParams",
    "ExportReceiptResult",
    "Frame",
    "FrameRoot",
    "GetCapabilities",
    "IntakeDestination",
    "IntakePlan",
    "IntakeSession",
    "InventoryCreateParams",
    "InventoryCreateResult",
    "InventoryEntriesPage",
    "InventoryEntriesParams",
    "InventoryEntry",
    "InventoryStatus",
    "JobDetail",
    "JobEvent",
    "JobSnapshot",
    "JobTransitionParams",
    "ListAssetsParams",
    "ListAssetsResult",
    "ListAuditParams",
    "ListAuditResult",
    "ListDestinationsResult",
    "ListJobsParams",
    "ListJobsResult",
    "ListPresetRevisionsResult",
    "ListProfilesResult",
    "ListProjectsResult",
    "ListReplicasResult",
    "ListVolumesResult",
    "LogicalClip",
    "ManifestAsset",
    "ManifestReplica",
    "MountedVolume",
    "OrganizationProfile",
    "OrganizeEntry",
    "OrganizePreview",
    "OrganizePreviewParams",
    "PlanApproveParams",
    "PlanCreateParams",
    "PlanDestination",
    "PlanEntriesPage",
    "PlanEntriesParams",
    "PlanEntry",
    "PlanIdParams",
    "PresetContent",
    "PresetExclusion",
    "PresetExportResult",
    "PresetGroup",
    "PresetImportParams",
    "PresetMatchConditions",
    "PresetRevisionDetail",
    "PresetRevisionSummary",
    "PresetRule",
    "ProfilePreviewParams",
    "ProjectDetail",
    "ProjectManifest",
    "ProjectSummary",
    "ReconcileAssetParams",
    "ReconcileEntry",
    "ReconcileProjectParams",
    "ReconcileReport",
    "ReplicaSummary",
    "RequestFrame",
    "ResolveClip",
    "ResolveDestinationParams",
    "ResolveDestinationsResult",
    "ResolveImportManifest",
    "ResponseFrame",
    "RpcError",
    "RpcErrorCode",
    "SafeToFormatEval",
    "SaveDestinationParams",
    "SavePresetRevisionParams",
    "SaveProfileParams",
    "SourceInspectParams",
    "SourceInspectResult",
    "SourceInventoryEntry",
    "StoragePolicy",
    "ToolCheck",
    "TransferPlanEntryModel",
    "TransferPlanStatusModel",
    "UpdateProjectParams",
    "UpdateSettingsParams",
    "VerifyReplicaParams",
    "VerifyReplicaResult",
    "decode_frame",
    "encode_frame",
]
