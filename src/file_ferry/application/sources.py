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
import stat
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from file_ferry.persistence.connection import transaction
from file_ferry.persistence.repositories import sources as source_repo
from file_ferry.persistence.repositories.sources import SourceRow
from file_ferry.service.protocol import (
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


@dataclass(frozen=True)
class ScanItem:
    """One raw scan finding, before filtering."""

    rel: str
    size: int
    mtime: float
    entry_type: str  # file | symlink | other | error
    error: str | None = None


@dataclass(frozen=True)
class DetailedScan:
    """A scan that accounts for every entry it saw.

    ``scan_errors`` carries the findings for entries that could not be
    stat/read; ``non_files`` carries symlinks and unsupported objects
    that must be flagged rather than silently skipped (spec §6.3).
    """

    files: list[SourceInventoryEntry] = field(default_factory=list)
    non_files: list[SourceInventoryEntry] = field(default_factory=list)
    scan_errors: list[str] = field(default_factory=list)


def _is_skip_file(name: str) -> bool:
    return name in _SKIP_FILE_NAMES or name.startswith("._")  # AppleDouble sidecars


def _is_skip_dir(name: str) -> bool:
    return name in _SKIP_DIR_NAMES


class SourceService:
    """Register and inspect media sources read-only."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)

    def inspect(
        self, params: SourceInspectParams, *, max_entries: int | None = None
    ) -> SourceInspectResult:
        """Identify a source and scan it without writing.

        Returns an inventory summary (file count, total bytes, a
        deterministic manifest hash) plus the scanned file entries. The
        manifest hash covers the sorted ``(path, size, mtime)`` tuples,
        so re-scanning an unchanged source yields the same fingerprint.

        ``max_entries`` bounds only the wire payload when a caller
        explicitly passes one; the ``truncated`` flag then says so. The
        default is unbounded: the baseline silently capped the payload at
        5,000 entries while reporting the true count, and the desktop
        organize flow then copied only what it was given (spec §2,
        confirmed defect; A01). Full server-side inventories (P2) make
        even an explicit cap harmless to correctness.
        """
        root = Path(params.path).expanduser()
        if not root.exists():
            raise FileNotFoundError(f"source path does not exist: {root}")
        if not root.is_dir():
            raise NotADirectoryError(f"source path is not a directory: {root}")

        detailed = scan_inventory_detailed(root)
        entries = detailed.files
        total_bytes = sum(e.size for e in entries)
        manifest_hash = _manifest_hash(entries)

        source_id = self._register(
            root, params.kind, params.label, manifest_hash, len(entries), total_bytes
        )
        payload = entries if max_entries is None else entries[:max_entries]
        return SourceInspectResult(
            sourceId=source_id,
            rootPath=str(root),
            kind=params.kind,
            label=params.label,
            fileCount=len(entries),
            totalBytes=total_bytes,
            manifestHash=manifest_hash,
            entries=payload,
            truncated=max_entries is not None and len(payload) < len(entries),
            errorCount=len(detailed.scan_errors),
            scanErrors=detailed.scan_errors[:50],
            nonFiles=detailed.non_files,
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


def _walk(root: Path) -> Iterator[ScanItem]:
    """Yield scan items under ``root``, recording failures instead of hiding them.

    A file that cannot be stat/read is yielded as an *error* item rather
    than silently skipped: a scan whose result cannot account for every
    entry must not present itself as complete (spec §2 confirmed defect;
    §7.1 blocks approval on unexplained scan errors). The walker installs
    an ``onerror`` callback so a permission-denied descent is surfaced
    as an error finding rather than vanishing silently.
    """
    walk_errors: list[str] = []

    def _onerror(exc: OSError) -> None:
        walk_errors.append(f"{getattr(exc, 'filename', '')}: {exc}")

    for dirpath, dirnames, filenames in os.walk(root, onerror=_onerror):
        dirnames[:] = [d for d in dirnames if not _is_skip_dir(d)]
        base = Path(dirpath)
        for name in filenames:
            if _is_skip_file(name):
                continue
            full = base / name
            try:
                st = full.lstat()
            except OSError as exc:
                yield ScanItem(
                    rel=str(full.relative_to(root)),
                    size=0,
                    mtime=0.0,
                    entry_type="error",
                    error=f"lstat failed: {exc}",
                )
                continue
            if not stat.S_ISREG(st.st_mode):
                kind = "symlink" if stat.S_ISLNK(st.st_mode) else "other"
                yield ScanItem(
                    rel=str(full.relative_to(root)),
                    size=0,
                    mtime=0.0,
                    entry_type=kind,
                    error=None if kind == "symlink" else "unsupported filesystem object",
                )
                continue
            rel = str(full.relative_to(root))
            yield ScanItem(
                rel=rel, size=int(st.st_size), mtime=st.st_mtime, entry_type="file", error=None
            )
    for err in walk_errors:
        yield ScanItem(rel=err, size=0, mtime=0.0, entry_type="error", error="walk failed")


def scan_inventory(root: Path) -> list[SourceInventoryEntry]:
    """Return the read-only inventory of ``root`` (files only, no errors).

    Applies the same system-artifact exclusions as
    :meth:`SourceService.inspect` so a planner that re-scans a source at
    plan time agrees with the source scan that created the manifest.
    Error and non-file findings are excluded here; callers that need the
    full accounting use :func:`scan_inventory_detailed`.
    """
    entries = [item for item in _walk(root) if item.entry_type == "file"]
    entries.sort(key=lambda e: e.rel)
    return [SourceInventoryEntry(path=e.rel, size=e.size, mtime=e.mtime) for e in entries]


def scan_inventory_detailed(root: Path) -> DetailedScan:
    """Scan ``root`` keeping every finding, including errors.

    Returns files, non-file objects (symlinks and unsupported objects,
    flagged per spec §6.3), and the bounded error list with a total
    count. The manifest hash covers only regular files so it remains
    comparable with historical manifests.
    """
    items = sorted(_walk(root), key=lambda e: e.rel)
    files = [e for e in items if e.entry_type == "file"]
    others = [e for e in items if e.entry_type in ("symlink", "other")]
    errors = [e for e in items if e.entry_type == "error"]
    return DetailedScan(
        files=[SourceInventoryEntry(path=e.rel, size=e.size, mtime=e.mtime) for e in files],
        non_files=[
            SourceInventoryEntry(
                path=e.rel,
                size=e.size,
                mtime=e.mtime,
                entryType="symlink" if e.entry_type == "symlink" else "other",
            )
            for e in others
        ],
        scan_errors=[f"{e.rel}: {e.error}" for e in errors],
    )


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
