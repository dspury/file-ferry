"""Organization-profile service.

A named, versioned source-to-destination template plus a conflict and
mutation policy (plan §6.2 ``organization_profiles``). Saving a profile
with an existing name bumps its version rather than duplicating the
name.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from ferry.persistence.connection import transaction
from ferry.persistence.repositories import profiles as profile_repo
from ferry.persistence.repositories.profiles import ProfileRow
from ferry.service.protocol import (
    OrganizationProfile,
    SaveProfileParams,
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class ProfileNotFoundError(KeyError):
    """Raised when a named profile does not exist."""


class ProfileService:
    """CRUD for versioned organization profiles."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)

    def save(self, params: SaveProfileParams) -> OrganizationProfile:
        """Create a profile, or bump the version of an existing name."""
        now = _now_iso()
        template_json = json.dumps(params.template, sort_keys=True)
        with transaction(self._db_path) as conn:
            existing = profile_repo.get_profile_by_name(conn, params.name)
            if existing is None:
                profile_id = profile_repo.insert_profile(
                    conn,
                    ProfileRow(
                        id=0,
                        name=params.name,
                        version=1,
                        template=template_json,
                        conflict_policy=params.conflict_policy,
                        mutation_policy=params.mutation_policy,
                        created_at=now,
                        updated_at=now,
                    ),
                )
                row = profile_repo.get_profile(conn, profile_id)
            else:
                profile_repo.bump_version(
                    conn,
                    existing.id,
                    template=template_json,
                    conflict_policy=params.conflict_policy,
                    mutation_policy=params.mutation_policy,
                    version=existing.version + 1,
                    updated_at=now,
                )
                row = profile_repo.get_profile(conn, existing.id)
        assert row is not None
        return self._to_model(row)

    def get(self, profile_id: int) -> OrganizationProfile:
        with transaction(self._db_path) as conn:
            row = profile_repo.get_profile(conn, profile_id)
        if row is None:
            raise ProfileNotFoundError(profile_id)
        return self._to_model(row)

    def list(self) -> list[OrganizationProfile]:
        with transaction(self._db_path) as conn:
            rows = profile_repo.list_profiles(conn)
        return [self._to_model(r) for r in rows]

    @staticmethod
    def _to_model(row: ProfileRow) -> OrganizationProfile:
        try:
            template = json.loads(row.template)
        except json.JSONDecodeError:
            template = {}
        return OrganizationProfile(
            id=row.id,
            name=row.name,
            version=row.version,
            template=template,
            conflictPolicy=row.conflict_policy,
            mutationPolicy=row.mutation_policy,
            createdAt=row.created_at,
            updatedAt=row.updated_at,
        )
