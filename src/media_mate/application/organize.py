"""Existing-folder adoption / organization (plan §4.3, §7.3).

Adopts a source into a named organization profile destination. Always
provides a complete preview tree and collision report before a mutating
operation. ``copy`` is the default; ``move`` requires an elevated
confirmation (confirm_move); same-volume ``link`` is opt-in. Source
provenance is retained in the asset record even when the file is moved
(plan §2.7).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from media_mate.application.plan import detect_collisions
from media_mate.service.protocol import (
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


class OrganizeError(ValueError):
    """Raised when an organization operation cannot proceed."""


class OrganizeService:
    """Preview and apply existing-media organization."""

    def preview(self, params: OrganizePreviewParams) -> OrganizePreview:
        """Build the complete source-to-destination tree + collision report."""
        src_root = Path(params.source_root).expanduser()
        dest_root = Path(params.dest_root).expanduser()
        if not src_root.is_dir():
            raise OrganizeError(f"source is not a readable directory: {src_root}")
        if not dest_root.is_dir():
            raise OrganizeError(f"destination is not a directory: {dest_root}")
        if not os.access(dest_root, os.W_OK):
            raise OrganizeError(f"destination is not writable: {dest_root}")

        root = params.template.get("root", "") if params.template else ""
        prefix = Path(root) if root else Path()
        entries = self._map(params.entries, src_root, dest_root, prefix)
        collisions = detect_collisions(entries)
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
        """Perform copy / move / link. ``move`` requires ``confirm_move``."""
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
                "collisions detected; refusing to organize (use copy with review first)"
            )
        if params.mode == _MOVE and not params.confirm_move:
            raise OrganizeError("move requires explicit elevated confirmation (confirm_move)")

        outcomes: list[OrganizeOutcome] = []
        for entry in preview.entries:
            src = Path(entry.source_path)
            dest = Path(entry.dest_path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                if params.mode == _LINK:
                    self._ensure_same_volume(src, dest.parent)
                    os.link(src, dest)
                elif params.mode == _MOVE:
                    shutil.copy2(src, dest)
                    src.unlink()
                else:  # copy
                    shutil.copy2(src, dest)
                outcomes.append(
                    OrganizeOutcome(
                        sourcePath=str(src),
                        destPath=str(dest),
                        operation=params.mode,
                        ok=True,
                        error=None,
                    )
                )
            except OSError as exc:
                outcomes.append(
                    OrganizeOutcome(
                        sourcePath=str(src),
                        destPath=str(dest),
                        operation=params.mode,
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
        prefix: Path,
    ) -> list[OrganizeEntry]:
        out: list[OrganizeEntry] = []
        for entry in entries:
            rel = Path(entry.path)
            out.append(
                OrganizeEntry(
                    sourcePath=str(src_root / rel),
                    destPath=str(dest_root / prefix / rel),
                    size=entry.size,
                )
            )
        return out

    @staticmethod
    def _ensure_same_volume(src: Path, dest_dir: Path) -> None:
        if os.stat(src).st_dev != os.stat(dest_dir).st_dev:
            raise OrganizeError(
                f"link requires same-volume source and destination: {src} / {dest_dir}"
            )
