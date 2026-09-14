"""Organization-profile service.

A named, versioned source-to-destination template plus a conflict and
mutation policy (plan §6.2 ``organization_profiles``). Saving a profile
with an existing name bumps its version rather than duplicating the
name.

Since the destination-presets work this is no longer the only writer of
profile identity: ``profile.saveRevision`` appends immutable revisions
to the same presets. A legacy save that advanced the profile version
without writing its matching revision left the two histories diverged —
a destination pinned to "the current revision" would then be pinned to
content that no longer described the profile. So every legacy save now
writes its revision too, through the one shared conversion in
``application/preset_compat.py``, at a version number derived from both
sides (spec §4.2, R07).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from file_ferry.application.preset_compat import (
    canonical_revision_payload,
    convert_legacy_template,
    sha256_text,
)
from file_ferry.persistence.connection import transaction
from file_ferry.persistence.repositories import preset_revisions as revision_repo
from file_ferry.persistence.repositories import profiles as profile_repo
from file_ferry.persistence.repositories.preset_revisions import PresetRevisionRow
from file_ferry.persistence.repositories.profiles import ProfileRow
from file_ferry.service.protocol import (
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
        """Create a profile, or bump the version of an existing name.

        The version bump and its immutable revision are written in one
        transaction: the legacy template and the revision history can
        never be observed disagreeing about what version N contains.
        """
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
                version = 1
            else:
                profile_id = existing.id
                # Monotonic across both writers — never just this side's
                # own counter (spec §4.2).
                version = max(existing.version, revision_repo.max_revision(conn, profile_id)) + 1
                profile_repo.bump_version(
                    conn,
                    profile_id,
                    template=template_json,
                    conflict_policy=params.conflict_policy,
                    mutation_policy=params.mutation_policy,
                    version=version,
                    updated_at=now,
                )
            _write_legacy_revision(
                conn,
                preset_id=profile_id,
                name=params.name,
                version=version,
                template=params.template,
                conflict_policy=params.conflict_policy,
                now=now,
            )
            row = profile_repo.get_profile(conn, profile_id)
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


def _write_legacy_revision(
    conn: sqlite3.Connection,
    *,
    preset_id: int,
    name: str,
    version: int,
    template: dict[str, Any],
    conflict_policy: str,
    now: str,
) -> None:
    """Append the immutable revision that matches a legacy profile save.

    The conversion is the shared one, so a legacy save and the migration
    produce identical content for identical input. Whatever the schema
    cannot express — unknown template keys, a legacy conflict policy
    with no safe equivalent — is recorded as blocking review evidence
    rather than dropped, and the original template is kept verbatim.
    """
    fallback, mapped_policy, review = convert_legacy_template(template, conflict_policy)
    payload = canonical_revision_payload(
        description=f"converted from legacy profile save at version {version}",
        rules=[],
        groups=[],
        fallback_template=fallback,
        conflict_policy=mapped_policy,
        exclusions=[],
        review=review,
    )
    revision_repo.insert_revision(
        conn,
        PresetRevisionRow(
            id=0,
            preset_id=preset_id,
            revision=version,
            name=name,
            description=f"converted from legacy profile save at version {version}",
            rules_json="[]",
            groups_json="[]",
            fallback_template=fallback,
            conflict_policy=mapped_policy,
            exclusions_json="[]",
            review_json=json.dumps(review, sort_keys=True, separators=(",", ":")),
            legacy_template_json=json.dumps(template, sort_keys=True, separators=(",", ":")),
            schema_version=1,
            content_hash=sha256_text(payload),
            created_at=now,
        ),
    )
