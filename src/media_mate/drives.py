"""Drive / volume detection helpers.

Pure filesystem lookups — no UI dependencies — so they can be reused
by both the Textual TUI and the CLI without dragging in Textual.
"""

from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path


def _format_size(num_bytes: int) -> str:
    """Render a byte count as a short human-readable string (e.g. ``1.2T``)."""
    scaled = float(num_bytes)
    for unit in ("B", "K", "M", "G", "T"):
        if abs(scaled) < 1024:
            return f"{scaled:0.1f}{unit}"
        scaled /= 1024
    return f"{scaled:0.1f}P"


def _drive_label(path: Path) -> str:
    """Best-effort display label for a mount, including free/total space."""
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return path.name or str(path)
    free = _format_size(usage.free)
    total = _format_size(usage.total)
    name = path.name or str(path)
    return f"{name}  ·  {free} free / {total}"


def list_external_drives() -> list[Path]:
    """Return mount points for connected external / removable volumes.

    Cross-platform:
      - macOS:   every entry under ``/Volumes/`` except the system volume
        (detected by realpath resolving to ``/``). This correctly excludes
        ``Macintosh HD`` while still showing the user's data volume and any
        attached camera cards, backup disks, or USB sticks.
      - Linux:   every directory under ``/media/$USER/`` and
        ``/run/media/$USER/`` (modern GNOME/udisks2), deduplicated by
        realpath. Fallback to ``/media`` if the user-scoped path is empty.
      - Windows: every drive letter that exists except ``%SYSTEMDRIVE%``.

    Returned paths are sorted alphabetically for stable display order.
    """
    system = platform.system()
    drives: list[Path] = []

    if system == "Darwin":
        root_real = Path("/").resolve()
        volumes = Path("/Volumes")
        if volumes.is_dir():
            for child in sorted(volumes.iterdir(), key=lambda p: p.name.lower()):
                if not child.is_dir():
                    continue
                try:
                    if child.resolve() == root_real:
                        continue  # skip system volume
                except OSError:
                    continue
                drives.append(child)
        return drives

    if system == "Linux":
        user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
        bases: list[Path] = []
        if user:
            bases.append(Path(f"/media/{user}"))
            bases.append(Path(f"/run/media/{user}"))
        bases.append(Path("/media"))
        seen: set[str] = set()
        for base in bases:
            if not base.is_dir():
                continue
            for child in sorted(base.iterdir(), key=lambda p: p.name.lower()):
                if not child.is_dir():
                    continue
                try:
                    real = str(child.resolve())
                except OSError:
                    continue
                if real in seen:
                    continue
                seen.add(real)
                drives.append(child)
        return drives

    if system == "Windows":
        system_drive = (os.environ.get("SYSTEMDRIVE") or "C:").rstrip(":").upper()[:1] or "C"
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            if letter == system_drive:
                continue
            root = Path(f"{letter}:/")
            if root.exists() and root.is_dir():
                drives.append(root)
        return drives

    return drives


__all__ = ["_drive_label", "_format_size", "list_external_drives"]
