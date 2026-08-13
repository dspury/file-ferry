"""Tests for the sidecar handler wiring (``media_mate.service.wiring``).

The wiring is what turns an otherwise ``method_not_found``-only server
into a real sidecar: it registers a handler for every method in the
protocol catalog, validating params against the matching pydantic model
and dispatching to ``ApplicationService``.

These tests drive the server through its stdio loop with an in-memory
or temp SQLite database, so they cover the real request/response path
including the JSON-RPC envelope.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

from media_mate.application.service import METHOD_NAMES, ApplicationService
from media_mate.service.protocol import PROTOCOL_VERSION
from media_mate.service.server import SidecarServer
from media_mate.service.wiring import wire_server


def _serve(service: ApplicationService, request_line: str) -> str:
    """Send one request line to a wired server over stdio; return raw output."""
    server = SidecarServer(db_path=Path(":memory:"))
    wire_server(server, service)
    out = io.StringIO()
    server.run_once(io.StringIO(request_line), out)
    return out.getvalue().strip()


def _request(method: str, params: dict | None = None) -> str:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "v": PROTOCOL_VERSION,
            "kind": "request",
            "id": "w-test",
            "method": method,
            "params": params or {},
        }
    ) + "\n"


def _parse(response: str) -> dict:
    return json.loads(response)


def _service(tmp_path: Path) -> ApplicationService:
    svc = ApplicationService(db_path=tmp_path / "wiring.db", app_data_dir=tmp_path / "app")
    svc.bootstrap()
    return svc


class TestEveryMethodRegistered:
    def test_catalog_matches_method_names(self, tmp_path: Path) -> None:
        """Every METHOD_NAMES entry has a handler; the wired server knows it."""
        svc = _service(tmp_path)
        try:
            server = SidecarServer(db_path=Path(":memory:"))
            wire_server(server, svc)
            assert set(server._handlers.keys()) == set(METHOD_NAMES)
        finally:
            svc.close()

    def test_app_get_status_returns_capabilities(self, tmp_path: Path) -> None:
        svc = _service(tmp_path)
        try:
            resp = _parse(_serve(svc, _request("app.getStatus")))
            assert resp["id"] == "w-test"
            assert resp["kind"] == "response"
            result = resp["result"]
            assert result["protocolVersion"] == PROTOCOL_VERSION
            assert "app.getStatus" in result["capabilities"]
            assert set(result["capabilities"]) == set(METHOD_NAMES)
        finally:
            svc.close()


class TestProjectFlow:
    def test_create_and_list_projects(self, tmp_path: Path) -> None:
        svc = _service(tmp_path)
        try:
            working = tmp_path / "working"
            working.mkdir()
            # A single working root (backup is optional) avoids the
            # same-volume policy gate while still exercising the full
            # create -> persist -> list dispatch path.
            create_resp = _parse(
                _serve(
                    svc,
                    _request(
                        "project.create",
                        {"name": "Ep1", "workingRoot": str(working)},
                    ),
                )
            )
            assert create_resp["kind"] == "response"
            project_id = create_resp["result"]["projectId"]
            assert project_id

            list_resp = _parse(_serve(svc, _request("project.list")))
            assert list_resp["result"]["projects"][0]["id"] == project_id
        finally:
            svc.close()


class TestErrorMapping:
    def test_invalid_params_returns_typed_error(self, tmp_path: Path) -> None:
        svc = _service(tmp_path)
        try:
            resp = _parse(
                _serve(
                    svc,
                    _request("project.create", {"workingRoot": "/tmp/x"}),
                )
            )
            assert resp["kind"] == "error"
            assert resp["error"]["code"] == "invalid_params"
        finally:
            svc.close()

    def test_unknown_method_returns_method_not_found(self, tmp_path: Path) -> None:
        svc = _service(tmp_path)
        try:
            resp = _parse(_serve(svc, _request("nope.nope")))
            assert resp["kind"] == "error"
            assert resp["error"]["code"] == "method_not_found"
        finally:
            svc.close()

    def test_service_failure_becomes_internal_error(self, tmp_path: Path) -> None:
        """A nonexistent working root surfaces as an internal_error."""
        svc = _service(tmp_path)
        try:
            resp = _parse(
                _serve(
                    svc,
                    _request("project.create", {"name": "X", "workingRoot": "/no/such/dir"}),
                )
            )
            assert resp["kind"] == "error"
            assert resp["error"]["code"] == "internal_error"
        finally:
            svc.close()

    def test_missing_asset_id_returns_invalid_params(self, tmp_path: Path) -> None:
        svc = _service(tmp_path)
        try:
            resp = _parse(_serve(svc, _request("asset.get")))
            assert resp["kind"] == "error"
            assert resp["error"]["code"] == "invalid_params"
        finally:
            svc.close()
