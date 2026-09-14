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

The legacy ``file_ferry.drives.list_external_drives`` is the mount-point
source of truth; this module adds the typed ``MountedVolume`` shape and
the snapshot-diff observation.

Since P3 the adapter also attaches **identity evidence** from
``application/volume_identity.py``. That stays an observation too: the
adapter reports the best identifier the platform gave it and how much it
is worth, and the destination resolver decides what may be rebound on
it. A probe that fails or times out leaves the last good evidence in
place, marked stale, rather than downgrading a strong identity to a
guess — discovery degrading must not silently weaken recognition
(spec §5.2).
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from file_ferry.application.volume_identity import (
    IdentityProbe,
    ProbeResult,
    system_identity_probe,
)
from file_ferry.drives import list_external_drives
from file_ferry.service.protocol import DestinationIdentity, MountedVolume

#: Wall-clock bound for a filesystem metadata call. A ``statvfs`` on a
#: dead share has no timeout of its own, and discovery must not hang on
#: the storage this feature is about (spec §5.2).
FILESYSTEM_BUDGET_SECONDS = 5.0


@runtime_checkable
class VolumeAdapter(Protocol):
    """The testable interface for discovering mounted volumes."""

    def list_volumes(self) -> list[MountedVolume]:
        """Return the currently mounted volumes, observations only."""
        ...

    def last_warnings(self) -> list[str]:
        """Recoverable problems from the most recent observation, if any."""
        ...


class SystemVolumeAdapter:
    """Real adapter backed by the platform mount table.

    Includes the root mount plus every external / removable mount point
    from ``list_external_drives``, deduplicated by realpath. Sizes come
    from ``shutil.disk_usage``; the filesystem type is read from the
    platform ``mount`` output (best-effort, ``unknown`` on failure).
    Identity comes from the platform probe, which is time-bounded and
    may answer with nothing.
    """

    def __init__(
        self,
        *,
        identity_probe: IdentityProbe | None = None,
        budget: float = FILESYSTEM_BUDGET_SECONDS,
    ) -> None:
        self._probe = identity_probe if identity_probe is not None else system_identity_probe()
        self._identity_cache: dict[str, DestinationIdentity] = {}
        self._warnings: list[str] = []
        self._degraded = False
        self._budget = budget

    def last_warnings(self) -> list[str]:
        """Problems from the most recent probe. Recoverable, not fatal."""
        return list(self._warnings)

    @property
    def degraded(self) -> bool:
        """True when the last probe could not answer fully."""
        return self._degraded

    def list_volumes(self) -> list[MountedVolume]:
        self._warnings = []
        self._degraded = False
        mounts: list[Path] = [Path("/")]
        for external in list_external_drives():
            try:
                real = external.resolve()
            except OSError:
                real = external
            if real not in mounts:
                mounts.append(real)

        fs_types = self._filesystem_types()
        present: list[Path] = []
        sizes: dict[str, tuple[int, int]] = {}
        for mount in mounts:
            usage = _disk_usage_bounded(mount, budget=self._budget)
            if usage is None:
                # An unresponsive mount must not remove the volume from
                # discovery — the user still needs to see it, and manual
                # selection has to stay usable (spec §5.2). Sizes are
                # reported as unknown rather than the whole mount going
                # missing.
                self._warnings.append(
                    f"{mount} did not answer a free-space query within "
                    f"{self._budget:g}s; its capacity is shown as unknown"
                )
                self._degraded = True
                sizes[str(mount)] = (0, 0)
            else:
                sizes[str(mount)] = usage
            present.append(mount)

        identities = self._identities([str(m) for m in present])
        volumes: list[MountedVolume] = []
        for mount in present:
            total, free = sizes[str(mount)]
            label = mount.name or str(mount)
            filesystem = fs_types.get(str(mount.resolve())) or "unknown"
            volumes.append(
                MountedVolume(
                    path=str(mount),
                    label=label,
                    totalBytes=total,
                    freeBytes=free,
                    filesystem=filesystem,
                    identity=identities.get(str(mount)),
                    deviceId=_device_id(mount),
                )
            )
        volumes.sort(key=lambda v: v.path)
        return volumes

    def _identities(self, mount_paths: list[str]) -> dict[str, DestinationIdentity]:
        """Probe for identity, keeping the last answer as *stale* evidence.

        Two things are true at once and the first one used to hide the
        second:

        - A probe that times out must not turn a strong identity into
          nothing. That would flip a saved destination to "confirm this
          binding" with no explanation, and the operator could not tell
          a real device change from a slow one.
        - A cached identity is **not** evidence about what is mounted
          now. A drive can be swapped between two observations, so never
          having witnessed an unmount establishes nothing about
          continuity. Reusing cached evidence as if fresh is how a
          replacement drive at the same mount path gets recognized as
          the previous one — and then written to.

        So cached evidence is retained *and marked stale*, with the
        timestamp of when it was actually observed. It still shows the
        operator what this mount looked like last time; the resolver
        refuses to rebind on it and asks for confirmation instead
        (spec §5.1, R10).
        """
        # Prune first, and on every exit path: a mount that is gone must
        # never leave its identity behind for whatever is mounted at that
        # path next.
        self._prune_cache(mount_paths)
        carried = list(self._warnings)
        try:
            result: ProbeResult = self._probe.identify(mount_paths)
        except Exception as exc:  # a probe must never take the app down
            self._warnings = [*carried, f"volume identity probe failed: {exc}"]
            self._degraded = True
            return self._stale_only(mount_paths)
        self._warnings = carried + list(result.warnings)
        self._degraded = self._degraded or result.degraded or bool(result.warnings)

        observed_at = _now_iso()
        resolved: dict[str, DestinationIdentity] = {}
        for path in mount_paths:
            fresh = result.identities.get(path)
            if fresh is not None:
                stamped = fresh.model_copy(update={"observed_at": observed_at, "stale": False})
                self._identity_cache[path] = stamped
                resolved[path] = stamped
                continue
            cached = self._identity_cache.get(path)
            if cached is not None:
                # Not re-observed on this pass: keep it, but demote it.
                self._degraded = True
                resolved[path] = _as_stale(cached)
        return resolved

    def _stale_only(self, mount_paths: list[str]) -> dict[str, DestinationIdentity]:
        """Everything we still remember, all of it explicitly stale."""
        return {
            path: _as_stale(self._identity_cache[path])
            for path in mount_paths
            if path in self._identity_cache
        }

    def _prune_cache(self, mount_paths: list[str]) -> None:
        for gone in set(self._identity_cache) - set(mount_paths):
            self._identity_cache.pop(gone, None)

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
        self._initialized = False
        self._observed_at: float | None = None
        self._observed_iso: str | None = None
        self._volumes: list[MountedVolume] = []

    @property
    def initialized(self) -> bool:
        """Whether any observation has happened yet.

        Distinct from "observed nothing" (spec §5.2): a machine with no
        external volumes has an *empty baseline*, and the next volume to
        appear there is a mount event. Conflating the two — as a bare
        ``if not self._last`` does — swallows the first mount on exactly
        the machines where it matters most.
        """
        return self._initialized

    @property
    def observed_at(self) -> str | None:
        """When the last observation completed, ISO-8601, or None."""
        return self._observed_iso

    def age_seconds(self, *, now: float | None = None) -> float | None:
        """Seconds since the last observation, or None if never observed."""
        if self._observed_at is None:
            return None
        return max(0.0, (time.monotonic() if now is None else now) - self._observed_at)

    def last_volumes(self) -> list[MountedVolume]:
        """The most recent observation, which may be stale. Never refetches."""
        return list(self._volumes)

    def warnings(self) -> list[str]:
        """Recoverable discovery problems from the adapter, if it reports any."""
        getter = getattr(self._adapter, "last_warnings", None)
        if getter is None:
            return []
        try:
            return list(getter())
        except Exception:  # pragma: no cover - defensive
            return []

    def snapshot(self) -> list[MountedVolume]:
        """Return the current volumes and update the baseline."""
        volumes = self._adapter.list_volumes()
        self._record(volumes)
        return volumes

    def poll(self) -> VolumeChange:
        """Return volumes that appeared or disappeared since the last call.

        The first poll establishes the baseline and returns an empty
        change. Every later poll reports real deltas — including the
        first mount on a machine whose baseline was empty.
        """
        volumes = self._adapter.list_volumes()
        current = frozenset(v.path for v in volumes)
        first = not self._initialized
        previous = self._last
        self._record(volumes)
        if first:
            return VolumeChange(mounted=[], unmounted=[])
        mounted = [v for v in volumes if v.path not in previous]
        unmounted = sorted(previous - current)
        return VolumeChange(mounted=mounted, unmounted=unmounted)

    def _record(self, volumes: list[MountedVolume]) -> None:
        self._volumes = list(volumes)
        self._last = frozenset(v.path for v in volumes)
        self._initialized = True
        self._observed_at = time.monotonic()
        self._observed_iso = datetime.now(UTC).isoformat().replace("+00:00", "Z")


class VolumeChange:
    """The observation delta: volumes that mounted/unmounted."""

    def __init__(self, *, mounted: list[MountedVolume], unmounted: list[str]) -> None:
        self.mounted = mounted
        self.unmounted = unmounted

    @property
    def changed(self) -> bool:
        return bool(self.mounted or self.unmounted)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _as_stale(identity: DestinationIdentity) -> DestinationIdentity:
    """The same evidence, marked as not re-observed on this pass."""
    if identity.stale:
        return identity
    return identity.model_copy(
        update={
            "stale": True,
            "provenance": f"{identity.provenance} (not re-observed; last seen "
            f"{identity.observed_at or 'unknown'})",
        }
    )


def _device_id(path: Path) -> int | None:
    """``st_dev`` for a mount, for containment checks (never for identity)."""
    try:
        return int(path.stat().st_dev)
    except OSError:
        return None


def _disk_usage(path: Path) -> tuple[int, int]:
    """Return ``(total, free)`` bytes for the volume holding ``path``."""
    usage = shutil.disk_usage(path)
    return usage.total, usage.free


def _disk_usage_bounded(path: Path, *, budget: float) -> tuple[int, int] | None:
    """``_disk_usage`` with a wall-clock bound, or ``None`` if it does not answer.

    Subprocess timeouts bound the identity probes, but a ``statvfs`` on
    an unresponsive network share blocks in the kernel with no timeout of
    its own — so discovery could hang on exactly the storage this feature
    exists for. The call runs on a daemon thread and is abandoned when
    the budget expires.

    Honest about what this does and does not do: the syscall cannot be
    cancelled, so the thread stays blocked until the mount answers or the
    process exits. What it buys is that *discovery* returns, the volume
    is still listed, and manual selection stays usable (spec §5.2).
    """
    result: list[tuple[int, int] | None] = [None]

    def _probe() -> None:
        try:
            result[0] = _disk_usage(path)
        except OSError:
            result[0] = None

    worker = threading.Thread(target=_probe, name=f"disk-usage-{path}", daemon=True)
    worker.start()
    worker.join(budget)
    if worker.is_alive():
        return None
    return result[0]


__all__ = ["SystemVolumeAdapter", "VolumeAdapter", "VolumeChange", "VolumeObserver"]
