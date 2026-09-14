"""Transfer plans — durable, fingerprint-hashed plans (spec §4.3, §7.1).

A plan is what the user reviewed and approved: a snapshot of the
destination identity and binding, the chosen preset revision and its
content hash, the inventories it was derived from at the manifest
revision they had, the per-entry source-to-destination mapping with
action and conflict findings, the policy and reserve in force, a
capacity estimate, and a deterministic fingerprint over all of it.
Plans are immutable — the only mutation is the approval state, and
approval is keyed to the fingerprint so any later change (preset,
binding, source, conflict decisions) invalidates it rather than
allowing execution under stale terms.

Two rules shape everything here, and both exist because getting them
wrong loses files silently:

**A source is (inventory, entry), never a relative name.** Two drives
that both contain ``same.txt`` are two entries that *collide at one
destination path*. Treating the second as a duplicate of the first
drops a file the user asked to transfer and reports success.

**Nothing is excluded implicitly.** A scan error, an unsupported object,
a path that will not render safely — each stays in the plan as a
blocking review item until a person decides. An entry that vanished into
an exclusion counter is an entry nobody chose to leave behind.

Routing is the rule engine's (``application/rules.py``): keep-together
groups first, then ordered rules, first match wins, then the fallback.
Conflicts are the allocator's (``application/conflicts.py``): keep-both
by default with deterministic suffixes reserved against both the other
planned entries and the existing destination contents.

``skip_identical`` is still never issued. It requires proof of full
content equality (§6.4), and the checksums that prove it belong to the
P5 runner — so a plan records the conflict and a person decides, rather
than the planner asserting an identity it has not verified.

Decisions are carried, not applied in place. Resolving findings produces
a **new plan** (§8: "planResolve … produce a new plan revision after
decisions"), keyed by ``(inventory, source-relative path)`` so they
survive the rebuild that reassigns entry ids. An exclusion always
records who asked for it: ``excluded_by_user`` is what separates a
decision somebody made from a finding nobody has looked at yet.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import uuid
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from file_ferry.application import conflicts as conflict_rules
from file_ferry.application import rules as rule_engine
from file_ferry.application.preflight import PREFLIGHT_TTL_SECONDS, preflight_is_current
from file_ferry.application.presets import revision_root_prefix
from file_ferry.persistence.connection import transaction
from file_ferry.persistence.repositories import destinations as dest_repo
from file_ferry.persistence.repositories import inventories as inv_repo
from file_ferry.persistence.repositories import preflights as preflight_repo
from file_ferry.persistence.repositories import preset_revisions as revision_repo
from file_ferry.persistence.repositories import transfer_plans as plan_repo
from file_ferry.persistence.repositories.destinations import SavedDestinationRow
from file_ferry.persistence.repositories.inventories import InventoryEntryRow, InventoryRow
from file_ferry.persistence.repositories.preset_revisions import PresetRevisionRow
from file_ferry.persistence.repositories.transfer_plans import (
    TransferPlanEntryRow,
    TransferPlanRow,
)
from file_ferry.service.protocol import (
    PlanDecision,
    PlanEntriesPage,
    PresetContent,
    TransferPlanEntryModel,
    TransferPlanStatusModel,
)

#: Actions that mean "this plan cannot execute until a person decides".
BLOCKING_ACTIONS = frozenset({"needs_review"})

#: Entry types the P2 mapper can route. Everything else is a finding the
#: user must resolve — symlinks and unsupported objects are inventoried
#: and flagged, never dereferenced or recreated (spec §6.3).
_ROUTABLE_TYPES = frozenset({"file", "dir"})

_PAGE = 1000


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class TransferPlanError(ValueError):
    """Raised when a plan cannot be built, fetched, or approved."""


class TransferPlanNotFoundError(KeyError):
    """Raised when a named plan does not exist."""


@dataclass
class _Draft:
    """One entry under construction, before duplicate resolution."""

    inventory_id: int
    inventory_entry_id: int
    source_path: str
    rel_path: str
    entry_type: str
    dest_rel_path: str
    matched_rule: str | None
    size: int
    mtime: float | None
    action: str
    conflict: str | None
    exclusion_reason: str | None = None
    excluded_by_user: bool = False
    renamed_from: str | None = None
    warnings: list[str] = field(default_factory=list)
    #: The keep-together group this entry belongs to, the source subtree
    #: root that group claimed, and the destination that root evaluates
    #: to. Carried so a collision can be resolved at the root rather than
    #: by suffixing an internal member (spec §6.3, examples E16).
    group_id: str | None = None
    group_root: str | None = None
    group_dest_root: str | None = None
    #: Set on a directory entry that must survive the implied-directory
    #: pass: a relocated group root carries the decision that moved it.
    keep_dir: bool = False


@dataclass
class _InventorySnapshot:
    """What an inventory looked like when the plan was built.

    Approval re-reads this: a source that changed since review must
    force a replan rather than quietly substituting a different file
    list (spec §7.1).
    """

    inventory_id: int
    root_path: str
    label: str | None
    manifest_hash: str | None
    file_count: int
    dir_count: int
    error_count: int
    excluded_count: int
    total_bytes: int
    finished_at: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "inventoryId": self.inventory_id,
            "rootPath": self.root_path,
            "label": self.label,
            "manifestHash": self.manifest_hash,
            "fileCount": self.file_count,
            "dirCount": self.dir_count,
            "errorCount": self.error_count,
            "excludedCount": self.excluded_count,
            "totalBytes": self.total_bytes,
            "finishedAt": self.finished_at,
        }


class TransferPlanService:
    """Build, fetch, and approve transfer plans."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)

    # ---- create ------------------------------------------------------

    def create(
        self,
        *,
        destination_id: int,
        inventory_ids: Iterable[int],
        binding_path: str | None = None,
        preset_id: int | None = None,
        preset_revision: int | None = None,
        project_id: str | None = None,
        capacity_override_reason: str | None = None,
        decisions: Iterable[PlanDecision] | None = None,
        derived_from: str | None = None,
    ) -> TransferPlanStatusModel:
        """Build a plan from one or more inventories against a destination.

        Every input is captured verbatim and hashed into the
        fingerprint: the destination binding and identity evidence, the
        pinned preset revision and its content hash, the inventory
        manifests, the conflict/checksum/reserve policy, and the
        per-entry mapping. A later change to any of them is a different
        plan, not a silently re-approved one.
        """
        ids = list(inventory_ids)
        if not ids:
            raise TransferPlanError("at least one inventoryId is required")
        if len(set(ids)) != len(ids):
            raise TransferPlanError(
                "the same inventory was selected more than once; select each source exactly once"
            )
        plan_id = str(uuid.uuid4())
        with transaction(self._db_path) as conn:
            dest_row = self._load_destination(conn, destination_id)
            destination_root = self._resolve_binding(dest_row, binding_path)
            preset_row = self._load_preset_revision(conn, preset_id, preset_revision, dest_row)
            inventories = self._load_inventories(conn, ids)
            _reject_overlapping_sources(inventories, destination_root)
            plan, entries = _build_plan(
                plan_id=plan_id,
                conn=conn,
                inventories=inventories,
                destination_root=destination_root,
                dest_row=dest_row,
                preset_row=preset_row,
                preset_content=_content_of(preset_row),
                project_id=project_id,
                capacity_override_reason=capacity_override_reason,
                decisions=list(decisions or []),
                derived_from=derived_from,
            )
            plan_repo.insert_plan(conn, plan)
            if entries:
                plan_repo.insert_plan_entries(conn, plan_id, entries)
        return _to_status(plan)

    def resolve(
        self,
        plan_id: str,
        *,
        entry_ids: Iterable[int] = (),
        decisions: Iterable[PlanDecision] = (),
        reason: str | None = None,
    ) -> TransferPlanStatusModel:
        """Apply reviewed decisions, producing a **new** plan (spec §8).

        Plans are immutable, so a decision never edits one: it builds the
        next revision from the same inputs with the decision carried in,
        and records which plan it came from. The original stays exactly
        as it was reviewed.

        Decisions accumulate. Excluding one finding does not discard the
        decisions already made about the others, which would make a plan
        with several findings impossible to work through.
        """
        with transaction(self._db_path) as conn:
            row = plan_repo.get_plan(conn, plan_id)
            if row is None:
                raise TransferPlanNotFoundError(plan_id)
            if row.status in {"executing", "executed"}:
                raise TransferPlanError(
                    f"plan {plan_id} is {row.status}; a plan that has run cannot be edited"
                )
            if row.superseded_by is not None:
                raise TransferPlanError(
                    f"plan {plan_id} was already superseded by {row.superseded_by}; "
                    "record further decisions against that plan so they accumulate in "
                    "one line of revisions"
                )
            merged = _merge_decisions(
                _decisions_of(row),
                self._decisions_from_entries(conn, plan_id, entry_ids, reason),
                list(decisions),
            )
            snapshots = _snapshots_of(row)
            inventory_ids = [int(s["inventoryId"]) for s in snapshots]
            if row.destination_id is None:
                raise TransferPlanError("this plan has no saved destination to rebuild against")
            destination_id = row.destination_id
            preset_id = row.preset_id
            preset_revision = row.preset_revision
            project_id = row.project_id
            capacity_override_reason = row.capacity_override_reason
        if not merged:
            raise TransferPlanError("no decisions were supplied, so there is nothing to resolve")
        child = self.create(
            destination_id=destination_id,
            inventory_ids=inventory_ids,
            preset_id=preset_id,
            preset_revision=preset_revision,
            project_id=project_id,
            capacity_override_reason=capacity_override_reason,
            decisions=merged,
            derived_from=plan_id,
        )
        # The parent described a transfer the reviewer has just decided
        # against. Leaving its approval standing would leave two plans
        # for the same sources and destination, one of them approved and
        # superseded by its own reviewer's decision — and the runner
        # would be entitled to start it (R19). Invalidation happens after
        # the successor exists, so a failed rebuild leaves the plan the
        # user reviewed exactly as it was.
        with transaction(self._db_path) as conn:
            plan_repo.mark_superseded(conn, plan_id, by_plan_id=child.id)
        return child

    def _decisions_from_entries(
        self,
        conn: sqlite3.Connection,
        plan_id: str,
        entry_ids: Iterable[int],
        reason: str | None,
    ) -> list[PlanDecision]:
        """Translate review-screen entry ids into stable decision keys."""
        wanted = set(entry_ids)
        if not wanted:
            return []
        found: list[PlanDecision] = []
        after_id = 0
        while wanted:
            batch = plan_repo.page_plan_entries(conn, plan_id, limit=1000, after_id=after_id)
            if not batch:
                break
            for entry in batch:
                if entry.id in wanted and entry.inventory_id is not None:
                    wanted.discard(entry.id)
                    found.append(
                        PlanDecision(
                            inventoryId=entry.inventory_id,
                            relPath=entry.rel_path,
                            action="exclude",
                            reason=reason or entry.exclusion_reason,
                        )
                    )
            after_id = batch[-1].id
        if wanted:
            raise TransferPlanError(f"entries {sorted(wanted)} are not part of plan {plan_id}")
        return found

    # ---- read --------------------------------------------------------

    def get(self, plan_id: str) -> TransferPlanStatusModel:
        with transaction(self._db_path) as conn:
            row = plan_repo.get_plan(conn, plan_id)
        if row is None:
            raise TransferPlanNotFoundError(plan_id)
        return _to_status(row)

    def entries(self, plan_id: str, *, limit: int = 200, after: int = 0) -> PlanEntriesPage:
        effective_limit = max(1, min(int(limit), 1000))
        with transaction(self._db_path) as conn:
            rows = plan_repo.page_plan_entries(
                conn, plan_id, limit=effective_limit + 1, after_id=after
            )
            total = plan_repo.count_plan_entries(conn, plan_id)
        next_cursor: int | None = None
        if len(rows) > effective_limit:
            next_cursor = rows[effective_limit - 1].id
            rows = rows[:effective_limit]
        return PlanEntriesPage(
            entries=[_to_entry(r) for r in rows],
            total=total,
            nextCursor=next_cursor,
        )

    # ---- approval ----------------------------------------------------

    def approve(self, plan_id: str, fingerprint: str) -> TransferPlanStatusModel:
        """Approve an exact fingerprint, or explain why it cannot be.

        Approval is the gate execution trusts, so it checks three
        different things — and the third is the one that took a review
        round to get right:

        1. **The plan has not changed.** The caller's fingerprint must
           match.
        2. **The plan was ever approvable.** No unresolved blocking
           findings, no archived destination, no preset whose content
           hash moved, no inventory that is no longer complete, enough
           capacity, an override recorded where free space is unknown.
        3. **The world still matches it.** Steps 1 and 2 read stored
           rows, and stored rows do not move when a file is edited, a
           drive is unplugged, or a share unmounts. So approval requires
           a **preflight** that went back to the filesystem and the live
           storage observations — see :mod:`file_ferry.application.preflight`.
           Without one, approval refuses; it does not approve on the
           strength of records that describe a moment that has passed.

        The preflight must be passing, for this exact fingerprint, and
        recent. It is still not a substitute for the publication-time
        checks the P5 runner owes: preflight bounds the window between
        review and execution, it does not close it.
        """
        now = _now_iso()
        with transaction(self._db_path) as conn:
            row = plan_repo.get_plan(conn, plan_id)
            if row is None:
                raise TransferPlanNotFoundError(plan_id)
            if row.status == "invalidated":
                raise TransferPlanError(
                    f"plan {plan_id} was invalidated by a configuration change; "
                    "rebuild and review the new plan"
                )
            if row.status in {"executing", "executed"}:
                raise TransferPlanError(
                    f"plan {plan_id} is {row.status}; a plan is approved once, before it runs"
                )
            if row.fingerprint != fingerprint:
                raise TransferPlanError("plan fingerprint changed since review; rebuild and review")
            self._assert_approvable(conn, row)
            self._assert_preflighted(conn, row)
            plan_repo.set_plan_status(
                conn,
                plan_id,
                status="approved",
                approved_fingerprint=fingerprint,
                approved_at=now,
            )
            updated = plan_repo.get_plan(conn, plan_id)
        assert updated is not None
        return _to_status(updated)

    # ---- helpers -----------------------------------------------------

    def _assert_preflighted(self, conn: sqlite3.Connection, row: TransferPlanRow) -> None:
        """Require current, passing evidence that the world still matches.

        The failure this prevents: a plan built against a source and a
        destination, both of which then changed, approved anyway because
        every stored row still said what it said at planning time.
        """
        latest = preflight_repo.latest_for_plan(conn, row.id)
        if latest is None:
            raise TransferPlanError(
                "this plan has not been preflighted. Approval checks the actual source "
                "files and storage, not just the saved plan — run transfer.preflightStart "
                "and approve once it passes"
            )
        if latest.status == "running":
            raise TransferPlanError(
                f"preflight {latest.id} is still running "
                f"({latest.checked_entries}/{latest.total_entries} entries checked); "
                "wait for it to finish"
            )
        if latest.fingerprint != row.fingerprint:
            raise TransferPlanError(
                "the most recent preflight was for a different version of this plan; "
                "run it again against the current plan"
            )
        if latest.status != "passed":
            findings = _findings_of(latest)
            detail = "; ".join(findings) if findings else "see the preflight record"
            raise TransferPlanError(f"preflight failed: {detail}")
        if not preflight_is_current(latest, fingerprint=row.fingerprint):
            raise TransferPlanError(
                f"the last passing preflight is older than "
                f"{int(PREFLIGHT_TTL_SECONDS)}s; storage can change in that time, so run "
                "it again before approving"
            )

    def _assert_approvable(self, conn: sqlite3.Connection, row: TransferPlanRow) -> None:
        review = _preset_review_of(row)
        if review:
            # The revision carries content nobody has decided about —
            # a legacy template key Ferry does not understand, a legacy
            # conflict policy with no safe equivalent. Warning about it
            # and approving anyway is the silent-ignore §4.2 forbids
            # (R14). It is cleared by fixing the preset, never by this
            # service deciding on the user's behalf.
            items = "; ".join(review)
            raise TransferPlanError(
                f"the pinned preset revision (preset {row.preset_id} revision "
                f"{row.preset_revision}) still needs a decision about: {items}. "
                "Save a corrected revision that resolves it and pin that revision, then "
                "rebuild and review the plan"
            )
        if row.blocking_count:
            raise TransferPlanError(
                f"{row.blocking_count} entr{'y' if row.blocking_count == 1 else 'ies'} still "
                "need a decision (conflicts, scan errors, or unsupported objects); "
                "resolve or explicitly exclude them, then rebuild the plan"
            )
        if row.destination_id is not None:
            dest = dest_repo.get_destination(conn, row.destination_id)
            if dest is None:
                raise TransferPlanError("the saved destination no longer exists")
            if dest.archived_at is not None:
                raise TransferPlanError(
                    f"destination {dest.name!r} is archived; un-archive it or choose another"
                )
            if (dest.last_binding_path or "") != row.destination_binding_path:
                raise TransferPlanError(
                    "the destination binding changed since this plan was built; "
                    "rebuild and review the new plan"
                )
            if _identity_json(dest) != (row.destination_identity_json or "null"):
                raise TransferPlanError(
                    "the destination's identity evidence changed since this plan was built; "
                    "rebuild and review the new plan"
                )
            if dest.free_space_reserve != row.free_space_reserve:
                raise TransferPlanError(
                    "the destination's free-space reserve changed since this plan was built; "
                    "rebuild and review the new plan"
                )
        if row.preset_id is not None and row.preset_revision is not None:
            rev = revision_repo.get_revision(conn, row.preset_id, row.preset_revision)
            if rev is None:
                raise TransferPlanError(
                    f"preset {row.preset_id} revision {row.preset_revision} no longer exists"
                )
            if rev.content_hash != row.preset_content_hash:
                raise TransferPlanError(
                    "the pinned preset revision's content hash changed; rebuild and review"
                )
        for snap in _snapshots_of(row):
            current = inv_repo.get_inventory(conn, int(snap["inventoryId"]))
            if current is None:
                raise TransferPlanError(
                    f"inventory {snap['inventoryId']} no longer exists; rescan and replan"
                )
            if current.status != "complete":
                raise TransferPlanError(
                    f"inventory {current.id} is {current.status!r}; only a complete source "
                    "scan may be approved"
                )
            if current.manifest_hash != snap["manifestHash"]:
                raise TransferPlanError(
                    f"source {current.root_path} changed since it was reviewed "
                    "(manifest hash differs); rescan and replan"
                )
        if row.capacity_unknown:
            if not (row.capacity_override_reason or "").strip():
                raise TransferPlanError(
                    "free space at the destination could not be determined; approving "
                    "requires an explicit recorded override reason (spec §7.1)"
                )
        elif not row.capacity_ok:
            free = row.free_bytes if row.free_bytes is not None else 0
            raise TransferPlanError(
                f"destination has {free} bytes free but the plan needs {row.needed_bytes} "
                f"(including a {row.free_space_reserve}-byte reserve); free space or "
                "reduce the selection, then rebuild the plan"
            )

    def _load_destination(
        self, conn: sqlite3.Connection, destination_id: int
    ) -> SavedDestinationRow:
        row = dest_repo.get_destination(conn, destination_id)
        if row is None:
            raise TransferPlanError(f"destination {destination_id} not found")
        if row.archived_at is not None:
            raise TransferPlanError(
                f"destination {row.name!r} is archived; un-archive it or choose another"
            )
        return row

    @staticmethod
    def _resolve_binding(dest_row: SavedDestinationRow, binding_path: str | None) -> Path:
        """The one binding a plan may use: the destination's confirmed one.

        A caller-supplied path is accepted only when it *is* the saved
        binding. Anything else would let a plan be built against a
        location the destination has never been confirmed at — exactly
        the rebinding the §5.1 contract requires a user action for.
        """
        saved = dest_row.last_binding_path
        if not saved:
            raise TransferPlanError(
                f"destination {dest_row.name!r} has no confirmed binding; "
                "confirm it (destination.confirmBinding) before planning"
            )
        if binding_path is not None:
            given = str(Path(binding_path).expanduser())
            if given != saved:
                raise TransferPlanError(
                    f"binding path {given!r} is not the destination's confirmed binding "
                    f"({saved!r}); confirm the new location first "
                    "(destination.confirmBinding), which also invalidates stale approvals"
                )
        return Path(saved).expanduser()

    def _load_preset_revision(
        self,
        conn: sqlite3.Connection,
        preset_id: int | None,
        preset_revision: int | None,
        dest_row: SavedDestinationRow,
    ) -> PresetRevisionRow | None:
        """Resolve the preset revision this plan is built against.

        Never "whatever is latest". A destination is pinned to the
        revision the user saved it with, and saving a newer revision of
        the same preset must not silently re-route an existing
        destination's transfers (spec §4.2, R05). An explicit
        ``preset_revision`` is a per-transfer override; without one the
        pin decides.
        """
        pid = preset_id if preset_id is not None else dest_row.default_preset_id
        if pid is None:
            return None
        if preset_revision is not None:
            revision = preset_revision
        elif preset_id is None or preset_id == dest_row.default_preset_id:
            if dest_row.pinned_revision is None:
                raise TransferPlanError(
                    f"destination {dest_row.name!r} has preset {pid} but no pinned revision; "
                    "re-save the destination to pin one, or pass an explicit presetRevision"
                )
            revision = dest_row.pinned_revision
        else:
            raise TransferPlanError(
                f"preset {pid} is not this destination's default; pass an explicit "
                "presetRevision so the plan records which revision it used"
            )
        rev = revision_repo.get_revision(conn, pid, revision)
        if rev is None:
            raise TransferPlanError(f"preset {pid} has no revision {revision}")
        return rev

    def _load_inventories(
        self, conn: sqlite3.Connection, inventory_ids: list[int]
    ) -> list[InventoryRow]:
        out: list[InventoryRow] = []
        for inv_id in inventory_ids:
            row = inv_repo.get_inventory(conn, inv_id)
            if row is None:
                raise TransferPlanError(f"inventory {inv_id} not found")
            if row.status != "complete":
                detail = f": {row.error}" if row.error else ""
                raise TransferPlanError(
                    f"inventory {inv_id} is {row.status!r}; only complete inventories "
                    f"may plan{detail}"
                )
            out.append(row)
        return out


def _reject_overlapping_sources(inventories: list[InventoryRow], destination_root: Path) -> None:
    """Refuse selections that overlap each other or the destination.

    Spec §7.1: destination-inside-source, source-equals-destination and
    nested duplicate sources are rejected outright — one non-overlapping
    selection, chosen by the user, not silently de-duplicated here.
    """
    roots = [(inv, Path(inv.root_path).resolve()) for inv in inventories]
    dest = destination_root.resolve()
    for inv, root in roots:
        if root == dest:
            raise TransferPlanError(
                f"source {inv.root_path} is the destination itself; choose a different destination"
            )
        if _is_inside(dest, root):
            raise TransferPlanError(
                f"destination {destination_root} is inside source {inv.root_path}; "
                "choose a destination outside every selected source"
            )
        if _is_inside(root, dest):
            raise TransferPlanError(
                f"source {inv.root_path} is inside destination {destination_root}; "
                "choose sources outside the destination"
            )
    for i, (inv_a, root_a) in enumerate(roots):
        for inv_b, root_b in roots[i + 1 :]:
            if root_a == root_b:
                raise TransferPlanError(
                    f"sources {inv_a.id} and {inv_b.id} are the same folder "
                    f"({inv_a.root_path}); select it once"
                )
            if _is_inside(root_a, root_b) or _is_inside(root_b, root_a):
                raise TransferPlanError(
                    f"source {inv_a.root_path} and source {inv_b.root_path} are nested; "
                    "select one non-overlapping set of sources"
                )


def _is_inside(candidate: Path, ancestor: Path) -> bool:
    return candidate != ancestor and ancestor in candidate.parents


def _build_plan(
    *,
    plan_id: str,
    conn: sqlite3.Connection,
    inventories: list[InventoryRow],
    destination_root: Path,
    dest_row: SavedDestinationRow,
    preset_row: PresetRevisionRow | None,
    preset_content: PresetContent | None,
    project_id: str | None,
    capacity_override_reason: str | None,
    decisions: list[PlanDecision],
    derived_from: str | None,
) -> tuple[TransferPlanRow, list[TransferPlanEntryRow]]:
    """Map every inventory entry to a destination, keeping its provenance."""
    warnings: list[str] = []
    drafts: list[_Draft] = []
    decision_by_key = {(d.inventory_id, d.rel_path): d for d in decisions}
    legacy_prefix = revision_root_prefix(preset_row) if preset_row else None
    content = _effective_content(preset_content, legacy_prefix, warnings)
    review_items = _revision_review_items(preset_row)
    for item in review_items:
        warnings.append(f"preset revision needs review: {item}")

    root_len = len(str(destination_root).encode("utf-8")) + 1
    for inv in inventories:
        label = rule_engine.normalize_label(inv.label or Path(inv.root_path).name)
        for row in _iter_entries(conn, inv.id):
            drafts.append(
                _draft_for(
                    inv=inv,
                    source_label=label,
                    row=row,
                    content=content,
                    decision=decision_by_key.get((inv.id, row.rel_path)),
                    root_len=root_len,
                )
            )

    _cascade_directory_exclusions(drafts)
    warnings.extend(_allocate_destinations(drafts, destination_root, dest_row.conflict_policy))
    drafts = _drop_implied_directories(drafts)

    entries = [
        TransferPlanEntryRow(
            id=0,
            plan_id=plan_id,
            inventory_id=d.inventory_id,
            inventory_entry_id=d.inventory_entry_id,
            source_path=d.source_path,
            rel_path=d.rel_path,
            entry_type=d.entry_type,
            dest_rel_path=d.dest_rel_path,
            matched_rule=d.matched_rule,
            size=d.size,
            mtime=d.mtime,
            action=d.action,
            conflict=d.conflict,
            exclusion_reason=d.exclusion_reason,
            excluded_by_user=int(d.excluded_by_user),
            renamed_from=d.renamed_from,
            group_id=d.group_id,
        )
        for d in drafts
    ]
    for draft in drafts:
        warnings.extend(draft.warnings)

    copy_sizes = [d.size for d in drafts if d.action == "copy"]
    total_files = len(copy_sizes)
    total_bytes = sum(copy_sizes)
    blocking_count = sum(1 for d in drafts if d.action in BLOCKING_ACTIONS)
    conflict_count = sum(1 for d in drafts if d.conflict is not None)
    exclusion_count = sum(1 for d in drafts if d.action == "exclude")
    # Both origins are explicit, and neither is a silent drop — but a
    # rule the preset applies and a decision this reviewer made are not
    # the same fact, and §7.3 requires the receipt to be able to tell
    # them apart (R15).
    rule_exclusion_count = sum(
        1 for d in drafts if d.action == "exclude" and not d.excluded_by_user
    )
    user_exclusion_count = exclusion_count - rule_exclusion_count

    # Capacity accounts for the planned writes, the temporary sibling a
    # verified copy writes before publishing (bounded by the largest
    # single file), and the destination's configured reserve — a plan
    # that fits only by eating the reserve does not fit (spec §7.1).
    temp_overhead = max(copy_sizes) if copy_sizes else 0
    reserve = int(dest_row.free_space_reserve or 0)
    needed = total_bytes + temp_overhead + reserve
    free: int | None
    try:
        free = int(shutil.disk_usage(destination_root).free)
    except OSError as exc:
        free = None
        capacity_unknown = True
        capacity_ok = False
        warnings.append(f"free space at {destination_root} could not be determined: {exc}")
    else:
        capacity_unknown = False
        capacity_ok = free >= needed
        if not capacity_ok:
            warnings.append(
                f"destination {destination_root} has {free} bytes free but the plan needs "
                f"{needed} (data {total_bytes} + temporary {temp_overhead} + reserve {reserve})"
            )
    if capacity_unknown and not (capacity_override_reason or "").strip():
        warnings.append(
            "free space is unknown; approval requires an explicit recorded override reason"
        )
    if blocking_count:
        warnings.append(
            f"{blocking_count} entr{'y' if blocking_count == 1 else 'ies'} need a decision "
            "before this plan can be approved"
        )
    if user_exclusion_count:
        warnings.append(
            f"{user_exclusion_count} entr{'y' if user_exclusion_count == 1 else 'ies'} are "
            "excluded by an explicit decision and will not be transferred"
        )
    if rule_exclusion_count:
        warnings.append(
            f"{rule_exclusion_count} entr{'y' if rule_exclusion_count == 1 else 'ies'} are "
            "excluded by the preset's own exclusion rules and will not be transferred"
        )
    if review_items:
        warnings.append(
            "this preset revision carries unresolved review evidence, so the plan cannot "
            "be approved until a corrected revision is pinned"
        )

    snapshots = [
        _InventorySnapshot(
            inventory_id=inv.id,
            root_path=inv.root_path,
            label=inv.label,
            manifest_hash=inv.manifest_hash,
            file_count=inv.file_count,
            dir_count=inv.dir_count,
            error_count=inv.error_count,
            excluded_count=inv.excluded_count,
            total_bytes=inv.total_bytes,
            finished_at=inv.finished_at,
        )
        for inv in inventories
    ]
    snapshot_json = json.dumps(
        [s.as_dict() for s in snapshots], sort_keys=True, separators=(",", ":")
    )
    identity_json = _identity_json(dest_row)
    decisions_json = json.dumps(
        sorted(
            (d.model_dump(by_alias=True) for d in decisions),
            key=lambda d: (d["inventoryId"], d["relPath"]),
        ),
        sort_keys=True,
        separators=(",", ":"),
    )

    fingerprint = _plan_fingerprint(
        destination_id=dest_row.id,
        destination_binding_path=str(destination_root),
        destination_identity_json=identity_json,
        conflict_policy=dest_row.conflict_policy,
        checksum_algo=dest_row.checksum_algo,
        free_space_reserve=reserve,
        preset_row=preset_row,
        preset_review=review_items,
        inventory_snapshot_json=snapshot_json,
        decisions_json=decisions_json,
        drafts=drafts,
        project_id=project_id,
        capacity_unknown=capacity_unknown,
        capacity_override_reason=capacity_override_reason,
        needed_bytes=needed,
    )
    now = _now_iso()
    plan = TransferPlanRow(
        id=plan_id,
        destination_id=dest_row.id,
        destination_binding_path=str(destination_root),
        preset_id=preset_row.preset_id if preset_row else None,
        preset_revision=preset_row.revision if preset_row else None,
        preset_content_hash=preset_row.content_hash if preset_row else None,
        project_id=project_id,
        inventory_snapshot_json=snapshot_json,
        destination_identity_json=identity_json,
        conflict_policy=dest_row.conflict_policy,
        checksum_algo=dest_row.checksum_algo,
        free_space_reserve=reserve,
        free_bytes=free,
        blocking_count=blocking_count,
        decisions_json=decisions_json,
        preset_review_json=json.dumps(review_items, separators=(",", ":")),
        rule_exclusion_count=rule_exclusion_count,
        derived_from=derived_from,
        superseded_by=None,
        category_map_version=rule_engine.CATEGORY_MAP_VERSION,
        fingerprint=fingerprint,
        status="draft",
        approved_fingerprint=None,
        capacity_ok=int(capacity_ok),
        capacity_unknown=int(capacity_unknown),
        capacity_override_reason=capacity_override_reason,
        needed_bytes=needed,
        total_bytes=total_bytes,
        total_files=total_files,
        conflict_count=conflict_count,
        exclusion_count=exclusion_count,
        warnings_json=json.dumps(warnings),
        created_at=now,
        approved_at=None,
    )
    return plan, entries


def _iter_entries(conn: sqlite3.Connection, inventory_id: int) -> Iterator[InventoryEntryRow]:
    """Page the whole inventory; a page size never bounds a plan (A01)."""
    after_id = 0
    while True:
        batch = inv_repo.page_entries(conn, inventory_id, limit=_PAGE, after_id=after_id)
        if not batch:
            return
        yield from batch
        after_id = batch[-1].id


def _effective_content(
    content: PresetContent | None, legacy_prefix: str | None, warnings: list[str]
) -> PresetContent:
    """The rules to route by, including the no-preset default.

    A destination with no preset still needs a defined behavior, and the
    honest default is the one the spec names: preserve the source
    structure beneath a per-source folder (§6.2). A legacy root-only
    profile keeps its literal prefix, which is what it always meant.
    """
    if content is not None and (content.rules or content.groups):
        return content
    if legacy_prefix:
        template = f"{legacy_prefix}/{{relative_dir}}/{{filename}}"
        warnings.append(
            f"this preset is a converted legacy root-only profile; every file is placed "
            f"under {legacy_prefix!r} preserving its source structure"
        )
    elif content is not None:
        template = content.fallback_template
    else:
        template = "Sources/{source_label}/{relative_dir}/{filename}"
        warnings.append(
            "no organization preset is selected; files preserve their source structure "
            "under a folder named for each source"
        )
    # Everything the revision *did* say still applies. Rebuilding the
    # content from the template alone silently dropped the preset's
    # exclusion rules, so a preset with no routing rules but a ".tmp"
    # exclusion copied the .tmp files anyway (R15).
    return PresetContent(
        fallbackTemplate=template,
        conflictPolicy=content.conflict_policy if content else "keep_both",
        exclusions=list(content.exclusions) if content else [],
        reviewRequired=list(content.review_required) if content else [],
    )


def _draft_for(
    *,
    inv: InventoryRow,
    source_label: str,
    row: InventoryEntryRow,
    content: PresetContent,
    decision: PlanDecision | None,
    root_len: int,
) -> _Draft:
    """One inventory entry's plan row — findings included, never dropped."""
    rel = row.rel_path
    source_path = str(Path(inv.root_path) / rel)
    base = _Draft(
        inventory_id=inv.id,
        inventory_entry_id=row.id,
        source_path=source_path,
        rel_path=rel,
        entry_type=row.entry_type,
        dest_rel_path=rel,
        matched_rule=None,
        size=row.size,
        mtime=row.mtime,
        action="copy",
        conflict=None,
    )
    if decision is not None and decision.action == "exclude":
        # A decision somebody made. It is recorded as such, counted
        # separately from successful copies, and never as a silent drop
        # (spec §6.3, §7.3).
        base.action = "exclude"
        base.excluded_by_user = True
        base.exclusion_reason = decision.reason or "excluded by the reviewer"
        return base
    if row.scan_status == "error":
        base.action = "needs_review"
        base.conflict = "source_scan_error"
        base.exclusion_reason = row.error or "the source entry could not be read"
        return base
    if row.entry_type not in _ROUTABLE_TYPES:
        base.action = "needs_review"
        base.conflict = f"unsupported_source_object:{row.entry_type}"
        base.exclusion_reason = (
            f"{row.entry_type} objects are inventoried and flagged, never dereferenced or "
            "recreated; exclude it explicitly or select a supported source subtree"
        )
        return base

    facts = rule_engine.FileFacts(
        rel_path=rel,
        source_label=source_label,
        size=row.size,
        mtime=row.mtime,
        entry_type=row.entry_type,
    )
    excluded = rule_engine.find_exclusion(content, facts)
    if excluded is not None:
        # A rule the user wrote into the preset. It is applied, recorded
        # with the rule that caused it, counted apart from the reviewer's
        # own decisions, and never silently dropped — an accepted field
        # that quietly did nothing was the defect this replaces (R15).
        base.action = "exclude"
        base.matched_rule = f"exclusion:{excluded.id}"
        base.exclusion_reason = (
            f"excluded by the preset's {excluded.id!r} exclusion rule: {excluded.reason}"
        )
        if row.entry_type == "dir":
            base.size = 0
        return base

    try:
        routing = rule_engine.route(content, facts, dest_root_len=root_len)
    except rule_engine.RuleError as exc:
        base.action = "needs_review"
        base.conflict = "unroutable"
        base.exclusion_reason = (
            f"{exc}. Rename the source path, adjust the preset, or exclude this entry "
            "from the plan with transfer.planResolve"
        )
        return base
    base.dest_rel_path = routing.dest_rel
    base.matched_rule = routing.matched_rule
    base.warnings.extend(routing.warnings)
    base.group_id = routing.group_id
    base.group_root = routing.group_root
    base.group_dest_root = routing.group_dest_root
    if row.entry_type == "dir":
        base.action = "dir"
        base.size = 0
    return base


def _cascade_directory_exclusions(drafts: list[_Draft]) -> None:
    """Exclude everything beneath a directory a preset exclusion claimed.

    A rule that excluded a folder but copied its contents would leave the
    files landing under a parent the plan said it would not create —
    incoherent, and the kind of half-applied rule that makes a review
    screen untrustworthy. The descendants inherit the rule that caused
    it, so the receipt names one reason rather than an unexplained gap.
    """
    roots = [
        d
        for d in drafts
        if d.action == "exclude" and not d.excluded_by_user and d.entry_type == "dir"
    ]
    if not roots:
        return
    by_inventory: dict[int, list[_Draft]] = {}
    for root in roots:
        by_inventory.setdefault(root.inventory_id, []).append(root)
    for draft in drafts:
        if draft.action in ("exclude", "needs_review"):
            continue
        for root in by_inventory.get(draft.inventory_id, ()):
            if draft.rel_path.startswith(f"{root.rel_path}/"):
                draft.action = "exclude"
                draft.matched_rule = root.matched_rule
                draft.exclusion_reason = (
                    f"{root.exclusion_reason} (inherited from the excluded directory "
                    f"{root.rel_path!r})"
                )
                if draft.entry_type == "dir":
                    draft.size = 0
                break


def _allocate_destinations(drafts: list[_Draft], destination_root: Path, policy: str) -> list[str]:
    """Resolve every destination collision, keeping both wherever safe.

    Order matters and is deliberate. Keep-together groups are placed
    first and as whole subtrees, because a group's collision is resolved
    at its root and that root has to be reserved before anything else can
    claim a name inside it. Then loose directories, so a file colliding
    with a directory this transfer creates is seen as such; then loose
    files in a stable order, so keep-both suffixes are assigned
    deterministically and the same plan produces the same names every
    time.

    Returns the plan-level warnings the group decisions produced.
    """
    reservations = conflict_rules.Reservations(dest_root=destination_root)
    routable = [d for d in drafts if d.action in ("copy", "dir")]
    groups: dict[tuple[int, str, str], list[_Draft]] = {}
    loose: list[_Draft] = []
    for draft in routable:
        if draft.group_id is not None and draft.group_dest_root is not None:
            key = (draft.inventory_id, draft.group_id, draft.group_root or "")
            groups.setdefault(key, []).append(draft)
        else:
            loose.append(draft)

    warnings: list[str] = []
    for key in sorted(groups, key=lambda k: (groups[k][0].group_dest_root or "", k)):
        warnings.extend(_allocate_group(groups[key], reservations, policy=policy))

    for draft in sorted(loose, key=lambda d: (d.entry_type != "dir", d.dest_rel_path)):
        try:
            allocation = conflict_rules.allocate(
                draft.dest_rel_path,
                reservations,
                policy=policy,
                entry_type=draft.entry_type,
            )
        except OSError as exc:  # pragma: no cover - defensive
            draft.action = "needs_review"
            draft.conflict = conflict_rules.EXISTING_UNREADABLE
            draft.exclusion_reason = str(exc)
            continue
        if allocation.conflict is None:
            draft.dest_rel_path = allocation.dest_rel
            continue
        draft.conflict = allocation.conflict
        draft.exclusion_reason = allocation.detail
        if allocation.renamed_from is not None:
            # Kept both: this is a resolved conflict, still reported so
            # review shows the rename rather than discovering it later.
            draft.dest_rel_path = allocation.dest_rel
            draft.renamed_from = allocation.renamed_from
        else:
            draft.action = "needs_review"
    return warnings


def _allocate_group(
    members: list[_Draft], reservations: conflict_rules.Reservations, *, policy: str
) -> list[str]:
    """Place one keep-together group as a unit (spec §6.3, examples E16).

    Either the entire group lands — at its configured root, or at a
    suffixed root with every internal path unchanged — or the entire
    group blocks. What never happens is a member being renamed on its
    own: the internal names are what the group was marked to protect, so
    resolving a collision by rewriting one of them defeats the purpose
    and does it invisibly.
    """
    dest_root_rel = members[0].group_dest_root or ""
    group_id = members[0].group_id
    source_root = members[0].group_root or ""
    try:
        allocation = conflict_rules.allocate_group_root(dest_root_rel, reservations, policy=policy)
    except OSError as exc:  # pragma: no cover - defensive
        allocation = conflict_rules.GroupAllocation(
            dest_root=dest_root_rel,
            conflict=conflict_rules.EXISTING_UNREADABLE,
            detail=str(exc),
        )

    if allocation.conflict is not None and allocation.renamed_from is None:
        detail = (
            f"the preserved group {group_id!r} ({source_root}) cannot be placed: "
            f"{allocation.detail}. Resolve it at the group root or exclude the group; "
            "no member of a preserved group is renamed individually"
        )
        for member in members:
            member.action = "needs_review"
            member.conflict = allocation.conflict
            member.exclusion_reason = detail
            member.keep_dir = member.entry_type == "dir"
        return [f"{len(members)} entr{'y' if len(members) == 1 else 'ies'}: {detail}"]

    relocated = allocation.renamed_from is not None
    for member in members:
        if relocated:
            member.dest_rel_path = _rebase(
                member.dest_rel_path, dest_root_rel, allocation.dest_root
            )
        if member.entry_type == "dir":
            reservations.claim_directory(member.dest_rel_path)
        else:
            reservations.claim(member.dest_rel_path)

    if not relocated:
        return []

    # The move is a reviewed fact, so it needs somewhere to live. The
    # group's own root directory entry carries it, and is kept even
    # though a directory with routed children is otherwise implied by
    # them (spec §6.2) — dropping it would leave the decision recorded
    # nowhere.
    root_entry = next((m for m in members if m.rel_path == source_root), None)
    if root_entry is None:  # pragma: no cover - the root is always inventoried
        root_entry = members[0]
    root_entry.keep_dir = True
    root_entry.conflict = allocation.conflict
    root_entry.exclusion_reason = allocation.detail
    root_entry.renamed_from = allocation.renamed_from
    return [
        f"preserved group {group_id!r} ({source_root}): {allocation.detail} "
        f"({len(members)} entries moved with it)"
    ]


def _rebase(dest_rel: str, old_root: str, new_root: str) -> str:
    """Move one path from under ``old_root`` to under ``new_root``."""
    if dest_rel == old_root:
        return new_root
    prefix = f"{old_root}/"
    if dest_rel.startswith(prefix):
        return f"{new_root}/{dest_rel[len(prefix) :]}"
    return dest_rel  # pragma: no cover - members are always under the root


def _drop_implied_directories(drafts: list[_Draft]) -> list[_Draft]:
    """Keep only directories that are not already created by their contents.

    A source directory holding files that this plan copies does not need
    an entry of its own: writing the files creates it. Emitting one
    anyway is what produced an empty ``Unsorted/card/Photos`` beside the
    ``Images/card/Photos/...`` its contents actually routed to — a
    fallback folder for every source parent, which the agreed examples
    rule out (R18).

    A genuinely empty source directory is different: nothing else will
    create it, and §6.3 says empty directories are preserved unless
    explicitly excluded. So it keeps its entry.

    A directory is *implied* only by a descendant that this plan will
    actually write — a copy, or a retained empty directory. A folder
    whose every child was excluded or blocked is not implied by them, and
    keeps its entry.
    """
    implied: set[tuple[int, str]] = set()

    def mark(inventory_id: int, rel_path: str) -> None:
        parts = PurePosixPath(rel_path).parts
        for depth in range(1, len(parts)):
            implied.add((inventory_id, "/".join(parts[:depth])))

    for draft in drafts:
        if draft.action == "copy":
            mark(draft.inventory_id, draft.rel_path)

    candidates = [
        d for d in drafts if d.entry_type == "dir" and d.action == "dir" and not d.keep_dir
    ]
    # Deepest first, so a retained empty directory implies its own
    # parents before those parents are judged.
    dropped: set[int] = set()
    for draft in sorted(candidates, key=lambda d: -len(PurePosixPath(d.rel_path).parts)):
        if (draft.inventory_id, draft.rel_path) in implied:
            dropped.add(id(draft))
        else:
            mark(draft.inventory_id, draft.rel_path)
    return [d for d in drafts if id(d) not in dropped]


def _preset_review_of(row: TransferPlanRow) -> list[str]:
    """The preset review evidence recorded on this plan (R14)."""
    try:
        value = json.loads(row.preset_review_json or "[]")
    except (TypeError, ValueError):
        return ["the plan's recorded preset review evidence is unreadable"]
    return [str(v) for v in value] if isinstance(value, list) else []


def _revision_review_items(row: PresetRevisionRow | None) -> list[str]:
    """Blocking review evidence carried on a preset revision (R07)."""
    if row is None or not row.review_json:
        return []
    try:
        value = json.loads(row.review_json)
    except (TypeError, ValueError):
        return ["the revision's review evidence is unreadable"]
    return [str(v) for v in value] if isinstance(value, list) else []


def _identity_json(dest_row: SavedDestinationRow) -> str:
    if not dest_row.identity_kind:
        return "null"
    return json.dumps(
        {
            "kind": dest_row.identity_kind,
            "value": dest_row.identity_value,
            "confidence": dest_row.identity_confidence,
            "provenance": dest_row.identity_provenance,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _findings_of(row: preflight_repo.PreflightRow) -> list[str]:
    try:
        value = json.loads(row.findings_json or "[]")
    except (TypeError, ValueError):
        return []
    return [str(v) for v in value] if isinstance(value, list) else []


def _decisions_of(row: TransferPlanRow) -> list[PlanDecision]:
    """The decisions already carried by a plan."""
    try:
        value = json.loads(row.decisions_json or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(value, list):
        return []
    out: list[PlanDecision] = []
    for item in value:
        try:
            out.append(PlanDecision.model_validate(item))
        except Exception:  # pragma: no cover - a malformed row is not fatal
            continue
    return out


def _merge_decisions(*groups: list[PlanDecision]) -> list[PlanDecision]:
    """Combine decision sets, later ones winning on the same key.

    Accumulating rather than replacing is the point: working through a
    plan with several findings should not mean re-deciding the earlier
    ones each round.
    """
    merged: dict[tuple[int, str], PlanDecision] = {}
    for group in groups:
        for decision in group:
            merged[(decision.inventory_id, decision.rel_path)] = decision
    return [merged[key] for key in sorted(merged)]


def _content_of(row: PresetRevisionRow | None) -> PresetContent | None:
    """Decode a revision's content for the rule engine."""
    if row is None:
        return None
    from file_ferry.application.presets import PresetRevisionService

    try:
        return PresetRevisionService._content_of(row)
    except Exception:  # pragma: no cover - surfaced as a plan warning instead
        return None


def _snapshots_of(row: TransferPlanRow) -> list[dict[str, Any]]:
    try:
        value = json.loads(row.inventory_snapshot_json or "[]")
    except (TypeError, ValueError):
        return []
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def _to_status(row: TransferPlanRow) -> TransferPlanStatusModel:
    return TransferPlanStatusModel(
        id=row.id,
        destinationId=row.destination_id,
        destinationBindingPath=row.destination_binding_path,
        presetId=row.preset_id,
        presetRevision=row.preset_revision,
        presetContentHash=row.preset_content_hash,
        projectId=row.project_id,
        fingerprint=row.fingerprint,
        status=row.status,  # type: ignore[arg-type]
        approvedFingerprint=row.approved_fingerprint,
        capacityOk=bool(row.capacity_ok),
        capacityUnknown=bool(row.capacity_unknown),
        capacityOverrideReason=row.capacity_override_reason,
        neededBytes=row.needed_bytes,
        totalBytes=row.total_bytes,
        totalFiles=row.total_files,
        conflictCount=row.conflict_count,
        exclusionCount=row.exclusion_count,
        ruleExclusionCount=row.rule_exclusion_count,
        blockingCount=row.blocking_count,
        presetReviewRequired=_preset_review_of(row),
        freeBytes=row.free_bytes,
        freeSpaceReserve=row.free_space_reserve,
        conflictPolicy=row.conflict_policy,
        checksumAlgo=row.checksum_algo,
        inventoryIds=[int(s["inventoryId"]) for s in _snapshots_of(row)],
        derivedFrom=row.derived_from,
        supersededBy=row.superseded_by,
        decisions=_decisions_of(row),
        categoryMapVersion=row.category_map_version,
        warnings=json.loads(row.warnings_json) if row.warnings_json else [],
        createdAt=row.created_at,
        approvedAt=row.approved_at,
    )


def _to_entry(row: TransferPlanEntryRow) -> TransferPlanEntryModel:
    return TransferPlanEntryModel(
        id=row.id,
        inventoryId=row.inventory_id,
        inventoryEntryId=row.inventory_entry_id,
        sourcePath=row.source_path,
        relPath=row.rel_path,
        entryType=row.entry_type,
        destRelPath=row.dest_rel_path,
        matchedRule=row.matched_rule,
        size=row.size,
        mtime=row.mtime,
        action=row.action,  # type: ignore[arg-type]
        conflict=row.conflict,
        exclusionReason=row.exclusion_reason,
        excludedByUser=bool(row.excluded_by_user),
        renamedFrom=row.renamed_from,
        groupId=row.group_id,
    )


def _plan_fingerprint(
    *,
    destination_id: int,
    destination_binding_path: str,
    destination_identity_json: str,
    conflict_policy: str,
    checksum_algo: str,
    free_space_reserve: int,
    preset_row: PresetRevisionRow | None,
    preset_review: list[str],
    inventory_snapshot_json: str,
    decisions_json: str,
    drafts: list[_Draft],
    project_id: str | None,
    capacity_unknown: bool,
    capacity_override_reason: str | None,
    needed_bytes: int,
) -> str:
    """Deterministic hash over the complete approved substance.

    Spec §7.1: *editing any input clears approval*, so the hash has to
    cover every input, not just the mapping. A fingerprint that omitted
    the source manifest, the file sizes and mtimes, the destination
    identity, the policy, or the reserve would keep matching while the
    thing it authorizes changed underneath it — which is the same as
    having no approval gate at all.
    """
    payload = {
        "destinationId": destination_id,
        "destinationBindingPath": destination_binding_path,
        "destinationIdentity": destination_identity_json,
        "conflictPolicy": conflict_policy,
        "checksumAlgo": checksum_algo,
        "freeSpaceReserve": free_space_reserve,
        "presetId": preset_row.preset_id if preset_row else None,
        "presetRevision": preset_row.revision if preset_row else None,
        "presetContentHash": preset_row.content_hash if preset_row else None,
        "presetReviewRequired": sorted(preset_review),
        "inventorySnapshot": inventory_snapshot_json,
        "decisions": decisions_json,
        "projectId": project_id,
        "capacityUnknown": capacity_unknown,
        "capacityOverrideReason": capacity_override_reason,
        "neededBytes": needed_bytes,
        "entries": [
            [
                d.inventory_id,
                d.rel_path,
                d.entry_type,
                d.size,
                None if d.mtime is None else round(d.mtime, 3),
                d.dest_rel_path,
                d.action,
                d.conflict,
                d.exclusion_reason,
                d.excluded_by_user,
                d.renamed_from,
                d.matched_rule,
                d.group_id,
            ]
            for d in drafts
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "BLOCKING_ACTIONS",
    "TransferPlanError",
    "TransferPlanNotFoundError",
    "TransferPlanService",
]
