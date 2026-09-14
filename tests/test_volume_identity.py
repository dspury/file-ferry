"""Platform identity evidence (spec §5.1, P3).

The parsers are tested against captured platform output rather than a
real disk, so the interesting judgements — what counts as strong
evidence, what gets sanitized away, what we refuse to guess — are
pinned without needing hardware. The probes themselves are tested for
their failure behavior, which is the part that matters: a probe that
times out must degrade honestly, never invent an identity.
"""

from __future__ import annotations

import plistlib
import subprocess
from pathlib import Path

import pytest

from file_ferry.application.volume_identity import (
    LinuxIdentityProbe,
    MacOSIdentityProbe,
    MountInfoEntry,
    NullIdentityProbe,
    linux_identity,
    parse_diskutil_plist,
    parse_linux_mountinfo,
    parse_macos_mount_table,
    path_only_identity,
    sanitize_share,
    share_host,
    share_identity_from_device,
    share_name,
)


class TestShareSanitization:
    """Credentials must never reach the database (spec §4.1)."""

    def test_strips_username(self) -> None:
        assert sanitize_share("alice@nas.local", "media") == "nas.local/media"

    def test_strips_username_and_password(self) -> None:
        value = sanitize_share("alice:hunter2@nas.local", "media")
        assert value == "nas.local/media"
        assert "hunter2" not in value
        assert "alice" not in value

    def test_lowercases_host_but_not_share(self) -> None:
        """DNS is case-insensitive; share names frequently are not."""
        assert sanitize_share("NAS.Local", "Media") == "nas.local/Media"

    def test_splits_host_and_share(self) -> None:
        assert share_host("nas.local/media") == "nas.local"
        assert share_name("nas.local/media") == "media"
        assert share_name("nas.local") == ""


class TestShareIdentityFromDevice:
    def test_smb_with_credentials(self) -> None:
        identity = share_identity_from_device("//alice@nas.local/media", "smbfs", "test")
        assert identity is not None
        assert identity.kind == "server_share"
        assert identity.value == "nas.local/media"
        assert identity.confidence == "strong"

    def test_nfs_export(self) -> None:
        identity = share_identity_from_device("fileserver:/export/video", "nfs", "test")
        assert identity is not None
        assert identity.value == "fileserver/export/video"

    def test_local_filesystem_is_not_a_share(self) -> None:
        """A local device string must not become a fabricated share identity."""
        assert share_identity_from_device("/dev/disk3s1", "apfs", "test") is None

    def test_network_fstype_with_unparseable_device_yields_nothing(self) -> None:
        """Better no identity than one invented from a mount path."""
        assert share_identity_from_device("/Volumes/whatever", "smbfs", "test") is None
        assert share_identity_from_device("//nas.local", "smbfs", "test") is None


class TestDiskutilPlist:
    @staticmethod
    def _plist(**fields: str) -> bytes:
        return plistlib.dumps(dict(fields))

    def test_volume_uuid_is_strong(self) -> None:
        identity = parse_diskutil_plist(
            self._plist(VolumeUUID="ABC-123", DiskUUID="DEF-456"), "/Volumes/X"
        )
        assert identity is not None
        assert identity.kind == "volume_uuid"
        assert identity.value == "abc-123", "identifiers are compared case-insensitively"
        assert identity.confidence == "strong"

    def test_disk_uuid_alone_is_only_medium(self) -> None:
        """A media UUID survives a reformat, so it is not the filesystem."""
        identity = parse_diskutil_plist(self._plist(DiskUUID="DEF-456"), "/Volumes/X")
        assert identity is not None
        assert identity.kind == "disk_uuid"
        assert identity.confidence == "medium"

    def test_no_uuid_yields_nothing(self) -> None:
        assert parse_diskutil_plist(self._plist(VolumeName="X"), "/Volumes/X") is None

    def test_garbage_payload_yields_nothing_rather_than_raising(self) -> None:
        assert parse_diskutil_plist(b"not a plist", "/Volumes/X") is None


class TestMacOSMountTable:
    SAMPLE = (
        "/dev/disk1s5s1 on / (apfs, sealed, local, read-only, journaled)\n"
        "/dev/disk3s1 on /Volumes/Backup (apfs, local, journaled, nobrowse)\n"
        "//alice@nas.local/media on /Volumes/media (smbfs, nodev, nosuid, mounted by alice)\n"
        "map auto_home on /System/Volumes/Data/home (autofs, automounted)\n"
    )

    def test_parses_devices_and_filesystems(self) -> None:
        table = parse_macos_mount_table(self.SAMPLE)
        assert table["/"] == ("/dev/disk1s5s1", "apfs")
        assert table["/Volumes/Backup"] == ("/dev/disk3s1", "apfs")
        assert table["/Volumes/media"] == ("//alice@nas.local/media", "smbfs")

    def test_handles_spaces_and_unicode_in_mount_points(self) -> None:
        """A25: mount paths are not ASCII and not space-free."""
        table = parse_macos_mount_table(
            "/dev/disk4s1 on /Volumes/Björn's Drive (backup) (exfat, local, nodev)\n"
        )
        assert "/Volumes/Björn's Drive (backup)" in table
        assert table["/Volumes/Björn's Drive (backup)"][1] == "exfat"

    def test_ignores_unparseable_lines(self) -> None:
        assert parse_macos_mount_table("garbage without the marker\n") == {}


class TestLinuxMountinfo:
    SAMPLE = (
        "25 1 259:2 / / rw,relatime shared:1 - ext4 /dev/nvme0n1p2 rw\n"
        "40 25 8:17 / /media/dana/Backup rw,nosuid shared:2 - exfat /dev/sdb1 rw\n"
        "52 25 0:52 / /media/dana/My\\040Drive rw shared:3 - vfat /dev/sdc1 rw\n"
        "60 25 0:60 / /mnt/nas rw shared:4 - cifs //alice@nas.local/media rw\n"
    )

    def test_parses_mount_points_and_sources(self) -> None:
        entries = {e.mount_point: e for e in parse_linux_mountinfo(self.SAMPLE)}
        assert entries["/media/dana/Backup"].source == "/dev/sdb1"
        assert entries["/media/dana/Backup"].fstype == "exfat"
        assert entries["/mnt/nas"].fstype == "cifs"

    def test_decodes_octal_escapes_in_mount_paths(self) -> None:
        """A25: the kernel escapes spaces as ``\\040``."""
        entries = {e.mount_point: e for e in parse_linux_mountinfo(self.SAMPLE)}
        assert "/media/dana/My Drive" in entries

    def test_uuid_from_device_is_strong(self) -> None:
        entry = MountInfoEntry(mount_point="/media/x", fstype="exfat", source="/dev/sdb1")
        identity = linux_identity(entry, {"/dev/sdb1": "1234-ABCD"})
        assert identity is not None
        assert identity.kind == "volume_uuid"
        assert identity.value == "1234-abcd"
        assert identity.confidence == "strong"

    def test_share_beats_uuid_lookup_for_network_mounts(self) -> None:
        entry = MountInfoEntry(
            mount_point="/mnt/nas", fstype="cifs", source="//alice@nas.local/media"
        )
        identity = linux_identity(entry, {})
        assert identity is not None
        assert identity.kind == "server_share"
        assert identity.value == "nas.local/media"

    def test_unknown_device_yields_nothing(self) -> None:
        entry = MountInfoEntry(mount_point="/media/x", fstype="exfat", source="/dev/sdb1")
        assert linux_identity(entry, {}) is None


class TestPathOnlyFallback:
    def test_is_always_weak(self) -> None:
        """A mount path is where something is, never what it is."""
        identity = path_only_identity("/Volumes/Backup")
        assert identity.kind == "path_only"
        assert identity.confidence == "weak"
        assert identity.value == "/Volumes/Backup"

    def test_null_probe_reports_the_limitation(self) -> None:
        result = NullIdentityProbe().identify(["/Volumes/A"])
        assert result.degraded is True
        assert result.warnings, "an unsupported platform must say so, not stay silent"
        assert result.identities["/Volumes/A"].confidence == "weak"


class TestProbeFailureBehavior:
    def test_macos_probe_timeout_degrades_without_inventing_identity(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A hung mount must not block discovery or fabricate evidence."""

        def _timeout(*_args: object, **_kwargs: object) -> object:
            raise subprocess.TimeoutExpired(cmd="diskutil", timeout=0.1)

        monkeypatch.setattr(subprocess, "run", _timeout)
        result = MacOSIdentityProbe(budget=0.1).identify(["/Volumes/Slow"])
        assert result.degraded is True
        assert "/Volumes/Slow" not in result.identities, (
            "no evidence is better than guessed evidence"
        )
        assert any("timed out" in w for w in result.warnings)

    def test_linux_probe_without_mountinfo_degrades(self, tmp_path: Path) -> None:
        probe = LinuxIdentityProbe(mountinfo=tmp_path / "absent", by_uuid=tmp_path / "also-absent")
        result = probe.identify(["/media/x"])
        assert result.degraded is True
        assert result.identities == {}
        assert result.warnings

    def test_linux_probe_falls_back_to_path_only_for_unknown_mounts(self, tmp_path: Path) -> None:
        mountinfo = tmp_path / "mountinfo"
        mountinfo.write_text("25 1 259:2 / /media/x rw shared:1 - exfat /dev/sdz9 rw\n")
        probe = LinuxIdentityProbe(mountinfo=mountinfo, by_uuid=tmp_path / "by-uuid")
        result = probe.identify(["/media/x"])
        assert result.identities["/media/x"].confidence == "weak"
        assert any("explicit confirmation" in w for w in result.warnings)
