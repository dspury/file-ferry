"""Transfer plan construction and approval (spec §4.3, §6.4, §7.1).

These are the guarantees that keep a plan from lying about what it will
do: every source entry is accounted for, nothing is excluded without
someone choosing it, "identical" is never inferred, and approval is a
gate rather than an echo of the fingerprint the caller was handed.
"""

from __future__ import annotations

import os
import unicodedata
from pathlib import Path

import pytest

from file_ferry.application.destinations import DestinationService
from file_ferry.application.inventory import InventoryService, wait_until_complete
from file_ferry.application.preflight import PreflightService, wait_for_preflight
from file_ferry.application.presets import PresetError, PresetRevisionService
from file_ferry.application.transfer_plan import (
    TransferPlanError,
    TransferPlanNotFoundError,
    TransferPlanService,
)
from file_ferry.service.protocol import (
    PresetContent,
    PresetExclusion,
    PresetGroup,
    PresetMatchConditions,
    PresetRule,
    SaveDestinationParams,
    SavePresetRevisionParams,
    TransferPlanEntryModel,
)


class Harness:
    """One isolated database with the four services wired over it."""

    def __init__(self, tmp_path: Path) -> None:
        from file_ferry.application.service import ApplicationService

        self.db_path = tmp_path / "ferry.db"
        boot = ApplicationService(db_path=self.db_path, app_data_dir=tmp_path / "app")
        boot.bootstrap()
        boot.close()
        self.tmp_path = tmp_path
        self.destinations = DestinationService(self.db_path)
        self.inventory = InventoryService(self.db_path)
        self.presets = PresetRevisionService(self.db_path)
        self.plans = TransferPlanService(self.db_path)
        # Approval requires a preflight (R09). These tests use local
        # folders, so an empty observation list is the honest input: the
        # resolver's local-folder branch checks the filesystem directly.
        self.preflights = PreflightService(
            self.db_path, destinations=self.destinations, observations=list
        )

    def source(self, name: str, files: dict[str, bytes]) -> int:
        root = self.tmp_path / name
        root.mkdir(parents=True, exist_ok=True)
        for rel, data in files.items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        status = wait_until_complete(self.inventory, self.inventory.create(str(root), name).id)
        assert status.status == "complete", status.error
        return status.id

    def destination(self, name: str = "NAS", **kwargs: object) -> int:
        root = self.tmp_path / f"dest-{name}"
        root.mkdir(parents=True, exist_ok=True)
        saved = self.destinations.save(
            SaveDestinationParams(name=name, path=str(root), **kwargs)  # type: ignore[arg-type]
        )
        return saved.id

    def dest_root(self, name: str = "NAS") -> Path:
        return self.tmp_path / f"dest-{name}"

    def preflight(self, plan_id: str) -> object:
        """Run a preflight to completion and return its status."""
        started = self.preflights.start(plan_id)
        return wait_for_preflight(self.preflights, started.id)

    def approve(self, plan: object) -> object:
        """Preflight then approve — the real order of operations."""
        status = self.preflight(plan.id)  # type: ignore[attr-defined]
        assert status.status == "passed", status.findings  # type: ignore[attr-defined]
        return self.plans.approve(plan.id, plan.fingerprint)  # type: ignore[attr-defined]

    def all_entries(self, plan_id: str) -> list[TransferPlanEntryModel]:
        out: list[TransferPlanEntryModel] = []
        cursor = 0
        while True:
            page = self.plans.entries(plan_id, limit=1000, after=cursor)
            out.extend(page.entries)
            if page.next_cursor is None:
                return out
            cursor = page.next_cursor


@pytest.fixture
def h(tmp_path: Path) -> Harness:
    return Harness(tmp_path)


# --- R02: source identity is (inventory, entry), never a relative name ---


def test_two_sources_with_the_same_name_both_survive(h: Harness) -> None:
    """A04: two drives holding ``same.txt`` are two entries, not one.

    Deduplicating by relative path dropped one of them and counted it as
    an exclusion nobody asked for — a file silently not transferred, on
    a run that reported success. With the default preset each source
    routes under its own label, so they do not even collide; what
    matters is that both are present and distinct.
    """
    a = h.source("drive_a", {"same.txt": b"AAA"})
    b = h.source("drive_b", {"same.txt": b"BBBBBB"})
    dest = h.destination()
    plan = h.plans.create(destination_id=dest, inventory_ids=[a, b])

    entries = [e for e in h.all_entries(plan.id) if e.entry_type == "file"]
    assert len(entries) == 2, "both sources' files must appear in the plan"
    assert {e.inventory_id for e in entries} == {a, b}
    assert {Path(e.source_path).parent.name for e in entries} == {"drive_a", "drive_b"}
    assert len({e.dest_rel_path for e in entries}) == 2, "two files, two destinations"
    assert plan.total_files == 2
    assert plan.exclusion_count == 0, "nothing was excluded; nobody decided anything"


def test_distinct_names_from_two_sources_do_not_conflict(h: Harness) -> None:
    a = h.source("drive_a", {"a.txt": b"A"})
    b = h.source("drive_b", {"b.txt": b"B"})
    plan = h.plans.create(destination_id=h.destination(), inventory_ids=[a, b])
    entries = [e for e in h.all_entries(plan.id) if e.entry_type == "file"]
    assert {e.action for e in entries} == {"copy"}
    assert plan.blocking_count == 0
    assert plan.total_files == 2


def test_scan_errors_and_unsupported_objects_stay_as_blocking_items(h: Harness) -> None:
    """A07/§6.3: findings block until someone excludes them explicitly."""
    root = h.tmp_path / "mixed"
    root.mkdir()
    (root / "good.mov").write_bytes(b"x")
    (root / "link.mov").symlink_to(root / "good.mov")
    inv = wait_until_complete(h.inventory, h.inventory.create(str(root), "mixed").id).id
    plan = h.plans.create(destination_id=h.destination(), inventory_ids=[inv])

    by_rel = {e.rel_path: e for e in h.all_entries(plan.id)}
    link = by_rel["link.mov"]
    assert link.action == "needs_review", "a symlink is never silently dropped"
    assert link.conflict == "unsupported_source_object:symlink"
    assert link.excluded_by_user is False, "no implicit exclusion is ever an approved one"
    assert link.exclusion_reason
    assert plan.blocking_count == 1
    assert plan.exclusion_count == 0


def test_nested_and_duplicate_sources_are_rejected(h: Harness) -> None:
    """§7.1: one non-overlapping selection, chosen by the user."""
    outer = h.tmp_path / "outer"
    (outer / "inner").mkdir(parents=True)
    (outer / "a.txt").write_bytes(b"a")
    (outer / "inner" / "b.txt").write_bytes(b"b")
    outer_inv = wait_until_complete(h.inventory, h.inventory.create(str(outer), "o").id).id
    inner_inv = wait_until_complete(
        h.inventory, h.inventory.create(str(outer / "inner"), "i").id
    ).id
    dest = h.destination()

    with pytest.raises(TransferPlanError, match="nested"):
        h.plans.create(destination_id=dest, inventory_ids=[outer_inv, inner_inv])
    with pytest.raises(TransferPlanError, match="selected more than once"):
        h.plans.create(destination_id=dest, inventory_ids=[outer_inv, outer_inv])


def test_destination_inside_source_is_rejected(h: Harness) -> None:
    root = h.tmp_path / "src"
    inside = root / "dest"
    inside.mkdir(parents=True)
    (root / "a.txt").write_bytes(b"a")
    inv = wait_until_complete(h.inventory, h.inventory.create(str(root), "s").id).id
    saved = h.destinations.save(SaveDestinationParams(name="Inside", path=str(inside)))
    with pytest.raises(TransferPlanError, match="inside source"):
        h.plans.create(destination_id=saved.id, inventory_ids=[inv])


def test_empty_directories_are_planned(h: Harness) -> None:
    """A18: an empty directory is preserved, not quietly lost."""
    root = h.tmp_path / "tree"
    (root / "empty").mkdir(parents=True)
    (root / "a.txt").write_bytes(b"a")
    inv = wait_until_complete(h.inventory, h.inventory.create(str(root), "t").id).id
    plan = h.plans.create(destination_id=h.destination(), inventory_ids=[inv])
    dirs = [e for e in h.all_entries(plan.id) if e.action == "dir"]
    assert [e.rel_path for e in dirs] == ["empty"]


# --- R03: "identical" requires content evidence, never size ---


def test_equal_size_different_content_is_not_identical(h: Harness) -> None:
    """A03: size equality is not content equality.

    Classifying these as ``skip_identical`` declares a file already
    transferred that never was, and the real bytes are then never
    copied. Until checksums exist (P5) the existing file is a conflict —
    keep-both writes the incoming copy beside it and reports the rename,
    and the original is never touched.
    """
    inv = h.source("src", {"f.txt": b"AAA"})
    dest_id = h.destination()
    existing = h.dest_root() / "Sources" / "src" / "f.txt"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"ZZZ")  # same size, different bytes

    plan = h.plans.create(destination_id=dest_id, inventory_ids=[inv])
    entry = next(e for e in h.all_entries(plan.id) if e.rel_path == "f.txt")
    assert entry.conflict == "existing_destination"
    assert entry.renamed_from == "Sources/src/f.txt"
    assert entry.dest_rel_path != "Sources/src/f.txt"
    assert existing.read_bytes() == b"ZZZ", "planning never touches the destination"


def test_no_plan_ever_emits_skip_identical_in_this_increment(h: Harness) -> None:
    inv = h.source("src", {"f.txt": b"AAA"})
    dest_id = h.destination()
    (h.dest_root() / "f.txt").write_bytes(b"AAA")  # byte-identical, still unproven
    plan = h.plans.create(destination_id=dest_id, inventory_ids=[inv])
    actions = {e.action for e in h.all_entries(plan.id)}
    assert "skip_identical" not in actions


def test_existing_destination_symlink_is_its_own_conflict(h: Harness) -> None:
    """A symlink at the target is a distinct finding, and never followed."""
    inv = h.source("src", {"f.txt": b"AAA"})
    dest_id = h.destination()
    other = h.tmp_path / "elsewhere.txt"
    other.write_bytes(b"AAA")
    target = h.dest_root() / "Sources" / "src" / "f.txt"
    target.parent.mkdir(parents=True)
    target.symlink_to(other)
    plan = h.plans.create(destination_id=dest_id, inventory_ids=[inv])
    entry = next(e for e in h.all_entries(plan.id) if e.rel_path == "f.txt")
    assert entry.conflict == "existing_destination_symlink"
    assert entry.renamed_from == "Sources/src/f.txt", "the copy lands beside it, never through it"
    assert other.read_bytes() == b"AAA"


# --- R04: approval is a gate, not an echo ---


def test_approval_refuses_unresolved_findings(h: Harness) -> None:
    """A finding nobody has decided blocks approval (spec §6.3, §7.1)."""
    root = h.tmp_path / "mixed"
    root.mkdir()
    (root / "good.mov").write_bytes(b"x")
    (root / "link.mov").symlink_to(root / "good.mov")
    inv = wait_until_complete(h.inventory, h.inventory.create(str(root), "mixed").id).id
    plan = h.plans.create(destination_id=h.destination(), inventory_ids=[inv])
    assert plan.blocking_count == 1
    with pytest.raises(TransferPlanError, match="need a decision"):
        h.plans.approve(plan.id, plan.fingerprint)
    assert h.plans.get(plan.id).status == "draft"


def test_clean_plan_approves(h: Harness) -> None:
    inv = h.source("src", {"a.txt": b"a", "sub/b.txt": b"b"})
    plan = h.plans.create(destination_id=h.destination(), inventory_ids=[inv])
    assert plan.blocking_count == 0
    approved = h.approve(plan)
    assert approved.status == "approved"
    assert approved.approved_fingerprint == plan.fingerprint


def test_editing_the_destination_invalidates_the_approval(h: Harness) -> None:
    """§4.1: an edit and its invalidation are never observed apart."""
    inv = h.source("src", {"a.txt": b"a"})
    dest_id = h.destination()
    plan = h.plans.create(destination_id=dest_id, inventory_ids=[inv])
    h.approve(plan)
    assert h.plans.get(plan.id).status == "approved"

    moved = h.tmp_path / "dest-moved"
    moved.mkdir()
    h.destinations.save(SaveDestinationParams(name="NAS", path=str(moved)))

    after = h.plans.get(plan.id)
    assert after.status == "invalidated"
    assert after.approved_fingerprint is None
    with pytest.raises(TransferPlanError, match="invalidated"):
        h.plans.approve(plan.id, plan.fingerprint)


def test_rebinding_and_archiving_invalidate_approvals(h: Harness) -> None:
    inv = h.source("src", {"a.txt": b"a"})
    dest_id = h.destination()
    plan = h.plans.create(destination_id=dest_id, inventory_ids=[inv])
    h.approve(plan)
    h.destinations.confirm_binding(dest_id, path=str(h.dest_root()))
    assert h.plans.get(plan.id).status == "invalidated"

    plan2 = h.plans.create(destination_id=dest_id, inventory_ids=[inv])
    h.approve(plan2)
    h.destinations.archive(dest_id)
    assert h.plans.get(plan2.id).status == "invalidated"


def test_capacity_accounts_for_the_saved_reserve(h: Harness) -> None:
    """§7.1: a plan that fits only by eating the reserve does not fit.

    The reserve was stored and then ignored, so a 3-byte plan against a
    10^18-byte reserve reported capacity OK.
    """
    inv = h.source("src", {"a.txt": b"abc"})
    dest_id = h.destination(freeSpaceReserve=10**18)
    plan = h.plans.create(destination_id=dest_id, inventory_ids=[inv])
    assert plan.free_space_reserve == 10**18
    assert plan.needed_bytes >= 10**18
    assert plan.capacity_ok is False
    assert any("reserve" in w for w in plan.warnings)
    with pytest.raises(TransferPlanError, match="bytes free"):
        h.plans.approve(plan.id, plan.fingerprint)


def test_unknown_capacity_requires_a_recorded_override(h: Harness) -> None:
    inv = h.source("src", {"a.txt": b"a"})
    dest_id = h.destination()
    plan = h.plans.create(destination_id=dest_id, inventory_ids=[inv])

    # Simulate the free-space probe having been inconclusive.
    from file_ferry.persistence.connection import transaction

    with transaction(h.db_path) as conn:
        conn.execute(
            "UPDATE transfer_plans SET capacity_unknown = 1, capacity_ok = 0 WHERE id = ?",
            (plan.id,),
        )
    with pytest.raises(TransferPlanError, match="explicit recorded override"):
        h.plans.approve(plan.id, plan.fingerprint)

    with transaction(h.db_path) as conn:
        conn.execute(
            "UPDATE transfer_plans SET capacity_override_reason = ? WHERE id = ?",
            ("operator confirmed the share has room", plan.id),
        )
    assert h.approve(plan).status == "approved"


def test_a_changed_source_forces_a_replan(h: Harness) -> None:
    """§7.1: never rescan and substitute a different file list invisibly."""
    inv = h.source("src", {"a.txt": b"a"})
    plan = h.plans.create(destination_id=h.destination(), inventory_ids=[inv])

    from file_ferry.persistence.connection import transaction

    with transaction(h.db_path) as conn:
        conn.execute(
            "UPDATE source_inventories SET manifest_hash = 'different' WHERE id = ?", (inv,)
        )
    with pytest.raises(TransferPlanError, match="changed since it was reviewed"):
        h.plans.approve(plan.id, plan.fingerprint)


def test_a_failed_inventory_cannot_be_planned(h: Harness) -> None:
    inv = h.source("src", {"a.txt": b"a"})
    from file_ferry.persistence.connection import transaction

    with transaction(h.db_path) as conn:
        conn.execute(
            "UPDATE source_inventories SET status = 'failed', error = 'disk gone' WHERE id = ?",
            (inv,),
        )
    with pytest.raises(TransferPlanError, match="disk gone"):
        h.plans.create(destination_id=h.destination(), inventory_ids=[inv])


def test_an_unconfirmed_binding_path_is_refused(h: Harness) -> None:
    """§5.1: rebinding is a user action, not a plan parameter."""
    inv = h.source("src", {"a.txt": b"a"})
    dest_id = h.destination()
    elsewhere = h.tmp_path / "somewhere-else"
    elsewhere.mkdir()
    with pytest.raises(TransferPlanError, match="confirmed binding"):
        h.plans.create(destination_id=dest_id, inventory_ids=[inv], binding_path=str(elsewhere))


def test_archived_destinations_cannot_be_planned(h: Harness) -> None:
    inv = h.source("src", {"a.txt": b"a"})
    dest_id = h.destination()
    h.destinations.archive(dest_id)
    with pytest.raises(TransferPlanError, match="archived"):
        h.plans.create(destination_id=dest_id, inventory_ids=[inv])


def test_fingerprint_covers_the_whole_substance(h: Harness) -> None:
    """A fingerprint that ignores an input is the same as no gate at all."""
    inv = h.source("src", {"a.txt": b"a"})
    base = h.plans.create(destination_id=h.destination("A"), inventory_ids=[inv])
    same = h.plans.create(destination_id=h.destination("A"), inventory_ids=[inv])
    assert same.fingerprint == base.fingerprint, "identical inputs are the same plan"

    reserved = h.destinations.save(
        SaveDestinationParams(name="A", path=str(h.dest_root("A")), freeSpaceReserve=4096)
    )
    with_reserve = h.plans.create(destination_id=reserved.id, inventory_ids=[inv])
    assert with_reserve.fingerprint != base.fingerprint, "the reserve is plan substance"

    policy = h.destinations.save(
        SaveDestinationParams(
            name="A",
            path=str(h.dest_root("A")),
            freeSpaceReserve=4096,
            checksumAlgo="sha256",
        )
    )
    with_algo = h.plans.create(destination_id=policy.id, inventory_ids=[inv])
    assert with_algo.fingerprint != with_reserve.fingerprint, "the algorithm is plan substance"


def test_approving_a_stale_fingerprint_is_refused(h: Harness) -> None:
    inv = h.source("src", {"a.txt": b"a"})
    plan = h.plans.create(destination_id=h.destination(), inventory_ids=[inv])
    with pytest.raises(TransferPlanError, match="fingerprint changed"):
        h.plans.approve(plan.id, "not-the-fingerprint")


def test_missing_plan_raises(h: Harness) -> None:
    with pytest.raises(TransferPlanNotFoundError):
        h.plans.get("no-such-plan")


# --- R05: pinned preset revisions ---


def _content(fallback: str = "Sources/{relative_dir}/{filename}") -> PresetContent:
    return PresetContent(fallbackTemplate=fallback)


def test_saving_a_new_revision_does_not_move_an_existing_pin(h: Harness) -> None:
    """§4.2: destinations stay pinned until the user chooses an update."""
    first = h.presets.save_revision(SavePresetRevisionParams(name="P", content=_content()))
    root = h.tmp_path / "dest-pinned"
    root.mkdir()
    saved = h.destinations.save(
        SaveDestinationParams(name="Pinned", path=str(root), defaultPresetId=first.preset_id)
    )
    assert saved.pinned_revision == first.revision == 1

    second = h.presets.save_revision(
        SavePresetRevisionParams(name="P", content=_content("Other/{filename}"))
    )
    assert second.revision == 2

    inv = h.source("src", {"a.txt": b"a"})
    plan = h.plans.create(destination_id=saved.id, inventory_ids=[inv])
    assert plan.preset_revision == 1, "a newer revision must not re-route an existing pin"
    assert plan.preset_content_hash == first.content_hash


def test_moving_the_pin_is_explicit_and_invalidates_approvals(h: Harness) -> None:
    first = h.presets.save_revision(SavePresetRevisionParams(name="P", content=_content()))
    root = h.tmp_path / "dest-pin2"
    root.mkdir()
    saved = h.destinations.save(
        SaveDestinationParams(name="Pin2", path=str(root), defaultPresetId=first.preset_id)
    )
    inv = h.source("src", {"a.txt": b"a"})
    plan = h.plans.create(destination_id=saved.id, inventory_ids=[inv])
    h.approve(plan)

    h.presets.save_revision(SavePresetRevisionParams(name="P", content=_content("Two/{filename}")))
    repinned = h.destinations.save(
        SaveDestinationParams(
            name="Pin2", path=str(root), defaultPresetId=first.preset_id, pinnedRevision=2
        )
    )
    assert repinned.pinned_revision == 2
    assert h.plans.get(plan.id).status == "invalidated"

    plan2 = h.plans.create(destination_id=saved.id, inventory_ids=[inv])
    assert plan2.preset_revision == 2


def test_pinning_validates_the_preset_revision_pair(h: Harness) -> None:
    from file_ferry.application.destinations import DestinationError

    first = h.presets.save_revision(SavePresetRevisionParams(name="P", content=_content()))
    root = h.tmp_path / "dest-badpin"
    root.mkdir()
    with pytest.raises(DestinationError, match="no revision 7"):
        h.destinations.save(
            SaveDestinationParams(
                name="BadPin", path=str(root), defaultPresetId=first.preset_id, pinnedRevision=7
            )
        )
    with pytest.raises(DestinationError, match="without a defaultPresetId"):
        h.destinations.save(SaveDestinationParams(name="BadPin2", path=str(root), pinnedRevision=1))


def test_a_legacy_root_preset_actually_applies_its_root(h: Harness) -> None:
    """R07: the stored legacy root was recorded and then never applied."""
    from file_ferry.application.profiles import ProfileService
    from file_ferry.service.protocol import SaveProfileParams

    profiles = ProfileService(h.db_path)
    legacy = profiles.save(
        SaveProfileParams(name="Legacy", template={"root": "Archive/2026"}, conflictPolicy="rename")
    )
    root = h.tmp_path / "dest-legacy"
    root.mkdir()
    saved = h.destinations.save(
        SaveDestinationParams(name="Legacy", path=str(root), defaultPresetId=legacy.id)
    )
    inv = h.source("src", {"a.txt": b"a"})
    plan = h.plans.create(destination_id=saved.id, inventory_ids=[inv])
    entry = next(e for e in h.all_entries(plan.id) if e.rel_path == "a.txt")
    assert entry.dest_rel_path == "Archive/2026/a.txt", (
        "the legacy root is applied, not merely recorded"
    )
    assert any("legacy root-only profile" in w for w in plan.warnings)


def test_a_preset_needing_review_is_surfaced_on_the_plan(h: Harness) -> None:
    from file_ferry.application.profiles import ProfileService
    from file_ferry.service.protocol import SaveProfileParams

    profiles = ProfileService(h.db_path)
    legacy = profiles.save(
        SaveProfileParams(
            name="Odd",
            template={"root": "Archive", "unknownKey": {"deep": 1}},
            conflictPolicy="overwrite",
        )
    )
    root = h.tmp_path / "dest-odd"
    root.mkdir()
    saved = h.destinations.save(
        SaveDestinationParams(name="Odd", path=str(root), defaultPresetId=legacy.id)
    )
    inv = h.source("src", {"a.txt": b"a"})
    plan = h.plans.create(destination_id=saved.id, inventory_ids=[inv])
    joined = " ".join(plan.warnings)
    assert "unknownKey" in joined
    assert "overwrite" in joined


# --- pagination (A01) ---


def test_plan_entries_paginate_without_gaps_or_duplicates(h: Harness) -> None:
    inv = h.source("many", {f"f{i:04d}.txt": b"x" for i in range(450)})
    plan = h.plans.create(destination_id=h.destination(), inventory_ids=[inv])
    page = h.plans.entries(plan.id, limit=100)
    assert page.total == 450
    assert len(page.entries) == 100
    seen = {e.id for e in h.all_entries(plan.id)}
    assert len(seen) == 450


class TestExclusionWorkflow:
    """§6.3/§8: findings are decided, and deciding produces a new plan.

    Until P4 every finding blocked approval with no way through, which
    made a plan containing one symlink permanently unusable. The way
    through is an explicit decision that is recorded as such — never a
    quiet drop, and never an edit to the plan that was reviewed.
    """

    @staticmethod
    def _with_a_finding(h: Harness) -> tuple[int, object]:
        root = h.tmp_path / "mixed"
        root.mkdir()
        (root / "good.mov").write_bytes(b"x")
        (root / "link.mov").symlink_to(root / "good.mov")
        inv = wait_until_complete(h.inventory, h.inventory.create(str(root), "mixed").id).id
        plan = h.plans.create(destination_id=h.destination(), inventory_ids=[inv])
        return inv, plan

    def test_excluding_a_finding_unblocks_approval(self, h: Harness) -> None:
        _inv, plan = self._with_a_finding(h)
        assert plan.blocking_count == 1
        with pytest.raises(TransferPlanError, match="need a decision"):
            h.plans.approve(plan.id, plan.fingerprint)

        finding = next(e for e in h.all_entries(plan.id) if e.action == "needs_review")
        resolved = h.plans.resolve(plan.id, entry_ids=[finding.id], reason="not needed on the NAS")
        assert resolved.blocking_count == 0
        assert resolved.exclusion_count == 1
        assert resolved.id != plan.id, "resolving produces a new plan"
        assert resolved.derived_from == plan.id
        assert h.approve(resolved).status == "approved"

    def test_the_reviewed_plan_is_never_edited(self, h: Harness) -> None:
        """Plans are immutable; the original stays exactly as reviewed."""
        _inv, plan = self._with_a_finding(h)
        finding = next(e for e in h.all_entries(plan.id) if e.action == "needs_review")
        h.plans.resolve(plan.id, entry_ids=[finding.id])
        original = h.plans.get(plan.id)
        assert original.blocking_count == 1
        assert original.exclusion_count == 0
        assert original.fingerprint == plan.fingerprint

    def test_an_exclusion_records_that_a_person_chose_it(self, h: Harness) -> None:
        """`excluded_by_user` is what separates a decision from a silence."""
        _inv, plan = self._with_a_finding(h)
        finding = next(e for e in h.all_entries(plan.id) if e.action == "needs_review")
        resolved = h.plans.resolve(plan.id, entry_ids=[finding.id], reason="a deliberate reason")
        excluded = next(e for e in h.all_entries(resolved.id) if e.action == "exclude")
        assert excluded.excluded_by_user is True
        assert excluded.exclusion_reason == "a deliberate reason"
        assert excluded.rel_path == "link.mov"

    def test_excluded_entries_are_counted_apart_from_copies(self, h: Harness) -> None:
        """§7.3: exclusions are counted separately from successful copies."""
        _inv, plan = self._with_a_finding(h)
        finding = next(e for e in h.all_entries(plan.id) if e.action == "needs_review")
        resolved = h.plans.resolve(plan.id, entry_ids=[finding.id])
        assert resolved.total_files == 1, "the excluded entry is not a planned copy"
        assert resolved.exclusion_count == 1
        assert any("excluded by an explicit decision" in w for w in resolved.warnings)

    def test_decisions_accumulate_across_rounds(self, h: Harness) -> None:
        """Deciding one finding must not discard the earlier decisions."""
        root = h.tmp_path / "many"
        root.mkdir()
        (root / "good.mov").write_bytes(b"x")
        (root / "one.mov").symlink_to(root / "good.mov")
        (root / "two.mov").symlink_to(root / "good.mov")
        inv = wait_until_complete(h.inventory, h.inventory.create(str(root), "many").id).id
        plan = h.plans.create(destination_id=h.destination(), inventory_ids=[inv])
        assert plan.blocking_count == 2

        findings = [e for e in h.all_entries(plan.id) if e.action == "needs_review"]
        first = h.plans.resolve(plan.id, entry_ids=[findings[0].id], reason="round one")
        assert first.blocking_count == 1

        still = next(e for e in h.all_entries(first.id) if e.action == "needs_review")
        second = h.plans.resolve(first.id, entry_ids=[still.id], reason="round two")
        assert second.blocking_count == 0
        assert second.exclusion_count == 2, "the first round's decision survived"
        reasons = {e.exclusion_reason for e in h.all_entries(second.id) if e.excluded_by_user}
        assert reasons == {"round one", "round two"}

    def test_decisions_are_part_of_the_approved_substance(self, h: Harness) -> None:
        """A different set of exclusions is a different plan."""
        _inv, plan = self._with_a_finding(h)
        finding = next(e for e in h.all_entries(plan.id) if e.action == "needs_review")
        resolved = h.plans.resolve(plan.id, entry_ids=[finding.id])
        assert resolved.fingerprint != plan.fingerprint
        assert [d.rel_path for d in resolved.decisions] == ["link.mov"]

    def test_resolving_an_entry_from_another_plan_is_refused(self, h: Harness) -> None:
        _inv, plan = self._with_a_finding(h)
        with pytest.raises(TransferPlanError, match="not part of plan"):
            h.plans.resolve(plan.id, entry_ids=[999_999])

    def test_resolving_nothing_is_refused(self, h: Harness) -> None:
        _inv, plan = self._with_a_finding(h)
        with pytest.raises(TransferPlanError, match="nothing to resolve"):
            h.plans.resolve(plan.id)


class TestAcceptanceMatrixP4:
    """The §10 cases the rule engine and conflict planner are responsible for."""

    def test_a17_a_preserved_group_keeps_every_file_type_together(self, h: Harness) -> None:
        """A17: video, XML, audio and project files stay one unit.

        Without groups the document rule pulls the `.xml` sidecar into
        `Documents/` while its `.mov` goes to `Video/`, and the project is
        silently taken apart by a transfer that reports success.
        """
        content = PresetContent(
            fallbackTemplate="Unsorted/{filename}",
            rules=[
                PresetRule(
                    id="video",
                    match=PresetMatchConditions(categories=["video"]),
                    destination="Video/{filename}",
                ),
                PresetRule(
                    id="docs",
                    match=PresetMatchConditions(categories=["document"]),
                    destination="Docs/{filename}",
                ),
            ],
            groups=[
                PresetGroup(
                    id="projects",
                    match=PresetMatchConditions(pathGlob="Project*"),
                    destination="Projects/{filename}",
                )
            ],
        )
        preset = h.presets.save_revision(SavePresetRevisionParams(name="Groups", content=content))
        inv = h.source(
            "card",
            {
                "ProjectA/shot.mov": b"v",
                "ProjectA/shot.xml": b"x",
                "ProjectA/audio.wav": b"a",
                "ProjectA/edit.prproj": b"p",
                "loose.pdf": b"d",
            },
        )
        root = h.tmp_path / "dest-group"
        root.mkdir()
        dest = h.destinations.save(
            SaveDestinationParams(name="Group", path=str(root), defaultPresetId=preset.preset_id)
        )
        plan = h.plans.create(destination_id=dest.id, inventory_ids=[inv])
        by_rel = {e.rel_path: e for e in h.all_entries(plan.id)}
        for name in ("shot.mov", "shot.xml", "audio.wav", "edit.prproj"):
            entry = by_rel[f"ProjectA/{name}"]
            assert entry.dest_rel_path == f"Projects/ProjectA/{name}", (
                f"{name} was split out of its group"
            )
        assert by_rel["loose.pdf"].dest_rel_path == "Docs/loose.pdf", (
            "files outside a group still follow the ordinary rules"
        )

    def test_a18_unknown_extensionless_and_empty_directories(self, h: Harness) -> None:
        """A18: fallback and preservation, with explicit counts."""
        inv = h.source("card", {"mystery.zzz": b"?", "LICENSE": b"t", "keep/a.mov": b"v"})
        (h.tmp_path / "card" / "Empty").mkdir()
        inv = wait_until_complete(
            h.inventory, h.inventory.create(str(h.tmp_path / "card"), "Card").id
        ).id
        plan = h.plans.create(destination_id=h.destination(), inventory_ids=[inv])
        by_rel = {e.rel_path: e for e in h.all_entries(plan.id)}

        assert by_rel["mystery.zzz"].action == "copy", "an unknown extension is never omitted"
        assert by_rel["LICENSE"].action == "copy", "an extensionless file is never omitted"
        assert by_rel["Empty"].action == "dir", "an empty directory is preserved"
        assert plan.total_files == 3
        assert plan.exclusion_count == 0

    def test_a05_case_and_unicode_collisions_are_distinct_and_lossless(self, h: Harness) -> None:
        """A05: detected before any write, and nothing is lost to them.

        The colliding pairs live in different source folders so the test
        works on case-sensitive and case-insensitive filesystems alike —
        on the latter, two such names cannot coexist in one directory at
        all, which is precisely why the destination needs the check.
        """
        content = PresetContent(
            fallbackTemplate="Flat/{filename}",
            rules=[
                PresetRule(
                    id="flatten",
                    match=PresetMatchConditions(pathGlob="*/*"),
                    destination="Flat/{filename}",
                )
            ],
        )
        preset = h.presets.save_revision(SavePresetRevisionParams(name="Flat", content=content))
        inv = h.source(
            "card",
            {
                "x/IMG_1.JPG": b"1",
                "y/img_1.jpg": b"2",
                f"x/{unicodedata.normalize('NFC', 'café.mov')}": b"3",
                f"y/{unicodedata.normalize('NFD', 'café.mov')}": b"4",
            },
        )
        root = h.tmp_path / "dest-flat"
        root.mkdir()
        dest = h.destinations.save(
            SaveDestinationParams(name="Flat", path=str(root), defaultPresetId=preset.preset_id)
        )
        plan = h.plans.create(destination_id=dest.id, inventory_ids=[inv])
        files = [e for e in h.all_entries(plan.id) if e.action == "copy"]

        assert len(files) == 4, "every source file is still planned"
        assert len({e.dest_rel_path for e in files}) == 4, "and none overwrites another"
        kinds = {e.conflict for e in files if e.conflict}
        assert "case_only" in kinds
        assert "unicode_normalization" in kinds
        assert all(not (root / e.dest_rel_path).exists() for e in files), (
            "detection happens before any write"
        )


# --- R14: a preset revision that needs review may not be approved ---


def _review_required_preset(h: Harness, item: str) -> object:
    return h.presets.save_revision(
        SavePresetRevisionParams(
            name="converted-legacy",
            content=PresetContent(
                fallbackTemplate="Sources/{source_label}/{relative_dir}/{filename}",
                reviewRequired=[item],
            ),
        )
    )


def test_a_preset_needing_review_refuses_approval_and_names_the_item(h: Harness) -> None:
    """A05/A20: warning about it and approving anyway is a silent ignore.

    `review_required` carries what a legacy conversion could not resolve
    — a template key Ferry does not understand, a conflict policy with
    no safe equivalent. The plan used to surface it as a warning and
    approve regardless, which means the one thing the field exists to
    prevent did not happen (R14).
    """
    item = "unknown legacy template key 'sort_by' = 'shoot_date'"
    saved = _review_required_preset(h, item)
    src = h.source("card", {"a.txt": b"A"})
    plan = h.plans.create(
        destination_id=h.destination(),
        inventory_ids=[src],
        preset_id=saved.preset_id,
        preset_revision=saved.revision,
    )
    assert plan.preset_review_required == [item], "the plan carries the evidence itself"
    assert any("needs review" in w for w in plan.warnings)

    status = h.preflight(plan.id)
    assert status.status == "passed", "the world is fine; the preset is not"
    with pytest.raises(TransferPlanError) as excinfo:
        h.plans.approve(plan.id, plan.fingerprint)
    message = str(excinfo.value)
    assert item in message, "the refusal names what needs deciding"
    assert "corrected revision" in message, "and says how to get past it"


def test_a_corrected_revision_makes_the_same_plan_approvable(h: Harness) -> None:
    """The path through is fixing the preset, never clearing it silently."""
    saved = _review_required_preset(h, "unknown legacy template key 'x'")
    src = h.source("card", {"a.txt": b"A"})
    dest = h.destination()
    blocked = h.plans.create(
        destination_id=dest,
        inventory_ids=[src],
        preset_id=saved.preset_id,
        preset_revision=saved.revision,
    )
    with pytest.raises(TransferPlanError):
        h.approve(blocked)

    corrected = h.presets.save_revision(
        SavePresetRevisionParams(
            name="converted-legacy",
            content=PresetContent(
                fallbackTemplate="Sources/{source_label}/{relative_dir}/{filename}"
            ),
        )
    )
    plan = h.plans.create(
        destination_id=dest,
        inventory_ids=[src],
        preset_id=corrected.preset_id,
        preset_revision=corrected.revision,
    )
    assert plan.preset_review_required == []
    assert h.approve(plan).status == "approved"


# --- R15: preset exclusion rules are applied, recorded, and counted ---


def _excluding(h: Harness, *exclusions: PresetExclusion) -> object:
    return h.presets.save_revision(
        SavePresetRevisionParams(
            name="with-exclusions",
            content=PresetContent(
                fallbackTemplate="Sources/{source_label}/{relative_dir}/{filename}",
                exclusions=list(exclusions),
            ),
        )
    )


def _plan_with_exclusions(h: Harness, files: dict[str, bytes], *exclusions: PresetExclusion):
    saved = _excluding(h, *exclusions)
    src = h.source("card", files)
    plan = h.plans.create(
        destination_id=h.destination(),
        inventory_ids=[src],
        preset_id=saved.preset_id,
        preset_revision=saved.revision,
    )
    return plan, {e.rel_path: e for e in h.all_entries(plan.id)}


def test_an_extension_exclusion_is_applied_and_says_which_rule_did_it(h: Harness) -> None:
    """A18: the field was stored, hashed, exported — and inert (R15).

    A user who saved "never copy .tmp" and watched the plan copy them
    anyway has been told the opposite of the truth by a screen whose only
    job is to say what will happen.
    """
    plan, entries = _plan_with_exclusions(
        h,
        {"junk.tmp": b"x", "keep.mov": b"y"},
        PresetExclusion(
            id="scratch",
            reason="editor scratch files",
            match=PresetMatchConditions(extensions=[".tmp"]),
        ),
    )
    excluded = entries["junk.tmp"]
    assert excluded.action == "exclude"
    assert excluded.matched_rule == "exclusion:scratch"
    assert "scratch" in (excluded.exclusion_reason or "")
    assert "editor scratch files" in (excluded.exclusion_reason or ""), "the user's own words"
    assert entries["keep.mov"].action == "copy"
    assert plan.total_files == 1, "an excluded file is not a planned copy"


def test_preset_exclusions_and_reviewer_decisions_stay_distinguishable(h: Harness) -> None:
    """§7.3: both are explicit, and they are not the same fact."""
    plan, entries = _plan_with_exclusions(
        h,
        {"junk.tmp": b"x", "unwanted.mov": b"y", "keep.mov": b"z"},
        PresetExclusion(
            id="scratch", reason="scratch", match=PresetMatchConditions(extensions=[".tmp"])
        ),
    )
    assert plan.exclusion_count == 1
    assert plan.rule_exclusion_count == 1
    assert entries["junk.tmp"].excluded_by_user is False, (
        "a preset rule is not a decision this reviewer made"
    )

    resolved = h.plans.resolve(plan.id, entry_ids=[entries["unwanted.mov"].id], reason="not needed")
    after = {e.rel_path: e for e in h.all_entries(resolved.id)}
    assert resolved.exclusion_count == 2
    assert resolved.rule_exclusion_count == 1, "one rule exclusion, one human decision"
    assert after["unwanted.mov"].excluded_by_user is True
    assert after["junk.tmp"].excluded_by_user is False


def test_glob_and_category_exclusions_are_recorded_the_same_way(h: Harness) -> None:
    plan, entries = _plan_with_exclusions(
        h,
        {"Cache/render.dat": b"x", "backup.zip": b"y", "clip.mov": b"z"},
        PresetExclusion(
            id="caches", reason="render caches", match=PresetMatchConditions(pathGlob="Cache/*")
        ),
        PresetExclusion(
            id="archives",
            reason="archives live elsewhere",
            match=PresetMatchConditions(categories=["archive"]),
        ),
    )
    assert entries["Cache/render.dat"].matched_rule == "exclusion:caches"
    assert entries["backup.zip"].matched_rule == "exclusion:archives"
    assert entries["clip.mov"].action == "copy"
    assert plan.rule_exclusion_count == 2


def test_excluding_a_directory_excludes_what_is_inside_it(h: Harness) -> None:
    """Copying the contents of a folder the plan says it will skip is incoherent."""
    plan, entries = _plan_with_exclusions(
        h,
        {"Cache/a.mov": b"x", "Cache/deep/b.mov": b"y", "keep.mov": b"z"},
        PresetExclusion(
            id="caches", reason="render caches", match=PresetMatchConditions(pathGlob="Cache")
        ),
    )
    assert entries["Cache"].action == "exclude"
    for rel in ("Cache/a.mov", "Cache/deep/b.mov"):
        assert entries[rel].action == "exclude", rel
        assert "inherited from the excluded directory" in (entries[rel].exclusion_reason or "")
    assert entries["keep.mov"].action == "copy"
    assert plan.total_files == 1


def test_an_exclusion_rule_with_no_conditions_is_rejected_at_save(h: Harness) -> None:
    """Same rule as a routing rule: it would match everything."""
    with pytest.raises(PresetError, match=r"exclusions\[0\].match: at least one condition"):
        _excluding(h, PresetExclusion(id="all", reason="everything", match=PresetMatchConditions()))


def test_an_exclusion_without_a_reason_is_rejected_at_save(h: Harness) -> None:
    """The reason is what review and the receipt show for every skipped file."""
    with pytest.raises(PresetError, match=r"exclusions\[0\].reason"):
        _excluding(
            h,
            PresetExclusion(
                id="tmp", reason="  ", match=PresetMatchConditions(extensions=[".tmp"])
            ),
        )


# --- R16: a symlink on the destination path is never written through ---


def test_a_directory_symlink_at_the_destination_blocks_the_plan(h: Harness) -> None:
    """A06/A12: `is_dir()` follows links, so one looked like a directory.

    Every file beneath it planned as a clean copy, preflight passed, and
    approval succeeded — while publication would have written outside the
    destination root, through a link the plan never mentioned (R16).
    """
    src = h.source("card", {"Photos/a.txt": b"A", "Photos/deep/b.txt": b"B"})
    dest_id = h.destination()
    outside = h.tmp_path / "somewhere-else"
    outside.mkdir()
    (h.dest_root() / "Sources" / "card").mkdir(parents=True)
    os.symlink(outside, h.dest_root() / "Sources" / "card" / "Photos")

    plan = h.plans.create(destination_id=dest_id, inventory_ids=[src])
    entries = {e.rel_path: e for e in h.all_entries(plan.id)}
    assert plan.blocking_count >= 2
    for rel in ("Photos/a.txt", "Photos/deep/b.txt"):
        assert entries[rel].action == "needs_review", rel
        assert entries[rel].conflict == "existing_destination_symlink", rel
        assert "symbolic link" in (entries[rel].exclusion_reason or "")
    with pytest.raises(TransferPlanError):
        h.plans.approve(plan.id, plan.fingerprint)


def test_a_symlink_pointing_inside_the_destination_blocks_too(h: Harness) -> None:
    """Where it points is not the question; Ferry does not write through links."""
    src = h.source("card", {"Photos/a.txt": b"A"})
    dest_id = h.destination()
    inside = h.dest_root() / "real-photos"
    inside.mkdir(parents=True)
    (h.dest_root() / "Sources" / "card").mkdir(parents=True)
    os.symlink(inside, h.dest_root() / "Sources" / "card" / "Photos")

    plan = h.plans.create(destination_id=dest_id, inventory_ids=[src])
    entry = {e.rel_path: e for e in h.all_entries(plan.id)}["Photos/a.txt"]
    assert entry.action == "needs_review"
    assert entry.conflict == "existing_destination_symlink"


def test_a_real_existing_directory_still_merges(h: Harness) -> None:
    """The fix must not turn ordinary re-use of a destination into a blocker."""
    src = h.source("card", {"Photos/a.txt": b"A"})
    dest_id = h.destination()
    (h.dest_root() / "Sources" / "card" / "Photos").mkdir(parents=True)

    plan = h.plans.create(destination_id=dest_id, inventory_ids=[src])
    entry = {e.rel_path: e for e in h.all_entries(plan.id)}["Photos/a.txt"]
    assert entry.action == "copy"
    assert plan.blocking_count == 0
    assert h.approve(plan).status == "approved"


# --- R17: a preserved group is resolved at its root, never member by member ---


def _group_preset(h: Harness, *, policy: str = "keep_both") -> object:
    return h.presets.save_revision(
        SavePresetRevisionParams(
            name="collections",
            content=PresetContent(
                fallbackTemplate="Unsorted/{source_label}/{relative_dir}/{filename}",
                conflictPolicy=policy,
                groups=[
                    PresetGroup(
                        id="proj",
                        match=PresetMatchConditions(pathGlob="Proj"),
                        destination="Collections/{source_label}/{relative_dir}/{filename}",
                    )
                ],
            ),
        )
    )


_GROUP_FILES = {
    "Proj/edit.drp": b"project",
    "Proj/Media/A001.mov": b"movie",
    "Proj/Media/A001.xml": b"sidecar",
    "loose.pdf": b"doc",
}


def test_the_group_root_lands_under_the_group_not_the_fallback(h: Harness) -> None:
    """A17/E08: the root used to route through the fallback and strand itself."""
    saved = _group_preset(h)
    src = h.source("card", _GROUP_FILES)
    plan = h.plans.create(
        destination_id=h.destination(),
        inventory_ids=[src],
        preset_id=saved.preset_id,
        preset_revision=saved.revision,
    )
    entries = {e.rel_path: e for e in h.all_entries(plan.id)}
    assert "Unsorted/card/Proj" not in {e.dest_rel_path for e in entries.values()}
    for rel in ("Proj/edit.drp", "Proj/Media/A001.mov", "Proj/Media/A001.xml"):
        assert entries[rel].dest_rel_path.startswith("Collections/card/Proj/"), rel
        assert entries[rel].group_id == "proj", "review can show the containment"
    assert entries["loose.pdf"].dest_rel_path == "Unsorted/card/loose.pdf"
    assert entries["loose.pdf"].group_id is None


def test_a_colliding_group_moves_whole_and_keeps_its_internal_paths(h: Harness) -> None:
    """E16, decision 5: never suffix an internal member automatically.

    Renaming `A001.mov` to `A001 (2).mov` inside a project breaks exactly
    the references the "keep together" mark exists to protect — and does
    it silently, with `blocking_count` at zero.
    """
    saved = _group_preset(h)
    src = h.source("card", _GROUP_FILES)
    occupied = h.dest_root() / "Collections" / "card" / "Proj"
    occupied.mkdir(parents=True)
    (occupied / "edit.drp").write_bytes(b"somebody else's project")

    plan = h.plans.create(
        destination_id=h.destination(),
        inventory_ids=[src],
        preset_id=saved.preset_id,
        preset_revision=saved.revision,
    )
    entries = {e.rel_path: e for e in h.all_entries(plan.id)}
    assert entries["Proj/Media/A001.mov"].dest_rel_path == (
        "Collections/card/Proj (2)/Media/A001.mov"
    )
    assert entries["Proj/edit.drp"].dest_rel_path == "Collections/card/Proj (2)/edit.drp"
    assert entries["Proj/edit.drp"].renamed_from is None, "no member was renamed"
    assert entries["Proj/Media/A001.mov"].renamed_from is None

    root = entries["Proj"]
    assert root.entry_type == "dir"
    assert root.renamed_from == "Collections/card/Proj", "the move is recorded at the root"
    assert "no member was renamed individually" in (root.exclusion_reason or "")
    assert any("preserved group 'proj'" in w for w in plan.warnings)
    assert h.approve(plan).status == "approved"


def test_a_group_collision_blocks_whole_under_a_review_policy(h: Harness) -> None:
    """The alternative the examples allow: block, still never split."""
    saved = _group_preset(h)
    dest = h.destination(conflictPolicy="needs_review")
    src = h.source("card", _GROUP_FILES)
    occupied = h.dest_root() / "Collections" / "card" / "Proj"
    occupied.mkdir(parents=True)
    (occupied / "edit.drp").write_bytes(b"somebody else's project")

    plan = h.plans.create(
        destination_id=dest,
        inventory_ids=[src],
        preset_id=saved.preset_id,
        preset_revision=saved.revision,
    )
    entries = {e.rel_path: e for e in h.all_entries(plan.id)}
    members = [e for e in entries.values() if e.group_id == "proj"]
    assert members and all(e.action == "needs_review" for e in members)
    assert all(e.renamed_from is None for e in members)
    assert entries["loose.pdf"].action == "copy", "the rest of the plan is unaffected"
    with pytest.raises(TransferPlanError):
        h.plans.approve(plan.id, plan.fingerprint)


# --- R18: no empty fallback duplicate for every source parent ---


def test_a_parent_of_routed_files_gets_no_empty_fallback_folder(h: Harness) -> None:
    """The category preset routed files out and recreated their parents.

    `Photos/Trip` whose only contents went to `Images/...` came back as an
    empty `Unsorted/card/Photos/Trip` — a fallback duplicate of every
    source parent, which the agreed examples rule out (R18).
    """
    content = h.presets.builtin_content("sort-by-category")
    saved = h.presets.save_revision(SavePresetRevisionParams(name="cat", content=content))
    src = h.source("card", {"Photos/Trip/IMG_001.JPG": b"J"})
    plan = h.plans.create(
        destination_id=h.destination(),
        inventory_ids=[src],
        preset_id=saved.preset_id,
        preset_revision=saved.revision,
    )
    mapping = {e.rel_path: e.dest_rel_path for e in h.all_entries(plan.id)}
    assert mapping == {"Photos/Trip/IMG_001.JPG": "Images/card/Photos/Trip/IMG_001.JPG"}


def test_a_genuinely_empty_directory_keeps_its_entry(h: Harness) -> None:
    """§6.3: empty directories are preserved unless explicitly excluded.

    Nothing else will create it, so it is not implied by anything.
    """
    src_root = h.tmp_path / "card"
    (src_root / "Photos").mkdir(parents=True)
    (src_root / "Photos" / "a.jpg").write_bytes(b"J")
    (src_root / "Empty").mkdir()
    (src_root / "Photos" / "AlsoEmpty").mkdir()
    from file_ferry.application.inventory import wait_until_complete

    status = wait_until_complete(h.inventory, h.inventory.create(str(src_root), "card").id)
    plan = h.plans.create(destination_id=h.destination(), inventory_ids=[status.id])
    mapping = {e.rel_path: (e.entry_type, e.dest_rel_path) for e in h.all_entries(plan.id)}
    assert mapping["Empty"] == ("dir", "Sources/card/Empty")
    assert mapping["Photos/AlsoEmpty"] == ("dir", "Sources/card/Photos/AlsoEmpty")
    assert "Photos" not in mapping, "Photos holds a file this plan copies"


# --- R19: resolving an approved plan does not leave two live plans ---


def test_resolving_an_approved_plan_invalidates_it(h: Harness) -> None:
    """A08/§8: the reviewer's own decision superseded it.

    Leaving the parent approved left two plans for the same sources and
    destination, one of them approved, and the runner entitled to start
    either (R19).
    """
    src = h.source("card", {"a.txt": b"A", "b.txt": b"B"})
    plan = h.plans.create(destination_id=h.destination(), inventory_ids=[src])
    assert h.approve(plan).status == "approved"

    entry = next(e for e in h.all_entries(plan.id) if e.rel_path == "b.txt")
    child = h.plans.resolve(plan.id, entry_ids=[entry.id], reason="not needed")

    parent = h.plans.get(plan.id)
    assert parent.status == "invalidated"
    assert parent.approved_fingerprint is None, "the approval is cleared, not just the status"
    assert parent.superseded_by == child.id
    assert child.derived_from == plan.id, "the lineage survives"
    with pytest.raises(TransferPlanError, match="invalidated"):
        h.plans.approve(plan.id, plan.fingerprint)


def test_further_decisions_go_to_the_successor_not_the_superseded_plan(h: Harness) -> None:
    """Otherwise two sibling plans accumulate different halves of the review."""
    src = h.source("card", {"a.txt": b"A", "b.txt": b"B", "c.txt": b"C"})
    plan = h.plans.create(destination_id=h.destination(), inventory_ids=[src])
    entries = {e.rel_path: e for e in h.all_entries(plan.id)}
    child = h.plans.resolve(plan.id, entry_ids=[entries["b.txt"].id], reason="no")

    with pytest.raises(TransferPlanError, match="already superseded"):
        h.plans.resolve(plan.id, entry_ids=[entries["c.txt"].id], reason="no")

    child_entries = {e.rel_path: e for e in h.all_entries(child.id)}
    grandchild = h.plans.resolve(child.id, entry_ids=[child_entries["c.txt"].id], reason="no")
    assert grandchild.exclusion_count == 2, "decisions still accumulate down the line"
