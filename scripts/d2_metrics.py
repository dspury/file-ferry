#!/usr/bin/env python3
"""D-2 §12.2 storage-matrix collector.

The app records duration, sustained throughput and the sidecar's peak RSS in
the receipt (``transfer_runner._performance_block``). It cannot record, from
inside a run, the things a two-hour campaign needs over time: the throughput
*curve* and DB/job state sampled while work is in flight, and the peak memory
of *both* processes (the Electron main process as well as the sidecar). This
collector samples a running ferry from the outside — read-only — and writes a
timeline the operator attaches to the D-2 record.

It also checks receipt integrity independently: it recomputes the stored
receipt's sha256 and compares it with the ``receipt_hash`` the database holds,
and checks the exported file byte-for-byte against it.

Nothing here is part of the app. It requires no write access to the database
and keeps running if ferry restarts (it re-resolves the processes each tick).

usage:
    python scripts/d2_metrics.py --app-data ~/Library/Application\\ Support/ferry \\
        --interval 30 --out /tmp/d2-timeline.jsonl
    python scripts/d2_metrics.py --verify-receipt --db <path>/ferry.db
    python scripts/d2_metrics.py --self-test

Keep the output file, and the D-2 record, out of the repository: the timeline
carries execution ids and byte counts, not paths, but the record template's
free-text fields are where private addresses and filenames must not be typed.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# pure helpers (unit-tested in tests/test_d2_metrics.py)
# ---------------------------------------------------------------------------


def throughput(delta_bytes: int, delta_seconds: float) -> float | None:
    """Bytes per second between two samples, or None when time did not pass."""
    if delta_seconds <= 0:
        return None
    return delta_bytes / delta_seconds


def peak(values: list[float | int | None]) -> float | int | None:
    """The largest defined value, or None for an empty/all-None input."""
    defined = [v for v in values if v is not None]
    return max(defined) if defined else None


def summarize(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Peak RSS per process, peak and average throughput, over a timeline.

    Throughput is taken per execution between consecutive samples where the
    byte counter moved forward; a resume that re-reads a counter must not
    produce a negative or absurd rate, so only positive deltas count.
    """
    rss_names = ("sidecar_rss_bytes", "app_rss_bytes")
    per_exec: dict[str, list[tuple[float, int]]] = {}
    for sample in samples:
        t = sample.get("at_epoch")
        for ex in sample.get("executions", []):
            if t is None:
                continue
            per_exec.setdefault(ex["id"], []).append((t, ex.get("bytes_committed", 0)))

    rates: list[float] = []
    for points in per_exec.values():
        points.sort()
        for (t0, b0), (t1, b1) in itertools.pairwise(points):
            rate = throughput(b1 - b0, t1 - t0)
            if rate is not None and rate > 0:
                rates.append(rate)

    durations = [
        ex.get("duration_seconds")
        for s in samples
        for ex in s.get("executions", [])
        if ex.get("duration_seconds") is not None
    ]
    return {
        "samples": len(samples),
        "peak_rss_bytes": {name: peak([s.get(name) for s in samples]) for name in rss_names},
        "peak_throughput_bytes_per_second": peak(rates),
        "average_throughput_bytes_per_second": (sum(rates) / len(rates)) if rates else None,
        "sample_intervals": len(rates),
        "max_reported_duration_seconds": peak(durations),
    }


def receipt_hash_matches(receipt_json: str, receipt_hash: str) -> bool:
    """The stored receipt text hashes to the hash the database records."""
    return hashlib.sha256(receipt_json.encode("utf-8")).hexdigest() == receipt_hash


def export_matches(receipt_json: str, exported: bytes) -> bool:
    """The exported file is byte-for-byte the stored receipt text."""
    return exported == receipt_json.encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def independent_walk(receipt: dict[str, Any]) -> dict[str, Any]:
    """Compare source and destination *by content*, not by ferry's checksum.

    Uses the receipt only as the mapping (sourcePath -> destRoot/destRelPath),
    then hashes both sides with sha256. Ferry's own xxhash64 result is the
    claim; this is the evidence. Directory entries have no content to compare
    and are counted separately.
    """
    dest_root = Path(receipt.get("destination", {}).get("destRoot", ""))
    results: list[dict[str, str]] = []
    directories = 0
    planned: set[str] = set()
    for entry in receipt.get("entries", []):
        if entry.get("state") != "committed":
            continue
        rel = entry.get("destRelPath")
        source = Path(entry.get("sourcePath", ""))
        if rel is None or not source.exists() or source.is_dir():
            directories += 1
            continue
        planned.add(rel)
        dest = dest_root / rel
        if not dest.exists():
            results.append({"dest_rel": rel, "status": "missing-at-destination"})
        elif sha256_file(source) == sha256_file(dest):
            results.append({"dest_rel": rel, "status": "verified-identical"})
        else:
            results.append({"dest_rel": rel, "status": "MISMATCH"})
    extras = []
    if dest_root.exists():
        extras = [
            str(p.relative_to(dest_root))
            for p in dest_root.rglob("*")
            if p.is_file() and str(p.relative_to(dest_root)) not in planned
        ]
    tally: dict[str, int] = {}
    for r in results:
        tally[r["status"]] = tally.get(r["status"], 0) + 1
    return {"tally": tally, "directories": directories, "extra": extras, "results": results}


def item_checksums_present(entry: dict[str, Any]) -> bool:
    """A committed entry carries both checksums and they agree.

    ``None`` for anything that is not a committed file entry, so a directory
    or an excluded row is not counted as an integrity failure.
    """
    if entry.get("state") != "committed":
        return True
    source, dest = entry.get("sourceChecksum"), entry.get("destChecksum")
    if source is None and dest is None:
        return True  # a directory entry has no checksum to compare
    return source is not None and dest is not None and source == dest


# ---------------------------------------------------------------------------
# host probing
# ---------------------------------------------------------------------------


def rss_bytes(pid: int | None) -> int | None:
    if pid is None:
        return None
    try:
        out = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        return int(out) * 1024 if out else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def find_pid(pattern: str) -> int | None:
    """The first pid whose command line contains ``pattern``, or None."""
    try:
        out = subprocess.run(
            ["pgrep", "-f", pattern], capture_output=True, text=True, timeout=5
        ).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return None
    for token in out:
        if token.isdigit():
            return int(token)
    return None


def db_path_from_args(args: argparse.Namespace) -> Path:
    if args.db:
        return Path(args.db).expanduser()
    if args.app_data:
        return Path(args.app_data).expanduser() / "ferry.db"
    raise SystemExit("give --db or --app-data")


# ---------------------------------------------------------------------------
# database sampling (read-only)
# ---------------------------------------------------------------------------


def _connect_ro(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def sample_executions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT e.id AS id,
               e.plan_id AS plan_id,
               e.state AS state,
               e.started_at AS started_at,
               e.updated_at AS updated_at,
               COUNT(i.plan_entry_id) AS ledger_entries,
               COALESCE(SUM(i.bytes_copied), 0) AS bytes_committed,
               COALESCE(SUM(CASE WHEN i.state = 'committed' THEN 1 ELSE 0 END), 0) AS items_committed,
               COALESCE(SUM(CASE WHEN i.state = 'committed'
                                  AND i.source_checksum IS NULL
                                  AND i.dest_checksum IS NULL
                             THEN 1 ELSE 0 END), 0) AS items_committed_directories,
               COALESCE(SUM(CASE WHEN i.state = 'failed' THEN 1 ELSE 0 END), 0) AS items_failed
        FROM transfer_executions e
        LEFT JOIN transfer_execution_items i ON i.execution_id = e.id
        GROUP BY e.id
        ORDER BY e.started_at ASC
        """
    ).fetchall()
    out = []
    for r in rows:
        duration = None
        started = _parse(r["started_at"])
        if started is not None:
            updated = _parse(r["updated_at"]) or started
            if r["state"] in {"succeeded", "failed", "cancelled", "needs_attention"}:
                duration = (updated - started).total_seconds()
            else:
                duration = (time.time() - started).total_seconds()
        out.append(
            {
                "id": r["id"],
                "plan_id": r["plan_id"],
                "state": r["state"],
                "bytes_committed": r["bytes_committed"],
                # `committed` counts files and directories; split them so a
                # byte/file count is not read against a mixed total (#207).
                "items_committed": r["items_committed"],
                "files_committed": r["items_committed"] - r["items_committed_directories"],
                "directories_committed": r["items_committed_directories"],
                "items_failed": r["items_failed"],
                "ledger_entries": r["ledger_entries"],
                "started_at": r["started_at"],
                "updated_at": r["updated_at"],
                "duration_seconds": duration,
            }
        )
    return out


def _parse(stamp: str | None) -> float | None:
    if not stamp:
        return None
    from datetime import datetime

    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# receipt integrity
# ---------------------------------------------------------------------------


def verify_receipts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT execution_id, receipt_json, receipt_hash, exported_path FROM transfer_receipts"
    ).fetchall()
    report = []
    for r in rows:
        receipt_json = r["receipt_json"]
        entry = {
            "execution_id": r["execution_id"],
            "hash_matches": receipt_hash_matches(receipt_json, r["receipt_hash"]),
            "exported_path_present": r["exported_path"] is not None,
        }
        try:
            body = json.loads(receipt_json)
        except ValueError:
            body = {}
        entries = body.get("entries", [])
        committed = [e for e in entries if e.get("state") == "committed"]
        entry["ledger_entries"] = len(entries)
        entry["committed_entries"] = len(committed)
        entry["entries_with_matching_checksums"] = sum(
            1 for e in committed if item_checksums_present(e)
        )
        entry["entries_missing_or_mismatched_checksums"] = (
            len(committed) - entry["entries_with_matching_checksums"]
        )
        if r["exported_path"]:
            path = Path(r["exported_path"])
            if path.exists():
                entry["export_matches"] = export_matches(receipt_json, path.read_bytes())
            else:
                entry["export_matches"] = None
                entry["export_missing"] = True
        report.append(entry)
    return report


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------


def verify_destinations(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Independent content walk of every succeeded receipt's destination."""
    rows = conn.execute(
        "SELECT execution_id, receipt_json FROM transfer_receipts WHERE final_state = 'succeeded'"
    ).fetchall()
    out = []
    for r in rows:
        try:
            receipt = json.loads(r["receipt_json"])
        except ValueError:
            continue
        walk = independent_walk(receipt)
        failures = [x for x in walk["results"] if x["status"] != "verified-identical"]
        out.append(
            {
                "execution_id": r["execution_id"],
                "tally": walk["tally"],
                "directories": walk["directories"],
                "extra_count": len(walk["extra"]),
                "failures": failures[:50],
                "extra": walk["extra"][:50],
            }
        )
    return out


def self_test() -> int:
    assert throughput(100, 2) == 50
    assert throughput(100, 0) is None
    assert peak([1, None, 3]) == 3
    assert peak([]) is None
    assert receipt_hash_matches('{"a":1}', hashlib.sha256(b'{"a":1}').hexdigest())
    assert not receipt_hash_matches('{"a":1}', "deadbeef")
    assert item_checksums_present(
        {"state": "committed", "sourceChecksum": "x", "destChecksum": "x"}
    )
    assert not item_checksums_present(
        {"state": "committed", "sourceChecksum": "x", "destChecksum": "y"}
    )
    assert item_checksums_present(
        {"state": "excluded", "sourceChecksum": None, "destChecksum": None}
    )
    summary = summarize(
        [
            {
                "at_epoch": 0,
                "sidecar_rss_bytes": 10,
                "executions": [{"id": "e", "bytes_committed": 0}],
            },
            {
                "at_epoch": 1,
                "sidecar_rss_bytes": 20,
                "executions": [{"id": "e", "bytes_committed": 100}],
            },
        ]
    )
    assert summary["peak_rss_bytes"]["sidecar_rss_bytes"] == 20
    assert summary["peak_throughput_bytes_per_second"] == 100
    print("self-test ok")
    return 0


def sample_loop(args: argparse.Namespace) -> int:
    db = db_path_from_args(args)
    out = Path(args.out).expanduser()
    samples: list[dict[str, Any]] = []
    sidecar_pattern = args.sidecar_pattern
    app_pattern = args.app_pattern
    deadline = None if args.duration <= 0 else time.monotonic() + args.duration

    def tick() -> None:
        try:
            conn = _connect_ro(db)
            try:
                executions = sample_executions(conn)
            finally:
                conn.close()
        except sqlite3.Error as exc:
            executions = []
            print(f"[d2] database not readable yet: {exc}", file=sys.stderr)
        sidecar_pid = find_pid(sidecar_pattern)
        app_pid = find_pid(app_pattern)
        sample = {
            "at_epoch": time.time(),
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "sidecar_pid": sidecar_pid,
            "app_pid": app_pid,
            "sidecar_rss_bytes": rss_bytes(sidecar_pid),
            "app_rss_bytes": rss_bytes(app_pid),
            "executions": executions,
        }
        samples.append(sample)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(sample, sort_keys=True) + "\n")
        active = ", ".join(f"{e['id'][:8]}:{e['state']}:{e['bytes_committed']}" for e in executions)
        print(f"[d2] {sample['at']} sidecar_rss={sample['sidecar_rss_bytes']} {active}")

    print(
        f"[d2] sampling every {args.interval}s for "
        f"{'until interrupted' if deadline is None else f'{args.duration}s'} -> {out}"
    )
    try:
        while True:
            tick()
            if deadline is not None and time.monotonic() >= deadline:
                break
            time.sleep(max(0.2, args.interval))
    except KeyboardInterrupt:
        print("\n[d2] interrupted; writing summary", file=sys.stderr)

    summary = summarize(samples)
    out.with_suffix(out.suffix + ".summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="D-2 storage-matrix collector")
    parser.add_argument("--db", help="ferry DB path")
    parser.add_argument("--app-data", help="ferry application-data directory (contains ferry.db)")
    parser.add_argument("--interval", type=float, default=30.0, help="seconds between samples")
    parser.add_argument(
        "--duration", type=float, default=0.0, help="seconds to sample; 0 = until Ctrl-C"
    )
    parser.add_argument("--out", default="/tmp/d2-timeline.jsonl", help="timeline output (JSONL)")
    parser.add_argument(
        "--sidecar-pattern", default="ferry-service", help="pgrep pattern for the sidecar"
    )
    parser.add_argument(
        "--app-pattern", default="ferry.app/Contents/MacOS/ferry", help="pgrep pattern for the app"
    )
    parser.add_argument(
        "--verify-receipt", action="store_true", help="check receipt integrity and exit"
    )
    parser.add_argument(
        "--verify-destination",
        action="store_true",
        help="independently hash source vs destination for every succeeded receipt and exit",
    )
    parser.add_argument(
        "--self-test", action="store_true", help="run the pure-helper self-test and exit"
    )
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()
    if args.verify_destination:
        db = db_path_from_args(args)
        conn = _connect_ro(db)
        try:
            report = verify_destinations(conn)
        finally:
            conn.close()
        print(json.dumps(report, indent=2))
        return 1 if any(r["failures"] or r["extra"] for r in report) else 0
    if args.verify_receipt:
        db = db_path_from_args(args)
        conn = _connect_ro(db)
        try:
            report = verify_receipts(conn)
        finally:
            conn.close()
        print(json.dumps(report, indent=2))
        bad = [r for r in report if not r["hash_matches"] or r.get("export_matches") is False]
        return 1 if bad else 0
    return sample_loop(args)


if __name__ == "__main__":
    raise SystemExit(main())
