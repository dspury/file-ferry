"""Asset service — stable media identity.

An asset is a stable identity for a piece of media (plan §6.3: a path
is a location, not an identity). An asset is observed from a scanned
source: source-relative path + size + mtime (+ checksum when available).
Re-scanning is idempotent by ``(source_id, source_relative_path)``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from media_mate.persistence.connection import transaction
from media_mate.persistence.repositories import assets as asset_repo
from media_mate.persistence.repositories.assets import AssetRow
from media_mate.service.protocol import (
    AssetSummary,
    SourceInventoryEntry,
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class AssetNotFoundError(KeyError):
    """Raised when a named asset does not exist."""


class AssetService:
    """Identity and inventory for media assets."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)

    def adopt_source(
        self,
        source_id: int,
        entries: list[SourceInventoryEntry],
    ) -> list[str]:
        """Create asset rows for a scanned source inventory.

        Idempotent per ``(source_id, source_relative_path)``. Returns the
        list of asset ids created or matched.
        """
        now = _now_iso()
        ids: list[str] = []
        with transaction(self._db_path) as conn:
            for entry in entries:
                existing = asset_repo.get_asset_by_path(conn, source_id, entry.path)
                if existing is not None:
                    ids.append(existing.id)
                    continue
                asset_id = str(uuid.uuid4())
                asset_repo.insert_asset(
                    conn,
                    AssetRow(
                        id=asset_id,
                        source_id=source_id,
                        source_relative_path=entry.path,
                        observed_size=entry.size,
                        observed_mtime=entry.mtime,
                        observed_checksum=None,
                        checksum_algo=None,
                        lifecycle_state="discovered",
                        media_kind=None,
                        probed_at=None,
                        first_seen_at=now,
                    ),
                )
                ids.append(asset_id)
        return ids

    def get(self, asset_id: str) -> AssetSummary:
        with transaction(self._db_path) as conn:
            row = asset_repo.get_asset(conn, asset_id)
        if row is None:
            raise AssetNotFoundError(asset_id)
        return self._to_model(row)

    def list(self, project_id: str | None = None) -> list[AssetSummary]:
        with transaction(self._db_path) as conn:
            rows = asset_repo.list_assets(conn, project_id)
        return [self._to_model(r) for r in rows]

    @staticmethod
    def _to_model(row: AssetRow) -> AssetSummary:
        return AssetSummary(
            id=row.id,
            sourceId=row.source_id,
            sourceRelativePath=row.source_relative_path,
            observedSize=row.observed_size,
            observedMtime=row.observed_mtime,
            lifecycleState=row.lifecycle_state,
            mediaKind=row.media_kind,
            firstSeenAt=row.first_seen_at,
        )
