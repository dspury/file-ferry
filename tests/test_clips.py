"""Logical-clip detection (plan §6.2, §7.3)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ferry.application.clips import ClipService, clip_key, detect_groups
from ferry.application.service import ApplicationService


def test_clip_key_strips_number_run() -> None:
    assert clip_key("A001_C001_01.mov") == "A001_C001"
    assert clip_key("CLIP.002.mov") == "CLIP"
    assert clip_key("Interview_05.mov") == "Interview"
    assert clip_key("standalone.mov") == "standalone"


def test_detect_groups_groups_spanned() -> None:
    groups = detect_groups(["A001_C001_01.mov", "A001_C001_02.mov", "A001_C001_03.mov", "solo.mov"])
    assert "A001_C001" in groups
    assert len(groups["A001_C001"]) == 3
    assert "solo.mov" not in groups  # single files are not clip groups


@pytest.fixture
def db(tmp_path: Path) -> Path:
    db = tmp_path / "ferry.db"
    boot = ApplicationService(db_path=db, app_data_dir=tmp_path / "app")
    boot.bootstrap()
    boot.close()
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO sources (kind, root_path, status, captured_at) "
            "VALUES ('card', '/tmp', 'scanned', 'now')"
        )
        conn.executemany(
            "INSERT INTO assets (id, source_id, source_relative_path, first_seen_at) "
            "VALUES (?, 1, ?, 'now')",
            [
                ("a1", "CLIP_01.mov"),
                ("a2", "CLIP_02.mov"),
                ("a3", "CLIP.srt"),  # sidecar
                ("a4", "SINGLE.mov"),  # no group
            ],
        )
        conn.commit()
    return db


def test_detect_persists_logical_clip(db: Path) -> None:
    svc = ClipService(db)
    clips = svc.detect(source_id=1)
    assert len(clips) == 1
    clip = clips[0]
    assert clip.clip_name == "CLIP"
    assert clip.confidence > 0
    member_roles = {m.role for m in clip.members}
    assert "primary" in member_roles
    assert "sidecar" in member_roles


def test_detect_is_idempotent(db: Path) -> None:
    svc = ClipService(db)
    svc.detect(source_id=1)
    clips = svc.detect(source_id=1)
    assert len(clips) == 1
    assert len(clips[0].members) == 3  # no duplicate members on re-detect


def test_list_returns_detected(db: Path) -> None:
    svc = ClipService(db)
    svc.detect(source_id=1)
    clips = svc.list(source_id=1)
    assert len(clips) == 1
    assert clips[0].clip_name == "CLIP"
