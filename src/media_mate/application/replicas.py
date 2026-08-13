"""Replica service and the safe-to-format gate (ADR-0004).

A *replica* is one physical location of one asset. It is *verified*
only when the source and destination checksums agree under a
receipt-recorded algorithm. A failed verification never overwrites a
prior verified baseline ("no silent baseline replacement").

The :func:`evaluate_gate` function is the pure ADR-0004 safe-to-format
gate. The service wraps the verification primitives; the intake service
drives the gate over a session's assets and destinations.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from media_mate.application.policies import StoragePolicy
from media_mate.persistence.connection import transaction
from media_mate.persistence.repositories import replicas as replica_repo
from media_mate.service.protocol import ReplicaSummary, VerifyReplicaResult


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class ReplicaNotFoundError(KeyError):
    """Raised when a named replica does not exist."""


def compute_checksum(path: Path, algo: str) -> str:
    """Compute a full-file checksum with the configured algorithm."""
    algo_lower = algo.lower()
    h: Any
    if algo_lower == "sha256":
        h = hashlib.sha256()
    elif algo_lower == "xxhash64":
        import xxhash

        h = xxhash.xxh64()
    else:
        raise ValueError(f"unsupported checksum algorithm: {algo}")

    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return cast(str, h.hexdigest())


@dataclass(frozen=True)
class SafeToFormatResult:
    """The outcome of the safe-to-format gate."""

    safe: bool
    unmet: list[str]


def evaluate_gate(
    *,
    policy: StoragePolicy,
    required_destinations: list[str],
    verified_destination_kinds: set[str],
    source_readable_at: str | None,
    needs_attention_open: bool,
    uncertain_warning: bool,
    replica_metadata_ok: bool,
) -> SafeToFormatResult:
    """Evaluate the ADR-0004 safe-to-format gate (conditions 1-5).

    The gate is satisfied only when ALL conditions hold; the returned
    ``unmet`` list names exactly which conditions failed so the UI can
    show the unmet reasons rather than a green bar.
    """
    unmet: list[str] = []

    missing = [kind for kind in required_destinations if kind not in verified_destination_kinds]
    if missing:
        unmet.append(f"missing verified replica in required destination: {', '.join(missing)}")

    if source_readable_at is None:
        unmet.append("source was never verified readable")

    if needs_attention_open:
        unmet.append("an open needs-attention job references this source")

    if uncertain_warning:
        unmet.append("an uncertain warning is open (possible continued write to source)")

    if not replica_metadata_ok:
        unmet.append("required checksum metadata is missing on a replica")

    return SafeToFormatResult(safe=not unmet, unmet=unmet)


class ReplicaService:
    """Verification primitives for replicas."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)

    def verify(
        self,
        replica_id: int,
        source_path: Path,
        algo: str,
    ) -> VerifyReplicaResult:
        """Verify a replica against its source file.

        Computes the source and destination checksums, records the
        attempt, and never overwrites a prior verified baseline on
        failure.
        """
        with transaction(self._db_path) as conn:
            row = replica_repo.get_replica(conn, replica_id)
            if row is None:
                raise ReplicaNotFoundError(replica_id)
            dest = Path(row.path)
            source_checksum = compute_checksum(source_path, algo)
            if dest.exists():
                replica_checksum = compute_checksum(dest, algo)
                verified = source_checksum == replica_checksum
            else:
                replica_checksum = ""
                verified = False
            now = _now_iso()
            replica_repo.record_verification_attempt(
                conn,
                replica_id,
                checksum=replica_checksum or None,
                algo=algo,
                source_checksum=source_checksum,
                verified=verified,
                verified_at=now,
                size=_size_or_none(dest),
                availability="present" if dest.exists() else "missing",
                last_checked_at=now,
            )
        return VerifyReplicaResult(
            replicaId=replica_id,
            verified=verified,
            checksumAlgo=algo,
            sourceChecksum=source_checksum,
            replicaChecksum=replica_checksum,
        )

    def record_verified(
        self,
        asset_id: str,
        project_id: str,
        path: str,
        *,
        checksum: str,
        algo: str,
        source_checksum: str,
    ) -> int:
        """Record a verified replica, updating an existing (asset, path) row.

        Used by the offload engine after a successful copy+verify so a
        re-run updates rather than duplicates the replica for a location.
        """
        now = _now_iso()
        with transaction(self._db_path) as conn:
            existing = conn.execute(
                "SELECT id FROM replicas WHERE asset_id = ? AND path = ?",
                (asset_id, path),
            ).fetchone()
            if existing is not None:
                replica_repo.record_verification_attempt(
                    conn,
                    int(existing["id"]),
                    checksum=checksum,
                    algo=algo,
                    source_checksum=source_checksum,
                    verified=True,
                    verified_at=now,
                    size=_size_or_none(Path(path)),
                    availability="present" if Path(path).exists() else "missing",
                    last_checked_at=now,
                )
                return int(existing["id"])
            return self.record(
                asset_id,
                project_id,
                path,
                checksum=checksum,
                algo=algo,
                source_checksum=source_checksum,
                verified=True,
            )

    def list(self, asset_id: str) -> list[ReplicaSummary]:
        with transaction(self._db_path) as conn:
            rows = replica_repo.list_replicas(conn, asset_id)
        return [
            ReplicaSummary(
                id=r.id,
                assetId=r.asset_id,
                projectId=r.project_id,
                path=r.path,
                checksum=r.checksum,
                checksumAlgo=r.checksum_algo,
                verified=bool(r.verified),
                verifiedAt=r.verified_at,
                availability=r.availability,
            )
            for r in rows
        ]

    def record(
        self,
        asset_id: str,
        project_id: str,
        path: str,
        *,
        checksum: str,
        algo: str,
        source_checksum: str,
        verified: bool,
    ) -> int:
        """Record an already-established replica (e.g. adopted copy)."""
        now = _now_iso()
        with transaction(self._db_path) as conn:
            replica_id = replica_repo.insert_replica(
                conn,
                replica_repo.ReplicaRow(
                    id=0,
                    asset_id=asset_id,
                    project_id=project_id,
                    path=path,
                    volume_fingerprint=None,
                    size=_size_or_none(Path(path)),
                    checksum=checksum,
                    checksum_algo=algo,
                    verified=1 if verified else 0,
                    verified_at=now if verified else None,
                    source_checksum=source_checksum,
                    availability="present" if Path(path).exists() else "missing",
                    last_checked_at=now,
                ),
            )
        return replica_id


def _size_or_none(path: Path) -> int | None:
    try:
        return int(path.stat().st_size)
    except OSError:
        return None
