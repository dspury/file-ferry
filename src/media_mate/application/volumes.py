"""System volume observation adapter.

The desktop shell reports mounted volumes to the renderer (``source.
listVolumes``) and can subscribe to mount/unmount observations. The
adapter here is the tested boundary between the application and the
platform.

Design constraints (plan §8.1, §10.6.2):

- **Observations only.** The adapter reports what is mounted, with the
  sizes and filesystem type it can read. It must NOT label a volume a
  camera card, an editor's drive, or anything else — classification is
  the user's decision and lives in the intake/planning layer.
- **Testable interface.** ``VolumeAdapter`` is a Protocol; the system
  adapter is one implementation. Tests inject a fake adapter into the
  observer to prove the diff logic without touching the real mount
  table.

The legacy ``media_mate.drives.list_external_drives`` is the mount-point
source of truth; this module adds the typed ``MountedVolume`` shape and
the snapshot-diff observation.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from pathlib import Path
from typing import Protocol, runtime_checkable

from media_mate.drives import list_external_drives
from media_mate.service.protocol import MountedVolume


@runtime_checkable
class VolumeAdapter(Protocol):
    """The testable interface for discovering mounted volumes."""

    def list_volumes(self) -> list[MountedVolume]:
        """Return the currently mounted volumes, observations only."""
        ...


class SystemVolumeAdapter:
    """Real adapter backed by the platform mount table.

    Includes the root mount plus every external / removable mount point
    from ``list_external_drives``, deduplicated by realpath. Sizes come
    from ``shutil.disk_usage``; the filesystem type is read from the
    platform ``mount`` output (best-effort, ``unknown`` on failure).
    """

    def list_volumes(self) -> list[MountedVolume]:
        mounts: list[Path] = [Path("/")]
        for external in list_external_drives():
            try:
                real = external.resolve()
            except OSError:
                real = external
            if real not in mounts:
                mounts.append(real)

        fs_types = self._filesystem_types()
        volumes: list[MountedVolume] = []
        for mount in mounts:
            try:
                total, free = _disk_usage(mount)
            except OSError:
                continue
            label = mount.name or str(mount)
            filesystem = fs_types.get(str(mount.resolve())) or "unknown"
            volumes.append(
                MountedVolume(
                    path=str(mount),
                    label=label,
                    totalBytes=total,
                    freeBytes=free,
                    filesystem=filesystem,
                )
            )
        volumes.sort(key=lambda v: v.path)
        return volumes

    def _filesystem_types(self) -> dict[str, str]:
        """Map mount realpath -> filesystem type string (best-effort)."""
        system = platform.system()
        try:
            if system == "Darwin":
                out = subprocess.run(
                    ["/sbin/mount"], capture_output=True, text=True, timeout=5
                ).stdout
            elif system == "Linux":
                out = subprocess.run(["mount"], capture_output=True, text=True, timeout=5).stdout
            else:
                return {}
        except (OSError, subprocess.SubprocessError):
            return {}

        result: dict[str, str] = {}
        for line in out.splitlines():
            # macOS: "/dev/disk3s1 on /Volumes/X (apfs, local, ...)"
            # Linux: "/dev/sda1 on /mnt/x type ext4 (rw,...)"
            try:
                if " on " not in line:
                    continue
                after_on = line.split(" on ", 1)[1]
                mount_point = after_on.split(" ")[0]
                if system == "Darwin":
                    paren = after_on.find("(")
                    fstype = after_on[paren + 1 :].split(",")[0].strip() if paren != -1 else "?"
                else:
                    # "type ext4"
                    tidx = after_on.find("type ")
                    fstype = after_on[tidx + len("type ") :].split(" ")[0] if tidx != -1 else "?"
                result[mount_point] = fstype
            except (ValueError, IndexError):
                continue
        return result


class VolumeObserver:
    """Diffs volume snapshots to emit mount/unmount observations.

    ``poll`` returns the change since the last snapshot. It is a pure
    diff over ``MountedVolume.path``; classification never happens
    here. The first call records a baseline and returns an empty change.
    """

    def __init__(self, adapter: VolumeAdapter) -> None:
        self._adapter = adapter
        self._last: frozenset[str] = frozenset()

    def snapshot(self) -> list[MountedVolume]:
        """Return the current volumes and update the baseline."""
        volumes = self._adapter.list_volumes()
        self._last = frozenset(v.path for v in volumes)
        return volumes

    def poll(self) -> VolumeChange:
        """Return volumes that appeared or disappeared since the last call.

        The first poll establishes the baseline and returns an empty
        change.
        """
        volumes = self._adapter.list_volumes()
        current = frozenset(v.path for v in volumes)
        if not self._last:
            self._last = current
            return VolumeChange(mounted=[], unmounted=[])
        mounted = [v for v in volumes if v.path not in self._last]
        unmounted = sorted(self._last - current)
        self._last = current
        return VolumeChange(mounted=mounted, unmounted=unmounted)


class VolumeChange:
    """The observation delta: volumes that mounted/unmounted."""

    def __init__(self, *, mounted: list[MountedVolume], unmounted: list[str]) -> None:
        self.mounted = mounted
        self.unmounted = unmounted

    @property
    def changed(self) -> bool:
        return bool(self.mounted or self.unmounted)


def _disk_usage(path: Path) -> tuple[int, int]:
    """Return ``(total, free)`` bytes for the volume holding ``path``."""
    usage = shutil.disk_usage(path)
    return usage.total, usage.free


__all__ = ["SystemVolumeAdapter", "VolumeAdapter", "VolumeChange", "VolumeObserver"]
