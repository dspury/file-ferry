"""D-2 §12.2 collector — pure helpers and the receipt-integrity check.

The collector is a script, not a package module, so it is loaded by path. The
pure functions are what the D-2 record depends on: throughput arithmetic, peak
selection, and the receipt hash/export/checksum comparison.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path
from types import ModuleType

import pytest


def _load_collector() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts" / "d2_metrics.py"
    spec = importlib.util.spec_from_file_location("d2_metrics", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


metrics = _load_collector()


def test_throughput_guards_zero_time() -> None:
    assert metrics.throughput(100, 2) == 50
    assert metrics.throughput(100, 0) is None
    assert metrics.throughput(-5, 1) == -5  # callers filter sign; the helper does not lie


def test_peak_ignores_none_and_empties() -> None:
    assert metrics.peak([1, None, 3, 2]) == 3
    assert metrics.peak([None, None]) is None
    assert metrics.peak([]) is None


def test_summarize_reports_peak_rss_and_rates() -> None:
    samples = [
        {
            "at_epoch": 0.0,
            "sidecar_rss_bytes": 10,
            "app_rss_bytes": 100,
            "executions": [{"id": "e", "bytes_committed": 0}],
        },
        {
            "at_epoch": 2.0,
            "sidecar_rss_bytes": 40,
            "app_rss_bytes": 80,
            "executions": [{"id": "e", "bytes_committed": 200}],
        },
        {
            "at_epoch": 4.0,
            "sidecar_rss_bytes": 30,
            "app_rss_bytes": 90,
            "executions": [{"id": "e", "bytes_committed": 300, "duration_seconds": 4.0}],
        },
    ]
    summary = metrics.summarize(samples)
    assert summary["samples"] == 3
    assert summary["peak_rss_bytes"]["sidecar_rss_bytes"] == 40
    assert summary["peak_rss_bytes"]["app_rss_bytes"] == 100
    # Rates: 100 B/s then 50 B/s; peak 100, average 75.
    assert summary["peak_throughput_bytes_per_second"] == 100
    assert summary["average_throughput_bytes_per_second"] == 75
    assert summary["max_reported_duration_seconds"] == 4.0


def test_summarize_ignores_counters_that_move_backwards() -> None:
    """A resumed counter must not yield a negative or absurd rate."""
    samples = [
        {"at_epoch": 0.0, "executions": [{"id": "e", "bytes_committed": 500}]},
        {"at_epoch": 1.0, "executions": [{"id": "e", "bytes_committed": 100}]},
        {"at_epoch": 2.0, "executions": [{"id": "e", "bytes_committed": 300}]},
    ]
    summary = metrics.summarize(samples)
    assert summary["peak_throughput_bytes_per_second"] == 200
    assert summary["average_throughput_bytes_per_second"] == 200


def test_receipt_hash_matches_only_the_stored_text() -> None:
    text = json.dumps({"finalState": "succeeded"}, sort_keys=True)
    good = hashlib.sha256(text.encode()).hexdigest()
    assert metrics.receipt_hash_matches(text, good)
    assert not metrics.receipt_hash_matches(text + " ", good)
    assert not metrics.receipt_hash_matches(text, "deadbeef")


def test_export_matches_is_byte_for_byte() -> None:
    text = '{"a": 1}'
    assert metrics.export_matches(text, text.encode())
    assert not metrics.export_matches(text, (text + "\n").encode())


def test_item_checksums_present_classifies_entries() -> None:
    assert metrics.item_checksums_present(
        {"state": "committed", "sourceChecksum": "aa", "destChecksum": "aa"}
    )
    assert not metrics.item_checksums_present(
        {"state": "committed", "sourceChecksum": "aa", "destChecksum": "bb"}
    )
    # A committed directory has no checksum to compare; not a failure.
    assert metrics.item_checksums_present(
        {"state": "committed", "sourceChecksum": None, "destChecksum": None}
    )
    # A non-committed entry is not counted.
    assert metrics.item_checksums_present(
        {"state": "excluded", "sourceChecksum": None, "destChecksum": None}
    )


def test_verify_receipts_flags_bad_hash_and_bad_export(tmp_path: Path) -> None:
    receipt = json.dumps(
        {
            "finalState": "succeeded",
            "entries": [
                {"state": "committed", "sourceChecksum": "s", "destChecksum": "s"},
                {"state": "committed", "sourceChecksum": "s", "destChecksum": "x"},
                {"state": "excluded", "sourceChecksum": None, "destChecksum": None},
            ],
        }
    )
    good_hash = hashlib.sha256(receipt.encode()).hexdigest()
    exported = tmp_path / "export.json"
    exported.write_text(receipt, encoding="utf-8")
    mismatch_export = tmp_path / "mismatch.json"
    mismatch_export.write_text(receipt + " ", encoding="utf-8")

    db = tmp_path / "ferry.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE transfer_receipts (execution_id TEXT PRIMARY KEY, receipt_json TEXT, "
            "receipt_hash TEXT, exported_path TEXT)"
        )
        conn.execute(
            "INSERT INTO transfer_receipts VALUES (?, ?, ?, ?)",
            ("ok", receipt, good_hash, str(exported)),
        )
        # Correct text, wrong hash, and an export that differs from the text.
        conn.execute(
            "INSERT INTO transfer_receipts VALUES (?, ?, ?, ?)",
            ("bad", receipt, "0" * 64, str(mismatch_export)),
        )
        conn.commit()

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        report = {r["execution_id"]: r for r in metrics.verify_receipts(conn)}
    finally:
        conn.close()

    assert report["ok"]["hash_matches"] is True
    assert report["ok"]["export_matches"] is True
    assert report["ok"]["entries_with_matching_checksums"] == 1
    assert report["ok"]["entries_missing_or_mismatched_checksums"] == 1
    assert report["bad"]["hash_matches"] is False
    assert report["bad"]["export_matches"] is False


def test_independent_walk_matches_and_flags(tmp_path: Path) -> None:
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    (src / "a").mkdir(parents=True)
    (dst / "a").mkdir(parents=True)
    (src / "a" / "x.bin").write_bytes(b"hello")
    (dst / "a" / "x.bin").write_bytes(b"hello")
    (src / "a" / "y.bin").write_bytes(b"world")
    (dst / "a" / "y.bin").write_bytes(b"world!")  # differs
    (dst / "a" / "extra.bin").write_bytes(b"extra")  # residual

    receipt = {
        "destination": {"destRoot": str(dst)},
        "entries": [
            {
                "state": "committed",
                "sourcePath": str(src / "a" / "x.bin"),
                "destRelPath": "a/x.bin",
            },
            {
                "state": "committed",
                "sourcePath": str(src / "a" / "y.bin"),
                "destRelPath": "a/y.bin",
            },
            {"state": "committed", "sourcePath": str(src / "a"), "destRelPath": "a"},
            {"state": "excluded", "sourcePath": str(src / "a" / "z.bin"), "destRelPath": "a/z.bin"},
        ],
    }
    walk = metrics.independent_walk(receipt)
    assert walk["tally"] == {"verified-identical": 1, "MISMATCH": 1}
    assert walk["directories"] == 1
    assert walk["extra"] == ["a/extra.bin"]


@pytest.mark.parametrize("_", [0])
def test_collector_self_test_passes(_: int) -> None:
    assert metrics.self_test() == 0
