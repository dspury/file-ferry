"""Source service — registration and read-only intake scanning.

Implements the plan Section 4.2/4.3 intake inventory step: a source is
identified (card or existing media), a volume/source fingerprint is
recorded, and the tree is scanned *without writing*. The inventory is
the input to the intake planner (a later package); this service only
records the source row and returns a deterministic manifest summary.

System-artifact exclusions follow the plan §7.1 ("excluding existing
system-artifact rules consistently").
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from ferry.persistence.connection import transaction
from ferry.persistence.repositories import sources as source_repo
from ferry.persistence.repositories.sources import SourceRow
from ferry.service.protocol import (
    SourceInspectParams,
    SourceInspectResult,
    SourceInventoryEntry,
)

# Files and directories that are system artifacts, not media.
_SKIP_FILE_NAMES = {
    ".DS_Store",
    "Thumbs.db",
    "Desktop.ini",
    ".localized",
    ".trashes",
    ".fseventsd",
    ".Spotlight-V100",
    ".TemporaryItems",
}
_SKIP_DIR_NAMES = {
    "__MACOSX",
    ".thumbnails",
    ".Trashes",
    ".Spotlight-V100",
    ".fseventsd",
    ".TemporaryItems",
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class SourceNotFoundError(KeyError):
    """Raised when a named source does not exist."""


def _is_skip_file(name: str) -> bool:
    return name in _SKIP_FILE_NAMES or name.startswith("._")  # AppleDouble sidecars


def _is_skip_dir(name: str) -> bool:
    return name in _SKIP_DIR_NAMES


class SourceService:
    """Register and inspect media sources read-only."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)

    def inspect(
        self, params: SourceInspectParams, *, max_entries: int = 5000
    ) -> SourceInspectResult:
        """Identify a source and scan it without writing.

        Returns an inventory summary (file count, total bytes, a
        deterministic manifest hash) plus the scanned file entries. The
        manifest hash covers the sorted ``(path, size, mtime)`` tuples,
        so re-scanning an unchanged source yields the same fingerprint.
        """
        root = Path(params.path).expanduser()
        if not root.exists():
            raise FileNotFoundError(f"source path does not exist: {root}")
        if not root.is_dir():
            raise NotADirectoryError(f"source path is not a directory: {root}")

        entries = scan_inventory(root)
        total_bytes = sum(e.size for e in entries)
        manifest_hash = _manifest_hash(entries)

        source_id = self._register(
            root, params.kind, params.label, manifest_hash, len(entries), total_bytes
        )
        # Bound the entries returned over the wire; the full inventory is
        # re-derived by the intake planner from the source manifest.
        return SourceInspectResult(
            sourceId=source_id,
            rootPath=str(root),
            kind=params.kind,
            label=params.label,
            fileCount=len(entries),
            totalBytes=total_bytes,
            manifestHash=manifest_hash,
            entries=entries[:max_entries],
        )

    def get(self, source_id: int) -> SourceRow:
        with transaction(self._db_path) as conn:
            row = source_repo.get_source(conn, source_id)
        if row is None:
            raise SourceNotFoundError(source_id)
        return row

    def _register(
        self,
        root: Path,
        kind: str,
        label: str | None,
        manifest_hash: str,
        file_count: int,
        total_bytes: int,
    ) -> int:
        now = _now_iso()
        source = SourceRow(
            id=0,
            kind=kind,
            root_path=str(root),
            label=label,
            volume_fingerprint=_volume_fingerprint(root),
            manifest_hash=manifest_hash,
            file_count=file_count,
            total_bytes=total_bytes,
            status="scanned",
            source_readable_at=now,
            captured_at=now,
        )
        with transaction(self._db_path) as conn:
            existing = conn.execute(
                "SELECT id FROM sources WHERE root_path = ? AND kind = ?",
                (str(root), kind),
            ).fetchone()
            if existing is not None:
                source_id = int(existing["id"])
                source_repo.update_scan_result(
                    conn,
                    source_id,
                    manifest_hash=manifest_hash,
                    file_count=file_count,
                    total_bytes=total_bytes,
                    status="scanned",
                    volume_fingerprint=source.volume_fingerprint,
                    source_readable_at=now,
                )
                return source_id
            return source_repo.insert_source(conn, source)


def _walk(root: Path) -> Iterable[tuple[str, int, float]]:
    """Yield ``(relative_path, size, mtime)`` for media files under ``root``."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not _is_skip_dir(d)]
        base = Path(dirpath)
        for name in filenames:
            if _is_skip_file(name):
                continue
            full = base / name
            try:
                st = full.stat()
            except OSError:
                continue
            if not os.path.isfile(full):
                continue
            rel = str(full.relative_to(root))
            yield rel, int(st.st_size), st.st_mtime


def scan_inventory(root: Path) -> list[SourceInventoryEntry]:
    """Return the read-only media-file inventory of ``root``.

    Applies the same system-artifact exclusions as :meth:`SourceService.inspect`
    so a planner that re-scans a source at plan time agrees with the
    source scan that created the manifest.
    """
    entries = [
        SourceInventoryEntry(path=rel, size=size, mtime=mtime) for rel, size, mtime in _walk(root)
    ]
    entries.sort(key=lambda e: e.path)
    return entries


def _manifest_hash(entries: list[SourceInventoryEntry]) -> str:
    canonical = json.dumps(
        [[e.path, e.size, round(e.mtime, 3)] for e in entries],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _volume_fingerprint(path: Path) -> str:
    """A best-effort fingerprint of the volume holding ``path``.

    Combines the filesystem device id and the filesystem type. This is
    evidence, not a guarantee of unique volume identity (ADR-0004).
    """
    try:
        st = os.stat(path)
        return f"dev:{st.st_dev}"
    except OSError:
        return "unknown"
