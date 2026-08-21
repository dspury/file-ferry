"""Tests for the volume observation adapter.

The adapter is the tested boundary between the application and the
platform (plan §8.1, §10.6.2). The tests inject a fake ``VolumeAdapter``
into the observer to prove the snapshot-diff logic without touching the
real mount table, and exercise the real ``SystemVolumeAdapter`` shape.
"""

from __future__ import annotations

from file_ferry.application.volumes import (
    SystemVolumeAdapter,
    VolumeChange,
    VolumeObserver,
)
from file_ferry.service.protocol import MountedVolume


def _volume(path: str, label: str) -> MountedVolume:
    return MountedVolume(
        path=path,
        label=label,
        totalBytes=1_000,
        freeBytes=500,
        filesystem="apfs",
    )


class FakeAdapter:
    """A scripted ``VolumeAdapter`` for the observer tests."""

    def __init__(self, initial: list[MountedVolume]) -> None:
        self._volumes = list(initial)

    def set(self, volumes: list[MountedVolume]) -> None:
        self._volumes = list(volumes)

    def list_volumes(self) -> list[MountedVolume]:
        return list(self._volumes)


class TestVolumeObserver:
    def test_first_poll_is_empty_baseline(self) -> None:
        adapter = FakeAdapter([_volume("/Volumes/A", "A")])
        observer = VolumeObserver(adapter)
        change = observer.poll()
        assert not change.changed
        assert change.mounted == []
        assert change.unmounted == []

    def test_detects_mount(self) -> None:
        adapter = FakeAdapter([_volume("/Volumes/A", "A")])
        observer = VolumeObserver(adapter)
        observer.poll()  # baseline
        new = _volume("/Volumes/B", "B")
        adapter.set([_volume("/Volumes/A", "A"), new])
        change = observer.poll()
        assert change.changed
        assert [v.path for v in change.mounted] == ["/Volumes/B"]
        assert change.unmounted == []

    def test_detects_unmount(self) -> None:
        adapter = FakeAdapter([_volume("/Volumes/A", "A"), _volume("/Volumes/B", "B")])
        observer = VolumeObserver(adapter)
        observer.poll()  # baseline
        adapter.set([_volume("/Volumes/A", "A")])
        change = observer.poll()
        assert change.changed
        assert change.mounted == []
        assert change.unmounted == ["/Volumes/B"]

    def test_no_change_when_identical(self) -> None:
        adapter = FakeAdapter([_volume("/Volumes/A", "A")])
        observer = VolumeObserver(adapter)
        observer.poll()
        change = observer.poll()
        assert not change.changed

    def test_observer_accepts_any_adapter_protocol(self) -> None:
        """The observer takes the testable VolumeAdapter interface."""
        adapter = FakeAdapter([])
        observer = VolumeObserver(adapter)
        assert observer.snapshot() == []

    def test_snapshot_updates_baseline(self) -> None:
        adapter = FakeAdapter([_volume("/Volumes/A", "A")])
        observer = VolumeObserver(adapter)
        assert [v.path for v in observer.snapshot()] == ["/Volumes/A"]
        # After snapshot, the next poll sees no change.
        change = observer.poll()
        assert not change.changed


class TestVolumeChange:
    def test_changed_is_false_for_empty(self) -> None:
        assert not VolumeChange(mounted=[], unmounted=[]).changed

    def test_changed_is_true_for_mount(self) -> None:
        assert VolumeChange(mounted=[_volume("/Volumes/A", "A")], unmounted=[]).changed

    def test_changed_is_true_for_unmount(self) -> None:
        assert VolumeChange(mounted=[], unmounted=["/Volumes/B"]).changed


class TestSystemVolumeAdapter:
    def test_returns_mounted_volumes(self) -> None:
        """The real adapter returns a typed list with the root included."""
        adapter = SystemVolumeAdapter()
        volumes = adapter.list_volumes()
        assert isinstance(volumes, list)
        assert volumes, "expected at least the root mount"
        for volume in volumes:
            assert volume.path
            assert volume.total_bytes >= 0
            assert volume.free_bytes >= 0
            assert volume.filesystem
        # The root mount is always present.
        assert any(v.path == "/" for v in volumes)
