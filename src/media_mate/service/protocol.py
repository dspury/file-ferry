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


class CreateProjectParams(FrozenModel):
    """The params for ``project.create``."""

    name: str
    working_root: str = Field(alias="workingRoot")
    backup_root: str = Field(alias="backupRoot")


class CreateProjectResult(FrozenModel):
    """The result of ``project.create``."""

    project_id: str = Field(alias="projectId")


class ProjectSummary(FrozenModel):
    """One row in the ``project.list`` result."""

    id: str
    name: str
    working_root: str = Field(alias="workingRoot")
    backup_root: str = Field(alias="backupRoot")
    created_at: str = Field(alias="createdAt")


class ListProjectsResult(FrozenModel):
    """The result of ``project.list``."""

    projects: list[ProjectSummary]


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
    "AppStatus",
    "CreateProjectParams",
    "CreateProjectResult",
    "ErrorFrame",
    "EventFrame",
    "Frame",
    "FrameRoot",
    "GetCapabilities",
    "JobEvent",
    "JobSnapshot",
    "ListProjectsResult",
    "ListVolumesResult",
    "MountedVolume",
    "ProjectSummary",
    "RequestFrame",
    "ResponseFrame",
    "RpcError",
    "RpcErrorCode",
    "decode_frame",
    "encode_frame",
]
