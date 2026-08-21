"""Operation receipt writer (ADR-0003 §6.5, ADR-0004)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from file_ferry.application.policies import default_policy
from file_ferry.application.receipts import ReceiptStore, build_receipt
from file_ferry.persistence.connection import open_connection, transaction


def test_receipt_hash_is_deterministic_and_path_independent() -> None:
    a = build_receipt(
        operation_id="op-1",
        kind="project",
        app_version="0.2.4",
        protocol_version=1,
        policy=default_policy(),
        planned=[{"action": "create_project"}],
        checksums=[{"algo": "xxhash64", "value": "abc"}],
        final_state="created",
    )
    b = build_receipt(
        operation_id="op-2",  # different id
        kind="project",
        app_version="0.2.4",
        protocol_version=1,
        policy=default_policy(),
        planned=[{"action": "create_project"}],
        checksums=[{"algo": "xxhash64", "value": "abc"}],
        final_state="created",
    )
    # Hash covers substance only — id/timestamps do not change it.
    assert a.receipt_hash() == b.receipt_hash()


def test_receipt_hash_changes_on_substance() -> None:
    a = build_receipt(
        operation_id="op-1",
        kind="project",
        app_version="0.2.4",
        protocol_version=1,
        final_state="created",
        planned=[{"action": "create_project"}],
    )
    b = build_receipt(
        operation_id="op-1",
        kind="project",
        app_version="0.2.4",
        protocol_version=1,
        final_state="created",
        planned=[{"action": "update_project"}],  # different planned op
    )
    assert a.receipt_hash() != b.receipt_hash()


def test_store_writes_file_and_row(tmp_path: Path) -> None:
    db = tmp_path / "db.sqlite"
    with open_connection(db) as conn:
        conn.executescript(
            """
            CREATE TABLE operation_receipts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                operation_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                receipt_json TEXT NOT NULL,
                receipt_hash TEXT NOT NULL,
                display_summary TEXT,
                receipt_path TEXT,
                export_version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                UNIQUE(operation_id, kind)
            )
            """
        )
    store = ReceiptStore(tmp_path / "app_data")
    receipt = build_receipt(
        operation_id="intake-1",
        kind="intake",
        app_version="0.2.4",
        protocol_version=1,
        final_state="completed",
    )
    with transaction(db) as conn:
        file_path = store.write(conn, receipt)

    assert file_path.exists()
    on_disk = json.loads(file_path.read_text(encoding="utf-8"))
    assert on_disk["operationId"] == "intake-1"
    assert on_disk["finalState"] == "completed"

    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT operation_id, kind, receipt_hash, receipt_path, export_version "
            "FROM operation_receipts WHERE operation_id = 'intake-1'"
        ).fetchone()
        assert row is not None
        assert row["kind"] == "intake"
        assert row["export_version"] == 1
        # The stored hash equals the computed receipt hash.
        assert row["receipt_hash"] == receipt.receipt_hash()
