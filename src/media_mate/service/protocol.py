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


# ---------------------------------------------------------------------------
# jobs
# ---------------------------------------------------------------------------


class JobDetail(FrozenModel):
    """A durable job row."""

    id: str
    project_id: str = Field(alias="projectId")
    session_id: str | None = Field(alias="sessionId")
    command: str
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

    project_id: str = Field(alias="projectId")
    command: str
    args_fingerprint: str | None = Field(default=None, alias="argsFingerprint")
    session_id: str | None = Field(default=None, alias="sessionId")
    total_steps: int = Field(default=0, alias="totalSteps")


class JobTransitionParams(FrozenModel):
    """The params for ``job.transition``."""

    id: str
    from_state: str = Field(alias="fromState")
    to_state: str = Field(alias="toState")


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


class SourceInventoryEntry(FrozenModel):
    """One file found by a read-only source scan."""

    path: str
    size: int
    mtime: float


class SourceInspectParams(FrozenModel):
    """The params for ``source.inspect``."""

    path: str
    kind: Literal["card", "existing_media"] = "existing_media"
    label: str | None = None


class SourceInspectResult(FrozenModel):
    """The result of ``source.inspect`` — a read-only scan summary."""

    source_id: int = Field(alias="sourceId")
    root_path: str = Field(alias="rootPath")
    kind: str
    label: str | None = None
    file_count: int = Field(alias="fileCount")
    total_bytes: int = Field(alias="totalBytes")
    manifest_hash: str = Field(alias="manifestHash")
    entries: list[SourceInventoryEntry]


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


class JobEvent(FrozenModel):
    """The payload of a ``job.updated`` event."""

    job_id: str = Field(alias="jobId")
    snapshot: JobSnapshot


class MountedVolume(FrozenModel):
    """One volume on the host filesystem."""

    path: str
    label: str
    total_bytes: int = Field(alias="totalBytes")
    free_bytes: int = Field(alias="freeBytes")
    filesystem: str


class ListVolumesResult(FrozenModel):
    """The result of ``source.listVolumes``."""

    volumes: list[MountedVolume]


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
    "AddDestinationParams",
    "AppStatus",
    "ArchiveProjectParams",
    "AssetSummary",
    "AuditEvent",
    "BuildPlanParams",
    "CancelJobParams",
    "CollisionIssue",
    "CreateIntakeSessionParams",
    "CreateJobParams",
    "CreateProjectParams",
    "CreateProjectResult",
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
    "JobDetail",
    "JobEvent",
    "JobSnapshot",
    "JobTransitionParams",
    "ListAssetsParams",
    "ListAssetsResult",
    "ListAuditParams",
    "ListAuditResult",
    "ListJobsResult",
    "ListProfilesResult",
    "ListProjectsResult",
    "ListReplicasResult",
    "ListVolumesResult",
    "MountedVolume",
    "OrganizationProfile",
    "PlanDestination",
    "PlanEntry",
    "ProjectDetail",
    "ProjectSummary",
    "ReplicaSummary",
    "RequestFrame",
    "ResponseFrame",
    "RpcError",
    "RpcErrorCode",
    "SafeToFormatEval",
    "SaveProfileParams",
    "SourceInspectParams",
    "SourceInspectResult",
    "SourceInventoryEntry",
    "StoragePolicy",
    "UpdateProjectParams",
    "VerifyReplicaParams",
    "VerifyReplicaResult",
    "decode_frame",
    "encode_frame",
]
