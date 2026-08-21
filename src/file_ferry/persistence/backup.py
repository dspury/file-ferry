"""SQLite backup utilities.

The migration runner writes a backup of the database file before
each migration step. The backup uses SQLite's online backup API
(``sqlite3.Connection.backup``) to get a consistent snapshot even
when the database is in WAL mode. Every backup has a sibling
``.sha256`` file with the digest of the backup so restores can be
verified.

See ADR-0003 (application persistence model).
"""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

BACKUP_PREFIX = "ferry"
BACKUP_SUFFIX = ".db"


def _now_iso() -> str:
    """Return the current UTC timestamp in a filename-safe ISO format."""
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H-%M-%SZ")


def write_backup(db_path: Path, backups_dir: Path, version: int) -> Path:
    """Copy the database file to ``backups_dir`` and return the path.

    The backup uses SQLite's online backup API so the snapshot is
    consistent even if WAL mode is active. The backup filename is
    ``ferry-{ISO8601}-pre-{version:03d}.db``.
    """
    backups_dir.mkdir(parents=True, exist_ok=True)
    target = backups_dir / f"{BACKUP_PREFIX}-{_now_iso()}-pre-{version:03d}{BACKUP_SUFFIX}"
    source = sqlite3.connect(str(db_path), timeout=5.0)
    try:
        dest = sqlite3.connect(str(target), timeout=5.0)
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()
    return target


def write_checksum(backup_path: Path) -> Path:
    """Write a SHA-256 checksum of the backup file next to it.

    Returns the path to the checksum file.
    """
    digest = hashlib.sha256(backup_path.read_bytes()).hexdigest()
    checksum_path = backup_path.with_suffix(backup_path.suffix + ".sha256")
    checksum_path.write_text(f"{digest}  {backup_path.name}\n", encoding="utf-8")
    return checksum_path


def restore_from(backup_path: Path, db_path: Path) -> None:
    """Restore the database to its state at the backup time.

    The current database file is overwritten. WAL sidecars are removed
    so the restored (non-WAL) state is consistent on the next open.
    """
    if not backup_path.exists():
        raise FileNotFoundError(f"backup not found: {backup_path}")
    for sidecar in (
        db_path.with_suffix(db_path.suffix + "-shm"),
        db_path.with_suffix(db_path.suffix + "-wal"),
    ):
        if sidecar.exists():
            sidecar.unlink()
    shutil.copy2(backup_path, db_path)


def verify_checksum(backup_path: Path) -> bool:
    """Return True if the backup's checksum file matches the backup contents."""
    checksum_path = backup_path.with_suffix(backup_path.suffix + ".sha256")
    if not checksum_path.exists():
        return False
    expected = checksum_path.read_text(encoding="utf-8").split()[0]
    actual = hashlib.sha256(backup_path.read_bytes()).hexdigest()
    return expected == actual
