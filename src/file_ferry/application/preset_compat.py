"""Legacy profile ↔ immutable preset revision compatibility (spec §4.2).

Two writers reach the same rows: the legacy ``profile.save`` path, which
has always stored one mutable ``organization_profiles`` template and a
version number, and the new ``profile.saveRevision`` path, which appends
immutable revisions. They must not diverge — a legacy save that advances
the profile version without producing the matching revision leaves the
destination's pinned revision pointing at content that no longer
describes the profile.

This module is the single conversion the migration, the legacy service,
and the revision service all share, so the mapping is defined once:

- A **root-only** legacy template is equivalent to preserving the source
  relative path beneath a literal prefix, so it converts to
  ``<root>/{relative_dir}/{filename}``.
- A root that is not a safe relative path, or that contains template
  tokens, is *not* reinterpreted as a literal prefix. Advanced token
  templates were never legacy-root semantics, and guessing would route
  files somewhere the user never asked for. It becomes a blocking
  review item and the revision falls back to the default.
- Every other key in a legacy template is unknown to this schema. It is
  recorded verbatim as a blocking review item, never dropped.
- Legacy conflict policies are mapped explicitly. ``rename`` is the
  ``keep_both`` the new contract already guarantees; ``skip`` and
  ``overwrite`` have no safe equivalent — ``skip`` skipped on name
  alone, which §6.4 forbids without checksum proof, and the new
  workflow has no replace option at all — so both become
  ``needs_review`` with the original recorded.

Nothing here decides *policy*; it records what a legacy profile said and
what a human still has to confirm.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

DEFAULT_FALLBACK_TEMPLATE = "Unsorted/{source_label}/{relative_dir}/{filename}"

# Legacy conflict policy → (new policy, review item or None).
_LEGACY_CONFLICT_MAP: dict[str, tuple[str, str | None]] = {
    "rename": ("keep_both", None),
    "keep_both": ("keep_both", None),
    "skip": (
        "needs_review",
        "legacy conflict policy 'skip' skipped existing files by name alone; the new "
        "contract only skips on full checksum equality (spec §6.4), so conflicts now "
        "need a decision",
    ),
    "overwrite": (
        "needs_review",
        "legacy conflict policy 'overwrite' replaced existing destination files; the new "
        "workflow has no replace option (spec §6.4), so conflicts now need a decision",
    ),
    "needs_review": ("needs_review", None),
    "skip_identical": ("skip_identical", None),
}

_TOKEN_RE = re.compile(r"\{[^}]*\}")


def legacy_root_prefix(template: dict[str, Any]) -> str | None:
    """The literal path prefix a root-only legacy template implies.

    ``None`` when the template has no usable root, or when its root
    cannot be treated as a literal prefix (absolute, escaping, or
    token-bearing). Callers must then fall back and surface a review
    item rather than inventing a location.
    """
    root = template.get("root")
    if not root or not isinstance(root, str) or not root.strip():
        return None
    if _TOKEN_RE.search(root):
        return None
    from file_ferry.application.transfer_safety import (
        UnsafeDestinationError,
        validate_relpath,
    )

    try:
        return str(validate_relpath(root))
    except UnsafeDestinationError:
        return None


def convert_legacy_template(
    template: dict[str, Any], conflict_policy: str | None
) -> tuple[str, str, list[str]]:
    """Convert one legacy profile template into valid revision content.

    Returns ``(fallback_template, conflict_policy, review_items)``.
    ``review_items`` is non-empty exactly when something needs a human
    decision before the revision is safe to transfer with.
    """
    review: list[str] = []
    prefix = legacy_root_prefix(template)
    raw_root = template.get("root")
    if prefix is not None:
        fallback = f"{prefix}/{{relative_dir}}/{{filename}}"
    else:
        fallback = DEFAULT_FALLBACK_TEMPLATE
        if raw_root:
            review.append(
                f"legacy template root {raw_root!r} is not a plain relative prefix "
                "(absolute, escaping, or token-bearing); it was not reinterpreted as a "
                f"literal folder — confirm the intended destination (fell back to {fallback!r})"
            )
    for key in sorted(k for k in template if k != "root"):
        review.append(
            f"legacy template key {key!r} is unknown to the preset schema and was not "
            f"applied; its value is preserved verbatim (value: {template[key]!r})"
        )
    mapped, note = _LEGACY_CONFLICT_MAP.get(
        (conflict_policy or "").strip(),
        ("needs_review", f"legacy conflict policy {conflict_policy!r} is unrecognized"),
    )
    if note:
        review.append(note)
    return fallback, mapped, review


def canonical_revision_payload(
    *,
    description: str | None,
    rules: list[Any],
    groups: list[Any],
    fallback_template: str,
    conflict_policy: str,
    exclusions: list[Any],
    review: list[str],
    schema_version: int = 1,
) -> str:
    """The canonical JSON a revision's ``content_hash`` is taken over.

    Kept here so the migration and both services hash identically — a
    revision written by one writer and re-derived by another must not
    change identity.
    """
    return json.dumps(
        {
            "description": description,
            "rules": rules,
            "groups": groups,
            "fallbackTemplate": fallback_template,
            "conflictPolicy": conflict_policy,
            "exclusions": exclusions,
            "reviewRequired": review,
            "schemaVersion": schema_version,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


__all__ = [
    "DEFAULT_FALLBACK_TEMPLATE",
    "canonical_revision_payload",
    "convert_legacy_template",
    "legacy_root_prefix",
    "sha256_text",
]
