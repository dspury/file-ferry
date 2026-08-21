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
        for cmd in ("project", "source", "intake", "jobs", "receipt", "reconcile"):
            assert cmd in result.output
