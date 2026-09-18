"""Approval must validate the world, not its own records (spec §7.1, R09).

The failure these exist to prevent: a plan whose source files changed
and whose destination was removed was still approved, because every
check read a stored row and stored rows do not move when the filesystem
does.

These drive the real `ApplicationService` — mutating actual files and
actual directories — rather than editing database rows to simulate
change, which is precisely the shortcut that let the defect through.
"""

from __future__ import annotations

import errno
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest

from file_ferry.application.preflight import (
    PREFLIGHT_TTL_SECONDS,
    PreflightError,
    _supports_exclusive_publish,
    recover_abandoned_preflights,
)
from file_ferry.application.service import ApplicationService
from file_ferry.application.transfer_plan import TransferPlanError
from file_ferry.persistence.connection import transaction
from file_ferry.service.protocol import (
    InventoryCreateParams,
    InventoryStatusParams,
    PlanApproveParams,
    PlanCreateParams,
    PlanEntriesParams,
    PreflightStartParams,
    PreflightStatusParams,
    SaveDestinationParams,
)


class World:
    """A real service over a real source directory and destination."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.service = ApplicationService(
            db_path=tmp_path / "ferry.db", app_data_dir=tmp_path / "app"
        )
        self.service.bootstrap()
        self.source = tmp_path / "source"
        self.source.mkdir()
        (self.source / "a.txt").write_bytes(b"original bytes")
        (self.source / "nested").mkdir()
        (self.source / "nested" / "b.txt").write_bytes(b"more bytes")
        self.dest = tmp_path / "destination"
        self.dest.mkdir()

    def close(self) -> None:
        self.service.shutdown()
        self.service.close()

    def plan(self, **destination_kwargs: Any) -> Any:
        inventory_id = self.service.inventory_create(
            InventoryCreateParams(path=str(self.source), label="src")
        ).inventory_id
        while (
            self.service.inventory_status(InventoryStatusParams(id=inventory_id)).status
            == "scanning"
        ):
            time.sleep(0.01)
        destination = self.service.destination_save(
            SaveDestinationParams(name="D", path=str(self.dest), **destination_kwargs)
        )
        return self.service.transfer_plan_create(
            PlanCreateParams(destinationId=destination.id, inventoryIds=[inventory_id])
        )

    def first_copy_target(self, plan: Any) -> str:
        """The destination-relative path of a planned copy.

        Read from the plan rather than assumed: where a file lands is the
        rule engine's decision, and hard-coding it here would make these
        tests quietly stop testing anything the day a default changes.
        """
        page = self.service.transfer_plan_entries(PlanEntriesParams(id=plan.id, limit=1000))
        for entry in page.entries:
            if entry.action == "copy":
                return entry.dest_rel_path
        raise AssertionError("the plan has no copy entries")

    def preflight(self, plan_id: str) -> Any:
        started = self.service.transfer_preflight_start(PreflightStartParams(planId=plan_id))
        for _ in range(3000):
            status = self.service.transfer_preflight_status(PreflightStatusParams(id=started.id))
            if status.status != "running":
                return status
            time.sleep(0.01)
        raise AssertionError("preflight never finished")

    def approve(self, plan: Any) -> Any:
        return self.service.transfer_plan_approve(
            PlanApproveParams(id=plan.id, fingerprint=plan.fingerprint)
        )


@pytest.fixture
def world(tmp_path: Path) -> Any:
    w = World(tmp_path)
    try:
        yield w
    finally:
        w.close()


def test_an_unchanged_world_preflights_and_approves(world: World) -> None:
    """The gate must not block ordinary work."""
    plan = world.plan()
    status = world.preflight(plan.id)
    assert status.status == "passed", status.findings
    assert status.findings == []
    assert status.total_entries == status.checked_entries
    assert status.destination_status == "available"
    assert status.free_bytes is not None
    assert world.approve(plan).status == "approved"


def test_approval_without_a_preflight_is_refused(world: World) -> None:
    """Stored rows alone are never sufficient evidence."""
    from file_ferry.service.protocol import PlanIdParams

    plan = world.plan()
    with pytest.raises(TransferPlanError, match="has not been preflighted"):
        world.approve(plan)
    assert world.service.transfer_plan_get(PlanIdParams(id=plan.id)).status == "draft"


def test_changed_source_bytes_force_a_replan(world: World) -> None:
    """A stored manifest hash does not change when a file does."""
    plan = world.plan()
    (world.source / "a.txt").write_bytes(b"completely different content")

    status = world.preflight(plan.id)
    assert status.status == "failed"
    assert any("have changed since they were scanned" in f for f in status.findings)
    with pytest.raises(TransferPlanError, match="preflight failed"):
        world.approve(plan)


def test_a_file_added_to_the_source_forces_a_replan(world: World) -> None:
    """§7.1: additions require a replan, not a silent substitution."""
    plan = world.plan()
    (world.source / "surprise.txt").write_bytes(b"not in the plan")
    status = world.preflight(plan.id)
    assert status.status == "failed"
    assert any("have changed since they were scanned" in f for f in status.findings)


def test_a_deleted_planned_file_is_caught(world: World) -> None:
    plan = world.plan()
    (world.source / "nested" / "b.txt").unlink()
    status = world.preflight(plan.id)
    assert status.status == "failed"
    assert status.findings


def test_a_removed_destination_refuses_approval(world: World) -> None:
    """The exact reproduction from the review: destination gone, approved."""
    plan = world.plan()
    shutil.rmtree(world.dest)

    status = world.preflight(plan.id)
    assert status.status == "failed"
    assert any("destination is offline" in f for f in status.findings)
    with pytest.raises(TransferPlanError, match="preflight failed"):
        world.approve(plan)


def test_content_appearing_at_a_planned_target_refuses_approval(world: World) -> None:
    """§6.4: a new file at a reserved path invalidates that entry."""
    plan = world.plan()
    target = world.dest / world.first_copy_target(plan)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"someone else wrote this")

    status = world.preflight(plan.id)
    assert status.status == "failed"
    assert any("did not exist at planning time" in f for f in status.findings)


def test_a_broken_symlink_at_a_planned_target_still_counts_as_occupied(
    world: World,
) -> None:
    """`exists()` says no; the name is taken all the same."""
    plan = world.plan()
    target = world.dest / world.first_copy_target(plan)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(world.tmp_path / "nothing-here")
    status = world.preflight(plan.id)
    assert status.status == "failed"
    assert any("did not exist at planning time" in f for f in status.findings)


def test_capacity_is_recomputed_against_live_free_space(world: World) -> None:
    """Free space is a live number; the reserve is part of what is needed."""
    plan = world.plan(freeSpaceReserve=10**15)
    status = world.preflight(plan.id)
    assert status.status == "failed"
    assert any("bytes free but the plan needs" in f for f in status.findings)


def test_a_preflight_for_a_different_fingerprint_is_not_accepted(world: World) -> None:
    """Evidence is bound to the exact plan it validated."""
    plan = world.plan()
    assert world.preflight(plan.id).status == "passed"
    with transaction(world.tmp_path / "ferry.db") as conn:
        conn.execute(
            "UPDATE transfer_plan_preflights SET fingerprint = 'a-different-plan' "
            "WHERE plan_id = ?",
            (plan.id,),
        )
    with pytest.raises(TransferPlanError, match="different version of this plan"):
        world.approve(plan)


def test_an_expired_pass_is_re_run_not_trusted(world: World) -> None:
    """Storage can vanish in the window between checking and approving."""
    plan = world.plan()
    assert world.preflight(plan.id).status == "passed"
    stale = "2020-01-01T00:00:00Z"
    with transaction(world.tmp_path / "ferry.db") as conn:
        conn.execute(
            "UPDATE transfer_plan_preflights SET finished_at = ? WHERE plan_id = ?",
            (stale, plan.id),
        )
    with pytest.raises(TransferPlanError, match=f"older than {int(PREFLIGHT_TTL_SECONDS)}s"):
        world.approve(plan)


def test_a_later_failure_supersedes_an_earlier_pass(world: World) -> None:
    """Approval reads the latest run, not the most convenient one."""
    plan = world.plan()
    assert world.preflight(plan.id).status == "passed"
    shutil.rmtree(world.dest)
    assert world.preflight(plan.id).status == "failed"
    with pytest.raises(TransferPlanError, match="preflight failed"):
        world.approve(plan)


def test_a_running_preflight_blocks_approval_rather_than_being_ignored(
    world: World, tmp_path: Path
) -> None:
    plan = world.plan()
    world.preflight(plan.id)
    with transaction(tmp_path / "ferry.db") as conn:
        conn.execute(
            "UPDATE transfer_plan_preflights SET status = 'running', finished_at = NULL "
            "WHERE plan_id = ?",
            (plan.id,),
        )
    with pytest.raises(TransferPlanError, match="still running"):
        world.approve(plan)


def test_abandoned_preflights_are_failed_on_restart(world: World, tmp_path: Path) -> None:
    """A stuck `running` row must never read as "not failed, so fine"."""
    plan = world.plan()
    world.preflight(plan.id)
    with transaction(tmp_path / "ferry.db") as conn:
        conn.execute(
            "UPDATE transfer_plan_preflights SET status = 'running', finished_at = NULL "
            "WHERE plan_id = ?",
            (plan.id,),
        )
    moved = recover_abandoned_preflights(tmp_path / "ferry.db")
    assert moved
    with transaction(tmp_path / "ferry.db") as conn:
        row = conn.execute(
            "SELECT status, findings_json FROM transfer_plan_preflights WHERE plan_id = ?",
            (plan.id,),
        ).fetchone()
    assert row["status"] == "failed"
    assert "abandoned" in row["findings_json"]


def test_preflight_reports_progress_over_a_large_plan(world: World) -> None:
    """§12: an expensive check must be observable, not a silent block."""
    for i in range(1200):
        (world.source / f"f{i:04d}.txt").write_bytes(b"x")
    plan = world.plan()
    status = world.preflight(plan.id)
    assert status.status == "passed", status.findings
    assert status.total_entries == status.checked_entries
    assert status.checked_entries >= 1200


def test_preflight_of_a_missing_plan_raises(world: World) -> None:
    with pytest.raises(PreflightError, match="not found"):
        world.service.transfer_preflight_start(PreflightStartParams(planId="no-such-plan"))


def test_a_local_folder_with_unverifiable_backing_fails_preflight(world: World) -> None:
    """R12 through the real pipeline, not just the resolver.

    `local_folder` is the default destination kind, so a local folder
    whose recorded storage evidence cannot be matched against what is
    actually mounted must stop the transfer at approval — not merely
    report an unhappy resolver state that nothing reads.

    The evidence is recorded *before* the plan is built, so this tests
    the preflight rather than the (separately covered) invalidation that
    a rebinding triggers.
    """
    from file_ferry.application.destinations import DestinationService
    from file_ferry.service.protocol import DestinationIdentity

    destinations = DestinationService(world.tmp_path / "ferry.db")
    saved = world.service.destination_save(SaveDestinationParams(name="D", path=str(world.dest)))
    # Confirming without observations is the §5.1 escape hatch, so the
    # service accepts this; the live observations then disagree with it.
    destinations.confirm_binding(
        saved.id,
        path=str(world.dest),
        identity=DestinationIdentity(
            kind="volume_uuid",
            value="a-disk-this-folder-is-not-on",
            confidence="strong",
            provenance="test",
        ),
    )

    inventory_id = world.service.inventory_create(
        InventoryCreateParams(path=str(world.source), label="src")
    ).inventory_id
    while (
        world.service.inventory_status(InventoryStatusParams(id=inventory_id)).status == "scanning"
    ):
        time.sleep(0.01)
    plan = world.service.transfer_plan_create(
        PlanCreateParams(destinationId=saved.id, inventoryIds=[inventory_id])
    )

    status = world.preflight(plan.id)
    assert status.status == "failed"
    assert any("destination is needs_confirmation" in f for f in status.findings), status.findings
    with pytest.raises(TransferPlanError, match="preflight failed"):
        world.approve(plan)


def test_an_ordinary_local_folder_still_passes_preflight(world: World) -> None:
    """The default path must not need a confirmation dance to work."""
    plan = world.plan()
    status = world.preflight(plan.id)
    assert status.status == "passed", status.findings
    assert status.destination_status == "available"
    assert world.approve(plan).status == "approved"


def test_a_symlink_appearing_at_a_planned_path_fails_preflight(world: World) -> None:
    """R16: the plan was clean; the destination changed underneath it.

    The planner refuses a symlink it can see, but preflight is what
    stands between review and execution — and a link created after
    planning is exactly the change stored rows cannot show. `is_dir()`
    follows links, so the component has to be tested with `lstat`, and at
    every level: the planner emits no directory entry for a parent its
    own routed children imply.
    """
    plan = world.plan()
    assert world.preflight(plan.id).status == "passed"

    target = Path(world.first_copy_target(plan))
    parent = world.dest / target.parent
    parent.parent.mkdir(parents=True, exist_ok=True)
    outside = world.tmp_path / "elsewhere"
    outside.mkdir()
    parent.symlink_to(outside, target_is_directory=True)

    status = world.preflight(plan.id)
    assert status.status == "failed"
    assert any("symbolic link" in f for f in status.findings), status.findings
    with pytest.raises(TransferPlanError, match="preflight failed"):
        world.approve(plan)


def test_a_real_directory_appearing_at_a_planned_path_still_passes(world: World) -> None:
    """The symlink check must not refuse an ordinary destination folder."""
    plan = world.plan()
    target = Path(world.first_copy_target(plan))
    (world.dest / target.parent).mkdir(parents=True, exist_ok=True)
    assert world.preflight(plan.id).status == "passed"
    assert world.approve(plan).status == "approved"


# ---- publish capability (#211) ---------------------------------------------
#
# Every file is published with `os.link`, which macOS SMB refuses with
# ENOTSUP. Preflight must find that out before approval, not let the first
# item fail mid-transfer. Real SMB is unreachable from CI, so the refusing
# filesystem below is a monkeypatched `os.link`; only the *errno* is the
# one the primitive actually returns. No test here claims to have touched a
# real network mount.


def _link_raising(code: int) -> Any:
    def link(src: object, dst: object, **kwargs: object) -> None:
        raise OSError(code, os.strerror(code), str(dst))

    return link


def _probe_leftovers(root: Path) -> list[str]:
    return sorted(p.name for p in root.iterdir())


class TestPublishCapabilityProbe:
    def test_probe_passes_where_link_works(self, tmp_path: Path) -> None:
        target = tmp_path / "dest"
        target.mkdir()
        assert _supports_exclusive_publish(target) is True
        assert _probe_leftovers(target) == []

    @pytest.mark.parametrize(
        "code",
        [errno.ENOTSUP, errno.EOPNOTSUPP, errno.EPERM, errno.EACCES, errno.ENOSYS, errno.EMLINK],
        ids=["ENOTSUP", "EOPNOTSUPP", "EPERM", "EACCES", "ENOSYS", "EMLINK"],
    )
    def test_probe_detects_a_link_less_filesystem(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int
    ) -> None:
        target = tmp_path / "dest"
        target.mkdir()
        monkeypatch.setattr(os, "link", _link_raising(code))
        assert _supports_exclusive_publish(target) is False
        # The half-created file is cleaned up on the failure path too.
        assert _probe_leftovers(target) == []

    def test_probe_raises_when_it_cannot_run_at_all(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A read-only or unsearchable root is reported, never read as a pass."""
        target = tmp_path / "dest"
        target.mkdir()

        def refuse(*args: object, **kwargs: object) -> tuple[int, str]:
            raise OSError(errno.EROFS, os.strerror(errno.EROFS))

        monkeypatch.setattr(tempfile, "mkstemp", refuse)
        with pytest.raises(OSError) as caught:
            _supports_exclusive_publish(target)
        assert caught.value.errno == errno.EROFS


def test_a_link_less_destination_is_refused_before_approval(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#211's safety net: the destination is named and blocking, up front."""
    plan = world.plan()
    monkeypatch.setattr(os, "link", _link_raising(errno.ENOTSUP))

    status = world.preflight(plan.id)
    assert status.status == "failed"
    assert status.resolved_binding_path is not None
    assert any(
        status.resolved_binding_path in finding and "non-overwriting publish" in finding
        for finding in status.findings
    ), status.findings
    with pytest.raises(TransferPlanError, match="preflight failed"):
        world.approve(plan)
    assert _probe_leftovers(world.dest) == []


def test_a_local_destination_is_not_flagged_and_collects_no_debris(world: World) -> None:
    """The converse: a volume that can link is unaffected and left clean."""
    plan = world.plan()
    status = world.preflight(plan.id)
    assert status.status == "passed", status.findings
    assert not any("non-overwriting publish" in finding for finding in status.findings)
    assert _probe_leftovers(world.dest) == []
    assert world.approve(plan).status == "approved"


def test_a_destination_the_probe_cannot_test_fails_closed(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not being able to test the primitive is not evidence that it works."""
    plan = world.plan()

    def refuse(*args: object, **kwargs: object) -> tuple[int, str]:
        raise OSError(errno.EROFS, os.strerror(errno.EROFS))

    monkeypatch.setattr(tempfile, "mkstemp", refuse)
    status = world.preflight(plan.id)
    assert status.status == "failed"
    assert any("could not check whether" in finding for finding in status.findings), status.findings
    with pytest.raises(TransferPlanError, match="preflight failed"):
        world.approve(plan)
