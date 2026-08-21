"""Audit service — legacy runs backfill and event reads."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from media_mate.application.audit import AuditService
from media_mate.service.protocol import ListAuditParams


@pytest.fixture
def db(tmp_path: Path) -> Path:
    from media_mate.application.service import ApplicationService

    db = tmp_path / "media-mate.db"
    boot = ApplicationService(db_path=db, app_data_dir=tmp_path / "app")
    boot.bootstrap()
    boot.close()
    # Seed legacy runs (the v0.2.4 audit log).
    with sqlite3.connect(db) as conn:
        conn.executemany(
            """
            INSERT INTO runs (started_at, finished_at, command, config_hash, status, error)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                ("2026-08-01T10:00:00Z", "2026-08-01T10:05:00Z", "probe", "abc", "completed", None),
                ("2026-08-02T11:00:00Z", None, "organize", None, "running", None),
            ],
        )
        conn.commit()
    return db


def test_backfill_links_unambiguous_runs(db: Path) -> None:
    svc = AuditService(db)
    count = svc.backfill_legacy()
    assert count == 2

    events = svc.list(ListAuditParams())
    assert len(events) == 2
    assert {e.entity_type for e in events} == {"run"}
    assert {e.event_type for e in events} == {"run.completed", "run.running"}
    run_ids = {e.run_id for e in events}
    assert run_ids == {1, 2}


def test_backfill_is_idempotent(db: Path) -> None:
    svc = AuditService(db)
    assert svc.backfill_legacy() == 2
    assert svc.backfill_legacy() == 0  # nothing left to link


def test_list_filters_by_entity(db: Path) -> None:
    svc = AuditService(db)
    svc.backfill_legacy()
    events = svc.list(ListAuditParams(entityId="1"))
    assert len(events) == 1
    assert events[0].entity_id == "1"
    assert events[0].data["command"] == "probe"
