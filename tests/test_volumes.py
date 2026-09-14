"""Tests for the volume observation adapter.

The adapter is the tested boundary between the application and the
platform (plan §8.1, §10.6.2). The tests inject a fake ``VolumeAdapter``
into the observer to prove the snapshot-diff logic without touching the
real mount table, and exercise the real ``SystemVolumeAdapter`` shape.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from file_ferry.application.volume_identity import ProbeResult
from file_ferry.application.volumes import (
    SystemVolumeAdapter,
    VolumeChange,
    VolumeObserver,
)
from file_ferry.service.protocol import DestinationIdentity, MountedVolume


def _uuid(value: str) -> DestinationIdentity:
    return DestinationIdentity(
        kind="volume_uuid", value=value, confidence="strong", provenance="fake"
    )


class _FakeProbe:
    """An identity probe under test control, including its failures."""

    def __init__(self, identities: dict[str, DestinationIdentity]) -> None:
        self._identities = dict(identities)
        self._warning: str | None = None

    def set(self, identities: dict[str, DestinationIdentity]) -> None:
        self._identities = dict(identities)

    def fail(self, warning: str) -> None:
        self._identities = {}
        self._warning = warning

    def identify(self, mount_paths: list[str]) -> ProbeResult:
        return ProbeResult(
            identities={p: i for p, i in self._identities.items() if p in mount_paths},
            warnings=[self._warning] if self._warning else [],
            degraded=self._warning is not None,
        )


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

    def __init__(self, initial: list[MountedVolume], warnings: list[str] | None = None) -> None:
        self._volumes = list(initial)
        self._warnings = list(warnings or [])

    def set(self, volumes: list[MountedVolume]) -> None:
        self._volumes = list(volumes)

    def set_warnings(self, warnings: list[str]) -> None:
        self._warnings = list(warnings)

    def list_volumes(self) -> list[MountedVolume]:
        return list(self._volumes)

    def last_warnings(self) -> list[str]:
        return list(self._warnings)


class TestVolumeObserver:
    def test_first_poll_is_empty_baseline(self) -> None:
        adapter = FakeAdapter([_volume("/Volumes/A", "A")])
        observer = VolumeObserver(adapter)
        assert not observer.initialized
        change = observer.poll()
        assert not change.changed
        assert change.mounted == []
        assert change.unmounted == []
        assert observer.initialized

    def test_empty_baseline_is_not_an_uninitialized_observer(self) -> None:
        """A25: "observed nothing" and "has not observed" are different.

        A laptop with no external drives has an *empty* baseline, and the
        first drive plugged into it is a mount event. Treating an empty
        baseline as "not yet initialized" — which a bare ``if not
        self._last`` does — swallows that first mount, on exactly the
        machines where it is the only thing that ever happens.
        """
        adapter = FakeAdapter([])
        observer = VolumeObserver(adapter)
        assert not observer.initialized
        assert not observer.poll().changed
        assert observer.initialized, "an empty observation still initializes the baseline"

        adapter.set([_volume("/Volumes/First", "First")])
        change = observer.poll()
        assert change.changed
        assert [v.path for v in change.mounted] == ["/Volumes/First"]

    def test_unmounting_everything_still_reports_the_unmount(self) -> None:
        """The mirror image: going back to empty is a real observation."""
        adapter = FakeAdapter([_volume("/Volumes/A", "A")])
        observer = VolumeObserver(adapter)
        observer.poll()
        adapter.set([])
        change = observer.poll()
        assert change.unmounted == ["/Volumes/A"]
        # And the now-empty baseline is still a baseline.
        adapter.set([_volume("/Volumes/A", "A")])
        assert [v.path for v in observer.poll().mounted] == ["/Volumes/A"]

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


class TestObservationFreshness:
    """§5.2: an observation must be visibly stale, never confidently wrong."""

    def test_age_is_unknown_before_any_observation(self) -> None:
        observer = VolumeObserver(FakeAdapter([]))
        assert observer.age_seconds() is None
        assert observer.observed_at is None

    def test_age_is_recorded_after_observing(self) -> None:
        observer = VolumeObserver(FakeAdapter([_volume("/Volumes/A", "A")]))
        observer.snapshot()
        age = observer.age_seconds()
        assert age is not None and age >= 0.0
        assert observer.observed_at is not None

    def test_last_volumes_never_refetches(self) -> None:
        """Reading the cached observation must not touch the platform."""
        adapter = FakeAdapter([_volume("/Volumes/A", "A")])
        observer = VolumeObserver(adapter)
        observer.snapshot()
        adapter.set([_volume("/Volumes/B", "B")])
        assert [v.path for v in observer.last_volumes()] == ["/Volumes/A"]

    def test_adapter_warnings_are_surfaced(self) -> None:
        adapter = FakeAdapter([], warnings=["diskutil timed out"])
        observer = VolumeObserver(adapter)
        observer.snapshot()
        assert observer.warnings() == ["diskutil timed out"]

    def test_an_adapter_without_warnings_support_is_fine(self) -> None:
        class Minimal:
            def list_volumes(self) -> list[MountedVolume]:
                return []

        assert VolumeObserver(Minimal()).warnings() == []


class TestVolumeChange:
    def test_changed_is_false_for_empty(self) -> None:
        assert not VolumeChange(mounted=[], unmounted=[]).changed

    def test_changed_is_true_for_mount(self) -> None:
        assert VolumeChange(mounted=[_volume("/Volumes/A", "A")], unmounted=[]).changed

    def test_changed_is_true_for_unmount(self) -> None:
        assert VolumeChange(mounted=[], unmounted=["/Volumes/B"]).changed


class TestIdentityAttachment:
    """The adapter attaches evidence; it never decides what it means."""

    def test_identity_from_the_probe_reaches_the_volume(self) -> None:
        adapter = SystemVolumeAdapter(identity_probe=_FakeProbe({"/": _uuid("vol-1")}))
        volumes = {v.path: v for v in adapter.list_volumes()}
        assert volumes["/"].identity is not None
        assert volumes["/"].identity.value == "vol-1"

    def test_a_failing_probe_keeps_the_last_good_identity(self) -> None:
        """A timeout must not silently downgrade a recognized volume.

        If a transient probe failure turned a strong identity into
        nothing, a saved destination would flip to "confirm this
        binding" with no explanation and no way for the operator to tell
        a real device change from a slow one.
        """
        probe = _FakeProbe({"/": _uuid("vol-1")})
        adapter = SystemVolumeAdapter(identity_probe=probe)
        assert {v.path: v.identity for v in adapter.list_volumes()}["/"] is not None

        probe.fail("diskutil timed out")
        volumes = {v.path: v for v in adapter.list_volumes()}
        assert volumes["/"].identity is not None
        assert volumes["/"].identity.value == "vol-1", "previous evidence is retained"
        assert adapter.degraded
        assert adapter.last_warnings()

    def test_a_raising_probe_does_not_take_discovery_down(self) -> None:
        class Exploding:
            def identify(self, mount_paths: list[str]) -> object:
                raise RuntimeError("boom")

        adapter = SystemVolumeAdapter(identity_probe=Exploding())
        volumes = adapter.list_volumes()
        assert volumes, "discovery still lists mounts; manual selection stays usable"
        assert adapter.degraded
        assert any("boom" in w for w in adapter.last_warnings())

    def test_a_vanished_mount_does_not_leave_its_identity_behind(self) -> None:
        """A later mount at the same path must not inherit the old identity."""
        probe = _FakeProbe({"/": _uuid("vol-1"), "/Volumes/Gone": _uuid("vol-2")})
        adapter = SystemVolumeAdapter(identity_probe=probe)
        adapter.list_volumes()
        probe.set({"/": _uuid("vol-1")})
        adapter.list_volumes()
        assert "/Volumes/Gone" not in adapter._identity_cache


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


class TestBoundedFilesystemCalls:
    """§5.2: discovery must not hang on the storage it exists to find."""

    def test_an_unresponsive_mount_still_appears_with_a_warning(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A `statvfs` on a dead share blocks in the kernel with no timeout.

        The volume must still be listed — the user needs to see it, and
        manual selection has to stay usable — with its capacity reported
        as unknown rather than discovery blocking forever.
        """
        import time as _time

        from file_ferry.application import volumes as volumes_module

        def _hang(_path: Path) -> tuple[int, int]:
            _time.sleep(30)
            return (1, 1)

        monkeypatch.setattr(volumes_module, "_disk_usage", _hang)
        adapter = SystemVolumeAdapter(identity_probe=_FakeProbe({}), budget=0.05)
        started = _time.monotonic()
        volumes = adapter.list_volumes()
        elapsed = _time.monotonic() - started

        assert volumes, "an unresponsive mount is not silently dropped from discovery"
        assert elapsed < 5.0, f"discovery took {elapsed:.1f}s; it must be bounded"
        assert adapter.degraded
        assert any("did not answer a free-space query" in w for w in adapter.last_warnings())
        assert all(v.total_bytes == 0 and v.free_bytes == 0 for v in volumes)

    def test_warnings_do_not_accumulate_across_observations(self) -> None:
        """A recovered mount must stop being reported as a problem."""
        adapter = SystemVolumeAdapter(identity_probe=_FakeProbe({}))
        adapter.list_volumes()
        first = len(adapter.last_warnings())
        adapter.list_volumes()
        assert len(adapter.last_warnings()) == first
