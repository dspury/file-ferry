"""The destination-preset workflow through the real RPC surface.

Spec §10: "Add targeted end-to-end tests through real service wiring for
scan → save destination → save preset → plan → approve". Service-level
tests prove each piece in isolation; this proves the pieces are actually
reachable over the protocol, with the field names the renderer uses, and
that the safety gates survive the trip through wiring.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest

from file_ferry.application.service import ApplicationService
from file_ferry.service.protocol import PROTOCOL_VERSION
from file_ferry.service.server import SidecarServer
from file_ferry.service.wiring import wire_server


class Rpc:
    """A wired sidecar, driven one request at a time over stdio."""

    def __init__(self, tmp_path: Path) -> None:
        self.service = ApplicationService(
            db_path=tmp_path / "ferry.db",
            app_data_dir=tmp_path / "app",
            config_path=tmp_path / "config.toml",
        )
        self.service.bootstrap()

    def close(self) -> None:
        self.service.shutdown()
        self.service.close()

    def raw(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        server = SidecarServer(db_path=Path(":memory:"))
        wire_server(server, self.service)
        line = (
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "v": PROTOCOL_VERSION,
                    "kind": "request",
                    "id": "e2e",
                    "method": method,
                    "params": params or {},
                }
            )
            + "\n"
        )
        out = io.StringIO()
        server.run_once(io.StringIO(line), out)
        parsed: dict[str, Any] = json.loads(out.getvalue().strip())
        return parsed

    def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        response = self.raw(method, params)
        assert "error" not in response, f"{method} failed: {response.get('error')}"
        return response["result"]

    def error(self, method: str, params: dict[str, Any] | None = None) -> str:
        response = self.raw(method, params)
        assert "error" in response, f"{method} unexpectedly succeeded: {response}"
        return str(response["error"].get("message", ""))

    def preflight(self, plan_id: str) -> dict[str, Any]:
        """Run a preflight to completion over the wire."""
        import time

        started = self.call("transfer.preflightStart", {"planId": plan_id})
        for _ in range(3000):
            status = self.call("transfer.preflightStatus", {"id": started["id"]})
            if status["status"] != "running":
                return status
            time.sleep(0.01)
        raise AssertionError("preflight never finished")

    def approve(self, plan: dict[str, Any]) -> dict[str, Any]:
        """Preflight, then approve — the real order of operations (R09)."""
        status = self.preflight(plan["id"])
        assert status["status"] == "passed", status["findings"]
        result: dict[str, Any] = self.call(
            "transfer.planApprove", {"id": plan["id"], "fingerprint": plan["fingerprint"]}
        )
        return result

    def inventory(self, path: Path, label: str) -> dict[str, Any]:
        created = self.call("inventory.create", {"path": str(path), "label": label})
        inventory_id = created["inventoryId"]
        for _ in range(3000):
            status = self.call("inventory.status", {"id": inventory_id})
            if status["status"] != "scanning":
                assert status["status"] == "complete", status.get("error")
                return status
            import time

            time.sleep(0.01)
        raise AssertionError("inventory never finished scanning")


@pytest.fixture
def rpc(tmp_path: Path) -> Any:
    client = Rpc(tmp_path)
    try:
        yield client
    finally:
        client.close()


def test_every_new_method_is_advertised(rpc: Rpc) -> None:
    """Capability discovery covers the new surface (spec §8)."""
    capabilities = set(rpc.call("app.getCapabilities")["methods"])
    for method in (
        "destination.save",
        "destination.list",
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
        "transfer.planApprove",
        "transfer.preflightStart",
        "transfer.preflightStatus",
        "destination.discovery",
    ):
        assert method in capabilities, f"{method} is not discoverable"


def test_scan_save_preset_plan_approve(rpc: Rpc, tmp_path: Path) -> None:
    """The whole happy path, over the wire, with camelCase field names."""
    source = tmp_path / "card"
    (source / "DCIM" / "100").mkdir(parents=True)
    (source / "DCIM" / "100" / "A001.MOV").write_bytes(b"movie-bytes")
    (source / "notes.txt").write_bytes(b"notes")
    (source / "empty").mkdir()
    dest_root = tmp_path / "nas"
    dest_root.mkdir()

    inventory = rpc.inventory(source, "Card A")
    assert inventory["fileCount"] == 2
    assert inventory["dirCount"] == 3, "directories, including the empty one, are inventoried"
    assert inventory["errorCount"] == 0

    preset = rpc.call(
        "profile.saveRevision",
        {
            "name": "Preserve",
            "content": {"fallbackTemplate": "Sources/{relative_dir}/{filename}"},
        },
    )
    assert preset["revision"] == 1

    destination = rpc.call(
        "destination.save",
        {
            "name": "Studio NAS",
            "path": str(dest_root),
            "defaultPresetId": preset["presetId"],
            "freeSpaceReserve": 1024,
        },
    )
    assert destination["pinnedRevision"] == 1, "the save pins a concrete revision"

    resolved = rpc.call("destination.resolve", {"id": destination["id"]})
    assert resolved["resolutions"][0]["status"] == "available"

    plan = rpc.call(
        "transfer.planCreate",
        {"destinationId": destination["id"], "inventoryIds": [inventory["id"]]},
    )
    assert plan["status"] == "draft"
    assert plan["presetRevision"] == 1
    assert plan["blockingCount"] == 0
    assert plan["totalFiles"] == 2
    assert plan["freeSpaceReserve"] == 1024
    assert plan["neededBytes"] >= 1024, "the reserve is part of what the plan needs"
    assert plan["inventoryIds"] == [inventory["id"]]

    entries = rpc.call("transfer.planEntries", {"id": plan["id"], "limit": 1000})
    by_rel = {e["relPath"]: e for e in entries["entries"]}
    # 2 files + the one genuinely empty directory. ``DCIM`` and
    # ``DCIM/100`` hold files this plan copies, so writing those files
    # creates them; a separate entry for each would be an empty duplicate
    # of every source parent, which the agreed examples rule out (R18).
    assert entries["total"] == 3, "2 files + 1 genuinely empty directory"
    assert "DCIM" not in by_rel and "DCIM/100" not in by_rel, (
        "a directory whose contents this plan copies is created by them"
    )
    # The preset preserves the source structure beneath a per-source
    # folder, so the mapping is visible and the source tree survives.
    assert by_rel["DCIM/100/A001.MOV"]["destRelPath"] == "Sources/DCIM/100/A001.MOV"
    assert by_rel["DCIM/100/A001.MOV"]["inventoryId"] == inventory["id"]
    assert by_rel["DCIM/100/A001.MOV"]["matchedRule"] == "fallback"
    assert by_rel["empty"]["action"] == "dir", (
        "an empty source directory has no contents to imply it, so it keeps its entry"
    )
    assert all(e["excludedByUser"] is False for e in entries["entries"])

    approved = rpc.approve(plan)
    assert approved["status"] == "approved"
    assert approved["approvedFingerprint"] == plan["fingerprint"]


def test_editing_the_destination_invalidates_over_the_wire(rpc: Rpc, tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "a.txt").write_bytes(b"a")
    dest_root = tmp_path / "nas"
    dest_root.mkdir()
    moved = tmp_path / "nas2"
    moved.mkdir()

    inventory = rpc.inventory(source, "Src")
    destination = rpc.call("destination.save", {"name": "D", "path": str(dest_root)})
    plan = rpc.call(
        "transfer.planCreate",
        {"destinationId": destination["id"], "inventoryIds": [inventory["id"]]},
    )
    rpc.approve(plan)

    rpc.call("destination.save", {"name": "D", "path": str(moved)})
    assert rpc.call("transfer.planGet", {"id": plan["id"]})["status"] == "invalidated"
    message = rpc.error(
        "transfer.planApprove", {"id": plan["id"], "fingerprint": plan["fingerprint"]}
    )
    assert "invalidated" in message


def test_two_sources_with_one_name_both_survive_over_the_wire(rpc: Rpc, tmp_path: Path) -> None:
    """A04 end to end: two sources, one relative name, nothing lost.

    With the default preset each source routes under its own label, so
    both land distinctly. The guarantee under test is that neither is
    dropped and neither overwrites the other — not that a particular
    collision strategy fires.
    """
    for name in ("drive_a", "drive_b"):
        root = tmp_path / name
        root.mkdir()
        (root / "same.txt").write_bytes(name.encode())
    dest_root = tmp_path / "nas"
    dest_root.mkdir()

    a = rpc.inventory(tmp_path / "drive_a", "A")
    b = rpc.inventory(tmp_path / "drive_b", "B")
    destination = rpc.call("destination.save", {"name": "D", "path": str(dest_root)})
    plan = rpc.call(
        "transfer.planCreate",
        {"destinationId": destination["id"], "inventoryIds": [a["id"], b["id"]]},
    )
    entries = rpc.call("transfer.planEntries", {"id": plan["id"], "limit": 1000})
    files = [e for e in entries["entries"] if e["entryType"] == "file"]
    assert len(files) == 2, "neither source's file was dropped"
    assert len({e["destRelPath"] for e in files}) == 2, "and neither overwrites the other"
    assert {e["inventoryId"] for e in files} == {a["id"], b["id"]}
    assert plan["blockingCount"] == 0
    assert plan["exclusionCount"] == 0
    assert rpc.approve(plan)["status"] == "approved"


def test_preset_export_carries_no_local_paths(rpc: Rpc, tmp_path: Path) -> None:
    """§4.2: exported presets are portable — no paths, no identities."""
    dest_root = tmp_path / "nas"
    dest_root.mkdir()
    preset = rpc.call(
        "profile.saveRevision",
        {"name": "Portable", "content": {"fallbackTemplate": "Sources/{filename}"}},
    )
    rpc.call(
        "destination.save",
        {"name": "D", "path": str(dest_root), "defaultPresetId": preset["presetId"]},
    )
    exported = rpc.call("profile.export", {"presetId": preset["presetId"]})
    assert str(dest_root) not in exported["payload"]
    assert str(tmp_path) not in exported["payload"]

    imported = rpc.call("profile.import", {"payload": exported["payload"], "newName": "Copy"})
    assert imported["presetId"] != preset["presetId"], "an import is a new local identity"


def test_discovery_reports_what_it_knows_and_what_it_could_not(rpc: Rpc) -> None:
    """§5.2: discovery degrading is a recoverable warning, not a dead end."""
    status = rpc.call("destination.discovery")
    assert isinstance(status["volumes"], list)
    assert status["observedAt"] is not None, "an observation has actually happened"
    assert status["ageSeconds"] is not None
    assert status["stale"] is False
    assert isinstance(status["warnings"], list)
    # Whatever this machine reports, every volume carries either real
    # evidence or an explicit weak fallback — never a silent absence
    # dressed up as identity.
    for volume in status["volumes"]:
        identity = volume.get("identity")
        if identity is not None:
            assert identity["confidence"] in {"strong", "medium", "weak"}
            assert identity["provenance"], "evidence records where it came from"


def test_resolve_uses_real_observations_over_the_wire(rpc: Rpc, tmp_path: Path) -> None:
    """P3: the resolver is actually fed discovery, not an empty list.

    Before P3 `destination.resolve` passed no observations at all, so
    over the wire it could only ever reach its path-only branch — the
    resolver rules existed but nothing exercised them in production.
    """
    dest_root = tmp_path / "nas"
    dest_root.mkdir()
    destination = rpc.call("destination.save", {"name": "Local", "path": str(dest_root)})

    resolution = rpc.call("destination.resolve", {"id": destination["id"]})["resolutions"][0]
    assert resolution["status"] == "available"
    assert resolution["bindingPath"] == str(dest_root)

    # Confirming a binding captures the platform's *real* evidence for
    # that location, which is only possible if observations reached the
    # service. That is the thing this test exists to prove.
    volume_dest = rpc.call(
        "destination.save",
        {"name": "Volume", "path": str(dest_root), "locationKind": "volume_folder"},
    )
    confirmed = rpc.call(
        "destination.confirmBinding",
        {"destinationId": volume_dest["id"], "path": str(dest_root)},
    )
    identity = confirmed["identity"]
    assert identity is not None, "the confirmed binding recorded observed storage evidence"
    assert identity["provenance"].endswith("confirmed by user")
    assert identity["stale"] is False

    # And a destination whose storage is gone is offline, not available.
    import shutil

    gone = tmp_path / "removable"
    gone.mkdir()
    vanishing = rpc.call("destination.save", {"name": "Removable", "path": str(gone)})
    shutil.rmtree(gone)
    vanished = rpc.call("destination.resolve", {"id": vanishing["id"]})["resolutions"][0]
    assert vanished["status"] == "offline"
    assert vanished["bindingPath"] is None


def test_confirm_binding_refuses_a_contradictory_identity(rpc: Rpc, tmp_path: Path) -> None:
    """R11: a binding whose path and identity disagree is never recorded.

    Submitting "this folder is on volume X" for a folder observably on
    volume Y would persist evidence that was never true, and the
    resolver would then reason from it — recognizing the wrong storage
    later, with a confident reason string.
    """
    folder = tmp_path / "local"
    folder.mkdir()
    destination = rpc.call(
        "destination.save",
        {"name": "Contradiction", "path": str(folder), "locationKind": "volume_folder"},
    )
    message = rpc.error(
        "destination.confirmBinding",
        {
            "destinationId": destination["id"],
            "path": str(folder),
            "identity": {
                "kind": "volume_uuid",
                "value": "a-uuid-this-folder-is-not-on",
                "confidence": "strong",
                "provenance": "test",
            },
        },
    )
    assert "path and identity disagree" in message
    saved = rpc.call("destination.get", {"id": destination["id"]})
    assert saved["identity"] is None, "nothing contradictory was persisted"


def test_resolve_without_refresh_reuses_the_last_observation(rpc: Rpc, tmp_path: Path) -> None:
    """A UI that re-renders must not re-probe the platform each time."""
    dest_root = tmp_path / "nas"
    dest_root.mkdir()
    destination = rpc.call("destination.save", {"name": "Local", "path": str(dest_root)})
    rpc.call("destination.discovery")  # establish an observation
    cached = rpc.call("destination.resolve", {"id": destination["id"], "refresh": False})
    assert cached["resolutions"][0]["status"] == "available"


def test_confirm_binding_is_the_only_thing_that_rebinds(rpc: Rpc, tmp_path: Path) -> None:
    """§5.1: recognition never rebinds; an explicit user action does."""
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    destination = rpc.call("destination.save", {"name": "D", "path": str(first)})

    rpc.call("destination.resolve", {"id": destination["id"]})
    assert rpc.call("destination.get", {"id": destination["id"]})["lastBindingPath"] == str(first)

    rebound = rpc.call(
        "destination.confirmBinding",
        {"destinationId": destination["id"], "path": str(second)},
    )
    assert rebound["lastBindingPath"] == str(second)
    assert rebound["lastSeenAt"] is not None


def test_rebinding_invalidates_an_approved_plan_over_the_wire(rpc: Rpc, tmp_path: Path) -> None:
    """§5.1: rebinding invalidates pending plan approval."""
    source = tmp_path / "src"
    source.mkdir()
    (source / "a.txt").write_bytes(b"a")
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()

    inventory = rpc.inventory(source, "Src")
    destination = rpc.call("destination.save", {"name": "D", "path": str(first)})
    plan = rpc.call(
        "transfer.planCreate",
        {"destinationId": destination["id"], "inventoryIds": [inventory["id"]]},
    )
    rpc.approve(plan)

    rpc.call(
        "destination.confirmBinding",
        {"destinationId": destination["id"], "path": str(second)},
    )
    assert rpc.call("transfer.planGet", {"id": plan["id"]})["status"] == "invalidated"
