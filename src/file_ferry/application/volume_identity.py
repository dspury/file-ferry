"""Platform identity evidence for mounted storage (spec §5.1, P3).

A saved destination has to be recognizable when it comes back. The
question this module answers is narrow: *what durable identifier can
the platform tell us about this mount point right now?* It answers with
evidence and a confidence level, never with a decision — whether a
destination rebinds to a candidate is the resolver's call, and a weak
answer must never authorize it.

What counts as evidence, in descending order:

- **Volume UUID** (strong). A filesystem-level identifier that survives
  remount, rename, and a different mount path.
- **Disk/media UUID** (medium). Identifies the hardware, not the
  filesystem — a reformat keeps it, which is why it is not strong.
- **Server/share** (strong for shares). The sanitized ``server/share``
  a network mount was made from. Credentials embedded in a mount device
  string are stripped and never stored (spec §4.1).
- **Path only** (weak). What we fall back to when the platform will not
  tell us anything. A label, a size, an ``st_dev``, or a previous mount
  path is *not* identity: `/Volumes/Backup` is whatever was plugged in
  most recently, and rebinding on it would write a transfer to the
  wrong disk.

Everything here is split into pure parsers over captured platform text
and a thin probe that shells out, so the interesting logic is testable
without a real disk. Probes are time-bounded; on timeout or failure the
caller keeps its previous observation and marks it stale rather than
downgrading a strong identity to a guess (spec §5.2).
"""

from __future__ import annotations

import platform
import plistlib
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from file_ferry.service.protocol import DestinationIdentity

#: Per-probe wall-clock budget. A slow or hung mount must not block
#: discovery (spec §5.2: time-bound platform probes).
PROBE_BUDGET_SECONDS = 5.0

#: Filesystem types that mean "this is a network share", by platform name.
NETWORK_FILESYSTEMS = frozenset({"smbfs", "cifs", "nfs", "nfs4", "afpfs", "webdav", "ftp", "smb3"})


@dataclass(frozen=True)
class ProbeResult:
    """What one discovery pass learned, including what it could not learn.

    ``warnings`` are recoverable: discovery degrading must leave manual
    folder selection usable, not block the UI (spec §5.2).
    """

    identities: dict[str, DestinationIdentity]
    warnings: list[str]
    degraded: bool = False


@runtime_checkable
class IdentityProbe(Protocol):
    """The testable boundary between the resolver and the platform."""

    def identify(self, mount_paths: list[str]) -> ProbeResult:
        """Return identity evidence keyed by mount path, best effort."""
        ...


# ---------------------------------------------------------------------------
# sanitization
# ---------------------------------------------------------------------------

_CREDENTIALS = re.compile(r"^[^/@]*@")


def sanitize_share(server: str, share: str) -> str:
    """Normalize a ``server/share`` identity, dropping any credentials.

    Mount device strings routinely carry a username, and on some systems
    a password: ``//alice:hunter2@nas.local/media``. None of that may be
    persisted (spec §4.1), and none of it is identity anyway — the same
    share mounted by two people is the same share. The host is
    lowercased because DNS is case-insensitive; the share name is not,
    because on many servers it is not.
    """
    host = _CREDENTIALS.sub("", server).strip().strip("/").lower()
    name = share.strip().strip("/")
    return f"{host}/{name}" if name else host


def share_host(identity_value: str) -> str:
    """The host half of a sanitized ``server/share`` value."""
    return identity_value.split("/", 1)[0]


def share_name(identity_value: str) -> str:
    """The share half of a sanitized ``server/share`` value."""
    parts = identity_value.split("/", 1)
    return parts[1] if len(parts) > 1 else ""


def share_identity_from_device(
    device: str, fstype: str, provenance: str
) -> DestinationIdentity | None:
    """Parse a mount device string into a share identity, or ``None``.

    Handles the two shapes in practice:

    - SMB/AFP: ``//user@server/share`` or ``//server/share``
    - NFS: ``server:/export/path``

    A device string that names neither is not a share, and inventing an
    identity from it would be exactly the "reused mount path as identity"
    the spec forbids.
    """
    if fstype.lower() not in NETWORK_FILESYSTEMS:
        return None
    text = device.strip()
    if text.startswith("//"):
        body = text[2:]
        if "/" not in body:
            return None
        server, share = body.split("/", 1)
        value = sanitize_share(server, share)
    elif ":" in text and not text.startswith("/"):
        server, export = text.split(":", 1)
        value = sanitize_share(server, export)
    else:
        return None
    if not share_host(value):
        return None
    return DestinationIdentity(
        kind="server_share",
        value=value,
        confidence="strong",
        provenance=provenance,
    )


# ---------------------------------------------------------------------------
# macOS
# ---------------------------------------------------------------------------


def parse_diskutil_plist(payload: bytes, mount_path: str) -> DestinationIdentity | None:
    """Identity from one ``diskutil info -plist <mount>`` payload.

    ``VolumeUUID`` is the filesystem and is strong. ``DiskUUID`` names
    the media and is only medium: reformatting a disk keeps it, so a
    match is evidence the *hardware* came back, not that the saved
    filesystem did.
    """
    try:
        info = plistlib.loads(payload)
    except Exception:
        return None
    if not isinstance(info, dict):
        return None
    volume_uuid = info.get("VolumeUUID")
    if isinstance(volume_uuid, str) and volume_uuid.strip():
        return DestinationIdentity(
            kind="volume_uuid",
            value=volume_uuid.strip().lower(),
            confidence="strong",
            provenance=f"macos.diskutil:VolumeUUID:{mount_path}",
        )
    disk_uuid = info.get("DiskUUID")
    if isinstance(disk_uuid, str) and disk_uuid.strip():
        return DestinationIdentity(
            kind="disk_uuid",
            value=disk_uuid.strip().lower(),
            confidence="medium",
            provenance=f"macos.diskutil:DiskUUID:{mount_path}",
        )
    return None


def parse_macos_mount_table(text: str) -> dict[str, tuple[str, str]]:
    """Map mount point -> ``(device, fstype)`` from ``/sbin/mount`` output.

    Lines look like::

        //alice@nas.local/media on /Volumes/media (smbfs, nodev, nosuid)
        /dev/disk3s1 on /Volumes/Backup (apfs, local, journaled)

    A mount point containing " on " or parentheses is unusual but legal,
    so the split is anchored on the *last* " on " and the *last* " (".
    """
    out: dict[str, tuple[str, str]] = {}
    for line in text.splitlines():
        if " on " not in line:
            continue
        device, _, rest = line.rpartition(" on ")
        head, sep, tail = rest.rpartition(" (")
        if not sep:
            continue
        mount_point = head.strip()
        fstype = tail.split(",")[0].strip().rstrip(")")
        if mount_point:
            out[mount_point] = (device.strip(), fstype)
    return out


# ---------------------------------------------------------------------------
# Linux
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MountInfoEntry:
    """One row of ``/proc/self/mountinfo`` that we care about."""

    mount_point: str
    fstype: str
    source: str


def parse_linux_mountinfo(text: str) -> list[MountInfoEntry]:
    """Parse ``/proc/self/mountinfo``.

    Format: fields up to a ``-`` separator, then ``fstype source
    super_options``. The mount point is field 5 and is octal-escaped for
    spaces and other awkward characters, which is how Unicode and spaced
    mount paths stay correct (spec §5.2).
    """
    entries: list[MountInfoEntry] = []
    for line in text.splitlines():
        if " - " not in line:
            continue
        left, _, right = line.partition(" - ")
        left_fields = left.split()
        right_fields = right.split()
        if len(left_fields) < 5 or len(right_fields) < 2:
            continue
        entries.append(
            MountInfoEntry(
                mount_point=_unescape_octal(left_fields[4]),
                fstype=right_fields[0],
                source=_unescape_octal(right_fields[1]),
            )
        )
    return entries


def _unescape_octal(value: str) -> str:
    """Decode the ``\\040``-style escapes the kernel writes for mount paths."""
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), value)


def linux_identity(
    entry: MountInfoEntry, uuid_by_device: dict[str, str]
) -> DestinationIdentity | None:
    """Identity for one Linux mount, from its source device or share."""
    share = share_identity_from_device(
        entry.source, entry.fstype, f"linux.mountinfo:{entry.mount_point}"
    )
    if share is not None:
        return share
    uuid = uuid_by_device.get(entry.source)
    if uuid:
        return DestinationIdentity(
            kind="volume_uuid",
            value=uuid.strip().lower(),
            confidence="strong",
            provenance=f"linux.by-uuid:{entry.mount_point}",
        )
    return None


def read_uuid_map(by_uuid_dir: Path) -> dict[str, str]:
    """Map resolved device path -> filesystem UUID from ``/dev/disk/by-uuid``."""
    out: dict[str, str] = {}
    try:
        children = list(by_uuid_dir.iterdir())
    except OSError:
        return out
    for link in children:
        try:
            out[str(link.resolve())] = link.name
        except OSError:
            continue
    return out


# ---------------------------------------------------------------------------
# probes
# ---------------------------------------------------------------------------


def path_only_identity(mount_path: str) -> DestinationIdentity:
    """The honest fallback: we know where it is mounted and nothing else.

    Returned so the caller can *show* that identity is unavailable here.
    It is weak by construction and the resolver will never rebind on it.
    """
    return DestinationIdentity(
        kind="path_only",
        value=str(mount_path),
        confidence="weak",
        provenance=f"{platform.system().lower() or 'unknown'}.path-only",
    )


class NullIdentityProbe:
    """A probe for platforms we cannot interrogate. Honest, not silent."""

    def identify(self, mount_paths: list[str]) -> ProbeResult:
        system = platform.system() or "this platform"
        return ProbeResult(
            identities={p: path_only_identity(p) for p in mount_paths},
            warnings=[
                f"{system} does not expose durable volume identity to Ferry, so saved "
                "destinations on it must be confirmed by hand each time they are rebound"
            ],
            degraded=True,
        )


class MacOSIdentityProbe:
    """``diskutil`` for local volumes, the mount table for network shares."""

    def __init__(self, *, budget: float = PROBE_BUDGET_SECONDS) -> None:
        self._budget = budget

    def identify(self, mount_paths: list[str]) -> ProbeResult:
        identities: dict[str, DestinationIdentity] = {}
        warnings: list[str] = []
        degraded = False

        mount_table: dict[str, tuple[str, str]] = {}
        try:
            mount_table = parse_macos_mount_table(self._run(["/sbin/mount"]))
        except _ProbeError as exc:
            warnings.append(f"could not read the mount table: {exc}")
            degraded = True

        for mount_path in mount_paths:
            device, fstype = mount_table.get(mount_path, ("", ""))
            share = share_identity_from_device(device, fstype, f"macos.mount:{mount_path}")
            if share is not None:
                identities[mount_path] = share
                continue
            try:
                payload = self._run_bytes(["/usr/sbin/diskutil", "info", "-plist", mount_path])
            except _ProbeError as exc:
                warnings.append(f"identity probe failed for {mount_path}: {exc}")
                degraded = True
                continue
            identity = parse_diskutil_plist(payload, mount_path)
            if identity is None:
                identities[mount_path] = path_only_identity(mount_path)
                warnings.append(
                    f"{mount_path} reports no volume UUID; it can only be recognized by "
                    "explicit confirmation"
                )
            else:
                identities[mount_path] = identity
        return ProbeResult(identities=identities, warnings=warnings, degraded=degraded)

    def _run(self, argv: list[str]) -> str:
        return self._run_bytes(argv).decode("utf-8", "replace")

    def _run_bytes(self, argv: list[str]) -> bytes:
        try:
            completed = subprocess.run(argv, capture_output=True, timeout=self._budget, check=False)
        except subprocess.TimeoutExpired as exc:
            raise _ProbeError(f"timed out after {self._budget:g}s") from exc
        except OSError as exc:
            raise _ProbeError(str(exc)) from exc
        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", "replace").strip() or "non-zero exit"
            raise _ProbeError(detail)
        return completed.stdout


class LinuxIdentityProbe:
    """``/proc/self/mountinfo`` plus ``/dev/disk/by-uuid``."""

    def __init__(
        self,
        *,
        mountinfo: Path = Path("/proc/self/mountinfo"),
        by_uuid: Path = Path("/dev/disk/by-uuid"),
    ) -> None:
        self._mountinfo = mountinfo
        self._by_uuid = by_uuid

    def identify(self, mount_paths: list[str]) -> ProbeResult:
        warnings: list[str] = []
        try:
            text = self._mountinfo.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return ProbeResult(
                identities={},
                warnings=[f"could not read {self._mountinfo}: {exc}"],
                degraded=True,
            )
        uuid_map = read_uuid_map(self._by_uuid)
        by_mount = {e.mount_point: e for e in parse_linux_mountinfo(text)}
        identities: dict[str, DestinationIdentity] = {}
        for mount_path in mount_paths:
            entry = by_mount.get(mount_path)
            identity = linux_identity(entry, uuid_map) if entry is not None else None
            if identity is None:
                identities[mount_path] = path_only_identity(mount_path)
                warnings.append(
                    f"{mount_path} has no filesystem UUID available; it can only be "
                    "recognized by explicit confirmation"
                )
            else:
                identities[mount_path] = identity
        return ProbeResult(identities=identities, warnings=warnings)


class _ProbeError(RuntimeError):
    """A platform probe did not answer within its budget."""


def system_identity_probe() -> IdentityProbe:
    """The probe for the running platform.

    Windows gets the null probe deliberately: Ferry has no tested way to
    read a volume GUID there, and claiming weak evidence is strong would
    be worse than saying so (spec §1.2 — report other platform coverage
    honestly).
    """
    system = platform.system()
    if system == "Darwin":
        return MacOSIdentityProbe()
    if system == "Linux":
        return LinuxIdentityProbe()
    return NullIdentityProbe()


__all__ = [
    "NETWORK_FILESYSTEMS",
    "PROBE_BUDGET_SECONDS",
    "IdentityProbe",
    "LinuxIdentityProbe",
    "MacOSIdentityProbe",
    "MountInfoEntry",
    "NullIdentityProbe",
    "ProbeResult",
    "linux_identity",
    "parse_diskutil_plist",
    "parse_linux_mountinfo",
    "parse_macos_mount_table",
    "path_only_identity",
    "read_uuid_map",
    "sanitize_share",
    "share_host",
    "share_identity_from_device",
    "share_name",
    "system_identity_probe",
]
