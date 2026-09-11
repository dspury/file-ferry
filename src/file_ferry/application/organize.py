"""Existing-folder adoption / organization (plan §4.3, §7.3).

Adopts a source into a named organization profile destination. Always
provides a complete preview tree and collision report before a mutating
operation.

Safety contract (destination-presets spec §1.2, P1 guards):

- ``copy`` is the only supported mode. ``move``/``link`` are disabled
  with an actionable error until an independently specified safety
  contract exists — a deliberate visible restriction, not a removal.
- Every rendered destination is containment-validated against the
  destination root (no absolute paths, ``..``, or symlink escapes).
- Collisions are detected both among planned entries **and against
  files already present at the destination**.
- Publication is exclusive: an existing destination file is never
  replaced, and each copy is checksum-verified before it counts as
  succeeded.
"""

from __future__ import annotations

from pathlib import Path

from file_ferry.application.plan import detect_collisions
from file_ferry.application.transfer_safety import (
    CopyVerification,
    UnsafeDestinationError,
    copy_file_verified,
    render_destination,
    validate_dest_root,
    validate_relpath,
)
from file_ferry.service.protocol import (
    OrganizeApplyParams,
    OrganizeEntry,
    OrganizeOutcome,
    OrganizePreview,
    OrganizePreviewParams,
    OrganizeResult,
    SourceInventoryEntry,
)

_COPY = "copy"
_MOVE = "move"
_LINK = "link"

_DISABLED_MODES_MESSAGE = (
    "organize {mode} is disabled until it meets the verified-transfer safety "
    "contract (checksum-verified, no-overwrite, durable receipts). Use copy, "
    "or the new transfer workflow once it ships. See "
    "docs/DESTINATION-PRESETS-PRODUCTION-SPEC.md §1.2."
)


class OrganizeError(ValueError):
    """Raised when an organization operation cannot proceed."""


class OrganizeService:
    """Preview and apply existing-media organization."""

    def preview(self, params: OrganizePreviewParams) -> OrganizePreview:
        """Build the complete source-to-destination tree + collision report."""
        src_root = Path(params.source_root).expanduser()
        dest_root = validate_dest_root(Path(params.dest_root).expanduser())
        if not src_root.is_dir():
            raise OrganizeError(f"source is not a readable directory: {src_root}")
        if not dest_root.is_dir():  # pragma: no cover - validated above
            raise OrganizeError(f"destination is not a directory: {dest_root}")

        root = params.template.get("root", "") if params.template else ""
        prefix_parts = _template_prefix(root)
        entries = self._map(params.entries, src_root, dest_root, prefix_parts)
        collisions = detect_collisions(entries, dest_root=dest_root)
        total = sum(e.size for e in entries)
        return OrganizePreview(
            sourceRoot=str(src_root),
            destRoot=str(dest_root),
            entries=entries,
            collisions=collisions,
            totalBytes=total,
            mode=params.mode,
        )

    def apply(self, params: OrganizeApplyParams) -> OrganizeResult:
        """Perform verified, non-overwriting copies.

        ``move`` and ``link`` are rejected outright (see the module
        docstring); a collision report that includes anything already
        present at the destination blocks execution rather than
        overwriting it.
        """
        if params.mode == _MOVE:
            raise OrganizeError(_DISABLED_MODES_MESSAGE.format(mode="move"))
        if params.mode == _LINK:
            raise OrganizeError(_DISABLED_MODES_MESSAGE.format(mode="link"))

        preview = self.preview(
            OrganizePreviewParams(
                sourceRoot=params.source_root,
                destRoot=params.dest_root,
                entries=params.entries,
                template=params.template,
                mode=params.mode,
            )
        )
        if preview.collisions:
            raise OrganizeError(
                "collisions detected; refusing to organize (existing destination "
                "content is never replaced — review the plan and resolve conflicts)"
            )

        outcomes: list[OrganizeOutcome] = []
        dest_root = Path(preview.dest_root)
        for entry in preview.entries:
            src = Path(entry.source_path)
            dest = Path(entry.dest_path)
            try:
                # Containment was validated during preview; re-validate at
                # apply time against the *root* so a symlink mutated between
                # preview and apply cannot redirect the write.
                render_destination(dest_root, dest.relative_to(dest_root))
                verification: CopyVerification = copy_file_verified(src, dest)
                outcomes.append(
                    OrganizeOutcome(
                        sourcePath=str(src),
                        destPath=str(dest),
                        operation=_COPY,
                        ok=True,
                        error=None,
                        verification=_verification_payload(verification),
                    )
                )
            except OSError as exc:
                outcomes.append(
                    OrganizeOutcome(
                        sourcePath=str(src),
                        destPath=str(dest),
                        operation=_COPY,
                        ok=False,
                        error=str(exc),
                    )
                )
        return OrganizeResult(entries=outcomes)

    # ---- helpers -----------------------------------------------------

    @staticmethod
    def _map(
        entries: list[SourceInventoryEntry],
        src_root: Path,
        dest_root: Path,
        prefix_parts: tuple[str, ...],
    ) -> list[OrganizeEntry]:
        out: list[OrganizeEntry] = []
        for entry in entries:
            rel = validate_relpath(entry.path)
            dest = render_destination(dest_root, Path(*prefix_parts, *rel.parts))
            out.append(
                OrganizeEntry(
                    sourcePath=str(src_root / entry.path),
                    destPath=str(dest),
                    size=entry.size,
                )
            )
        return out


def _template_prefix(root: object) -> tuple[str, ...]:
    """Validate the template's ``root`` prefix; it must be a safe relative."""
    if not root:
        return ()
    if not isinstance(root, str):
        raise UnsafeDestinationError(f"template root must be a string: {root!r}")
    return validate_relpath(root).parts


def _verification_payload(verification: CopyVerification) -> dict[str, object]:
    return {
        "checksumAlgo": verification.checksum_algo,
        "sourceChecksum": verification.source_checksum,
        "destChecksum": verification.dest_checksum,
        "bytes": verification.bytes_copied,
        "mtimePreserved": verification.mtime_preserved,
    }
