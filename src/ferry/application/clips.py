"""Logical-clip detection and membership (plan §6.2, §7.3).

A logical clip groups multiple files that represent one media event:
spanned clips (a base name with an incrementing number run) and sidecars
(subtitle/audio/xml files sharing a video base). Detection is
conservative — uncertain inferences are surfaced as labeled, never
silently merged (plan §6.3).
"""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from ferry.persistence.connection import transaction
from ferry.service.protocol import ClipMember, LogicalClip

_SIDECAR_EXTS = {".srt", ".xml", ".wav", ".mp3", ".aac", ".mxf"}
_NUM_RUN = re.compile(r"^(?P<base>.+?)[ _.\-](?P<num>\d{2,})$")
_EXT = re.compile(r"^(?P<stem>.+?)(?P<ext>\.[A-Za-z0-9]+)$")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def clip_key(relpath: str) -> str:
    """Return a conservative grouping key for a source-relative path.

    Strips the extension, then a trailing numeric run (``_01``, ``.001``,
    `` 02``, ``-03``). Files sharing the key are candidates for one
    logical clip.
    """
    ext = _EXT.match(relpath)
    stem = ext.group("stem") if ext else relpath
    m = _NUM_RUN.match(stem)
    return m.group("base") if m else stem


def is_sidecar(path: str) -> bool:
    ext = _EXT.match(path)
    return ext is not None and ext.group("ext").lower() in _SIDECAR_EXTS


def detect_groups(relpaths: list[str]) -> dict[str, list[str]]:
    """Group paths into logical-clip candidates (base -> member paths)."""
    groups: dict[str, list[str]] = {}
    for p in relpaths:
        key = clip_key(p)
        if p != key:
            groups.setdefault(key, []).append(p)
    return groups


class ClipService:
    """Detect and persist logical clips for a source."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)

    def detect(self, source_id: int) -> list[LogicalClip]:
        """Detect logical clips for a source's assets and persist them."""
        clips: list[LogicalClip] = []
        with transaction(self._db_path) as conn:
            rows = conn.execute(
                "SELECT id, source_relative_path FROM assets WHERE source_id = ?",
                (source_id,),
            ).fetchall()
            by_path = {r["source_relative_path"]: r["id"] for r in rows}

            for key, members in sorted(detect_groups(list(by_path)).items()):
                if len(members) < 2:
                    continue
                confidence = _confidence(members)
                members_by_path = {m: by_path[m] for m in members if m in by_path}
                clip_id = self._persist(conn, source_id, key, confidence, members_by_path)
                clips.append(
                    LogicalClip(
                        id=clip_id,
                        sourceId=source_id,
                        clipName=key,
                        confidence=confidence,
                        resolved=False,
                        members=[
                            ClipMember(assetId=a, role=(is_sidecar(p) and "sidecar") or "primary")
                            for p, a in members_by_path.items()
                        ],
                    )
                )
        return clips

    def list(self, source_id: int) -> list[LogicalClip]:
        with transaction(self._db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM logical_clips WHERE source_id = ? ORDER BY clip_name ASC",
                (source_id,),
            ).fetchall()
            clips: list[LogicalClip] = []
            for row in rows:
                members = conn.execute(
                    """
                    SELECT m.asset_id, m.role FROM logical_clip_members m
                    WHERE m.logical_clip_id = ?
                    """,
                    (row["id"],),
                ).fetchall()
                clips.append(
                    LogicalClip(
                        id=row["id"],
                        sourceId=source_id,
                        clipName=row["clip_name"],
                        confidence=row["detection_confidence"],
                        resolved=bool(row["resolved"]),
                        members=[
                            ClipMember(assetId=r["asset_id"], role=r["role"]) for r in members
                        ],
                    )
                )
        return clips

    # ---- helpers -----------------------------------------------------

    @staticmethod
    def _persist(
        conn: sqlite3.Connection,
        source_id: int,
        key: str,
        confidence: float,
        members: dict[str, str],
    ) -> int:
        clip_id = _find_or_create_clip(conn, source_id, key, confidence)
        existing = {
            r["asset_id"]
            for r in conn.execute(
                "SELECT asset_id FROM logical_clip_members WHERE logical_clip_id = ?",
                (clip_id,),
            ).fetchall()
        }
        for path, asset_id in members.items():
            if asset_id in existing:
                continue
            role = "sidecar" if is_sidecar(path) else "primary"
            conn.execute(
                """
                INSERT INTO logical_clip_members (logical_clip_id, asset_id, role)
                VALUES (?, ?, ?)
                """,
                (clip_id, asset_id, role),
            )
        return clip_id


def _find_or_create_clip(
    conn: sqlite3.Connection, source_id: int, key: str, confidence: float
) -> int:
    row = conn.execute(
        "SELECT id FROM logical_clips WHERE source_id = ? AND clip_name = ?",
        (source_id, key),
    ).fetchone()
    if row is not None:
        return int(row["id"])
    cur = conn.execute(
        """
        INSERT INTO logical_clips (source_id, clip_name, detection_confidence, resolved, created_at)
        VALUES (?, ?, ?, 0, ?)
        """,
        (source_id, key, confidence, _now_iso()),
    )
    lastrowid = cur.lastrowid
    if lastrowid is None:
        raise RuntimeError("insert logical_clip failed")
    return int(lastrowid)


def _confidence(members: list[str]) -> float:
    primaries = [m for m in members if not is_sidecar(m)]
    return min(1.0, 0.5 + 0.25 * (len(primaries) - 1))
