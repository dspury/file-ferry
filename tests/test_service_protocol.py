"""IPC protocol round-trip tests.

These tests prove the Python side of the IPC contract matches the
TypeScript side (``desktop/shared/ipc-schema.ts`` and
``desktop/shared/ipc-methods.ts``). The matching TS tests are in
``desktop/tests/ipc-contract.test.ts``. When the protocol changes,
BOTH tests must be updated in the same commit.

See ADR-0002 (IPC protocol) and ADR-0005 (application service module
structure).
"""

from __future__ import annotations

import json

import pytest

from file_ferry.service.protocol import (
    PROTOCOL_VERSION,
    AppStatus,
    CreateProjectParams,
    CreateProjectResult,
    ErrorFrame,
    EventFrame,
    GetCapabilities,
    JobSnapshot,
    ListProjectsResult,
    ListVolumesResult,
    MountedVolume,
    ProjectSummary,
    RequestFrame,
    ResponseFrame,
    RpcError,
    StoragePolicy,
    decode_frame,
    encode_frame,
)


class TestProtocolVersion:
    def test_matches_desktop_version(self) -> None:
        assert PROTOCOL_VERSION == 1

    def test_serialized_version_is_number(self) -> None:
        frame = RequestFrame(
            jsonrpc="2.0",
            v=PROTOCOL_VERSION,
            kind="request",
            id="abc",
            method="app.getStatus",
            params={},
        )
        decoded = json.loads(encode_frame(frame).strip())
        assert decoded["v"] == 1
        assert isinstance(decoded["v"], int)


class TestFrameEncoding:
    def _request(self) -> RequestFrame:
        return RequestFrame(
            jsonrpc="2.0",
            v=PROTOCOL_VERSION,
            kind="request",
            id="abc-123",
            method="project.list",
            params={},
        )

    def _response(self) -> ResponseFrame:
        return ResponseFrame(
            jsonrpc="2.0",
            v=PROTOCOL_VERSION,
            kind="response",
            id="abc-123",
            result=[],
        )

    def _event(self) -> EventFrame:
        return EventFrame(
            jsonrpc="2.0",
            v=PROTOCOL_VERSION,
            kind="event",
            method="sidecar.ready",
            params={"timestamp": "2026-08-12T17:30:00Z"},
        )

    def _error(self) -> ErrorFrame:
        return ErrorFrame(
            jsonrpc="2.0",
            v=PROTOCOL_VERSION,
            kind="error",
            id="abc-123",
            error=RpcError(code="invalid_params", message="missing name"),
        )

    def test_request_round_trips(self) -> None:
        frame = self._request()
        decoded = decode_frame(encode_frame(frame))
        assert decoded is not None
        # equality on frozen pydantic models treats dict-typed fields
        # transparently; the round-trip must preserve the request.
        assert decoded.model_dump() == frame.model_dump()

    def test_response_round_trips(self) -> None:
        frame = self._response()
        decoded = decode_frame(encode_frame(frame))
        assert decoded is not None
        assert decoded.model_dump() == frame.model_dump()

    def test_event_round_trips(self) -> None:
        frame = self._event()
        decoded = decode_frame(encode_frame(frame))
        assert decoded is not None
        assert decoded.model_dump() == frame.model_dump()

    def test_error_round_trips(self) -> None:
        frame = self._error()
        decoded = decode_frame(encode_frame(frame))
        assert decoded is not None
        assert decoded.model_dump() == frame.model_dump()

    def test_encode_ends_with_newline(self) -> None:
        assert encode_frame(self._request()).endswith("\n")


class TestFrameDecoding:
    def test_empty_line_returns_none(self) -> None:
        assert decode_frame("") is None
        assert decode_frame("   \n") is None

    def test_invalid_json_returns_none(self) -> None:
        assert decode_frame("{not json\n") is None

    def test_missing_jsonrpc_returns_none(self) -> None:
        bad = json.dumps(
            {"v": PROTOCOL_VERSION, "kind": "request", "id": "x", "method": "a", "params": {}}
        )
        assert decode_frame(bad) is None

    def test_wrong_version_returns_none(self) -> None:
        bad = json.dumps(
            {
                "jsonrpc": "2.0",
                "v": PROTOCOL_VERSION + 1,
                "kind": "request",
                "id": "x",
                "method": "a",
                "params": {},
            }
        )
        assert decode_frame(bad) is None

    def test_unknown_kind_returns_none(self) -> None:
        bad = json.dumps({"jsonrpc": "2.0", "v": PROTOCOL_VERSION, "kind": "bogus", "id": "x"})
        assert decode_frame(bad) is None

    def test_missing_request_id_returns_none(self) -> None:
        bad = json.dumps(
            {
                "jsonrpc": "2.0",
                "v": PROTOCOL_VERSION,
                "kind": "request",
                "method": "a",
                "params": {},
            }
        )
        assert decode_frame(bad) is None

    def test_missing_response_result_returns_none(self) -> None:
        bad = json.dumps({"jsonrpc": "2.0", "v": PROTOCOL_VERSION, "kind": "response", "id": "x"})
        assert decode_frame(bad) is None


class TestNDJSONFraming:
    def test_multiple_frames_are_line_delimited(self) -> None:
        event = EventFrame(
            jsonrpc="2.0",
            v=PROTOCOL_VERSION,
            kind="event",
            method="sidecar.ready",
            params={"timestamp": "2026-08-12T17:30:00Z"},
        )
        response = ResponseFrame(
            jsonrpc="2.0",
            v=PROTOCOL_VERSION,
            kind="response",
            id="xyz",
            result=[],
        )
        wire = encode_frame(event) + encode_frame(response)
        lines = [line for line in wire.split("\n") if line]
        assert len(lines) == 2
        for line in lines:
            assert decode_frame(line) is not None


class TestAliasesMatchTypeScript:
    """Spot-checks that the Python wire format matches the TS shape.

    The TS side uses camelCase JSON keys (set via Pydantic alias). The
    Python side accepts either snake_case or camelCase when validating
    inbound; outbound is always camelCase.
    """

    def test_app_status_serializes_with_camel_case(self) -> None:
        status = AppStatus(
            sidecarVersion="0.0.0",
            protocolVersion=PROTOCOL_VERSION,
            capabilities=["app.getStatus", "project.list"],
        )
        dumped = json.loads(status.model_dump_json(by_alias=True))
        assert dumped == {
            "sidecarVersion": "0.0.0",
            "protocolVersion": 1,
            "capabilities": ["app.getStatus", "project.list"],
        }

    def test_create_project_params_uses_camel_case(self) -> None:
        params = CreateProjectParams(
            name="Episode-12",
            workingRoot="/Volumes/RAID",
            backupRoot="/Volumes/BACKUP",
        )
        dumped = json.loads(params.model_dump_json(by_alias=True))
        assert dumped["name"] == "Episode-12"
        assert dumped["workingRoot"] == "/Volumes/RAID"
        assert dumped["backupRoot"] == "/Volumes/BACKUP"

    def test_create_project_result_uses_camel_case(self) -> None:
        result = CreateProjectResult(projectId="proj-001")
        dumped = json.loads(result.model_dump_json(by_alias=True))
        assert dumped == {"projectId": "proj-001"}

    def test_project_summary_round_trips(self) -> None:
        summary = ProjectSummary(
            id="proj-001",
            name="Episode-12",
            workingRoot="/Volumes/RAID",
            backupRoot="/Volumes/BACKUP",
            status="active",
            storagePolicy=StoragePolicy(
                requiredReplicas=2,
                backupOnDifferentVolume=True,
                checksumAlgo="xxhash64",
                safetyReserveBytes=0,
                requireSourceFingerprint=True,
            ),
            createdAt="2026-08-12T17:30:00Z",
            updatedAt="2026-08-12T17:30:00Z",
            archivedAt=None,
        )
        dumped = json.loads(summary.model_dump_json(by_alias=True))
        assert dumped["workingRoot"] == "/Volumes/RAID"
        assert dumped["createdAt"] == "2026-08-12T17:30:00Z"
        assert dumped["storagePolicy"]["requiredReplicas"] == 2

    def test_list_projects_result(self) -> None:
        result = ListProjectsResult(projects=[])
        dumped = json.loads(result.model_dump_json(by_alias=True))
        assert dumped == {"projects": []}

    def test_mounted_volume_uses_camel_case(self) -> None:
        volume = MountedVolume(
            path="/Volumes/RAID",
            label="RAID",
            totalBytes=2_000_000_000_000,
            freeBytes=1_500_000_000_000,
            filesystem="apfs",
        )
        dumped = json.loads(volume.model_dump_json(by_alias=True))
        assert dumped["totalBytes"] == 2_000_000_000_000
        assert dumped["freeBytes"] == 1_500_000_000_000

    def test_list_volumes_result(self) -> None:
        result = ListVolumesResult(
            volumes=[
                MountedVolume(
                    path="/Volumes/RAID",
                    label="RAID",
                    totalBytes=2_000_000_000_000,
                    freeBytes=1_500_000_000_000,
                    filesystem="apfs",
                ),
            ]
        )
        dumped = json.loads(result.model_dump_json(by_alias=True))
        assert dumped["volumes"][0]["freeBytes"] == 1_500_000_000_000

    def test_job_snapshot_uses_camel_case(self) -> None:
        snapshot = JobSnapshot(
            id="job-001",
            state="running",
            currentStep="probe",
            completedSteps=["scan"],
            totalSteps=5,
            startedAt="2026-08-12T17:30:00Z",
            updatedAt="2026-08-12T17:31:00Z",
        )
        dumped = json.loads(snapshot.model_dump_json(by_alias=True))
        assert dumped["currentStep"] == "probe"
        assert dumped["completedSteps"] == ["scan"]
        assert dumped["totalSteps"] == 5

    def test_get_capabilities(self) -> None:
        caps = GetCapabilities(
            methods=["app.getStatus"],
            events=["sidecar.ready"],
            version=PROTOCOL_VERSION,
        )
        dumped = json.loads(caps.model_dump_json(by_alias=True))
        assert dumped == {"methods": ["app.getStatus"], "events": ["sidecar.ready"], "version": 1}


@pytest.mark.parametrize("kind", ["request", "response", "event", "error"])
def test_kind_discriminator_round_trips(kind: str) -> None:
    """The discriminator field must be preserved on every kind."""
    if kind == "request":
        frame = RequestFrame(
            jsonrpc="2.0",
            v=PROTOCOL_VERSION,
            kind="request",
            id="x",
            method="a",
            params={},
        )
    elif kind == "response":
        frame = ResponseFrame(
            jsonrpc="2.0",
            v=PROTOCOL_VERSION,
            kind="response",
            id="x",
            result=None,
        )
    elif kind == "event":
        frame = EventFrame(
            jsonrpc="2.0",
            v=PROTOCOL_VERSION,
            kind="event",
            method="a",
            params={},
        )
    else:
        frame = ErrorFrame(
            jsonrpc="2.0",
            v=PROTOCOL_VERSION,
            kind="error",
            id="x",
            error=RpcError(code="internal_error", message="x"),
        )
    decoded = decode_frame(encode_frame(frame))
    assert decoded is not None
    assert decoded.kind == kind
