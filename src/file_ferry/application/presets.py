"""Preset revisions — immutable, portable organization presets (spec §4.2).

A preset revision is an immutable snapshot: saving edits creates a new
revision with a monotonically increasing number and a content hash.
Destinations stay pinned to the revision they were saved with until the
user chooses an update. Portable JSON export/import covers presets only
— no absolute paths, no destination identities — and importing creates
a new local identity rather than overwriting anything.

The rule *engine* (match semantics, keep-together groups, category map)
is the P4 deliverable; this service owns storage, immutability, shape
validation, and portability, and rejects unknown template tokens with
field-specific errors so an invalid revision never becomes pinnable.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from file_ferry.application.preset_compat import (
    convert_legacy_template,
    legacy_root_prefix,
)
from file_ferry.application.rules import GROUP_TEMPLATE_TOKENS
from file_ferry.persistence.connection import transaction
from file_ferry.persistence.repositories import preset_revisions as revision_repo
from file_ferry.persistence.repositories import profiles as profile_repo
from file_ferry.persistence.repositories.preset_revisions import PresetRevisionRow
from file_ferry.persistence.repositories.profiles import ProfileRow
from file_ferry.service.protocol import (
    PresetContent,
    PresetExportResult,
    PresetRevisionSummary,
    SavePresetRevisionParams,
)

PRESET_SCHEMA_VERSION = 1

#: The two starting points a user picks between (spec §6.2). Both are
#: general: neither encodes a NAS layout, a vendor, or anyone's personal
#: taxonomy. "Preserve" is the safe default — it changes nothing about
#: how the files are arranged, so a transfer is only ever a copy.
BUILTIN_PRESETS: dict[str, dict[str, object]] = {
    "preserve-source-structure": {
        "name": "Preserve source structure",
        "description": (
            "Copies everything under a folder named for each source, keeping the "
            "original folder layout exactly as it is."
        ),
        "fallbackTemplate": "Sources/{source_label}/{relative_dir}/{filename}",
        "conflictPolicy": "keep_both",
        "rules": [],
        "groups": [],
    },
    "sort-by-category": {
        "name": "Sort loose files by category",
        "description": (
            "Sorts files into Video, Audio, Images, Documents and Archives by file "
            "extension. This is extension classification, not content inspection: a "
            "file's contents are never examined. Anything unrecognized goes to "
            "Unsorted rather than being guessed at."
        ),
        "fallbackTemplate": "Unsorted/{source_label}/{relative_dir}/{filename}",
        "conflictPolicy": "keep_both",
        "groups": [],
        # Source-relative structure is preserved *inside* each category
        # (examples §2). Flattening a category would collide every card's
        # IMG_0001.JPG in one folder and multiply keep-both suffixes, and
        # it would throw away the only remaining trace of which drive and
        # which folder a file came from. No date routing here either:
        # {year} means source modification time, which is usually not the
        # capture date, so it is an opt-in a user makes knowingly rather
        # than a default they inherit (examples §5).
        "rules": [
            {
                "id": "category-video",
                "match": {"categories": ["video"]},
                "destination": "Video/{source_label}/{relative_dir}/{filename}",
            },
            {
                "id": "category-audio",
                "match": {"categories": ["audio"]},
                "destination": "Audio/{source_label}/{relative_dir}/{filename}",
            },
            {
                "id": "category-images",
                "match": {"categories": ["image"]},
                "destination": "Images/{source_label}/{relative_dir}/{filename}",
            },
            {
                "id": "category-documents",
                "match": {"categories": ["document"]},
                "destination": "Documents/{source_label}/{relative_dir}/{filename}",
            },
            {
                "id": "category-archives",
                "match": {"categories": ["archive"]},
                "destination": "Archives/{source_label}/{relative_dir}/{filename}",
            },
        ],
    },
}

# Tokens every destination template may use (spec §6.2). ``{year}`` and
# ``{month}`` are explicitly source-mtime UTC in v1; the UI labels that.
TEMPLATE_TOKENS = frozenset(
    {"source_label", "relative_dir", "filename", "stem", "ext", "category", "year", "month"}
)

_CONFLICT_POLICIES = frozenset({"keep_both", "skip_identical", "needs_review"})


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class PresetError(ValueError):
    """Raised when preset content is invalid or a preset is missing."""


class PresetRevisionService:
    """Immutable revision storage for organization presets."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)

    # ---- revisions ---------------------------------------------------

    def save_revision(self, params: SavePresetRevisionParams) -> PresetRevisionSummary:
        """Validate and append a new immutable revision to a preset.

        The revision number is derived from the highest revision ever
        written *and* the legacy profile version, so the two writers
        (this one and legacy ``profile.save``) can never hand out the
        same number or let one side race ahead of the other (R07).
        """
        content = self._validated_content(params.content)
        now = _now_iso()
        payload = _canonical_content(content)
        content_hash = _sha256(payload)
        with transaction(self._db_path) as conn:
            preset = profile_repo.get_profile_by_name(conn, params.name)
            if preset is None:
                preset_id = profile_repo.insert_profile(
                    conn,
                    ProfileRow(
                        id=0,
                        name=params.name,
                        version=1,
                        # The legacy column keeps the fallback template as its
                        # root-only shape so legacy readers stay compatible.
                        template=json.dumps({"root": content.fallback_template}, sort_keys=True),
                        conflict_policy=content.conflict_policy,
                        mutation_policy="copy",
                        created_at=now,
                        updated_at=now,
                    ),
                )
                revision = 1
            else:
                preset_id = preset.id
                revision = max(preset.version, revision_repo.max_revision(conn, preset_id)) + 1
                profile_repo.bump_version(
                    conn,
                    preset_id,
                    template=json.dumps({"root": content.fallback_template}, sort_keys=True),
                    conflict_policy=content.conflict_policy,
                    mutation_policy="copy",
                    version=revision,
                    updated_at=now,
                )
            revision_id = revision_repo.insert_revision(
                conn,
                PresetRevisionRow(
                    id=0,
                    preset_id=preset_id,
                    revision=revision,
                    name=content.name or params.name,
                    description=content.description,
                    rules_json=json.dumps(
                        [r.model_dump(by_alias=True) for r in content.rules],
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    groups_json=json.dumps(
                        [g.model_dump(by_alias=True) for g in content.groups],
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    fallback_template=content.fallback_template,
                    conflict_policy=content.conflict_policy,
                    exclusions_json=json.dumps(
                        [e.model_dump(by_alias=True) for e in content.exclusions],
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    review_json=json.dumps(
                        list(content.review_required), sort_keys=True, separators=(",", ":")
                    ),
                    legacy_template_json=None,
                    schema_version=PRESET_SCHEMA_VERSION,
                    content_hash=content_hash,
                    created_at=now,
                ),
            )
            # A new revision does not move any destination's pin (spec
            # §4.2: destinations stay pinned until the user chooses an
            # update), so nothing is invalidated here.
        return PresetRevisionSummary(
            presetId=preset_id,
            revision=revision,
            contentHash=content_hash,
            createdAt=now,
            id=revision_id,
        )

    def get_revision(
        self, preset_id: int, revision: int | None = None
    ) -> tuple[PresetRevisionRow, PresetContent]:
        with transaction(self._db_path) as conn:
            row = (
                revision_repo.get_revision(conn, preset_id, revision)
                if revision is not None
                else revision_repo.latest_revision(conn, preset_id)
            )
        if row is None:
            raise PresetError(f"no revision {revision or 'latest'} for preset {preset_id}")
        return row, self._content_of(row)

    def list_revisions(
        self, preset_id: int, *, limit: int = 50, after_id: int = 0
    ) -> tuple[list[PresetRevisionSummary], int]:
        with transaction(self._db_path) as conn:
            rows, total = revision_repo.list_revisions(
                conn, preset_id, limit=limit, after_id=after_id
            )
        return (
            [
                PresetRevisionSummary(
                    presetId=r.preset_id,
                    revision=r.revision,
                    contentHash=r.content_hash,
                    createdAt=r.created_at,
                    id=r.id,
                )
                for r in rows
            ],
            total,
        )

    def builtin_content(self, key: str) -> PresetContent:
        """One of the two starting presets, as editable content (spec §6.2).

        Handed to the editor as a starting point rather than installed as
        a magic preset: the user owns what they save, and a built-in they
        cannot see inside would be exactly the "personal taxonomy baked
        into the app" the spec rules out.
        """
        spec = BUILTIN_PRESETS.get(key)
        if spec is None:
            raise PresetError(
                f"unknown built-in preset {key!r}; available: {sorted(BUILTIN_PRESETS)}"
            )
        return PresetContent.model_validate(spec)

    # ---- portability -------------------------------------------------

    def export_preset(self, preset_id: int, revision: int | None = None) -> PresetExportResult:
        """Export one revision as portable JSON — presets only (spec §4.2).

        The payload carries no absolute paths and no destination
        identities; importing it anywhere creates a fresh local preset.
        """
        row, content = self.get_revision(preset_id, revision)
        payload = {
            "format": "ferry-preset",
            "formatVersion": 1,
            "preset": _canonical_content(content),
        }
        return PresetExportResult(
            presetId=preset_id,
            revision=row.revision,
            payload=json.dumps(payload, sort_keys=True, indent=2),
        )

    def import_preset(
        self, payload_json: str, *, new_name: str | None = None
    ) -> PresetRevisionSummary:
        """Import a portable preset payload as a new local identity."""
        try:
            payload = json.loads(payload_json)
        except json.JSONDecodeError as exc:
            raise PresetError(f"preset payload is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("format") != "ferry-preset":
            raise PresetError("preset payload is not a ferry preset export")
        if payload.get("formatVersion") != 1:
            raise PresetError(f"unsupported preset format version: {payload.get('formatVersion')}")
        # ``payload["preset"]`` may be either a JSON-encoded string
        # (round-trips through ``export_preset``) or a plain object; both
        # shapes are accepted so the wire format can evolve without
        # breaking older clients.
        content_raw = payload.get("preset")
        if isinstance(content_raw, str):
            try:
                content_inner = json.loads(content_raw)
            except json.JSONDecodeError as exc:
                raise PresetError(f"preset content is not valid JSON: {exc}") from exc
        elif isinstance(content_raw, dict):
            content_inner = content_raw
        else:
            raise PresetError("preset payload has no preset content")
        # Validate via PresetContent so an imported payload cannot sneak
        # past schema checks. The pydantic model is the source of truth
        # for shape (literal constraints, alias handling, defaults).
        # ``schemaVersion`` is part of the wire envelope, not the
        # PresetContent model itself; the storage layer keeps it on
        # each revision row.
        content_inner.pop("schemaVersion", None)
        # The caller can rename an imported preset via ``new_name``;
        # otherwise we use the display name the payload carried
        # (falling back to a generic "Imported preset" when the inner
        # content omitted one). The display name is separate from the
        # canonical content identity the fingerprint covers, so we
        # strip it from the content (save_revision derives the row
        # name from ``params.name`` when the model name is empty).
        if new_name is not None:
            desired_name = new_name
        elif content_inner.get("name"):
            desired_name = str(content_inner["name"])
        else:
            desired_name = "Imported preset"
        content_inner = {k: v for k, v in content_inner.items() if k != "name"}
        content_inner.pop("schemaVersion", None)
        try:
            content_model = PresetContent.model_validate(content_inner)
        except Exception as exc:
            raise PresetError(f"preset payload shape invalid: {exc}") from exc
        with transaction(self._db_path) as conn:
            base, suffix = desired_name, 1
            name = desired_name
            while profile_repo.get_profile_by_name(conn, name) is not None:
                suffix += 1
                name = f"{base} ({suffix})"
        return self.save_revision(SavePresetRevisionParams(name=name, content=content_model))

    # ---- validation ---------------------------------------------------

    def _validated_content(self, content: PresetContent) -> PresetContent:
        """Field-specific validation; raises PresetError naming the field."""
        if content.conflict_policy not in _CONFLICT_POLICIES:
            raise PresetError(f"conflictPolicy: must be one of {sorted(_CONFLICT_POLICIES)}")
        _validate_template("fallbackTemplate", content.fallback_template)
        seen_rule_ids: set[str] = set()
        for i, rule in enumerate(content.rules):
            if not rule.id:
                raise PresetError(f"rules[{i}].id: stable rule id is required")
            if rule.id in seen_rule_ids:
                raise PresetError(f"rules[{i}].id: duplicate rule id {rule.id!r}")
            seen_rule_ids.add(rule.id)
            _validate_template(f"rules[{i}].destination", rule.destination)
            if not rule.match or not any(
                getattr(rule.match, f, None)
                for f in ("path_glob", "extensions", "categories", "source_label")
            ):
                raise PresetError(
                    f"rules[{i}].match: at least one condition is required "
                    "(pathGlob, extensions, categories, or sourceLabel)"
                )
        seen_group_ids: set[str] = set()
        for i, group in enumerate(content.groups):
            if not group.id:
                raise PresetError(f"groups[{i}].id: stable group id is required")
            if group.id in seen_group_ids:
                raise PresetError(f"groups[{i}].id: duplicate group id {group.id!r}")
            seen_group_ids.add(group.id)
            # A group destination is evaluated once, against the group's
            # root directory (examples §4). File-oriented tokens have no
            # meaning there, and {year}/{month} would make a preserved
            # subtree's location depend on metadata a directory may not
            # have — relocating or splitting the very thing the user
            # marked "keep together".
            _validate_template(
                f"groups[{i}].destination",
                group.destination,
                allowed=GROUP_TEMPLATE_TOKENS,
                note=(
                    "a group destination names a directory and is evaluated once for the group root"
                ),
            )
            if not group.match or not group.match.path_glob:
                raise PresetError(f"groups[{i}].match.pathGlob: a group needs a path glob")
        seen_exclusion_ids: set[str] = set()
        for i, exclusion in enumerate(content.exclusions):
            if not exclusion.id:
                raise PresetError(f"exclusions[{i}].id: stable exclusion id is required")
            if exclusion.id in seen_exclusion_ids:
                raise PresetError(f"exclusions[{i}].id: duplicate exclusion id {exclusion.id!r}")
            seen_exclusion_ids.add(exclusion.id)
            if not exclusion.reason.strip():
                # The reason is what review and the receipt show for every
                # file this rule leaves behind. "Excluded because a rule
                # said so" is not an account anybody can check.
                raise PresetError(
                    f"exclusions[{i}].reason: say why these files are excluded; the reason "
                    "is shown in review and recorded in the receipt"
                )
            if not exclusion.match or not any(
                getattr(exclusion.match, f, None)
                for f in ("path_glob", "extensions", "categories", "source_label")
            ):
                # Same rule as a routing rule, and for the same reason: a
                # condition-free exclusion would match everything and
                # empty the transfer.
                raise PresetError(
                    f"exclusions[{i}].match: at least one condition is required "
                    "(pathGlob, extensions, categories, or sourceLabel)"
                )
        return content

    @staticmethod
    def _content_of(row: PresetRevisionRow) -> PresetContent:
        """Decode a stored revision into content.

        Historical rows written before the conversion existed kept the
        legacy template *as* their rules payload (a JSON object, not a
        list). Reading those as "no rules" would silently discard the
        only record of what the profile asked for, so they are converted
        here the same way the migration converts them, and whatever needs
        a human decision comes back in ``review_required`` (R07).
        """
        review: list[str] = []
        rules: list[Any] = []
        groups: list[Any] = []
        exclusions: list[Any] = []
        fallback = row.fallback_template
        conflict = row.conflict_policy
        try:
            stored_review = json.loads(row.review_json) if row.review_json else []
            if isinstance(stored_review, list):
                review.extend(str(item) for item in stored_review)
        except (ValueError, TypeError):
            review.append("stored review evidence is unreadable; treat this revision as unsafe")
        raw_rules: Any = None
        try:
            raw_rules = json.loads(row.rules_json) if row.rules_json else []
        except (ValueError, TypeError) as exc:
            raise PresetError(f"stored revision {row.revision} is unreadable: {exc}") from exc
        if isinstance(raw_rules, list):
            rules = raw_rules
        elif isinstance(raw_rules, dict):
            # A pre-conversion legacy snapshot: convert now rather than
            # returning empty content that looks like a valid preset.
            template = raw_rules.get("template")
            if not isinstance(template, dict):
                template = {}
            fallback, conflict, legacy_review = convert_legacy_template(
                template, row.conflict_policy
            )
            review.extend(legacy_review)
            note = raw_rules.get("history_note")
            if note:
                review.append(str(note))
        else:
            review.append(
                f"stored rules payload for revision {row.revision} has an unexpected shape "
                "and was not applied"
            )
        for field_name, raw in (("groups", row.groups_json), ("exclusions", row.exclusions_json)):
            try:
                value = json.loads(raw) if raw else []
            except (ValueError, TypeError):
                value = None
            if isinstance(value, list):
                if field_name == "groups":
                    groups = value
                else:
                    exclusions = value
            else:
                review.append(
                    f"stored {field_name} payload for revision {row.revision} has an "
                    "unexpected shape and was not applied"
                )
        try:
            return PresetContent(
                name=row.name,
                description=row.description,
                rules=rules,
                groups=groups,
                fallbackTemplate=fallback,
                conflictPolicy=cast(
                    Literal["keep_both", "skip_identical", "needs_review"],
                    conflict,
                ),
                exclusions=exclusions,
                reviewRequired=review,
            )
        except (ValueError, TypeError) as exc:
            raise PresetError(f"stored revision {row.revision} is unreadable: {exc}") from exc


def legacy_template_of(row: PresetRevisionRow) -> dict[str, Any] | None:
    """The verbatim legacy template a revision was converted from."""
    if not row.legacy_template_json:
        return None
    try:
        value = json.loads(row.legacy_template_json)
    except (ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def revision_root_prefix(row: PresetRevisionRow) -> str | None:
    """The literal folder prefix this revision routes beneath, if any.

    The P2 planner preserves the source relative path; a revision
    converted from a legacy root-only profile must still apply that
    root, or the transfer silently lands somewhere the legacy profile
    never pointed at (R07). Returns ``None`` when the revision has no
    literal prefix (the full rule engine is P4).
    """
    legacy = legacy_template_of(row)
    if legacy is not None:
        return legacy_root_prefix(legacy)
    return None


def _validate_template(
    field: str,
    template: str,
    *,
    allowed: frozenset[str] = TEMPLATE_TOKENS,
    note: str | None = None,
) -> None:
    """Reject unknown tokens and unsafe path shapes, naming the field."""
    if not isinstance(template, str) or not template.strip():
        raise PresetError(f"{field}: a destination template is required")
    import re

    for token in re.findall(r"\{([a-z_]+)\}", template):
        if token in allowed:
            continue
        if token in TEMPLATE_TOKENS:
            detail = f" — {note}" if note else ""
            raise PresetError(
                f"{field}: template token {{{token}}} is not available here{detail} "
                f"(supported here: {sorted(allowed)})"
            )
        raise PresetError(
            f"{field}: unknown template token {{{token}}} (supported: {sorted(allowed)})"
        )
    # A template that resolves to an absolute path or climbs out of the
    # destination root is rejected at save time with the field named.
    probe = re.sub(r"\{[a-z_]+\}", "x", template)
    from file_ferry.application.transfer_safety import UnsafeDestinationError, validate_relpath

    try:
        validate_relpath(probe)
    except UnsafeDestinationError as exc:
        raise PresetError(f"{field}: {exc}") from exc


def _canonical_content(content: PresetContent) -> str:
    # The preset's display name is captured on the revision row
    # separately (it's the row's ``name`` column), so the canonical
    # fingerprint covers the content only; including ``name`` would
    # hash the display identity into the revision substance, which an
    # import that derives a new local name could not satisfy.
    return json.dumps(
        {
            "description": content.description,
            "rules": [r.model_dump(by_alias=True) for r in content.rules],
            "groups": [g.model_dump(by_alias=True) for g in content.groups],
            "fallbackTemplate": content.fallback_template,
            "conflictPolicy": content.conflict_policy,
            "exclusions": [e.model_dump(by_alias=True) for e in content.exclusions],
            "reviewRequired": list(content.review_required),
            "schemaVersion": PRESET_SCHEMA_VERSION,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()
