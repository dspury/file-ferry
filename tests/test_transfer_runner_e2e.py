"""The transfer runner through real service wiring (spec §7.2/§7.3, P5).

Spec §10 asks for end-to-end tests through real wiring for
scan → save destination → save preset → plan → approve → **execute →
receipt**. The earlier packages stopped at approve; this module carries
the same flow through the runner and proves the safety guarantees that
only exist once something has tried to break them.

Everything here goes over the RPC surface where the surface exists, so
a method that is unreachable from the renderer fails these tests rather
than passing a service-level unit test nobody can call.

Acceptance IDs from ``docs/DESTINATION-PRESETS-PRODUCTION-SPEC.md``:
A09 (external file at publication), A10 (cancellation), A11 (write
failure), A15 (crash at the publication boundary), A16 (source changed
under a resume), A21 (reservations released after a crash), A22
(receipt export failure is visible and retriable), A23 (repeat and
partial resume reuse rather than recopy).
"""

from __future__ import annotations

import io
import json
import os
import time
from pathlib import Path
from typing import Any

import pytest

from file_ferry.application.service import ApplicationService
from file_ferry.persistence.connection import transaction
from file_ferry.persistence.repositories import transfer_executions as exec_repo
from file_ferry.service.protocol import PROTOCOL_VERSION
from file_ferry.service.server import SidecarServer
from file_ferry.service.wiring import wire_server


class Rpc:
    """A wired sidecar driven one request at a time, dispatcher parked.

    The background dispatcher is stopped so that ``run(job_id)`` is the
    only thing that ever runs a job. Left running it would race every
    explicit dispatch here: the thread can claim the volume slot first
    and the test's own call returns having done nothing.
    """

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.service = ApplicationService(
            db_path=tmp_path / "ferry.db",
            app_data_dir=tmp_path / "app",
            config_path=tmp_path / "config.toml",
        )
        self.service.bootstrap()
        assert self.service._dispatcher is not None
        self.service._dispatcher.stop()

    def close(self) -> None:
        self.service.shutdown()
        self.service.close()

    # ---- transport ---------------------------------------------------

    def raw(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        server = SidecarServer(db_path=Path(":memory:"))
        wire_server(server, self.service)
        line = (
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "v": PROTOCOL_VERSION,
                    "kind": "request",
                    "id": "p5",
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

    # ---- flow helpers ------------------------------------------------

    def inventory(self, path: Path, label: str) -> dict[str, Any]:
        created = self.call("inventory.create", {"path": str(path), "label": label})
        for _ in range(3000):
            status = self.call("inventory.status", {"id": created["inventoryId"]})
            if status["status"] != "scanning":
                assert status["status"] == "complete", status.get("error")
                return status
            time.sleep(0.01)
        raise AssertionError("inventory never finished scanning")

    def preflight(self, plan_id: str) -> dict[str, Any]:
        started = self.call("transfer.preflightStart", {"planId": plan_id})
        for _ in range(3000):
            status = self.call("transfer.preflightStatus", {"id": started["id"]})
            if status["status"] != "running":
                return status
            time.sleep(0.01)
        raise AssertionError("preflight never finished")

    def approve(self, plan: dict[str, Any]) -> dict[str, Any]:
        status = self.preflight(plan["id"])
        assert status["status"] == "passed", status["findings"]
        result: dict[str, Any] = self.call(
            "transfer.planApprove", {"id": plan["id"], "fingerprint": plan["fingerprint"]}
        )
        return result

    def run(self, job_id: str) -> str:
        """Dispatch one job synchronously and return its resulting state."""
        return str(self.service.scheduler().dispatch(job_id).state)

    def execution_state(self, execution_id: str) -> str:
        with transaction(self.service._db_path) as conn:
            row = exec_repo.get_execution(conn, execution_id)
        assert row is not None
        return row.state

    def items(self, execution_id: str) -> dict[str, str]:
        """``dest_rel_path -> state`` for every ledger item."""
        with transaction(self.service._db_path) as conn:
            rows = exec_repo.get_execution_items(conn, execution_id)
        return {r.dest_rel_path: r.state for r in rows}

    def mapping(self, plan_id: str) -> dict[str, str]:
        """``relPath -> destRelPath`` as the plan actually mapped it.

        Derived rather than hard-coded: the default preset routes under
        ``Sources/<label>/``, and a test that assumed a layout would be
        testing its own assumption instead of the transfer.
        """
        page = self.call("transfer.planEntries", {"id": plan_id, "limit": 1000})
        return {e["relPath"]: e["destRelPath"] for e in page["entries"]}

    def order(self, plan_id: str) -> list[tuple[str, str]]:
        """``(relPath, destRelPath)`` in the order the runner will work.

        The ledger is built from the plan entries and processed by entry
        id, which is not alphabetical. Tests that need "the first item"
        or "the last item" ask here rather than assuming a layout.
        """
        page = self.call("transfer.planEntries", {"id": plan_id, "limit": 1000})
        entries = sorted(page["entries"], key=lambda e: e["id"])
        return [(e["relPath"], e["destRelPath"]) for e in entries if e["action"] == "copy"]

    def reservations(self) -> list[tuple[str, str]]:
        """Every reservation still held (``dest_root``, ``rel_path``)."""
        with transaction(self.service._db_path) as conn:
            rows = conn.execute(
                "SELECT dest_root, rel_path FROM transfer_path_reservations "
                "WHERE released_at IS NULL"
            ).fetchall()
        return [(r["dest_root"], r["rel_path"]) for r in rows]


@pytest.fixture
def rpc(tmp_path: Path) -> Any:
    client = Rpc(tmp_path)
    try:
        yield client
    finally:
        client.close()


def _tree(rpc: Rpc, files: dict[str, bytes], *, name: str = "card") -> tuple[Path, Path]:
    """A source tree and an empty destination root."""
    source = rpc.tmp_path / name
    for rel, data in files.items():
        target = source / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    dest = rpc.tmp_path / f"nas-{name}"
    dest.mkdir(parents=True, exist_ok=True)
    return source, dest


def _approved_plan(rpc: Rpc, files: dict[str, bytes], *, name: str = "card") -> dict[str, Any]:
    """Scan → destination → plan → preflight → approve, over the wire."""
    source, dest = _tree(rpc, files, name=name)
    inventory = rpc.inventory(source, f"Card {name}")
    destination = rpc.call("destination.save", {"name": f"NAS {name}", "path": str(dest)})
    plan = rpc.call(
        "transfer.planCreate",
        {"destinationId": destination["id"], "inventoryIds": [inventory["id"]]},
    )
    approved = rpc.approve(plan)
    assert approved["status"] == "approved"
    return {"plan": plan, "dest": dest, "source": source, "inventory": inventory}


# --- discoverability ------------------------------------------------------


def test_the_execution_methods_are_advertised(rpc: Rpc) -> None:
    """A method the renderer cannot discover may as well not exist."""
    capabilities = set(rpc.call("app.getCapabilities")["methods"])
    for method in ("transfer.start", "transfer.receipt", "transfer.receiptExport"):
        assert method in capabilities, f"{method} is not discoverable"


# --- the happy path: scan -> ... -> execute -> receipt --------------------


def test_scan_to_receipt_copies_verifies_and_receipts(rpc: Rpc) -> None:
    """The whole flow, over the wire, ending in a durable receipt."""
    ctx = _approved_plan(
        rpc,
        {
            "DCIM/100/A001.MOV": b"movie-bytes",
            "DCIM/100/A002.MOV": b"second-movie",
            "notes.txt": b"notes",
        },
    )
    plan, dest = ctx["plan"], ctx["dest"]

    started = rpc.call("transfer.start", {"id": plan["id"], "fingerprint": plan["fingerprint"]})
    assert started["job"]["state"] == "queued", "start returns before the copy runs"
    assert started["job"]["command"] == "transfer"
    assert started["job"]["argsFingerprint"] == plan["fingerprint"]
    execution_id = started["executionId"]

    assert rpc.run(started["job"]["id"]) == "succeeded"
    assert rpc.execution_state(execution_id) == "succeeded"

    # The bytes actually landed, and they are the source bytes.
    mapping = rpc.mapping(plan["id"])
    for rel, expected in (
        ("DCIM/100/A001.MOV", b"movie-bytes"),
        ("DCIM/100/A002.MOV", b"second-movie"),
        ("notes.txt", b"notes"),
    ):
        assert (dest / mapping[rel]).read_bytes() == expected
    # No temp files survive a clean run.
    assert not list(dest.rglob("*.ferrytmp*")), "temp files left behind"

    receipt = rpc.call("transfer.receipt", {"planId": plan["id"]})
    assert receipt["finalState"] == "succeeded"
    assert receipt["executionId"] == execution_id
    assert receipt["fingerprint"] == plan["fingerprint"]
    assert receipt["exportError"] is None
    body = receipt["receipt"]
    assert body["actual"]["committed"] == 3
    assert body["actual"]["failed"] == 0
    assert body["expected"]["totalFiles"] == 3
    assert body["errors"] == []
    # Every committed entry carries the checksum that proved it.
    for entry in body["entries"]:
        if entry["state"] == "committed":
            assert entry["sourceChecksum"]
            assert entry["destChecksum"] == entry["sourceChecksum"]

    # §12.2 performance block. Peak RSS is *since sidecar start* and is named
    # so on purpose; it must not be read as this run's memory.
    performance = body["performance"]
    assert performance["durationSeconds"] is not None
    assert performance["durationSeconds"] >= 0
    assert performance["bytesPerSecond"] is not None
    assert "sidecarPeakRssBytes" in performance
    assert "peakRssBytes" not in performance

    # The receipt was exported to disk as well as to the database (A22).
    exported = Path(receipt["exportedPath"])
    assert exported.is_file()
    assert json.loads(exported.read_text())["executionId"] == execution_id

    # The plan is spent, and nothing still holds a path.
    assert rpc.call("transfer.planGet", {"id": plan["id"]})["status"] == "executed"
    assert rpc.reservations() == []


def test_receipt_distinguishes_committed_files_from_directories(rpc: Rpc) -> None:
    """#207: `committed` counts ledger entries, files and directories alike.

    A source of two files and one empty directory reports `committed: 3`, not
    "2", so the receipt states the file and directory counts rather than
    leaving a later reader to reconcile 3 against a file count of 2.
    """
    source, dest = _tree(rpc, {"A001.MOV": b"movie", "notes.txt": b"notes"})
    (source / "empty").mkdir()
    inventory = rpc.inventory(source, "Card with an empty dir")
    destination = rpc.call("destination.save", {"name": "NAS dirs", "path": str(dest)})
    plan = rpc.call(
        "transfer.planCreate",
        {"destinationId": destination["id"], "inventoryIds": [inventory["id"]]},
    )
    rpc.approve(plan)
    started = rpc.call("transfer.start", {"id": plan["id"], "fingerprint": plan["fingerprint"]})
    assert rpc.run(started["job"]["id"]) == "succeeded"
    actual = rpc.call("transfer.receipt", {"planId": plan["id"]})["receipt"]["actual"]
    assert actual["files"] == 2
    assert actual["directories"] == 1
    assert actual["committed"] == 3
    assert actual["committed"] == actual["files"] + actual["directories"]


def test_start_is_idempotent_while_the_job_is_alive(rpc: Rpc) -> None:
    """A double-click must not queue the same plan twice."""
    ctx = _approved_plan(rpc, {"a.txt": b"a"})
    plan = ctx["plan"]
    first = rpc.call("transfer.start", {"id": plan["id"], "fingerprint": plan["fingerprint"]})
    second = rpc.call("transfer.start", {"id": plan["id"], "fingerprint": plan["fingerprint"]})
    assert second["executionId"] == first["executionId"]
    assert second["job"]["id"] == first["job"]["id"]


def test_starting_a_stale_fingerprint_is_refused(rpc: Rpc) -> None:
    """A08/§8: approval is for one exact plan substance, not a plan id."""
    ctx = _approved_plan(rpc, {"a.txt": b"a"})
    plan = ctx["plan"]
    message = rpc.error("transfer.start", {"id": plan["id"], "fingerprint": "not-the-approved-one"})
    assert "not approved" in message


def test_starting_an_unapproved_plan_is_refused(rpc: Rpc) -> None:
    """Execution is gated on approval, not on the caller's good intentions."""
    source, dest = _tree(rpc, {"a.txt": b"a"}, name="unapproved")
    inventory = rpc.inventory(source, "Unapproved")
    destination = rpc.call("destination.save", {"name": "NAS u", "path": str(dest)})
    plan = rpc.call(
        "transfer.planCreate",
        {"destinationId": destination["id"], "inventoryIds": [inventory["id"]]},
    )
    message = rpc.error("transfer.start", {"id": plan["id"], "fingerprint": plan["fingerprint"]})
    assert "not approved" in message
    assert list(dest.iterdir()) == [], "a refused start writes nothing"


def test_a_receipt_is_refused_before_anything_ran(rpc: Rpc) -> None:
    """An absent receipt reports why, rather than returning an empty one."""
    ctx = _approved_plan(rpc, {"a.txt": b"a"})
    message = rpc.error("transfer.receipt", {"planId": ctx["plan"]["id"]})
    assert "no execution" in message


# --- A09: a file that appeared after approval -----------------------------


def test_a_file_created_externally_after_approval_is_never_overwritten(rpc: Rpc) -> None:
    """A09: publication is exclusive; a stranger's file stops the item."""
    ctx = _approved_plan(rpc, {"a.txt": b"source-bytes", "b.txt": b"other"})
    plan, dest = ctx["plan"], ctx["dest"]

    # Someone drops a file at the FIRST destination path the runner will
    # reach, between approval and run. First, so that the stop happens
    # before anything else commits and "committed == 0" means what it says.
    _first_rel, first_dest = rpc.order(plan["id"])[0]
    intruder = dest / first_dest
    intruder.parent.mkdir(parents=True, exist_ok=True)
    intruder.write_bytes(b"NOT-OURS")

    started = rpc.call("transfer.start", {"id": plan["id"], "fingerprint": plan["fingerprint"]})
    assert rpc.run(started["job"]["id"]) == "needs_attention"

    assert intruder.read_bytes() == b"NOT-OURS", "the stranger's file is intact"
    receipt = rpc.call("transfer.receipt", {"planId": plan["id"]})
    assert receipt["finalState"] == "needs_attention"
    assert receipt["receipt"]["actual"]["committed"] == 0, "no partial success is claimed"
    assert receipt["receipt"]["errors"], "the reason is recorded"
    assert rpc.reservations() == [], "a stopped run releases its reservations"


# --- A11: a write that fails ----------------------------------------------


def test_a_failing_write_leaves_the_source_intact_and_no_green_success(
    rpc: Rpc, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A11: an ENOSPC-shaped failure is attention, never a clean finish."""
    ctx = _approved_plan(rpc, {"a.txt": b"source-bytes"})
    plan, dest, source = ctx["plan"], ctx["dest"], ctx["source"]

    from file_ferry.application import transfer_runner as runner_mod

    def explode(*_args: object, **_kwargs: object) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(runner_mod, "copy_file_verified", explode)

    started = rpc.call("transfer.start", {"id": plan["id"], "fingerprint": plan["fingerprint"]})
    assert rpc.run(started["job"]["id"]) == "needs_attention"

    assert (source / "a.txt").read_bytes() == b"source-bytes", "the source is untouched"
    assert not (dest / rpc.mapping(plan["id"])["a.txt"]).exists(), (
        "no half-written file is published"
    )
    assert not list(dest.rglob("*.ferrytmp*")), "the temp file is cleaned up"
    receipt = rpc.call("transfer.receipt", {"planId": plan["id"]})
    assert receipt["finalState"] == "needs_attention"
    assert receipt["receipt"]["actual"]["committed"] == 0
    assert any("space" in e.lower() for e in receipt["receipt"]["errors"])
    assert rpc.reservations() == []


# --- A23: repeat and partial resume ---------------------------------------


def test_a_resume_keeps_committed_files_and_finishes_the_rest(
    rpc: Rpc, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A23: a resume completes the remainder; it never recopies or renames.

    The failure mode this guards is the one that produces ``a (1).txt``:
    a resumed run that cannot tell what it already published treats its
    own prior output as a conflict and writes beside it.
    """
    ctx = _approved_plan(rpc, {"a.txt": b"aaa", "b.txt": b"bbb"})
    plan, dest = ctx["plan"], ctx["dest"]
    order = rpc.order(plan["id"])
    assert len(order) == 2
    (_done_rel, done_dest), (stuck_rel, stuck_dest) = order

    from file_ferry.application import transfer_runner as runner_mod

    real_copy = runner_mod.copy_file_verified

    def fail_on_last(source: Any, *args: Any, **kwargs: Any) -> Any:
        if Path(source).name == Path(stuck_rel).name:
            raise OSError(28, "No space left on device")
        return real_copy(source, *args, **kwargs)

    monkeypatch.setattr(runner_mod, "copy_file_verified", fail_on_last)

    started = rpc.call("transfer.start", {"id": plan["id"], "fingerprint": plan["fingerprint"]})
    execution_id = started["executionId"]
    assert rpc.run(started["job"]["id"]) == "needs_attention"

    states = rpc.items(execution_id)
    assert states[done_dest] == "committed", "the earlier file did land"
    assert states[stuck_dest] == "failed"
    done_stat = (dest / done_dest).stat()

    # The cause goes away and the operator resumes.
    monkeypatch.setattr(runner_mod, "copy_file_verified", real_copy)
    resumed = rpc.service.job_resume(started["job"]["id"])
    assert resumed.state == "succeeded", "the resume finished the remainder"

    on_disk = sorted(str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file())
    assert on_disk == sorted(d for _rel, d in order), (
        "a resume must not explode into incremental names"
    )
    assert (dest / stuck_dest).read_bytes() == (ctx["source"] / stuck_rel).read_bytes()
    assert (dest / done_dest).stat().st_mtime_ns == done_stat.st_mtime_ns, (
        "the already-committed file was not rewritten"
    )

    receipt = rpc.call("transfer.receipt", {"planId": plan["id"]})
    assert receipt["finalState"] == "succeeded"
    assert receipt["receipt"]["actual"]["failed"] == 0
    assert receipt["receipt"]["interruptionLineage"], "the interruption is on the record"
    assert rpc.reservations() == []


# --- A21: a crash leaves nothing reserved forever -------------------------


def test_recovery_releases_reservations_a_dead_job_still_holds(rpc: Rpc) -> None:
    """A21: reservations outlive the process unless recovery releases them."""
    ctx = _approved_plan(rpc, {"a.txt": b"a", "b.txt": b"b"})
    plan = ctx["plan"]
    started = rpc.call("transfer.start", {"id": plan["id"], "fingerprint": plan["fingerprint"]})
    execution_id = started["executionId"]
    mapping = rpc.mapping(plan["id"])

    # Simulate a crash mid-run: items and reservations exist, the job is
    # dead, and no receipt was ever written.
    with transaction(rpc.service._db_path) as conn:
        exec_repo.insert_reservations(
            conn,
            dest_root=str(ctx["dest"]),
            rel_paths=[mapping["a.txt"]],
            execution_id=execution_id,
            acquired_at="2026-01-01T00:00:00Z",
        )
        conn.execute("UPDATE jobs SET state = 'failed' WHERE id = ?", (started["job"]["id"],))
    assert rpc.reservations(), "the crash left a reservation held"

    rpc.service.job_recover()
    assert rpc.reservations() == [], "recovery released it"
    assert rpc.execution_state(execution_id) == "needs_attention"


# --- A22: the receipt export can fail without faking success --------------


def test_a_failed_receipt_export_is_visible_and_retriable(
    rpc: Rpc, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A22: the database receipt is the record; the export is retriable."""
    ctx = _approved_plan(rpc, {"a.txt": b"a"})
    plan = ctx["plan"]

    real_replace = os.replace

    def fail_once(src: Any, dst: Any, *args: Any, **kwargs: Any) -> None:
        if str(dst).endswith(".json"):
            raise OSError(13, "Permission denied")
        real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "replace", fail_once)

    started = rpc.call("transfer.start", {"id": plan["id"], "fingerprint": plan["fingerprint"]})
    assert rpc.run(started["job"]["id"]) == "succeeded", (
        "the transfer itself succeeded; only its export did not"
    )

    receipt = rpc.call("transfer.receipt", {"planId": plan["id"]})
    assert receipt["finalState"] == "succeeded"
    assert receipt["exportedPath"] is None, "no export path is claimed"

    # The export is retriable once the cause is gone.
    monkeypatch.setattr(os, "replace", real_replace)
    retried = rpc.call("transfer.receiptExport", {"planId": plan["id"]})
    assert retried["exportedPath"] is not None
    assert Path(retried["exportedPath"]).is_file()
    assert json.loads(Path(retried["exportedPath"]).read_text())["finalState"] == "succeeded"


# --- A10: cancellation --------------------------------------------------


def test_cancelling_mid_copy_leaves_the_source_intact_and_receipts_the_stop(
    rpc: Rpc,
) -> None:
    """A10: a cancelled transfer is a deliberate stop, not a failure.

    The cancel is observed inside the copier's per-chunk check, so this
    exercises the real cancellation path rather than the cheap boundary
    check between items.
    """
    payload = b"x" * (4 * 1024 * 1024)
    ctx = _approved_plan(rpc, {"big.bin": payload})
    plan, dest, source = ctx["plan"], ctx["dest"], ctx["source"]
    _rel, dest_rel = rpc.order(plan["id"])[0]

    started = rpc.call("transfer.start", {"id": plan["id"], "fingerprint": plan["fingerprint"]})
    job_id = started["job"]["id"]
    rpc.service.scheduler().request_cancel(job_id)

    assert rpc.run(job_id) == "cancelled"

    assert (source / "big.bin").read_bytes() == payload, "the source is untouched"
    assert not (dest / dest_rel).exists(), "nothing was published"
    assert not list(dest.rglob("*.ferrytmp*")), "the partial temp is cleaned up"

    receipt = rpc.call("transfer.receipt", {"planId": plan["id"]})
    assert receipt["finalState"] == "cancelled"
    assert receipt["receipt"]["actual"]["committed"] == 0
    assert receipt["receipt"]["actual"]["failed"] == 0, "a cancellation is not a failure"
    assert rpc.reservations() == []


# --- A15: a crash at the publication boundary ---------------------------


def _stall_after_first(rpc: Rpc, ctx: dict[str, Any]) -> tuple[str, str, str]:
    """Run once so the ledger exists, stopping on the last item.

    Returns ``(execution_id, job_id, dest_rel_path_of_the_stuck_item)``.
    """
    plan = ctx["plan"]
    order = rpc.order(plan["id"])
    stuck_rel, stuck_dest = order[-1]
    from file_ferry.application import transfer_runner as runner_mod

    real_copy = runner_mod.copy_file_verified

    def fail_on_last(source: Any, *args: Any, **kwargs: Any) -> Any:
        if Path(source).name == Path(stuck_rel).name:
            raise OSError(28, "No space left on device")
        return real_copy(source, *args, **kwargs)

    runner_mod.copy_file_verified = fail_on_last  # type: ignore[assignment]
    try:
        started = rpc.call("transfer.start", {"id": plan["id"], "fingerprint": plan["fingerprint"]})
        assert rpc.run(started["job"]["id"]) == "needs_attention"
    finally:
        runner_mod.copy_file_verified = real_copy  # type: ignore[assignment]
    return started["executionId"], started["job"]["id"], stuck_dest


def _force_item_state(rpc: Rpc, execution_id: str, dest_rel: str, state: str) -> None:
    with transaction(rpc.service._db_path) as conn:
        conn.execute(
            "UPDATE transfer_execution_items SET state = ?, error = NULL "
            "WHERE execution_id = ? AND dest_rel_path = ?",
            (state, execution_id, dest_rel),
        )


def test_a_crash_after_publication_verifies_rather_than_recopies(rpc: Rpc) -> None:
    """A15: published-but-uncommitted is decided by a full checksum."""
    ctx = _approved_plan(rpc, {"a.txt": b"aaa", "b.txt": b"bbb"})
    plan, dest = ctx["plan"], ctx["dest"]
    execution_id, job_id, stuck_dest = _stall_after_first(rpc, ctx)

    # The crash window: the bytes were published but the commit never
    # landed, so the ledger still says "published".
    published = dest / stuck_dest
    published.parent.mkdir(parents=True, exist_ok=True)
    source_name = Path(stuck_dest).name
    published.write_bytes((ctx["source"] / source_name).read_bytes())
    mtime = published.stat().st_mtime_ns
    _force_item_state(rpc, execution_id, stuck_dest, "published")

    assert rpc.service.job_resume(job_id).state == "succeeded"

    assert rpc.items(execution_id)[stuck_dest] == "committed"
    assert published.stat().st_mtime_ns == mtime, "verified in place, not re-copied"
    receipt = rpc.call("transfer.receipt", {"planId": plan["id"]})
    assert receipt["finalState"] == "succeeded"
    assert any(
        e["state"] == "committed" and (e["warning"] or "").startswith("verified after")
        for e in receipt["receipt"]["entries"]
    ), "the receipt records that this file was verified, not copied"


def test_a_crash_that_published_the_wrong_bytes_refuses_to_overwrite(rpc: Rpc) -> None:
    """A15: an unequal published file stops the job; nothing is guessed."""
    ctx = _approved_plan(rpc, {"a.txt": b"aaa", "b.txt": b"bbb"})
    plan, dest = ctx["plan"], ctx["dest"]
    execution_id, job_id, stuck_dest = _stall_after_first(rpc, ctx)

    published = dest / stuck_dest
    published.parent.mkdir(parents=True, exist_ok=True)
    published.write_bytes(b"WRONG-BYTES")
    _force_item_state(rpc, execution_id, stuck_dest, "published")

    assert rpc.service.job_resume(job_id).state == "needs_attention"
    assert published.read_bytes() == b"WRONG-BYTES", "refused, not overwritten"
    receipt = rpc.call("transfer.receipt", {"planId": plan["id"]})
    assert receipt["finalState"] == "needs_attention"
    assert rpc.call("transfer.planGet", {"id": plan["id"]})["status"] != "executed"
    assert rpc.reservations() == []


# --- A16: the source moved under us -------------------------------------


def test_a_source_changed_before_the_resume_is_refused(rpc: Rpc) -> None:
    """A16: resume revalidates the source and demands a replan."""
    ctx = _approved_plan(rpc, {"a.txt": b"aaa", "b.txt": b"bbb"})
    plan, source = ctx["plan"], ctx["source"]
    _execution_id, job_id, _stuck = _stall_after_first(rpc, ctx)

    # The card is edited between the interruption and the resume.
    (source / "c-new.txt").write_bytes(b"added after the scan")

    assert rpc.service.job_resume(job_id).state == "needs_attention"
    receipt = rpc.call("transfer.receipt", {"planId": plan["id"]})
    assert receipt["finalState"] == "needs_attention"
    assert any("changed since they were scanned" in e for e in receipt["receipt"]["errors"]), (
        "the reason names the changed source"
    )
    assert rpc.call("transfer.planGet", {"id": plan["id"]})["status"] != "executed"


def test_a_source_edited_during_the_copy_is_caught(
    rpc: Rpc, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A16: a file rewritten mid-copy never publishes as if it were whole."""
    ctx = _approved_plan(rpc, {"a.txt": b"a" * 4096})
    plan, dest, source = ctx["plan"], ctx["dest"], ctx["source"]
    _rel, dest_rel = rpc.order(plan["id"])[0]

    from file_ferry.application import transfer_runner as runner_mod
    from file_ferry.application.transfer_safety import SourceChangedError

    def changed(src: Any, *_args: Any, **_kwargs: Any) -> Any:
        raise SourceChangedError(Path(src), (1, 2, 3, 4), (1, 2, 5, 6))

    monkeypatch.setattr(runner_mod, "copy_file_verified", changed)

    started = rpc.call("transfer.start", {"id": plan["id"], "fingerprint": plan["fingerprint"]})
    assert rpc.run(started["job"]["id"]) == "needs_attention"

    assert not (dest / dest_rel).exists(), "a source that moved never publishes"
    assert (source / "a.txt").read_bytes() == b"a" * 4096
    receipt = rpc.call("transfer.receipt", {"planId": plan["id"]})
    assert receipt["finalState"] == "needs_attention"
    assert receipt["receipt"]["actual"]["committed"] == 0


# --- the real dispatcher, not the test's synchronous stand-in ------------


def test_the_background_dispatcher_runs_a_started_transfer(tmp_path: Path) -> None:
    """``transfer.start`` must reach the runner without a manual dispatch.

    Every other test here parks the dispatcher and calls ``dispatch``
    directly, which would pass even if the kick, the runner
    registration, or the volume resolver were missing. This one leaves
    the real loop running and only calls ``transfer.start``.
    """
    client = Rpc(tmp_path)
    # Undo the harness's parking: this test wants the real loop.
    assert client.service._dispatcher is not None
    client.service._dispatcher.start()
    try:
        ctx = _approved_plan(client, {"a.txt": b"aaa"})
        plan, dest = ctx["plan"], ctx["dest"]
        started = client.call(
            "transfer.start", {"id": plan["id"], "fingerprint": plan["fingerprint"]}
        )

        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            job = client.call("job.get", {"id": started["job"]["id"]})
            if job["state"] in {"succeeded", "failed", "needs_attention", "cancelled"}:
                break
            time.sleep(0.02)
        else:  # pragma: no cover - only on a hang
            raise AssertionError("the dispatcher never ran the transfer job")

        assert job["state"] == "succeeded", job.get("error")
        dest_rel = client.order(plan["id"])[0][1]
        assert (dest / dest_rel).read_bytes() == b"aaa"
        assert client.call("transfer.receipt", {"planId": plan["id"]})["finalState"] == "succeeded"
    finally:
        client.close()
