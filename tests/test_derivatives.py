"""Derivative service tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ferry.application.derivatives import DerivativeService


def _service(tmp_path: Path) -> DerivativeService:
    from ferry.application.service import ApplicationService

    db = tmp_path / "ferry.db"
    boot = ApplicationService(db_path=db, app_data_dir=tmp_path / "app")
    boot.bootstrap()
    boot.close()
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO assets (id, source_relative_path, first_seen_at) "
            "VALUES ('asset-1', 'clip.mov', 'now')"
        )
        conn.commit()
    return DerivativeService(db_path=db)


def test_record_and_list(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    svc.record(
        asset_id="asset-1",
        kind="proxy",
        output_path="/tmp/proxies/clip_proxy.mov",
        settings_fingerprint="fp1",
        status="ready",
        readiness=1.0,
    )
    derivs = svc.list("asset-1")
    assert len(derivs) == 1
    assert derivs[0].kind == "proxy"
    assert derivs[0].status == "ready"
    assert derivs[0].readiness == 1.0


def test_record_upserts_same_path(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    svc.record(
        asset_id="asset-1",
        kind="proxy",
        output_path="/tmp/p.mov",
        settings_fingerprint="fp",
        status="pending",
        readiness=0.0,
    )
    svc.update(
        asset_id="asset-1", kind="proxy", output_path="/tmp/p.mov", status="ready", readiness=1.0
    )
    derivs = svc.list("asset-1")
    assert len(derivs) == 1  # not duplicated
    assert derivs[0].status == "ready"


def test_record_distinct_paths_are_separate(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    svc.record(
        asset_id="asset-1",
        kind="proxy",
        output_path="/tmp/a.mov",
        settings_fingerprint="fp",
        status="ready",
        readiness=1.0,
    )
    svc.record(
        asset_id="asset-1",
        kind="proxy",
        output_path="/tmp/b.mov",
        settings_fingerprint="fp",
        status="failed",
        readiness=0.0,
    )
    assert len(svc.list("asset-1")) == 2
