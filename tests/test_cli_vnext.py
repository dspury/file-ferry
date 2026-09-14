"""Tests for the vNext CLI verbs in cli_vnext.py (plan §9)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from file_ferry.cli import main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _invoke(runner: CliRunner, db: Path, args: list[str]) -> object:
    return runner.invoke(main, ["--db", str(db), *args])


def _create_project(runner: CliRunner, db: Path, working: Path, name: str = "P") -> str:
    result = _invoke(runner, db, ["project", "create", name, "--working", str(working), "--json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)["projectId"]


class TestProjectVerb:
    def test_create_and_list(self, runner: CliRunner, tmp_path: Path) -> None:
        db = tmp_path / "db.sqlite"
        working = tmp_path / "working"
        working.mkdir()
        pid = _create_project(runner, db, working, "Ep1")
        assert pid

        listed = _invoke(runner, db, ["project", "list", "--json"])
        assert listed.exit_code == 0, listed.output
        projects = json.loads(listed.output)
        assert any(p["id"] == pid for p in projects)

    def test_get(self, runner: CliRunner, tmp_path: Path) -> None:
        db = tmp_path / "db.sqlite"
        working = tmp_path / "working"
        working.mkdir()
        pid = _create_project(runner, db, working, "Ep2")
        got = _invoke(runner, db, ["project", "get", pid, "--json"])
        assert got.exit_code == 0, got.output
        detail = json.loads(got.output)
        assert detail["name"] == "Ep2"
        assert detail["id"] == pid


class TestJobsVerb:
    def test_list_empty(self, runner: CliRunner, tmp_path: Path) -> None:
        db = tmp_path / "db.sqlite"
        listed = _invoke(runner, db, ["jobs", "list", "--json"])
        assert listed.exit_code == 0, listed.output
        assert json.loads(listed.output) == []


class TestSourceVerb:
    def test_inspect(self, runner: CliRunner, tmp_path: Path) -> None:
        db = tmp_path / "db.sqlite"
        src = tmp_path / "card"
        (src / "DCIM").mkdir(parents=True)
        (src / "DCIM" / "A001.mov").write_bytes(b"data")
        result = _invoke(runner, db, ["source", "inspect", str(src), "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["fileCount"] == 1
        assert data["totalBytes"] > 0

    def test_list_volumes(self, runner: CliRunner, tmp_path: Path) -> None:
        db = tmp_path / "db.sqlite"
        result = _invoke(runner, db, ["source", "list-volumes", "--json"])
        assert result.exit_code == 0, result.output
        volumes = json.loads(result.output)
        assert any(v["path"] == "/" for v in volumes)


class TestIntakeVerb:
    def test_plan(self, runner: CliRunner, tmp_path: Path) -> None:
        db = tmp_path / "db.sqlite"
        working = tmp_path / "working"
        working.mkdir()
        backup = tmp_path / "backup"
        backup.mkdir()
        src = tmp_path / "card"
        (src / "DCIM").mkdir(parents=True)
        (src / "DCIM" / "A001.mov").write_bytes(b"media-content")

        pid = _create_project(runner, db, working)
        inspected = _invoke(runner, db, ["source", "inspect", str(src), "--json"])
        source_id = json.loads(inspected.output)["sourceId"]

        result = _invoke(
            runner,
            db,
            [
                "intake",
                "plan",
                pid,
                str(source_id),
                "--working",
                str(working),
                "--backup",
                str(backup),
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        plan = json.loads(result.output)
        assert plan["capacityOk"] is True
        assert len(plan["entries"]) >= 1


class TestVNextHelp:
    def test_help_lists_vnext_verbs(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        for cmd in (
            "project",
            "source",
            "intake",
            "jobs",
            "receipt",
            "reconcile",
            "destination",
            "preset",
            "inventory",
            "plan",
            "preflight",
            "transfer",
        ):
            assert cmd in result.output


def _json_call(runner: CliRunner, db: Path, args: list[str]) -> object:
    result = _invoke(runner, db, [*args, "--json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


class TestDestinationVerb:
    def test_save_list_resolve(self, runner: CliRunner, tmp_path: Path) -> None:
        db = tmp_path / "db.sqlite"
        dest = tmp_path / "nas"
        dest.mkdir()

        saved = _json_call(
            runner, db, ["destination", "save", "--name", "NAS", "--path", str(dest)]
        )
        assert saved["name"] == "NAS"
        assert saved["lastRootPath"] == str(dest)

        listed = _json_call(runner, db, ["destination", "list"])
        assert [d["id"] for d in listed] == [saved["id"]]

        resolved = _json_call(runner, db, ["destination", "resolve"])
        assert len(resolved) == 1
        assert resolved[0]["destinationId"] == saved["id"]


class TestPresetVerb:
    def test_save_and_list_revisions(self, runner: CliRunner, tmp_path: Path) -> None:
        db = tmp_path / "db.sqlite"
        first = _json_call(
            runner,
            db,
            ["preset", "save", "--name", "Portable", "--fallback-template", "Sources/{filename}"],
        )
        assert first["revision"] == 1
        second = _json_call(
            runner,
            db,
            ["preset", "save", "--name", "Portable", "--fallback-template", "Other/{filename}"],
        )
        assert second["presetId"] == first["presetId"]
        assert second["revision"] == 2

        listed = _json_call(runner, db, ["preset", "list", "--preset-id", str(first["presetId"])])
        assert listed["total"] == 2
        assert {r["revision"] for r in listed["revisions"]} == {1, 2}


class TestInventoryVerb:
    def test_create_waits_and_status_inspects(self, runner: CliRunner, tmp_path: Path) -> None:
        db = tmp_path / "db.sqlite"
        src = tmp_path / "card"
        (src / "DCIM").mkdir(parents=True)
        (src / "DCIM" / "A001.MOV").write_bytes(b"media")

        created = _json_call(
            runner, db, ["inventory", "create", "--path", str(src), "--label", "C"]
        )
        assert created["status"] == "complete"
        assert created["fileCount"] == 1

        status = _json_call(runner, db, ["inventory", "status", str(created["id"])])
        assert status["fileCount"] == 1


class TestTransferFlow:
    def test_scan_to_receipt_over_the_cli(self, runner: CliRunner, tmp_path: Path) -> None:
        """scan -> destination -> preset -> plan -> preflight -> approve -> transfer -> receipt."""
        db = tmp_path / "db.sqlite"
        src = tmp_path / "card"
        (src / "DCIM" / "100").mkdir(parents=True)
        (src / "DCIM" / "100" / "A001.MOV").write_bytes(b"movie-bytes")
        (src / "DCIM" / "100" / "A002.MOV").write_bytes(b"second-movie")
        (src / "notes.txt").write_bytes(b"notes")
        dst = tmp_path / "nas"
        dst.mkdir()

        inventory = _json_call(
            runner, db, ["inventory", "create", "--path", str(src), "--label", "Card"]
        )
        destination = _json_call(
            runner, db, ["destination", "save", "--name", "NAS", "--path", str(dst)]
        )
        preset = _json_call(
            runner,
            db,
            [
                "preset",
                "save",
                "--name",
                "Portable",
                "--fallback-template",
                "Sources/{source_label}/{relative_dir}/{filename}",
            ],
        )
        plan = _json_call(
            runner,
            db,
            [
                "plan",
                "create",
                "--destination-id",
                str(destination["id"]),
                "--inventory",
                str(inventory["id"]),
                "--preset-id",
                str(preset["presetId"]),
                "--preset-revision",
                str(preset["revision"]),
            ],
        )

        preflight = _json_call(runner, db, ["preflight", "run", plan["id"]])
        assert preflight["status"] == "passed"

        approved = _json_call(
            runner, db, ["plan", "approve", plan["id"], "--fingerprint", plan["fingerprint"]]
        )
        assert approved["status"] == "approved"

        started = _json_call(
            runner, db, ["transfer", "start", plan["id"], "--fingerprint", plan["fingerprint"]]
        )
        assert started["state"] == "succeeded"

        receipt = _json_call(runner, db, ["transfer", "receipt", plan["id"]])
        assert receipt["finalState"] == "succeeded"
        assert receipt["receipt"]["actual"]["committed"] == 3
        assert receipt["receipt"]["actual"]["failed"] == 0

        landed = sorted(str(p.relative_to(dst)) for p in dst.rglob("*") if p.is_file())
        assert landed == [
            "Sources/Card/DCIM/100/A001.MOV",
            "Sources/Card/DCIM/100/A002.MOV",
            "Sources/Card/notes.txt",
        ]
