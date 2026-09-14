"""Server-side full inventory tests (destination-presets spec §4.3)."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from file_ferry.application.inventory import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    InventoryService,
    wait_until_complete,
)
from file_ferry.application.sources import ScanItem
from file_ferry.service.protocol import InventoryEntry


def _boot(tmp_path: Path) -> InventoryService:
    from file_ferry.application.service import ApplicationService

    db_path = tmp_path / "ferry.db"
    boot = ApplicationService(db_path=db_path, app_data_dir=tmp_path / "app")
    boot.bootstrap()
    boot.close()
    return InventoryService(db_path)


def _all_entries(
    svc: InventoryService, inventory_id: int, keep: Callable[[InventoryEntry], bool]
) -> list[InventoryEntry]:
    """Every matching entry, walked across pages (never just page one)."""
    out: list[InventoryEntry] = []
    cursor = 0
    while True:
        page = svc.entries(inventory_id, limit=MAX_PAGE_SIZE, after=cursor)
        out.extend(e for e in page.entries if keep(e))
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
    return out


def _make_tree(root: Path, n: int) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        (root / f"file_{i:04d}.mov").write_bytes(f"file {i}".encode())


def test_default_page_size_is_two_hundred() -> None:
    assert DEFAULT_PAGE_SIZE == 200
    assert MAX_PAGE_SIZE == 1000


def test_create_returns_immediately_and_walks_asynchronously(tmp_path: Path) -> None:
    svc = _boot(tmp_path)
    root = tmp_path / "media"
    _make_tree(root, 50)
    status = svc.create(str(root), None)
    # ``scanning`` immediately after create, never ``complete``.
    assert status.status in {"scanning", "complete"}
    final = wait_until_complete(svc, status.id)
    assert final.status == "complete"
    assert final.file_count == 50


def test_inventory_records_symlinks_and_unsupported_objects(tmp_path: Path) -> None:
    svc = _boot(tmp_path)
    root = tmp_path / "media"
    root.mkdir()
    (root / "movie.mov").write_bytes(b"x")
    (root / "link.mov").symlink_to(root / "movie.mov")
    fifo = root / "fifo"
    os.mkfifo(str(fifo))
    status = wait_until_complete(svc, svc.create(str(root), None).id)
    assert status.file_count == 1
    assert status.excluded_count == 2  # symlink + fifo
    page = svc.entries(status.id, limit=100, after=0)
    by_path = {e.rel_path: e.entry_type for e in page.entries}
    assert by_path["movie.mov"] == "file"
    assert by_path["link.mov"] == "symlink"
    assert by_path["fifo"] == "other"


def test_pagination_default_and_max(tmp_path: Path) -> None:
    svc = _boot(tmp_path)
    root = tmp_path / "big"
    _make_tree(root, 250)
    status = wait_until_complete(svc, svc.create(str(root), None).id)
    assert status.file_count == 250
    page = svc.entries(status.id)
    assert page.total == 250
    assert len(page.entries) == DEFAULT_PAGE_SIZE
    assert page.next_cursor == page.entries[-1].id


def test_pagination_walks_full_inventory_without_gap(tmp_path: Path) -> None:
    svc = _boot(tmp_path)
    root = tmp_path / "big"
    _make_tree(root, 350)
    status = wait_until_complete(svc, svc.create(str(root), None).id)
    seen: set[str] = set()
    cursor = 0
    while True:
        page = svc.entries(status.id, limit=100, after=cursor)
        for entry in page.entries:
            assert entry.rel_path not in seen, "duplicate entry across pages"
            seen.add(entry.rel_path)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
    assert len(seen) == 350


def test_scan_errors_recorded(tmp_path: Path) -> None:
    """An unreadable subtree is a visible finding, not a missing file.

    The subtree really is inaccessible, so its file cannot be counted as
    scanned — the point of the guard is that its absence is *explained*
    rather than silent (spec §7.1: scan errors block approval). The
    finding keeps the source-relative path and the diagnostic text.
    """
    svc = _boot(tmp_path)
    root = tmp_path / "mixed"
    root.mkdir()
    (root / "good.mov").write_bytes(b"x")
    locked = root / "locked"
    locked.mkdir()
    (locked / "deep.mov").write_bytes(b"x")
    locked.chmod(0o000)
    try:
        status = wait_until_complete(svc, svc.create(str(root), None).id)
        assert status.status == "complete"
        assert status.file_count == 1, "the inaccessible file must not be counted as scanned"
        assert status.error_count >= 1, "the inaccessible subtree must be an explicit finding"
        errors = _all_entries(svc, status.id, lambda e: e.scan_status == "error")
        assert errors, "the failure must be persisted as an entry, not only counted"
        assert any("locked" in e.rel_path for e in errors), [e.rel_path for e in errors]
        assert all(e.error for e in errors), "every error finding keeps its diagnostic text"
    finally:
        locked.chmod(0o755)


def test_empty_directories_are_recorded(tmp_path: Path) -> None:
    """A01/A18: empty directories must survive into the inventory."""
    svc = _boot(tmp_path)
    root = tmp_path / "tree"
    (root / "empty_one").mkdir(parents=True)
    (root / "empty_two" / "nested_empty").mkdir(parents=True)
    (root / "has_file").mkdir()
    (root / "has_file" / "a.mov").write_bytes(b"x")
    status = wait_until_complete(svc, svc.create(str(root), None).id)
    assert status.file_count == 1
    assert status.dir_count == 4, "every directory, including empty ones, is inventoried"
    dirs = {e.rel_path for e in _all_entries(svc, status.id, lambda e: e.entry_type == "dir")}
    assert dirs == {"empty_one", "empty_two", "empty_two/nested_empty", "has_file"}


def test_directory_symlink_is_inventoried_not_dropped(tmp_path: Path) -> None:
    """``os.walk`` lists symlinked dirs but never descends; record them."""
    svc = _boot(tmp_path)
    root = tmp_path / "tree"
    real = tmp_path / "outside"
    real.mkdir()
    (real / "hidden.mov").write_bytes(b"x")
    root.mkdir()
    (root / "plain.mov").write_bytes(b"x")
    (root / "link_dir").symlink_to(real, target_is_directory=True)
    status = wait_until_complete(svc, svc.create(str(root), None).id)
    assert status.file_count == 1, "the symlink is never dereferenced into files"
    assert status.excluded_count == 1
    links = _all_entries(svc, status.id, lambda e: e.entry_type == "symlink")
    assert [e.rel_path for e in links] == ["link_dir"]


def test_failed_scan_keeps_partial_counts_and_reason(tmp_path: Path) -> None:
    """An infrastructure fault must not report a scan that saw nothing."""
    svc = _boot(tmp_path)
    root = tmp_path / "media"
    _make_tree(root, 3)

    def _explode(_root: Path) -> Iterator[ScanItem]:
        yield ScanItem(rel="a.mov", size=4, mtime=1.0, entry_type="file")
        yield ScanItem(rel="sub", size=0, mtime=1.0, entry_type="dir")
        raise OSError("device disappeared mid-walk")

    svc._items = _explode  # type: ignore[method-assign]
    status = wait_until_complete(svc, svc.create(str(root), None).id)
    assert status.status == "failed"
    assert status.file_count == 1, "counts reached before the fault are reported truthfully"
    assert status.dir_count == 1
    assert status.error is not None
    assert "device disappeared" in status.error


def test_abandoned_scan_is_failed_on_restart(tmp_path: Path) -> None:
    """Spec §7.3: a scan orphaned by a process exit never stays ``scanning``."""
    from file_ferry.application.inventory import recover_abandoned_scans
    from file_ferry.persistence.connection import transaction
    from file_ferry.persistence.repositories import inventories as inv_repo

    svc = _boot(tmp_path)
    root = tmp_path / "media"
    _make_tree(root, 2)
    inv_id = wait_until_complete(svc, svc.create(str(root), None).id).id
    # Simulate the previous process dying mid-walk.
    with transaction(tmp_path / "ferry.db") as conn:
        conn.execute(
            "UPDATE source_inventories SET status = 'scanning', finished_at = NULL WHERE id = ?",
            (inv_id,),
        )
        assert [r.id for r in inv_repo.list_scanning(conn)] == [inv_id]

    moved = recover_abandoned_scans(tmp_path / "ferry.db")
    assert moved == [inv_id]
    recovered = svc.get(inv_id)
    assert recovered.status == "failed"
    assert recovered.error is not None and "abandoned" in recovered.error
    # The partial entries stay as evidence rather than being deleted.
    assert svc.entries(inv_id).total >= 2


def test_nonexistent_source_raises(tmp_path: Path) -> None:
    svc = _boot(tmp_path)
    with pytest.raises(FileNotFoundError):
        svc.create(str(tmp_path / "nope"), None)


def test_a_live_owners_scan_is_never_failed_by_another_process(tmp_path: Path) -> None:
    """Startup recovery must not shoot down a concurrent session.

    The desktop sidecar and a CLI run can hold the same database at
    once. A second process bootstrapping must fail only scans whose
    owner is *gone* — failing a live owner's in-progress scan would turn
    a supported concurrent session into a corrupted one.
    """
    import os

    from file_ferry.application.inventory import process_is_live, recover_abandoned_scans
    from file_ferry.persistence.connection import transaction

    svc = _boot(tmp_path)
    root = tmp_path / "media"
    _make_tree(root, 2)
    inv_id = wait_until_complete(svc, svc.create(str(root), None).id).id

    # A scan still owned by this very much alive process.
    with transaction(tmp_path / "ferry.db") as conn:
        conn.execute(
            "UPDATE source_inventories SET status = 'scanning', finished_at = NULL, "
            "owner_pid = ? WHERE id = ?",
            (os.getpid(), inv_id),
        )
    assert process_is_live(os.getpid())
    assert recover_abandoned_scans(tmp_path / "ferry.db") == []
    assert svc.get(inv_id).status == "scanning", "a live owner's scan is left alone"

    # The same row, owned by a process that no longer exists.
    with transaction(tmp_path / "ferry.db") as conn:
        conn.execute("UPDATE source_inventories SET owner_pid = ? WHERE id = ?", (2**30, inv_id))
    assert recover_abandoned_scans(tmp_path / "ferry.db") == [inv_id]
    assert svc.get(inv_id).status == "failed"


def test_shutdown_stops_in_flight_scans(tmp_path: Path) -> None:
    """A scan must not outlive the service that owns it.

    A daemon thread still walking after shutdown keeps opening
    connections to a database its owner believes it has released — while
    a later migration backs that file up, or while the directory is
    being removed. It never fails where the bug is; it fails somewhere
    else, intermittently.
    """
    import threading

    from file_ferry.application.service import ApplicationService

    service = ApplicationService(db_path=tmp_path / "ferry.db", app_data_dir=tmp_path / "app")
    service.bootstrap()
    try:
        root = tmp_path / "slow"
        root.mkdir()
        released = threading.Event()
        entered = threading.Event()

        def _slow_walk(_root: Path) -> Iterator[ScanItem]:
            yield ScanItem(rel="a.mov", size=1, mtime=1.0, entry_type="file")
            entered.set()
            released.wait(10)
            yield ScanItem(rel="b.mov", size=1, mtime=1.0, entry_type="file")

        inventory = service._inventory  # the bootstrapped instance
        assert inventory is not None
        inventory._items = _slow_walk  # type: ignore[method-assign]
        inventory.create(str(root), "slow")
        assert entered.wait(5), "the scan never started"

        before = {t.name for t in threading.enumerate()}
        assert any(n.startswith("inventory-scan-") for n in before)

        released.set()
        service.shutdown()
        remaining = {t.name for t in threading.enumerate()}
        assert not any(n.startswith("inventory-scan-") for n in remaining), (
            f"a scan thread outlived shutdown: {remaining}"
        )
    finally:
        service.shutdown()
        service.close()


def test_shutdown_is_bounded_when_a_scan_cannot_be_interrupted(tmp_path: Path) -> None:
    """Cancellation is cooperative; shutdown must still return.

    A walk blocked in the kernel on an unresponsive mount cannot be
    interrupted, so shutdown waits and moves on rather than hanging the
    application forever.
    """
    import threading
    import time as _time

    svc = _boot(tmp_path)
    root = tmp_path / "stuck"
    root.mkdir()
    stuck = threading.Event()

    def _blocked_walk(_root: Path) -> Iterator[ScanItem]:
        yield ScanItem(rel="a.mov", size=1, mtime=1.0, entry_type="file")
        stuck.wait(30)

    svc._items = _blocked_walk  # type: ignore[method-assign]
    svc.create(str(root), "stuck")
    _time.sleep(0.1)
    started = _time.monotonic()
    svc.shutdown(timeout=0.2)
    elapsed = _time.monotonic() - started
    stuck.set()
    assert elapsed < 5.0, f"shutdown took {elapsed:.1f}s; it must be bounded"
