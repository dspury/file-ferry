"""Intake service — session + destinations + safe-to-format evaluation.

This is the Package 2 boundary for intake: it records an intake
session and its required/optional destinations, adopts a scanned
source into assets (with replicas), and evaluates the ADR-0004
safe-to-format gate. The copy engine and the planner (plan §7.1/§7.2)
land in Package 3/4 on top of these primitives.
"""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from media_mate.application.assets import AssetService
from media_mate.application.policies import StoragePolicy
from media_mate.application.replicas import ReplicaService, evaluate_gate
from media_mate.application.sources import _volume_fingerprint
from media_mate.persistence.connection import transaction
from media_mate.persistence.repositories import intake as intake_repo
from media_mate.persistence.repositories import projects as project_repo
from media_mate.persistence.repositories import sources as source_repo
from media_mate.persistence.repositories.intake import IntakeDestinationRow, IntakeSessionRow
from media_mate.service.protocol import (
    AddDestinationParams,
    CreateIntakeSessionParams,
    IntakeDestination,
    IntakeSession,
    SafeToFormatEval,
    SourceInventoryEntry,
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class IntakeSessionNotFoundError(KeyError):
    """Raised when a named intake session does not exist."""


class IntakeService:
    """Sessions, destinations, adoption, and the safe-to-format gate."""

    def __init__(
        self,
        db_path: Path,
        assets: AssetService,
        replicas: ReplicaService,
        *,
        # Injectable so tests can stub the filesystem check. ADR-0004
        # requires recomputing the source's volume fingerprint at the
        # end of the run so the gate can detect a card that was still
        # being written to during the offload.
        volume_fingerprint_of: Callable[[Path], str] | None = None,
    ) -> None:
        self._db_path = Path(db_path)
        self._assets = assets
        self._replicas = replicas
        self._volume_fingerprint_of = volume_fingerprint_of or _volume_fingerprint

    def _capture_volume_fingerprint(
        self, conn: sqlite3.Connection, source_id: int | None
    ) -> str | None:
        """Return the scan-time fingerprint of a source, or ``None``.

        Prefers the value already stored on the source row (the same
        value the scanner wrote); falls back to a live recompute if
        the source's row has no fingerprint yet (older DB).
        """
        if source_id is None:
            return None
        row = source_repo.get_source(conn, source_id)
        if row is None:
            return None
        if row.volume_fingerprint:
            return row.volume_fingerprint
        try:
            return self._volume_fingerprint_of(Path(row.root_path))
        except OSError:
            return None

    # ---- session + destinations --------------------------------------

    def create_session(self, params: CreateIntakeSessionParams) -> IntakeSession:
        now = _now_iso()
        session_id = str(uuid.uuid4())
        with transaction(self._db_path) as conn:
            if project_repo.get_project(conn, params.project_id) is None:
                from media_mate.application.projects import ProjectNotFoundError

                raise ProjectNotFoundError(params.project_id)
            # ADR-0004 condition (4): capture the source's volume
            # fingerprint at session-start so the gate can detect a
            # change later.
            fingerprint_at_scan = self._capture_volume_fingerprint(conn, params.source_id)
            row = IntakeSessionRow(
                id=session_id,
                project_id=params.project_id,
                source_id=params.source_id,
                kind=params.kind,
                plan_fingerprint=None,
                policy_fingerprint=None,
                status="planned",
                safe_to_format=0,
                source_readable_at=now,
                created_at=now,
                updated_at=now,
                completed_at=None,
                volume_fingerprint_at_scan=fingerprint_at_scan,
            )
            intake_repo.insert_session(conn, row)
        return self._to_session(row)

    def add_destination(self, params: AddDestinationParams) -> IntakeDestination:
        dest = IntakeDestinationRow(
            id=0,
            intake_session_id=params.intake_session_id,
            kind=params.kind,
            root_path=params.root_path,
            role=params.role,
            required=1 if params.required else 0,
            verified=0,
            verified_at=None,
        )
        with transaction(self._db_path) as conn:
            if intake_repo.get_session(conn, params.intake_session_id) is None:
                raise IntakeSessionNotFoundError(params.intake_session_id)
            intake_repo.insert_destination(conn, dest)
        return IntakeDestination(
            id=dest.id,
            intakeSessionId=params.intake_session_id,
            kind=params.kind,
            rootPath=params.root_path,
            role=params.role,
            required=params.required,
            verified=False,
        )

    # ---- adoption ----------------------------------------------------

    def get_session(self, session_id: str) -> IntakeSession:
        with transaction(self._db_path) as conn:
            row = intake_repo.get_session(conn, session_id)
        if row is None:
            raise IntakeSessionNotFoundError(session_id)
        return self._to_session(row)

    def get_destinations(self, session_id: str) -> list[IntakeDestination]:
        with transaction(self._db_path) as conn:
            if intake_repo.get_session(conn, session_id) is None:
                raise IntakeSessionNotFoundError(session_id)
            rows = intake_repo.list_destinations(conn, session_id)
        return [
            IntakeDestination(
                id=d.id,
                intakeSessionId=session_id,
                kind=d.kind,
                rootPath=d.root_path,
                role=d.role,
                required=bool(d.required),
                verified=bool(d.verified),
            )
            for d in rows
        ]

    def adopt_source(
        self,
        session_id: str,
        source_id: int,
        entries: list[SourceInventoryEntry],
        destination_root: str,
        *,
        project_id: str | None = None,
    ) -> list[str]:
        """Adopt a scanned source into the project: create assets and a
        replica for each entry under ``destination_root``.

        Returns the list of asset ids. The replicas are recorded as
        unverified; the copy engine verifies them later.
        """
        asset_ids = self._assets.adopt_source(source_id, entries)
        with transaction(self._db_path) as conn:
            session = intake_repo.get_session(conn, session_id)
            if session is None:
                raise IntakeSessionNotFoundError(session_id)
            pid = project_id or session.project_id
        for asset_id, entry in zip(asset_ids, entries, strict=True):
            self._replicas.record(
                asset_id,
                pid,
                str(Path(destination_root) / entry.path),
                checksum="",
                algo="xxhash64",
                source_checksum="",
                verified=False,
            )
        return asset_ids

    # ---- safe-to-format gate -----------------------------------------

    def evaluate(self, session_id: str) -> SafeToFormatEval:
        """Evaluate the ADR-0004 safe-to-format gate for a session.

        The session is safe only if EVERY asset in the session has a
        verified replica in every required destination, and all other
        gate conditions hold.
        """
        with transaction(self._db_path) as conn:
            session = intake_repo.get_session(conn, session_id)
            if session is None:
                raise IntakeSessionNotFoundError(session_id)
            project = project_repo.get_project(conn, session.project_id)
            policy = self._policy_of(project.storage_policy) if project else None
            destinations = intake_repo.list_destinations(conn, session_id)
            source_id = session.source_id
            assets = self._assets_for_source(conn, source_id) if source_id is not None else []
            needs_attention_open = self._needs_attention_open(conn, session_id)
            # ADR-0004 condition (4): compare the scan-time fingerprint
            # to a fresh recomputation on the source root. If the
            # fingerprint changed, the source may have continued to be
            # written during the offload and the gate should fail.
            uncertain_warning = self._fingerprint_changed(conn, session)

        if policy is None:
            return SafeToFormatEval(
                sessionId=session_id,
                safe=False,
                unmet=["project storage policy is missing"],
            )

        required_kinds = [d.kind for d in destinations if d.required]
        if not assets:
            return SafeToFormatEval(
                sessionId=session_id,
                safe=False,
                unmet=["session has no adopted assets to verify"],
            )

        aggregate_unmet: list[str] = []
        all_safe = True
        for asset_id in assets:
            verified_kinds = self._verified_destination_kinds(asset_id, destinations)
            meta_ok = self._replica_metadata_ok(asset_id)
            result = evaluate_gate(
                policy=policy,
                required_destinations=required_kinds,
                verified_destination_kinds=verified_kinds,
                source_readable_at=session.source_readable_at,
                needs_attention_open=needs_attention_open,
                uncertain_warning=uncertain_warning,
                replica_metadata_ok=meta_ok,
            )
            if not result.safe:
                all_safe = False
                aggregate_unmet.extend(result.unmet)

        return SafeToFormatEval(
            sessionId=session_id,
            safe=all_safe,
            unmet=_dedupe(aggregate_unmet),
        )

    def _fingerprint_changed(self, conn: sqlite3.Connection, session: IntakeSessionRow) -> bool:
        """Return True if the source's volume fingerprint changed since scan.

        Returns False for sessions whose source has no fingerprint at
        scan time (sessions that predate migration 003); the gate falls
        back to its pre-PR behavior in that case. Returns True if the
        source row is missing, because that is itself evidence of a
        state change we can't reason about.
        """
        if session.source_id is None:
            return False
        source = source_repo.get_source(conn, session.source_id)
        if source is None:
            return True
        at_scan = session.volume_fingerprint_at_scan
        if at_scan is None:
            return False
        # _volume_fingerprint returns the literal string "unknown" when
        # the path is stat-inaccessible. That will compare unequal to
        # any value observed at scan time, which is exactly the safe
        # answer for a card that was ejected mid-offload.
        current = self._volume_fingerprint_of(Path(source.root_path))
        return current != at_scan

    # ---- helpers -----------------------------------------------------

    def _verified_destination_kinds(
        self, asset_id: str, destinations: list[IntakeDestinationRow]
    ) -> set[str]:
        """Return the destination kinds that hold a verified replica of an asset."""
        kinds: set[str] = set()
        with transaction(self._db_path) as conn:
            replicas = [r for r in self._replicas_by_asset(conn, asset_id) if r["verified"] == 1]
            for dest in destinations:
                if any(r["path"].startswith(dest.root_path.rstrip("/") + "/") for r in replicas):
                    kinds.add(dest.kind)
        return kinds

    @staticmethod
    def _replicas_by_asset(conn: sqlite3.Connection, asset_id: str) -> list[sqlite3.Row]:
        return conn.execute("SELECT * FROM replicas WHERE asset_id = ?", (asset_id,)).fetchall()

    @staticmethod
    def _assets_for_source(conn: sqlite3.Connection, source_id: int) -> list[str]:
        rows = conn.execute("SELECT id FROM assets WHERE source_id = ?", (source_id,)).fetchall()
        return [r["id"] for r in rows]

    @staticmethod
    def _needs_attention_open(conn: sqlite3.Connection, session_id: str) -> bool:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE session_id = ? AND state = 'needs_attention'",
            (session_id,),
        ).fetchone()
        return int(row["n"]) > 0

    def _replica_metadata_ok(self, asset_id: str) -> bool:
        with transaction(self._db_path) as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM replicas WHERE asset_id = ? AND checksum_algo IS NULL",
                (asset_id,),
            ).fetchone()
            return int(row["n"]) == 0

    @staticmethod
    def _policy_of(storage_policy_json: str) -> StoragePolicy | None:
        try:
            return StoragePolicy.model_validate_json(storage_policy_json)
        except Exception:
            return None

    @staticmethod
    def _to_session(row: IntakeSessionRow) -> IntakeSession:
        return IntakeSession(
            id=row.id,
            projectId=row.project_id,
            sourceId=row.source_id,
            kind=row.kind,
            status=row.status,
            safeToFormat=bool(row.safe_to_format),
            createdAt=row.created_at,
            updatedAt=row.updated_at,
        )


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
