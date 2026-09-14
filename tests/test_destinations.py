"""Destination service tests (destination-presets spec §4.1, §5).

Pydantic models expose field names for Python attribute access;
serialization uses the camelCase aliases. Tests use the snake_case
attribute names throughout.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from file_ferry.application.destinations import (
    CONFLICT_POLICIES,
    DestinationError,
    DestinationNotFoundError,
    DestinationObservation,
    DestinationService,
)
from file_ferry.service.protocol import (
    DestinationIdentity,
    SaveDestinationParams,
)


def _svc(tmp_path: Path) -> DestinationService:
    from file_ferry.application.service import ApplicationService

    db_path = tmp_path / "ferry.db"
    boot = ApplicationService(db_path=db_path, app_data_dir=tmp_path / "app")
    boot.bootstrap()
    boot.close()
    return DestinationService(db_path)


def test_creates_local_folder_destination(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    summary = svc.save(
        SaveDestinationParams(name="NAS", path=str(tmp_path / "dest"), conflictPolicy="keep_both")
    )
    assert summary.id > 0
    assert summary.name == "NAS"
    assert summary.location_kind == "local_folder"
    assert summary.last_root_path.endswith("dest")


def test_list_excludes_archived_by_default(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    svc.save(SaveDestinationParams(name="A", path=str(tmp_path / "a")))
    b = svc.save(SaveDestinationParams(name="B", path=str(tmp_path / "b")))
    svc.archive(b.id)
    listed = svc.list_destinations().destinations
    names = {d.name for d in listed}
    assert names == {"A"}
    assert "B" not in names
    all_listed = svc.list_destinations(include_archived=True).destinations
    assert {d.name for d in all_listed} == {"A", "B"}


def test_validates_duplicate_name_case_insensitive(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    first = svc.save(SaveDestinationParams(name="NAS", path=str(tmp_path / "a")))
    again = svc.save(SaveDestinationParams(name="nas", path=str(tmp_path / "a2")))
    assert again.id == first.id
    listed = svc.list_destinations().destinations
    assert [d.name for d in listed] == ["NAS"]


def test_rejects_subfolder_with_dotdot(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    with pytest.raises(DestinationError, match="subfolderPath"):
        svc.save(
            SaveDestinationParams(name="X", path=str(tmp_path / "x"), subfolderPath="../escape")
        )


def _identity(
    value: str = "v-uuid",
    *,
    kind: str = "volume_uuid",
    confidence: str = "strong",
) -> DestinationIdentity:
    return DestinationIdentity(
        kind=kind,  # type: ignore[arg-type]
        value=value,
        confidence=confidence,  # type: ignore[arg-type]
        provenance="test",
    )


def _mount(
    path: Path, identity: DestinationIdentity | None = None, **kwargs: object
) -> DestinationObservation:
    """One observed mount point. Observations describe mounts, not folders."""
    return DestinationObservation(
        path=str(path),
        label=path.name,
        identity=identity,
        **kwargs,  # type: ignore[arg-type]
    )


def test_resolve_local_folder_returns_available(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    dest = tmp_path / "nas"
    dest.mkdir()
    saved = svc.save(SaveDestinationParams(name="NAS", path=str(dest)))
    resolutions = svc.resolve(destination_id=saved.id).resolutions
    assert len(resolutions) == 1
    assert resolutions[0].status == "available"
    assert resolutions[0].binding_path is not None


def test_resolve_offline_when_path_missing(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    saved = svc.save(SaveDestinationParams(name="Ghost", path=str(tmp_path / "nope")))
    resolution = svc.resolve(destination_id=saved.id).resolutions[0]
    assert resolution.status == "offline"
    assert "never recreates" in resolution.reason, (
        "§5.1: a vanished folder must not be recreated on a different filesystem"
    )


def test_a13_same_volume_remounted_at_a_new_path_resolves(tmp_path: Path) -> None:
    """A13: strong identity plus the relative subfolder finds it again.

    The volume was saved at one mount path and comes back at another —
    the everyday case on macOS, where a second mount of ``Backup``
    becomes ``Backup 1``. Identity is what carries across; the saved
    subfolder is then resolved *within* the matched mount.
    """
    svc = _svc(tmp_path)
    first_mount = tmp_path / "Volumes" / "Backup"
    (first_mount / "Projects").mkdir(parents=True)
    saved = svc.save(
        SaveDestinationParams(
            name="Backup",
            path=str(first_mount / "Projects"),
            locationKind="volume_folder",
            subfolderPath="Projects",
        )
    )
    svc.confirm_binding(saved.id, path=str(first_mount / "Projects"), identity=_identity())

    # Same disk, new mount point.
    second_mount = tmp_path / "Volumes" / "Backup 1"
    (second_mount / "Projects").mkdir(parents=True)
    resolution = svc.resolve(
        destination_id=saved.id, observations=[_mount(second_mount, _identity())]
    ).resolutions[0]
    assert resolution.status == "available"
    assert resolution.binding_path == str(second_mount / "Projects")


def test_subfolder_missing_inside_a_matched_volume_needs_confirmation(tmp_path: Path) -> None:
    """The disk is right but the folder is gone; never create one silently."""
    svc = _svc(tmp_path)
    mount = tmp_path / "vol"
    mount.mkdir()
    saved = svc.save(
        SaveDestinationParams(
            name="Vol",
            path=str(mount / "Projects"),
            locationKind="volume_folder",
            subfolderPath="Projects",
        )
    )
    svc.confirm_binding(saved.id, path=str(mount / "Projects"), identity=_identity())
    resolution = svc.resolve(
        destination_id=saved.id, observations=[_mount(mount, _identity())]
    ).resolutions[0]
    assert resolution.status == "needs_confirmation"
    assert "does not create a destination folder" in resolution.reason


def test_a14_a_different_drive_reusing_the_label_does_not_match(tmp_path: Path) -> None:
    """A14: same name, same mount path, different disk — no rebinding.

    A label and a mount path are what the *last* thing plugged in
    happened to be called. Rebinding on them writes the transfer to
    whatever drive is in the slot.
    """
    svc = _svc(tmp_path)
    mount = tmp_path / "Volumes" / "Backup"
    mount.mkdir(parents=True)
    saved = svc.save(
        SaveDestinationParams(name="Backup", path=str(mount), locationKind="volume_folder")
    )
    svc.confirm_binding(saved.id, path=str(mount), identity=_identity("the-real-disk"))

    imposter = _mount(mount, _identity("a-different-disk"))
    resolution = svc.resolve(destination_id=saved.id, observations=[imposter]).resolutions[0]
    assert resolution.status == "needs_confirmation"
    assert resolution.binding_path is None, "never bind automatically to an unmatched device"
    assert "does not match" in resolution.reason
    assert "A different disk or share is in that place" in resolution.reason


def test_a14_duplicate_identity_across_two_devices_is_ambiguous(tmp_path: Path) -> None:
    """A14: two devices presenting one identifier is not a tie to break."""
    svc = _svc(tmp_path)
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    saved = svc.save(SaveDestinationParams(name="Dup", path=str(a), locationKind="volume_folder"))
    svc.confirm_binding(saved.id, path=str(a), identity=_identity("X"))
    resolution = svc.resolve(
        destination_id=saved.id,
        observations=[_mount(a, _identity("X")), _mount(b, _identity("X"))],
    ).resolutions[0]
    assert resolution.status == "ambiguous"
    assert resolution.binding_path is None
    assert sorted(resolution.candidate_paths) == sorted([str(a), str(b)])


def test_medium_confidence_identity_only_needs_confirmation(tmp_path: Path) -> None:
    """A disk UUID says the hardware came back, not the filesystem."""
    svc = _svc(tmp_path)
    mount = tmp_path / "v"
    mount.mkdir()
    saved = svc.save(
        SaveDestinationParams(name="Vol", path=str(mount), locationKind="volume_folder")
    )
    svc.confirm_binding(saved.id, path=str(mount), identity=_identity("d-uuid", kind="disk_uuid"))
    observed = _mount(mount, _identity("d-uuid", kind="disk_uuid", confidence="medium"))
    resolution = svc.resolve(destination_id=saved.id, observations=[observed]).resolutions[0]
    assert resolution.status == "needs_confirmation"
    assert "not enough to rebind automatically" in resolution.reason


def test_a12_unmounted_share_leaves_its_directory_and_must_not_be_used(
    tmp_path: Path,
) -> None:
    """A12: the mount directory survives the unmount. Do not write into it.

    This is the failure that fills a boot disk while reporting a
    successful transfer to the NAS.
    """
    svc = _svc(tmp_path)
    mount = tmp_path / "Volumes" / "media"
    mount.mkdir(parents=True)
    saved = svc.save(
        SaveDestinationParams(name="Share", path=str(mount), locationKind="mounted_share_folder")
    )
    svc.confirm_binding(
        saved.id,
        path=str(mount),
        identity=_identity("nas.local/media", kind="server_share"),
    )
    # The share is gone; the empty directory it was mounted on is not.
    assert mount.is_dir()
    resolution = svc.resolve(
        destination_id=saved.id, observations=[_mount(tmp_path / "other", _identity("elsewhere"))]
    ).resolutions[0]
    assert resolution.status == "needs_confirmation"
    assert resolution.binding_path is None, "refuse to bind to the leftover local directory"
    assert "left behind on the local disk" in resolution.reason


def test_share_on_a_different_host_needs_confirmation(tmp_path: Path) -> None:
    """§5.1: host aliases without established equivalence require confirmation."""
    svc = _svc(tmp_path)
    mount = tmp_path / "media"
    mount.mkdir()
    saved = svc.save(
        SaveDestinationParams(name="Share", path=str(mount), locationKind="mounted_share_folder")
    )
    svc.confirm_binding(
        saved.id,
        path=str(mount),
        identity=_identity("nas.local/media", kind="server_share"),
    )
    by_ip = _mount(mount, _identity("192.168.1.10/media", kind="server_share"))
    resolution = svc.resolve(destination_id=saved.id, observations=[by_ip]).resolutions[0]
    assert resolution.status == "needs_confirmation"
    assert "different host" in resolution.reason
    assert resolution.binding_path is None


def test_matching_share_resolves_available(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    mount = tmp_path / "media"
    (mount / "Footage").mkdir(parents=True)
    saved = svc.save(
        SaveDestinationParams(
            name="Share",
            path=str(mount / "Footage"),
            locationKind="mounted_share_folder",
            subfolderPath="Footage",
        )
    )
    identity = _identity("nas.local/media", kind="server_share")
    svc.confirm_binding(saved.id, path=str(mount / "Footage"), identity=identity)
    resolution = svc.resolve(
        destination_id=saved.id, observations=[_mount(mount, identity)]
    ).resolutions[0]
    assert resolution.status == "available"
    assert resolution.binding_path == str(mount / "Footage")


def test_read_only_matched_storage_is_unwritable(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    mount = tmp_path / "vol"
    mount.mkdir()
    saved = svc.save(
        SaveDestinationParams(name="RO", path=str(mount), locationKind="volume_folder")
    )
    svc.confirm_binding(saved.id, path=str(mount), identity=_identity())
    resolution = svc.resolve(
        destination_id=saved.id,
        observations=[_mount(mount, _identity(), is_writable=False)],
    ).resolutions[0]
    assert resolution.status == "unwritable"


def test_nothing_connected_is_offline_not_available(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    saved = svc.save(
        SaveDestinationParams(
            name="Gone", path=str(tmp_path / "absent"), locationKind="volume_folder"
        )
    )
    svc.confirm_binding(saved.id, path=str(tmp_path / "absent"), identity=_identity())
    resolution = svc.resolve(destination_id=saved.id, observations=[]).resolutions[0]
    assert resolution.status == "offline"


def test_without_observations_an_existing_path_is_not_trusted(tmp_path: Path) -> None:
    """A path that exists proves nothing about which device is mounted there."""
    svc = _svc(tmp_path)
    mount = tmp_path / "vol"
    mount.mkdir()
    saved = svc.save(
        SaveDestinationParams(name="Vol", path=str(mount), locationKind="volume_folder")
    )
    svc.confirm_binding(saved.id, path=str(mount), identity=_identity())
    resolution = svc.resolve(destination_id=saved.id, observations=[]).resolutions[0]
    assert resolution.status == "needs_confirmation"
    assert "no storage observations are available" in resolution.reason


def test_a25_spaces_and_unicode_in_mount_paths_resolve(tmp_path: Path) -> None:
    """A25: mount paths are not ASCII and not space-free."""
    svc = _svc(tmp_path)
    mount = tmp_path / "Björn's Drive (backup)"
    (mount / "Métrage vidéo").mkdir(parents=True)
    saved = svc.save(
        SaveDestinationParams(
            name="Unicode",
            path=str(mount / "Métrage vidéo"),
            locationKind="volume_folder",
            subfolderPath="Métrage vidéo",
        )
    )
    svc.confirm_binding(saved.id, path=str(mount / "Métrage vidéo"), identity=_identity())
    resolution = svc.resolve(
        destination_id=saved.id, observations=[_mount(mount, _identity())]
    ).resolutions[0]
    assert resolution.status == "available"
    assert resolution.binding_path == str(mount / "Métrage vidéo")


def test_rebinding_requires_an_explicit_user_action(tmp_path: Path) -> None:
    """§5.1: recognition never rebinds by itself; confirmation does."""
    svc = _svc(tmp_path)
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    saved = svc.save(
        SaveDestinationParams(name="Move", path=str(old), locationKind="volume_folder")
    )
    svc.confirm_binding(saved.id, path=str(old), identity=_identity())

    # Resolving against the new location reports it, but changes nothing.
    resolution = svc.resolve(
        destination_id=saved.id, observations=[_mount(new, _identity())]
    ).resolutions[0]
    assert resolution.status == "available"
    assert svc.get(saved.id).last_binding_path == str(old), (
        "resolve is an observation; it must not write the new binding"
    )

    updated = svc.confirm_binding(saved.id, path=str(new), identity=_identity())
    assert updated.last_binding_path == str(new)


def test_confirm_binding_records_identity(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    saved = svc.save(SaveDestinationParams(name="D", path=str(tmp_path / "d")))
    updated = svc.confirm_binding(
        saved.id,
        path=str(tmp_path / "d"),
        identity=DestinationIdentity(
            kind="volume_uuid", value="V", confidence="strong", provenance="p"
        ),
    )
    assert updated.identity is not None
    assert updated.identity.value == "V"


def test_archive_unknown_raises(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    with pytest.raises(DestinationNotFoundError):
        svc.archive(9999)


def test_policies_exposed() -> None:
    assert "keep_both" in CONFLICT_POLICIES
    assert "needs_review" in CONFLICT_POLICIES


class TestStaleEvidenceIsNotAuthority:
    """R10: remembered identity shows history, never current recognition."""

    def test_reused_identity_after_a_failed_probe_needs_confirmation(self, tmp_path: Path) -> None:
        """A drive can be swapped between two observations.

        Not having witnessed an unmount establishes nothing about
        continuity, so evidence that was remembered rather than read
        must not authorize a rebinding — otherwise a replacement drive
        at the same mount path is recognized as the previous one and
        written to.
        """
        svc = _svc(tmp_path)
        mount = tmp_path / "vol"
        mount.mkdir()
        saved = svc.save(
            SaveDestinationParams(name="V", path=str(mount), locationKind="volume_folder")
        )
        svc.confirm_binding(saved.id, path=str(mount), identity=_identity("ORIGINAL"))

        fresh = _identity("ORIGINAL")
        assert (
            svc.resolve(destination_id=saved.id, observations=[_mount(mount, fresh)])
            .resolutions[0]
            .status
            == "available"
        )

        remembered = fresh.model_copy(update={"stale": True, "observed_at": "2026-09-01T00:00:00Z"})
        resolution = svc.resolve(
            destination_id=saved.id, observations=[_mount(mount, remembered)]
        ).resolutions[0]
        assert resolution.status == "needs_confirmation"
        assert resolution.binding_path is None
        assert "remembered from an earlier observation" in resolution.reason

    def test_recovers_to_available_after_a_fresh_successful_probe(self, tmp_path: Path) -> None:
        """Degradation is not sticky; a good probe restores recognition."""
        svc = _svc(tmp_path)
        mount = tmp_path / "vol"
        mount.mkdir()
        saved = svc.save(
            SaveDestinationParams(name="V", path=str(mount), locationKind="volume_folder")
        )
        svc.confirm_binding(saved.id, path=str(mount), identity=_identity("X"))
        stale = _identity("X").model_copy(update={"stale": True})
        assert (
            svc.resolve(destination_id=saved.id, observations=[_mount(mount, stale)])
            .resolutions[0]
            .status
            == "needs_confirmation"
        )
        assert (
            svc.resolve(destination_id=saved.id, observations=[_mount(mount, _identity("X"))])
            .resolutions[0]
            .status
            == "available"
        )

    def test_a_replacement_drive_at_the_same_path_is_never_the_original(
        self, tmp_path: Path
    ) -> None:
        """The scenario R10 names: swap, then a failed probe."""
        svc = _svc(tmp_path)
        mount = tmp_path / "vol"
        mount.mkdir()
        saved = svc.save(
            SaveDestinationParams(name="V", path=str(mount), locationKind="volume_folder")
        )
        svc.confirm_binding(saved.id, path=str(mount), identity=_identity("ORIGINAL"))
        # The replacement is correctly identified: plainly not a match.
        replacement = svc.resolve(
            destination_id=saved.id, observations=[_mount(mount, _identity("REPLACEMENT"))]
        ).resolutions[0]
        assert replacement.status == "needs_confirmation"
        assert replacement.binding_path is None
        # And when the probe cannot read the replacement at all, the
        # remembered ORIGINAL must not stand in for it.
        remembered = _identity("ORIGINAL").model_copy(update={"stale": True})
        blind = svc.resolve(
            destination_id=saved.id, observations=[_mount(mount, remembered)]
        ).resolutions[0]
        assert blind.status == "needs_confirmation"
        assert blind.binding_path is None


class TestSubfolderContainment:
    """R11: a matched volume does not vouch for a folder inside it."""

    def test_subfolder_symlink_escaping_the_volume_is_refused(self, tmp_path: Path) -> None:
        """The write would land off the recognized storage entirely."""
        svc = _svc(tmp_path)
        mount = tmp_path / "vol"
        mount.mkdir()
        outside = tmp_path / "somewhere_else"
        outside.mkdir()
        (mount / "Projects").symlink_to(outside, target_is_directory=True)
        saved = svc.save(
            SaveDestinationParams(
                name="Escape",
                path=str(mount / "Projects"),
                locationKind="volume_folder",
                subfolderPath="Projects",
            )
        )
        svc.confirm_binding(saved.id, path=str(mount / "Projects"), identity=_identity())
        resolution = svc.resolve(
            destination_id=saved.id, observations=[_mount(mount, _identity())]
        ).resolutions[0]
        assert resolution.status == "needs_confirmation"
        assert resolution.binding_path is None
        assert "outside the recognized storage" in resolution.reason

    def test_a_symlinked_subfolder_staying_inside_the_volume_is_fine(self, tmp_path: Path) -> None:
        """Containment is the rule, not a ban on links (§5.1)."""
        svc = _svc(tmp_path)
        mount = tmp_path / "vol"
        (mount / "real").mkdir(parents=True)
        (mount / "Projects").symlink_to(mount / "real", target_is_directory=True)
        saved = svc.save(
            SaveDestinationParams(
                name="Inside",
                path=str(mount / "Projects"),
                locationKind="volume_folder",
                subfolderPath="Projects",
            )
        )
        svc.confirm_binding(saved.id, path=str(mount / "Projects"), identity=_identity())
        resolution = svc.resolve(
            destination_id=saved.id, observations=[_mount(mount, _identity())]
        ).resolutions[0]
        assert resolution.status == "available"

    def test_a_different_filesystem_mounted_inside_the_volume_is_refused(
        self, tmp_path: Path
    ) -> None:
        """A nested mount is invisible in the path but changes the storage."""
        svc = _svc(tmp_path)
        mount = tmp_path / "vol"
        (mount / "Projects").mkdir(parents=True)
        saved = svc.save(
            SaveDestinationParams(
                name="Nested",
                path=str(mount / "Projects"),
                locationKind="volume_folder",
                subfolderPath="Projects",
            )
        )
        svc.confirm_binding(saved.id, path=str(mount / "Projects"), identity=_identity())
        # Real nested mounts need root; the device id is what the check
        # actually reads, so state it directly.
        observation = _mount(mount, _identity())
        observation.device_id = (observation.device_id or 0) + 1
        resolution = svc.resolve(destination_id=saved.id, observations=[observation]).resolutions[0]
        assert resolution.status == "needs_confirmation"
        assert "different filesystem" in resolution.reason

    def test_a_local_folder_whose_backing_disk_changed_needs_confirmation(
        self, tmp_path: Path
    ) -> None:
        """R11: a local folder is bound by path, but a path is not storage."""
        svc = _svc(tmp_path)
        folder = tmp_path / "local"
        folder.mkdir()
        saved = svc.save(SaveDestinationParams(name="L", path=str(folder)))
        svc.confirm_binding(saved.id, path=str(folder), identity=_identity("ORIGINAL-DISK"))

        # The same path, now on storage reporting a different identity.
        moved = _mount(tmp_path, _identity("A-DIFFERENT-DISK"))
        resolution = svc.resolve(destination_id=saved.id, observations=[moved]).resolutions[0]
        assert resolution.status == "needs_confirmation"
        assert "backing disk appears to have changed" in resolution.reason

    def test_a_local_folder_on_its_saved_storage_stays_available(self, tmp_path: Path) -> None:
        svc = _svc(tmp_path)
        folder = tmp_path / "local"
        folder.mkdir()
        saved = svc.save(SaveDestinationParams(name="L", path=str(folder)))
        svc.confirm_binding(saved.id, path=str(folder), identity=_identity("DISK"))
        resolution = svc.resolve(
            destination_id=saved.id, observations=[_mount(tmp_path, _identity("DISK"))]
        ).resolutions[0]
        assert resolution.status == "available"


class TestConfirmBindingConsistency:
    """R11: a recorded binding must not contradict itself."""

    def test_contradictory_path_and_identity_are_refused(self, tmp_path: Path) -> None:
        svc = _svc(tmp_path)
        mount = tmp_path / "vol"
        (mount / "Projects").mkdir(parents=True)
        saved = svc.save(
            SaveDestinationParams(
                name="V", path=str(mount / "Projects"), locationKind="volume_folder"
            )
        )
        with pytest.raises(DestinationError, match="path and identity disagree"):
            svc.confirm_binding(
                saved.id,
                path=str(mount / "Projects"),
                identity=_identity("CLAIMED"),
                observations=[_mount(mount, _identity("ACTUALLY-THIS"))],
            )
        assert svc.get(saved.id).identity is None

    def test_subfolder_is_derived_from_the_mount_it_was_confirmed_on(self, tmp_path: Path) -> None:
        """Mount, subfolder, and binding stay consistent, so a remount resolves."""
        svc = _svc(tmp_path)
        mount = tmp_path / "vol"
        (mount / "Media" / "Footage").mkdir(parents=True)
        saved = svc.save(
            SaveDestinationParams(name="V", path=str(mount), locationKind="volume_folder")
        )
        updated = svc.confirm_binding(
            saved.id,
            path=str(mount / "Media" / "Footage"),
            identity=_identity(),
            observations=[_mount(mount, _identity())],
        )
        assert updated.subfolder_path == "Media/Footage"

    def test_confirming_without_observations_still_works(self, tmp_path: Path) -> None:
        """The escape hatch for storage the platform cannot identify (§5.1)."""
        svc = _svc(tmp_path)
        folder = tmp_path / "unknown-storage"
        folder.mkdir()
        saved = svc.save(SaveDestinationParams(name="U", path=str(folder)))
        updated = svc.confirm_binding(
            saved.id, path=str(folder), identity=_identity("operator-says-so")
        )
        assert updated.identity is not None
        assert updated.identity.value == "operator-says-so"
        assert "confirmed by user" in updated.identity.provenance


class TestLocalFolderBackingEvidence:
    """R12: `local_folder` is the default kind and gets the same rules.

    Once identity evidence has been recorded for a local folder,
    recognizing it again requires fresh, strong, matching evidence.
    Absence of contradiction is not confirmation: a folder whose disk was
    swapped looks exactly like one whose discovery has not run yet.
    """

    @staticmethod
    def _confirmed(tmp_path: Path, value: str = "ORIGINAL") -> tuple[DestinationService, int, Path]:
        svc = _svc(tmp_path)
        folder = tmp_path / "local"
        folder.mkdir()
        saved = svc.save(SaveDestinationParams(name="L", path=str(folder)))
        svc.confirm_binding(saved.id, path=str(folder), identity=_identity(value))
        return svc, saved.id, folder

    def test_no_observations_is_not_confirmation(self, tmp_path: Path) -> None:
        svc, dest_id, _ = self._confirmed(tmp_path)
        resolution = svc.resolve(destination_id=dest_id, observations=[]).resolutions[0]
        assert resolution.status == "needs_confirmation"
        assert "no storage observations are available" in resolution.reason

    def test_an_undeterminable_owner_is_not_confirmation(self, tmp_path: Path) -> None:
        svc, dest_id, _ = self._confirmed(tmp_path)
        elsewhere = _mount(tmp_path / "unrelated", _identity("SOMETHING-ELSE"))
        resolution = svc.resolve(destination_id=dest_id, observations=[elsewhere]).resolutions[0]
        assert resolution.status == "needs_confirmation"
        assert "could not determine which connected storage" in resolution.reason

    def test_stale_matching_evidence_is_not_confirmation(self, tmp_path: Path) -> None:
        """R10 applies identically here: a drive can be swapped."""
        svc, dest_id, _ = self._confirmed(tmp_path)
        stale = _identity("ORIGINAL").model_copy(update={"stale": True})
        resolution = svc.resolve(
            destination_id=dest_id, observations=[_mount(tmp_path, stale)]
        ).resolutions[0]
        assert resolution.status == "needs_confirmation"
        assert "remembered from an earlier observation" in resolution.reason

    def test_weak_matching_evidence_is_not_confirmation(self, tmp_path: Path) -> None:
        svc, dest_id, _ = self._confirmed(tmp_path)
        weak = _identity("ORIGINAL", confidence="weak")
        resolution = svc.resolve(
            destination_id=dest_id, observations=[_mount(tmp_path, weak)]
        ).resolutions[0]
        assert resolution.status == "needs_confirmation"

    def test_a_different_identity_is_refused(self, tmp_path: Path) -> None:
        svc, dest_id, _ = self._confirmed(tmp_path)
        resolution = svc.resolve(
            destination_id=dest_id, observations=[_mount(tmp_path, _identity("REPLACEMENT"))]
        ).resolutions[0]
        assert resolution.status == "needs_confirmation"
        assert "backing disk appears to have changed" in resolution.reason

    def test_a_fresh_strong_match_resolves_available(self, tmp_path: Path) -> None:
        """The supported case must keep working."""
        svc, dest_id, _ = self._confirmed(tmp_path)
        resolution = svc.resolve(
            destination_id=dest_id, observations=[_mount(tmp_path, _identity("ORIGINAL"))]
        ).resolutions[0]
        assert resolution.status == "available"

    def test_a_never_confirmed_local_folder_stays_usable(self, tmp_path: Path) -> None:
        """Ordinary local-folder usage must not require confirmation.

        Nothing was ever recorded about this folder's storage, so there
        is nothing to contradict — the explicit path binding is the whole
        of what the user asked for.
        """
        svc = _svc(tmp_path)
        folder = tmp_path / "plain"
        folder.mkdir()
        saved = svc.save(SaveDestinationParams(name="Plain", path=str(folder)))
        assert (
            svc.resolve(destination_id=saved.id, observations=[]).resolutions[0].status
            == "available"
        )

    def test_a_path_only_confirmation_is_honored_but_scoped(self, tmp_path: Path) -> None:
        """§5.1's escape hatch for storage the platform cannot identify.

        It stays valid while the platform still cannot identify the
        storage, and expires the moment it can — so a path confirmation
        never becomes permanent authority over whatever later occupies
        the path.
        """
        svc = _svc(tmp_path)
        folder = tmp_path / "unidentifiable"
        folder.mkdir()
        saved = svc.save(SaveDestinationParams(name="PathOnly", path=str(folder)))
        svc.confirm_binding(
            saved.id,
            path=str(folder),
            identity=_identity(str(folder), kind="path_only", confidence="weak"),
        )
        still_unknown = _mount(
            tmp_path, _identity(str(tmp_path), kind="path_only", confidence="weak")
        )
        assert (
            svc.resolve(destination_id=saved.id, observations=[still_unknown]).resolutions[0].status
            == "available"
        )

        now_known = _mount(tmp_path, _identity("REAL-UUID-AVAILABLE-NOW"))
        upgraded = svc.resolve(destination_id=saved.id, observations=[now_known]).resolutions[0]
        assert upgraded.status == "needs_confirmation"
        assert "confirmed by path alone" in upgraded.reason
