"""In-process typed client for the application services.

The CLI and TUI consume the same ``application`` services the desktop
shell consumes, but without the IPC layer. This client is the
thin wrapper that translates typed method calls into in-process
service invocations and back into the same response shapes the
desktop would receive.
"""

from __future__ import annotations

import uuid
from typing import Any

from file_ferry.application.service import ApplicationService
from file_ferry.service.protocol import (
    PROTOCOL_VERSION,
    AppStatus,
    CreateProjectParams,
    CreateProjectResult,
    GetCapabilities,
    JobSnapshot,
    ListProjectsResult,
    ListVolumesResult,
    MountedVolume,
)


class ApplicationClient:
    """A typed client that calls the application services in-process.

    The CLI and TUI both use this client; the desktop shell uses
    the sidecar's JSON-RPC server. The two paths return the same
    shape because the pydantic models are shared.
    """

    def __init__(self, service: ApplicationService) -> None:
        self._service = service

    def app_get_status(self) -> AppStatus:
        """Mirror of the ``app.getStatus`` method."""
        return AppStatus(
            sidecarVersion=self._service.sidecar_version(),
            protocolVersion=PROTOCOL_VERSION,
            capabilities=list(self._service.capabilities()),
        )

    def app_get_capabilities(self) -> GetCapabilities:
        return GetCapabilities(
            methods=list(self._service.method_names()),
            events=list(self._service.event_names()),
            version=PROTOCOL_VERSION,
        )

    def project_list(self) -> ListProjectsResult:
        return ListProjectsResult(projects=self._service.list_projects())

    def project_create(self, params: CreateProjectParams) -> CreateProjectResult:
        return CreateProjectResult(projectId=self._service.create_project(params))

    def source_list_volumes(self) -> ListVolumesResult:
        return ListVolumesResult(volumes=self._service.list_volumes())

    def job_subscribe(self, job_id: str) -> JobSnapshot:
        return self._service.job_snapshot(job_id)

    def job_unsubscribe(self, job_id: str) -> None:
        self._service.job_unsubscribe(job_id)

    def new_request_id(self) -> str:
        return str(uuid.uuid4())

    def __getattr__(self, name: str) -> Any:
        # Fallback for methods that are not yet implemented. The
        # desktop shell will eventually see a typed error from the
        # sidecar; the CLI sees a Python AttributeError, which is
        # the correct behavior for a client that does not know
        # the method.
        raise AttributeError(f"ApplicationClient has no method {name!r}")


def _build_volumes_from_service(volumes: list[MountedVolume]) -> ListVolumesResult:
    """Pass-through used by the in-process client (kept for symmetry)."""
    return ListVolumesResult(volumes=volumes)
