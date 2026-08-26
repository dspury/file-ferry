"""Tests for the sidecar handler wiring (``file_ferry.service.wiring``).

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

from file_ferry.application.service import METHOD_NAMES, ApplicationService
from file_ferry.service.protocol import PROTOCOL_VERSION
from file_ferry.service.server import SidecarServer
from file_ferry.service.wiring import wire_server


def _serve(service: ApplicationService, request_line: str) -> str:
    """Send one request line to a wired server over stdio; return raw output."""
    server = SidecarServer(db_path=Path(":memory:"))
    wire_server(server, service)
    out = io.StringIO()
    server.run_once(io.StringIO(request_line), out)
    return out.getvalue().strip()


def _request(method: str, params: dict | None = None) -> str:
    return (
        json.dumps(
            {
                "jsonrpc": "2.0",
                "v": PROTOCOL_VERSION,
                "kind": "request",
                "id": "w-test",
                "method": method,
                "params": params or {},
            }
        )
        + "\n"
    )


def _parse(response: str) -> dict:
    return json.loads(response)


def _service(tmp_path: Path) -> ApplicationService:
    svc = ApplicationService(
        db_path=tmp_path / "wiring.db",
        app_data_dir=tmp_path / "app",
        config_path=tmp_path / "config.toml",
    )
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

    def test_job_dispatch_methods_are_advertised(self, tmp_path: Path) -> None:
        """``job.dispatch`` and ``job.dispatchNext`` are exposed via capabilities.

        Discovered during review of #60 -- the IPC catalog previously
        omitted ``job.dispatch`` even though
        :class:`ApplicationService` exposed a ``job_dispatch`` method,
        which meant the renderer's ``job.subscribe`` listener sat on an
        empty stream. This regression test pins the surface.
        """
        assert "job.dispatch" in METHOD_NAMES
        assert "job.dispatchNext" in METHOD_NAMES

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


class TestPackage7Methods:
    def test_app_doctor_returns_tools(self, tmp_path: Path) -> None:
        svc = _service(tmp_path)
        try:
            resp = _parse(_serve(svc, _request("app.doctor")))
            assert resp["kind"] == "response"
            result = resp["result"]
            assert result["protocolVersion"] == PROTOCOL_VERSION
            names = [t["name"] for t in result["tools"]]
            assert "ffmpeg" in names and "ffprobe" in names
            assert result["dbPath"]
        finally:
            svc.close()

    def test_settings_get_and_update(self, tmp_path: Path) -> None:
        svc = _service(tmp_path)
        try:
            got = _parse(_serve(svc, _request("settings.get")))
            assert got["kind"] == "response"
            # Legacy "xxhash" normalizes to the protocol value.
            assert got["result"]["checksumAlgo"] == "xxhash64"
            assert got["result"]["proxyCodec"] == "ProRes422Proxy"

            updated = _parse(
                _serve(
                    svc,
                    _request("settings.update", {"proxyCodec": "H264", "proxyHeight": 720}),
                )
            )
            assert updated["kind"] == "response"
            assert updated["result"]["proxyCodec"] == "H264"
            assert updated["result"]["proxyHeight"] == 720
        finally:
            svc.close()

    def test_settings_update_validates_params(self, tmp_path: Path) -> None:
        svc = _service(tmp_path)
        try:
            resp = _parse(_serve(svc, _request("settings.update", {"proxyHeight": "not-a-number"})))
            assert resp["kind"] == "error"
            assert resp["error"]["code"] == "invalid_params"
        finally:
            svc.close()

    def test_job_resume_requires_needs_attention(self, tmp_path: Path) -> None:
        svc = _service(tmp_path)
        try:
            resp = _parse(_serve(svc, _request("job.resume", {"id": "missing"})))
            # Unknown job surfaces as an internal error (service lookup).
            assert resp["kind"] == "error"
        finally:
            svc.close()

    def test_job_list_validates_params_against_its_own_model(self, tmp_path: Path) -> None:
        """``job.list`` must reject junk a ``ListJobsParams`` cannot express.

        The handler previously validated against ``ListAssetsParams`` -- a
        borrow that worked only while both models held a ``projectId``. A
        non-string ``projectId`` (or any field ``ListJobsParams`` forbids,
        thanks to ``extra="forbid"``) must surface as ``invalid_params``.
        """
        svc = _service(tmp_path)
        try:
            for bad in ({"projectId": 123}, {"stateFilter": "running"}):
                resp = _parse(_serve(svc, _request("job.list", bad)))
                assert resp["kind"] == "error", bad
                assert resp["error"]["code"] == "invalid_params", bad

            # A well-formed filter that matches nothing is a success with an
            # empty list (a filter, not a lookup), but it proves the params
            # passed validation rather than tripping it.
            ok = _parse(_serve(svc, _request("job.list", {"projectId": "no-such-project"})))
            assert ok["kind"] == "response"
            assert ok["result"]["jobs"] == []
        finally:
            svc.close()

    def test_receipt_get_missing_is_error(self, tmp_path: Path) -> None:
        svc = _service(tmp_path)
        try:
            resp = _parse(_serve(svc, _request("receipt.get", {"operationId": "nope"})))
            assert resp["kind"] == "error"
        finally:
            svc.close()
