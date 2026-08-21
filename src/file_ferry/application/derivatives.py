"""Derivative service — per-asset proxy / derived output state.

Tracks proxy and later derived outputs per asset (plan §6.2
``derivatives``), making retries, staleness, and readiness visible. A
derivative is identified by ``(asset_id, kind, output_path)`` and can be
``pending`` -> ``ready`` or ``failed``; ``ready`` sets a 0..1 readiness.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from file_ferry.persistence.connection import transaction
from file_ferry.persistence.repositories import derivatives as deriv_repo
from file_ferry.service.protocol import DerivativeSummary


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class DerivativeService:
    """Record and update per-asset derivatives."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)

    def record(
        self,
        asset_id: str,
        *,
        kind: str,
        output_path: str,
        settings_fingerprint: str | None,
        status: str = "pending",
        readiness: float = 0.0,
    ) -> DerivativeSummary:
        """Record a derivative, updating an existing (asset, kind, path) row."""
        with transaction(self._db_path) as conn:
            existing = deriv_repo.get_derivative(conn, asset_id, kind, output_path)
            if existing is not None:
                deriv_repo.update_status(
                    conn,
                    asset_id,
                    kind,
                    output_path,
                    status=status,
                    readiness=int(readiness),
                )
            else:
                deriv_repo.insert_derivative(
                    conn,
                    deriv_repo.DerivativeRow(
                        id=0,
                        asset_id=asset_id,
                        kind=kind,
                        output_path=output_path,
                        settings_fingerprint=settings_fingerprint,
                        status=status,
                        readiness=int(readiness),
                        created_at=_now_iso(),
                    ),
                )
        return DerivativeSummary(
            id=0,
            assetId=asset_id,
            kind=kind,
            outputPath=output_path,
            settingsFingerprint=settings_fingerprint,
            status=status,
            readiness=readiness,
        )

    def update(
        self,
        asset_id: str,
        *,
        kind: str,
        output_path: str,
        status: str,
        readiness: float,
    ) -> DerivativeSummary:
        with transaction(self._db_path) as conn:
            deriv_repo.update_status(
                conn,
                asset_id,
                kind,
                output_path,
                status=status,
                readiness=int(readiness),
            )
        return DerivativeSummary(
            id=0,
            assetId=asset_id,
            kind=kind,
            outputPath=output_path,
            settingsFingerprint=None,
            status=status,
            readiness=readiness,
        )

    def list(self, asset_id: str) -> list[DerivativeSummary]:
        with transaction(self._db_path) as conn:
            rows = deriv_repo.list_for_asset(conn, asset_id)
        return [
            DerivativeSummary(
                id=r.id,
                assetId=r.asset_id,
                kind=r.kind,
                outputPath=r.output_path,
                settingsFingerprint=r.settings_fingerprint,
                status=r.status,
                readiness=float(r.readiness),
            )
            for r in rows
        ]
