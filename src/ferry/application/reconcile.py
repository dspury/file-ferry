"""Reconciliation (plan §4.5, §7.5).

Reconciliation compares known replicas with the present filesystem state
without automatically changing the accepted baseline. It distinguishes
present+verified, present+changed, and missing replicas.

``accept_change`` acknowledges a changed replica by recording new
evidence and an audit event that preserves the prior baseline — it never
silently overwrites history (plan §7.5).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from ferry.application.replicas import compute_checksum
from ferry.persistence.connection import transaction
from ferry.persistence.repositories import replicas as replica_repo
from ferry.service.protocol import (
    ReconcileEntry,
    ReconcileReport,
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class ReconcileError(ValueError):
    """Raised when a reconciliation action cannot be completed."""


class ReconcileService:
    """Detect and acknowledge replica state changes."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)

    def reconcile_asset(self, asset_id: str, *, algo: str = "xxhash64") -> ReconcileReport:
        """Compare every replica of an asset with the present filesystem."""
        entries: list[ReconcileEntry] = []
        with transaction(self._db_path) as conn:
            for replica in replica_repo.list_replicas(conn, asset_id):
                entries.append(self._check_replica(conn, replica, algo))
        return ReconcileReport(assetId=asset_id, entries=entries)

    def reconcile_project(
        self, project_id: str, *, algo: str = "xxhash64"
    ) -> list[ReconcileReport]:
        """Reconcile every asset that has a replica in the project."""
        with transaction(self._db_path) as conn:
            asset_ids = [
                r["asset_id"]
                for r in conn.execute(
                    "SELECT DISTINCT asset_id FROM replicas WHERE project_id = ?",
                    (project_id,),
                ).fetchall()
            ]
        return [self.reconcile_asset(aid, algo=algo) for aid in asset_ids]

    def accept_change(self, asset_id: str, replica_id: int, *, algo: str) -> ReconcileReport:
        """Acknowledge a changed replica, recording new evidence + history.

        Computes the current file checksum, marks the replica verified with
        it, and appends an audit event that preserves the prior baseline.
        """
        now = _now_iso()
        with transaction(self._db_path) as conn:
            replica = replica_repo.get_replica(conn, replica_id)
            if replica is None:
                raise ReconcileError(f"replica not found: {replica_id}")
            path = Path(replica.path)
            if not path.exists():
                raise ReconcileError(f"replica file is missing: {path}")
            new_checksum = compute_checksum(path, algo)
            old_checksum = replica.checksum

            replica_repo.record_verification_attempt(
                conn,
                replica_id,
                checksum=new_checksum,
                algo=algo,
                source_checksum=replica.source_checksum or new_checksum,
                verified=True,
                verified_at=now,
                size=int(path.stat().st_size),
                availability="present",
                last_checked_at=now,
            )
            conn.execute(
                """
                INSERT INTO audit_events (occurred_at, event_type, entity_type, entity_id, data)
                VALUES (?, 'reconcile.accept_change', 'asset', ?, ?)
                """,
                (
                    now,
                    asset_id,
                    json.dumps(
                        {
                            "replica_id": replica_id,
                            "old_checksum": old_checksum,
                            "new_checksum": new_checksum,
                        },
                        sort_keys=True,
                    ),
                ),
            )
        return self.reconcile_asset(asset_id, algo=algo)

    # ---- helpers -----------------------------------------------------

    def _check_replica(
        self, conn: sqlite3.Connection, replica: replica_repo.ReplicaRow, algo: str
    ) -> ReconcileEntry:
        path = Path(replica.path)
        if not path.exists():
            return ReconcileEntry(
                replicaId=replica.id,
                path=replica.path,
                availability="missing",
                status="missing",
                expectedChecksum=replica.checksum,
                actualChecksum=None,
            )
        try:
            actual = compute_checksum(path, algo)
        except OSError:
            return ReconcileEntry(
                replicaId=replica.id,
                path=replica.path,
                availability="inaccessible",
                status="inaccessible",
                expectedChecksum=replica.checksum,
                actualChecksum=None,
            )
        status = "verified" if actual == replica.checksum else "changed"
        return ReconcileEntry(
            replicaId=replica.id,
            path=replica.path,
            availability="present",
            status=status,
            expectedChecksum=replica.checksum,
            actualChecksum=actual,
        )
