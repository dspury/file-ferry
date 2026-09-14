"""Saved destinations and rebinding resolver (destination-presets spec §4.1, §5).

A saved destination is a durable record: a name the user recognizes,
the kind of storage it lives on, the location to write to, an identity
evidence string the resolver can match against future observations,
and a pinned preset revision the user chose.

Editing, rebinding, or archiving a destination invalidates its
unexecuted plans, in the same transaction as the change itself — an
approval that briefly outlived the configuration it was granted
against would authorize a transfer to a location nobody re-reviewed.
Historical plan snapshots (executing/executed) are never touched.

The pin matters for the same reason: a destination stays on the preset
revision it was saved with, so saving a newer revision of that preset
cannot silently re-route transfers that an existing destination has
already been set up for.

The resolver compares saved destinations against observed mounts/shares
that callers supply. It never reads the filesystem itself for evidence:
identity is a value passed in, never inferred from a path. This keeps
the resolver testable against fake observations and lets P3 plug in a
real platform adapter without changing the resolver rules.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from file_ferry.application.volume_identity import share_host, share_name
from file_ferry.persistence.connection import transaction
from file_ferry.persistence.repositories import destinations as dest_repo
from file_ferry.persistence.repositories import preset_revisions as revision_repo
from file_ferry.persistence.repositories import transfer_plans as plan_repo
from file_ferry.persistence.repositories.destinations import SavedDestinationRow
from file_ferry.service.protocol import (
    DestinationIdentity,
    DestinationResolution,
    DestinationSummary,
    ListDestinationsResult,
    MountedVolume,
    ResolveDestinationsResult,
    SaveDestinationParams,
)

CONFLICT_POLICIES = frozenset({"keep_both", "skip_identical", "needs_review"})
LOCATION_KINDS = frozenset({"local_folder", "volume_folder", "mounted_share_folder"})
CHECKSUM_ALGOS = frozenset({"xxhash64", "sha256"})


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class DestinationError(ValueError):
    """Raised when destination parameters are invalid."""


class DestinationNotFoundError(KeyError):
    """Raised when a named destination does not exist."""


class DestinationService:
    """Save, list, archive, and resolve saved destinations."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)

    # ---- save / list / archive --------------------------------------

    def save(self, params: SaveDestinationParams) -> DestinationSummary:
        """Create or update a saved destination.

        The first save creates the row; subsequent saves update the
        mutable fields (binding, defaults, pin). Two things happen in
        the *same* transaction as the edit:

        - the preset revision is resolved and **pinned** (spec §4.2). A
          destination saved against revision 1 keeps routing through
          revision 1 when someone later saves revision 2; only an
          explicit ``pinnedRevision`` moves it.
        - unexecuted plans for this destination are invalidated (spec
          §4.1). Doing it in the same transaction is the point — an edit
          and its invalidation can never be observed apart, so no window
          exists in which a stale approval still authorizes a transfer
          to the old location.
        """
        self._validate(params)
        location_kind = params.location_kind or self._infer_location_kind(params.path)
        now = _now_iso()
        resolved_path = str(Path(params.path).expanduser())
        with transaction(self._db_path) as conn:
            existing = dest_repo.get_destination_by_name(conn, params.name)
            pinned = self._resolve_pin(conn, params, existing)
            if existing is None:
                row_id = dest_repo.insert_destination(
                    conn,
                    SavedDestinationRow(
                        id=0,
                        name=params.name,
                        location_kind=location_kind,
                        last_root_path=resolved_path,
                        subfolder_path=params.subfolder_path,
                        identity_kind=None,
                        identity_value=None,
                        identity_confidence=None,
                        identity_provenance=None,
                        default_preset_id=params.default_preset_id,
                        pinned_revision=pinned,
                        conflict_policy=params.conflict_policy,
                        checksum_algo=params.checksum_algo,
                        free_space_reserve=params.free_space_reserve,
                        last_binding_path=resolved_path,
                        last_seen_at=None,
                        created_at=now,
                        updated_at=now,
                        archived_at=None,
                    ),
                )
            else:
                dest_repo.update_destination(
                    conn,
                    existing.id,
                    last_root_path=resolved_path,
                    subfolder_path=params.subfolder_path,
                    default_preset_id=params.default_preset_id,
                    pinned_revision=pinned,
                    clear_default_preset_id=params.default_preset_id is None,
                    conflict_policy=params.conflict_policy,
                    checksum_algo=params.checksum_algo,
                    free_space_reserve=params.free_space_reserve,
                    last_binding_path=resolved_path,
                    updated_at=now,
                    clear_pinned_revision=pinned is None,
                )
                row_id = existing.id
                plan_repo.invalidate_plans_for_destination(conn, existing.id)
        return self._get(row_id)

    @staticmethod
    def _resolve_pin(
        conn: sqlite3.Connection,
        params: SaveDestinationParams,
        existing: SavedDestinationRow | None,
    ) -> int | None:
        """The revision this destination will be pinned to.

        An explicit ``pinnedRevision`` is validated against the named
        preset and wins. Otherwise a destination that already has a pin
        for the same preset keeps it — saving the destination is not how
        a user opts into a newer preset revision. A destination newly
        given a preset pins that preset's current revision, so the pin
        is always a concrete revision and never "latest at read time".
        """
        preset_id = params.default_preset_id
        if preset_id is None:
            if params.pinned_revision is not None:
                raise DestinationError(
                    "pinnedRevision was given without a defaultPresetId; "
                    "a pin names a revision of a specific preset"
                )
            return None
        if params.pinned_revision is not None:
            if revision_repo.get_revision(conn, preset_id, params.pinned_revision) is None:
                raise DestinationError(
                    f"preset {preset_id} has no revision {params.pinned_revision}"
                )
            return params.pinned_revision
        if (
            existing is not None
            and existing.default_preset_id == preset_id
            and existing.pinned_revision is not None
        ):
            return existing.pinned_revision
        latest = revision_repo.latest_revision(conn, preset_id)
        if latest is None:
            raise DestinationError(
                f"preset {preset_id} has no revisions yet; save the preset before "
                "pinning a destination to it"
            )
        return latest.revision

    def list_destinations(self, *, include_archived: bool = False) -> ListDestinationsResult:
        with transaction(self._db_path) as conn:
            rows = dest_repo.list_destinations(conn, include_archived=include_archived)
        return ListDestinationsResult(destinations=[_to_summary(r) for r in rows])

    def archive(self, destination_id: int) -> DestinationSummary:
        """Archive a destination and invalidate its unexecuted plans.

        Both in one transaction (spec §4.1): an archived destination
        whose approved plan briefly survived would be a transfer nobody
        could see coming.
        """
        now = _now_iso()
        with transaction(self._db_path) as conn:
            row = dest_repo.get_destination(conn, destination_id)
            if row is None:
                raise DestinationNotFoundError(destination_id)
            dest_repo.update_destination(conn, row.id, archived_at=now, updated_at=now)
            plan_repo.invalidate_plans_for_destination(conn, destination_id)
            updated = dest_repo.get_destination(conn, destination_id)
            assert updated is not None
        return _to_summary(updated)

    def get(self, destination_id: int) -> DestinationSummary:
        return self._get(destination_id)

    # ---- resolution --------------------------------------------------

    def resolve(
        self,
        *,
        destination_id: int | None = None,
        observations: list[DestinationObservation] | None = None,
    ) -> ResolveDestinationsResult:
        """Match saved destinations against live storage observations.

        ``observations`` is the list of volumes/shares the caller has
        seen (P3 supplies these via the platform adapter; tests pass
        fakes). When omitted, the resolver falls back to a path-only
        check so an environment with no observation adapter can still
        say "available / offline / unwritable" — but anything requiring
        identity returns ``needs_confirmation``.
        """

        with transaction(self._db_path) as conn:
            if destination_id is None:
                rows = dest_repo.list_destinations(conn, include_archived=False)
            else:
                row = dest_repo.get_destination(conn, destination_id)
                if row is None:
                    raise DestinationNotFoundError(destination_id)
                rows = [row]
            # Re-read the plans in the same tx so an invalidation that
            # happens during resolve doesn't leave us with stale data.
            plan_statuses = {d.id: _last_plan_status(conn, d.id) for d in rows}
        resolvers = list(rows)
        resolutions: list[DestinationResolution] = []
        for row in resolvers:
            resolution = _resolve_one(row, observations or [])
            # If a binding change invalidated unexecuted plans, say so.
            status = plan_statuses.get(row.id)
            if status in {"invalidated"} and resolution.status == "available":
                resolution = resolution.model_copy(
                    update={
                        "reason": (f"{resolution.reason}; previously approved plan(s) invalidated")
                    }
                )
            resolutions.append(resolution)
        return ResolveDestinationsResult(resolutions=resolutions)

    def confirm_binding(
        self,
        destination_id: int,
        *,
        path: str,
        identity: DestinationIdentity | None = None,
        observations: list[DestinationObservation] | None = None,
    ) -> DestinationSummary:
        """Record a user-confirmed binding (spec §5.1).

        This is the one operation that rebinds, and the escape hatch for
        storage the platform cannot identify — so it records what the
        operator chose rather than second-guessing it. What it will not
        do is record a binding that contradicts itself: if observations
        are available and the chosen path sits on a volume presenting a
        *different* identity than the one being recorded, the two would
        disagree the moment anything read them back, and the resolver
        would then reason from evidence that was never true (R11).

        The mount, subfolder, and binding path are derived together from
        the confirmed path so they stay consistent. Unexecuted plans are
        invalidated in the same transaction, so an approval can never
        outlive the binding it was granted against.
        """
        resolved_input = Path(path).expanduser()
        observed = observations or []
        owner = _owning_mount(resolved_input, observed)
        self._reject_contradictory_binding(resolved_input, identity, owner)
        recorded = _confirmed_identity(identity, owner)

        now = _now_iso()
        with transaction(self._db_path) as conn:
            row = dest_repo.get_destination(conn, destination_id)
            if row is None:
                raise DestinationNotFoundError(destination_id)
            # A local folder is bound by its path and has no meaningful
            # "subfolder within a mount"; deriving one would record the
            # whole path relative to the boot volume, which says nothing.
            subfolder = (
                _subfolder_within(resolved_input, owner)
                if row.location_kind != "local_folder"
                else row.subfolder_path
            )
            dest_repo.update_destination(
                conn,
                destination_id,
                last_binding_path=str(resolved_input),
                last_root_path=str(resolved_input),
                subfolder_path=subfolder,
                last_seen_at=now,
                updated_at=now,
                identity_kind=recorded.kind if recorded else None,
                identity_value=recorded.value if recorded else None,
                identity_confidence=recorded.confidence if recorded else None,
                identity_provenance=recorded.provenance if recorded else None,
            )
            # Same transaction as the rebinding (spec §5.1): a plan
            # approved against the old binding must never outlive it.
            plan_repo.invalidate_plans_for_destination(conn, destination_id)
        return self._get(destination_id)

    @staticmethod
    def _reject_contradictory_binding(
        path: Path,
        identity: DestinationIdentity | None,
        owner: DestinationObservation | None,
    ) -> None:
        """Refuse an identity that the chosen path demonstrably is not on."""
        if identity is None or owner is None or owner.identity is None:
            return
        if owner.identity.stale:
            # We cannot contradict it with evidence we did not just read.
            return
        if owner.identity.kind == identity.kind and owner.identity.value == identity.value:
            return
        raise DestinationError(
            f"{path} is on storage reporting {owner.identity.kind} "
            f"{owner.identity.value!r}, but the binding was submitted with "
            f"{identity.kind} {identity.value!r}. Confirming would record a binding whose "
            "path and identity disagree; re-read discovery and confirm the storage you "
            "actually mean"
        )

    # ---- helpers -----------------------------------------------------

    def _get(self, destination_id: int) -> DestinationSummary:
        with transaction(self._db_path) as conn:
            row = dest_repo.get_destination(conn, destination_id)
        if row is None:
            raise DestinationNotFoundError(destination_id)
        return _to_summary(row)

    @staticmethod
    def _infer_location_kind(path: str) -> str:
        # Default to local_folder; the resolver (and a future UI surface)
        # upgrades this when identity evidence is recorded. Choosing a
        # kind based on a path alone is unsafe; the user confirms via
        # ``confirmBinding``.
        return "local_folder"

    def _validate(self, params: SaveDestinationParams) -> None:
        if not params.name.strip():
            raise DestinationError("name is required")
        if not params.path.strip():
            raise DestinationError("path is required")
        if params.conflict_policy not in CONFLICT_POLICIES:
            raise DestinationError(f"conflictPolicy must be one of {sorted(CONFLICT_POLICIES)}")
        if params.checksum_algo not in CHECKSUM_ALGOS:
            raise DestinationError(f"checksumAlgo must be one of {sorted(CHECKSUM_ALGOS)}")
        if params.location_kind is not None and params.location_kind not in LOCATION_KINDS:
            raise DestinationError(f"locationKind must be one of {sorted(LOCATION_KINDS)}")
        if params.subfolder_path is not None and (
            params.subfolder_path.startswith("/") or ".." in Path(params.subfolder_path).parts
        ):
            raise DestinationError("subfolderPath must be a safe relative path")


def _to_summary(row: SavedDestinationRow) -> DestinationSummary:
    identity: DestinationIdentity | None = None
    if row.identity_kind and row.identity_value and row.identity_confidence:
        identity = DestinationIdentity(
            kind=row.identity_kind,  # type: ignore[arg-type]
            value=row.identity_value,
            confidence=row.identity_confidence,  # type: ignore[arg-type]
            provenance=row.identity_provenance or "",
        )
    return DestinationSummary(
        id=row.id,
        name=row.name,
        locationKind=row.location_kind,
        lastRootPath=row.last_root_path,
        subfolderPath=row.subfolder_path,
        identity=identity,
        defaultPresetId=row.default_preset_id,
        pinnedRevision=row.pinned_revision,
        conflictPolicy=row.conflict_policy,
        checksumAlgo=row.checksum_algo,
        freeSpaceReserve=row.free_space_reserve,
        lastBindingPath=row.last_binding_path,
        lastSeenAt=row.last_seen_at,
        createdAt=row.created_at,
        updatedAt=row.updated_at,
        archivedAt=row.archived_at,
    )


# ---- resolution ---------------------------------------------------------


class DestinationObservation:
    """One mounted volume or share, as observed right now (spec §5.2).

    An observation describes a **mount**, not a destination: its path is
    the mount point, and ``identity`` is whatever evidence the platform
    probe could produce for it (``None`` when it could produce none).
    The resolver is what joins a saved destination's ``subfolder_path``
    to a matched mount — a saved folder is only ever looked for *inside*
    a volume whose identity already matched, never by scanning paths
    (spec §5.1).
    """

    def __init__(
        self,
        *,
        path: str,
        label: str,
        identity: DestinationIdentity | None,
        is_writable: bool = True,
        filesystem: str = "",
        device_id: int | None = None,
    ) -> None:
        self.path = path
        self.label = label
        self.identity = identity
        self.is_writable = is_writable
        self.filesystem = filesystem
        # ``st_dev`` of the mount. Worthless as identity — it is
        # reassigned across boots — but exactly right for "is this folder
        # still on the volume we matched?" (R11).
        self.device_id = device_id if device_id is not None else _device_id(Path(path))

    @classmethod
    def from_volume(cls, volume: MountedVolume) -> DestinationObservation:
        """Adapt a discovered volume into a resolver observation."""
        return cls(
            path=volume.path,
            label=volume.label,
            identity=volume.identity,
            filesystem=volume.filesystem,
            device_id=volume.device_id,
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<DestinationObservation {self.path!r} identity={self.identity!r}>"


def _resolve_one(
    saved: SavedDestinationRow, observations: list[DestinationObservation]
) -> DestinationResolution:
    """Spec §5.1: return one of the five availability states."""
    binding = saved.last_binding_path or saved.last_root_path
    if saved.location_kind == "local_folder":
        return _resolve_local_folder(saved, binding, observations)
    return _resolve_mounted(saved, binding, observations)


def _resolve_local_folder(
    saved: SavedDestinationRow,
    binding: str,
    observations: list[DestinationObservation],
) -> DestinationResolution:
    """An explicit path binding, validated but never recreated.

    Spec §5.1: a vanished folder must not be recreated on a different
    backing filesystem implicitly. So a missing path is ``offline`` — the
    folder might be on a disk that is merely unplugged, and silently
    making a new empty one on the boot volume would send the transfer to
    the wrong place while looking like success.
    """
    path = Path(binding)
    if not path.exists():
        return _resolution(
            saved,
            "offline",
            f"the saved folder is not present at {binding}. If it lives on a drive that "
            "is not connected, connect it; Ferry never recreates a missing destination "
            "folder, because the new one could be on a different disk",
        )
    if not path.is_dir():
        return _resolution(saved, "unwritable", f"path is not a directory: {binding}")
    if not _writable(path):
        return _resolution(
            saved, "unwritable", f"path is not writable: {binding}", binding_path=binding
        )
    backing = _backing_failure(saved, path, observations)
    if backing is not None:
        return _resolution(saved, "needs_confirmation", backing, candidates=[binding])
    return _resolution(
        saved,
        "available",
        "local folder exists and is writable",
        candidates=[binding],
        binding_path=binding,
    )


def _backing_failure(
    saved: SavedDestinationRow,
    path: Path,
    observations: list[DestinationObservation],
) -> str | None:
    """Why a local folder's backing storage is not the saved one, or ``None``.

    ``local_folder`` is the *default* destination kind, so this is the
    path most transfers take — it gets the same evidence rules as a
    volume, not weaker ones.

    A local folder is bound by path, and a path is not storage. Once
    identity evidence has been recorded for one, recognizing it again
    requires **fresh, strong, matching** evidence. Everything short of
    that asks:

    - *no observations, or the owning mount cannot be determined* —
      absence of contradiction is not confirmation. A folder whose disk
      was swapped looks exactly like one whose discovery has not run.
    - *stale or weak evidence* — R10 applies here identically; a drive
      can be replaced between two observations.
    - *different identity* — the backing disk changed.

    Two cases deliberately still pass, and neither is automatic
    recognition of unknown storage:

    - **No identity was ever recorded.** The user saved a path and never
      confirmed storage for it; the explicit path binding is the whole
      of what they asked for, and there is nothing to contradict.
    - **The recorded evidence is ``path_only``** — the §5.1 escape hatch
      for storage the platform cannot identify. Requiring strong
      evidence there would make such a destination permanently
      unusable. It is scoped rather than permanent: if the platform can
      now identify that storage, the path-only confirmation is out of
      date and the user is asked to re-confirm so real evidence gets
      recorded.
    """
    if not saved.identity_kind or not saved.identity_value:
        return None
    owner = _owning_mount(path, observations)
    if saved.identity_kind == "path_only":
        return _path_only_failure(saved, owner)
    if not observations:
        return (
            f"{path} exists, but no storage observations are available, so Ferry cannot "
            f"tell whether it is still on the saved {saved.identity_kind} "
            f"{saved.identity_value!r}. Confirm it before transferring"
        )
    if owner is None:
        return (
            f"{path} exists, but Ferry could not determine which connected storage it is "
            f"on, so it cannot verify the saved {saved.identity_kind} "
            f"{saved.identity_value!r}. Confirm it before transferring"
        )
    match = _classify_match(saved, owner.identity)
    if match == "strong":
        return None
    if match == "weak":
        return (
            f"{path} is on storage whose identifier matches the saved one, but "
            f"{_why_weak(owner)} — not enough to recognize it automatically. Confirm it "
            "if this is the right storage"
        )
    observed = (
        f"{owner.identity.kind} {owner.identity.value!r}"
        if owner.identity is not None
        else "no identity evidence"
    )
    return (
        f"{path} now sits on storage reporting {observed}, not the saved "
        f"{saved.identity_kind} {saved.identity_value!r}. The folder's backing disk "
        "appears to have changed; confirm it before transferring"
    )


def _path_only_failure(
    saved: SavedDestinationRow, owner: DestinationObservation | None
) -> str | None:
    """Scope the manual path-only confirmation (spec §5.1).

    A path-only confirmation says "I looked, and this is the right
    folder" about storage Ferry could not identify. That stays valid —
    but it must not become permanent authority over whatever later
    occupies the path. The moment the platform *can* identify that
    storage, the old confirmation is stale by definition and real
    evidence should be captured instead.
    """
    if owner is None or owner.identity is None:
        return None
    identity = owner.identity
    if identity.kind == "path_only" or identity.stale:
        return None
    if identity.kind == saved.identity_kind and identity.value == saved.identity_value:
        return None
    return (
        f"this destination was confirmed by path alone, but its storage now reports "
        f"{identity.kind} {identity.value!r}. Re-confirm it so the binding records real "
        "identity evidence instead of a path"
    )


def _owning_mount(
    path: Path, observations: list[DestinationObservation]
) -> DestinationObservation | None:
    """The observed mount a resolved path actually lives on, if any.

    Chooses the longest matching mount path so a nested mount wins over
    its parent, and compares ``st_dev`` when available so an alias does
    not fool it.
    """
    try:
        resolved = path.resolve()
    except OSError:
        return None
    device = _device_id(resolved)
    if device is not None:
        by_device = [o for o in observations if o.device_id == device]
        if len(by_device) == 1:
            return by_device[0]
    best: DestinationObservation | None = None
    best_len = -1
    for obs in observations:
        try:
            mount = Path(obs.path).resolve()
        except OSError:
            continue
        if resolved == mount or mount in resolved.parents:
            length = len(str(mount))
            if length > best_len:
                best, best_len = obs, length
    return best


def _resolve_mounted(
    saved: SavedDestinationRow,
    binding: str,
    observations: list[DestinationObservation],
) -> DestinationResolution:
    """Resolve a volume- or share-backed destination against observations.

    The order matters, and each branch exists for a failure that has
    actually cost someone data:

    1. **Strong identity match** → resolve the saved subfolder *within*
       that mount and check it is usable.
    2. **More than one strong match** → ``ambiguous``. Two devices
       presenting the same identifier is not a tie to break silently.
    3. **Weak match only** → ``needs_confirmation``. A label, a size, or
       a medium-confidence disk UUID is not authority to rebind.
    4. **Same share name on a different host** → ``needs_confirmation``.
       The host may be an alias for the saved one, or a completely
       different server that happens to export ``/media``.
    5. **Nothing matched but the old path still exists** →
       ``needs_confirmation``, never ``available``. This is A12: a
       network share unmounts and leaves its mount directory behind on
       the local disk, and writing into it fills the boot drive while
       reporting a successful transfer to the NAS.
    6. **Nothing matched and nothing there** → ``offline``.
    """
    if not observations:
        return _resolve_without_observations(saved, binding)

    strong: list[DestinationObservation] = []
    weak: list[DestinationObservation] = []
    for obs in observations:
        bucket = _classify_match(saved, obs.identity)
        if bucket == "strong":
            strong.append(obs)
        elif bucket == "weak":
            weak.append(obs)

    if len(strong) > 1:
        return _resolution(
            saved,
            "ambiguous",
            f"{len(strong)} connected volumes report the same identity "
            f"({saved.identity_value!r}); Ferry cannot tell them apart, so choose one "
            "explicitly before transferring",
            candidates=[_candidate_path(saved, m) for m in strong],
        )
    if strong:
        return _resolve_within(saved, strong[0])
    if weak:
        return _resolution(
            saved,
            "needs_confirmation",
            f"a connected volume carries this destination's identifier, but {_why_weak(weak[0])} "
            "— not enough to rebind automatically. Confirm it if this is the right storage",
            candidates=[_candidate_path(saved, m) for m in weak],
        )

    alias = _host_alias_candidates(saved, observations)
    if alias:
        return _resolution(
            saved,
            "needs_confirmation",
            f"a share named {share_name(saved.identity_value or '')!r} is mounted, but "
            f"from a different host than the saved {share_host(saved.identity_value or '')!r}. "
            "That may be the same server under another name, or a different server "
            "entirely; confirm before transferring",
            candidates=[_candidate_path(saved, m) for m in alias],
        )
    return _resolve_no_match(saved, binding, observations)


def _resolve_within(
    saved: SavedDestinationRow, mount: DestinationObservation
) -> DestinationResolution:
    """The identity matched; now find the saved folder inside that mount."""
    candidate = _candidate_path(saved, mount)
    if not mount.is_writable:
        return _resolution(
            saved,
            "unwritable",
            f"the matched storage is mounted read-only at {mount.path}",
            candidates=[candidate],
            binding_path=candidate,
        )
    path = Path(candidate)
    if not path.exists():
        return _resolution(
            saved,
            "needs_confirmation",
            f"the storage was recognized at {mount.path}, but the saved folder "
            f"{saved.subfolder_path or '(root)'!r} is not there. Confirm a folder to use; "
            "Ferry does not create a destination folder on its own",
            candidates=[mount.path],
        )
    if not path.is_dir():
        return _resolution(
            saved,
            "unwritable",
            f"{candidate} exists but is not a directory",
            candidates=[candidate],
        )
    escape = _containment_failure(path, mount)
    if escape is not None:
        return _resolution(saved, "needs_confirmation", escape, candidates=[candidate])
    if not _writable(path):
        return _resolution(
            saved,
            "unwritable",
            f"{candidate} is not writable by this user",
            candidates=[candidate],
            binding_path=candidate,
        )
    return _resolution(
        saved,
        "available",
        f"recognized by {saved.identity_kind} at {mount.path}",
        candidates=[candidate],
        binding_path=candidate,
    )


def _containment_failure(path: Path, mount: DestinationObservation) -> str | None:
    """Why this folder is not on the volume we just recognized, or ``None``.

    Matching a *volume's* identity does not prove a folder inside it
    still lives on that volume. Two ways it does not (R11):

    - the folder is a **symlink** pointing somewhere else entirely, so
      the write lands off the recognized storage while the path looks
      right;
    - a **different filesystem is mounted** at that point inside the
      volume, which the path cannot show at all.

    Resolution is compared against the *resolved* mount, so a mount path
    that is itself reached through an alias stays legitimate — the rule
    is containment, not a ban on symlinks.
    """
    try:
        resolved_path = path.resolve()
        resolved_mount = Path(mount.path).resolve()
    except OSError as exc:
        return f"{path} could not be resolved: {exc}"
    if resolved_path != resolved_mount and resolved_mount not in resolved_path.parents:
        return (
            f"{path} resolves to {resolved_path}, which is outside the recognized storage "
            f"at {resolved_mount}. The folder is a link to somewhere else, so writing to it "
            "would not write to this destination. Confirm the location you actually want"
        )
    folder_device = _device_id(resolved_path)
    if (
        mount.device_id is not None
        and folder_device is not None
        and folder_device != mount.device_id
    ):
        return (
            f"{path} sits on a different filesystem than the recognized storage at "
            f"{mount.path} — another volume is mounted inside it. Confirm the location "
            "you actually want"
        )
    return None


def _resolve_without_observations(
    saved: SavedDestinationRow, binding: str
) -> DestinationResolution:
    """No discovery data at all — say so rather than trusting the path.

    This is the state when the observer has not run yet, or when the
    platform probe is unavailable. The saved path existing proves
    nothing about *what* is mounted there, so the honest answers are
    ``needs_confirmation`` (something is there, a human must vouch for
    it) and ``offline`` (nothing is there).
    """
    if Path(binding).is_dir():
        return _resolution(
            saved,
            "needs_confirmation",
            "no storage observations are available, so the saved location cannot be "
            "verified as the right device; confirm it before transferring",
            candidates=[binding],
        )
    return _resolution(
        saved, "offline", "no storage observations are available and the saved path is absent"
    )


def _resolve_no_match(
    saved: SavedDestinationRow,
    binding: str,
    observations: list[DestinationObservation],
) -> DestinationResolution:
    """Nothing matched. Three different situations, three messages.

    They look identical from the saved record's point of view and are not
    the same problem at all:

    - Something *is* mounted at the saved path, but it is a different
      device (A14: a drive that reused the label, or a second card in
      the same slot). The storage is present and wrong.
    - Nothing is mounted there but the directory remains (A12: a share
      unmounted and left its mount point behind on the local disk).
    - Nothing is there at all: the storage is simply not connected.
    """
    occupant = next(
        (o for o in observations if o.identity is not None and _same_path(o.path, binding)),
        None,
    )
    if occupant is not None and occupant.identity is not None:
        return _resolution(
            saved,
            "needs_confirmation",
            f"storage is mounted at {binding}, but it reports "
            f"{occupant.identity.kind} {occupant.identity.value!r}, which does not match "
            f"this destination's identity ({saved.identity_value!r}). A different disk or "
            "share is in that place. Confirm explicitly only if this really is the "
            "storage you meant",
            candidates=[binding],
        )
    lingering = Path(binding)
    if lingering.is_dir():
        return _resolution(
            saved,
            "needs_confirmation",
            f"{binding} still exists on disk, but nothing mounted there matches this "
            "destination's identity — after a share unmounts, its mount directory is "
            "left behind on the local disk. Ferry will not write into it. Reconnect the "
            "storage, or confirm this path explicitly if it really is the right place",
            candidates=[binding],
        )
    unmatched = [o.path for o in observations if o.identity is None]
    detail = f"; {len(unmatched)} connected volume(s) could not be identified" if unmatched else ""
    return _resolution(
        saved,
        "offline",
        f"no connected storage matches this destination's saved identity{detail}",
        candidates=unmatched,
    )


def _resolution(
    saved: SavedDestinationRow,
    status: str,
    reason: str,
    *,
    candidates: list[str] | None = None,
    binding_path: str | None = None,
) -> DestinationResolution:
    return DestinationResolution(
        destinationId=saved.id,
        name=saved.name,
        status=status,  # type: ignore[arg-type]
        reason=reason,
        candidatePaths=candidates or [],
        bindingPath=binding_path,
    )


def _same_path(left: str, right: str) -> bool:
    """Compare two mount paths without resolving through symlinks.

    Resolving would defeat the point: a lingering mount *directory* and
    the share that used to be mounted on it share a path by definition,
    and following links is how A12 turns into a write to the boot disk.
    """
    return str(Path(left)).rstrip("/") == str(Path(right)).rstrip("/")


def _candidate_path(saved: SavedDestinationRow, mount: DestinationObservation) -> str:
    """The saved folder's location within one observed mount.

    Spec §5.1: the relative folder path is matched *only* within a
    matched volume or share. The subfolder is never searched for
    anywhere else, and it was validated as a safe relative path when the
    destination was saved.
    """
    subfolder = (saved.subfolder_path or "").strip("/")
    if not subfolder:
        return mount.path
    return str(Path(mount.path) / subfolder)


def _why_weak(mount: DestinationObservation) -> str:
    """Say *why* the evidence is not authority — the states differ."""
    identity = mount.identity
    if identity is None:
        return "no identity evidence is available"
    if identity.stale:
        return (
            "the identity was remembered from an earlier observation rather than read now "
            f"(last seen {identity.observed_at or 'at an unknown time'}); a drive can be "
            "swapped between observations"
        )
    return f"the evidence is only {identity.confidence} confidence"


def _host_alias_candidates(
    saved: SavedDestinationRow, observations: list[DestinationObservation]
) -> list[DestinationObservation]:
    """Shares whose name matches but whose host does not (spec §5.1).

    Host aliases without established equivalence require confirmation:
    ``nas.local/media`` and ``192.168.1.10/media`` are frequently the
    same box and occasionally are not, and Ferry has no way to establish
    which without asking.
    """
    if saved.identity_kind != "server_share" or not saved.identity_value:
        return []
    wanted = share_name(saved.identity_value)
    saved_host = share_host(saved.identity_value)
    if not wanted:
        return []
    out: list[DestinationObservation] = []
    for obs in observations:
        identity = obs.identity
        if identity is None or identity.kind != "server_share":
            continue
        if share_name(identity.value) != wanted:
            continue
        if share_host(identity.value) == saved_host:
            continue
        out.append(obs)
    return out


def _classify_match(saved: SavedDestinationRow, identity: DestinationIdentity | None) -> str:
    """Return ``"strong" | "weak" | "none"`` for a candidate observation.

    ``strong`` means the saved destination has identity evidence and a
    **currently observed** identity matches it by kind and value with
    strong confidence. Anything else that matches by kind/value is
    ``weak`` — a ``disk_uuid`` match, which says the hardware came back
    but not that the saved filesystem did; a ``path_only`` match, which
    says nothing at all; and stale evidence, which says what used to be
    there.
    """
    if identity is None or saved.identity_kind is None or saved.identity_value is None:
        return "none"
    if saved.identity_kind != identity.kind or saved.identity_value != identity.value:
        return "none"
    if identity.stale:
        # Remembered, not re-observed. A drive can be swapped between two
        # observations, so this says what *was* here, never what is
        # (spec §5.1, R10).
        return "weak"
    return "strong" if identity.confidence == "strong" else "weak"


def _identity_matches(saved: SavedDestinationRow, identity: DestinationIdentity | None) -> bool:
    return _classify_match(saved, identity) == "strong"


def _writable(path: Path) -> bool:
    try:
        return path.is_dir() and bool(os.access(path, os.W_OK | os.X_OK))
    except OSError:
        return False


def _device_id(path: Path) -> int | None:
    """``st_dev`` for a path — a containment signal, never an identity."""
    try:
        return int(path.stat().st_dev)
    except OSError:
        return None


def _last_plan_status(conn: sqlite3.Connection, destination_id: int) -> str | None:
    """The most recent plan status for a destination, if any."""
    try:
        row = conn.execute(
            "SELECT status FROM transfer_plans WHERE destination_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (destination_id,),
        ).fetchone()
    except Exception:
        return None
    return row["status"] if row else None


__all__ = [
    "CONFLICT_POLICIES",
    "LOCATION_KINDS",
    "DestinationError",
    "DestinationNotFoundError",
    "DestinationObservation",
    "DestinationService",
]


def _subfolder_within(path: Path, owner: DestinationObservation | None) -> str | None:
    """The confirmed path expressed relative to the mount it lives on.

    Keeping mount, subfolder, and binding path derived from one another
    is what lets a later remount resolve the same folder in a new place.
    A path that is not under any observed mount has no subfolder, and
    the explicit binding stands on its own.
    """
    if owner is None:
        return None
    try:
        resolved = path.resolve()
        mount = Path(owner.path).resolve()
    except OSError:
        return None
    if resolved == mount:
        return None
    try:
        relative = resolved.relative_to(mount)
    except ValueError:
        return None
    return str(relative) or None


def _confirmed_identity(
    identity: DestinationIdentity | None, owner: DestinationObservation | None
) -> DestinationIdentity | None:
    """The identity to store, annotated with the fact a human vouched for it.

    Stale evidence is recorded as confirmed rather than stale: the
    operator looked at the drive and said yes, which is stronger than a
    remembered probe. The provenance keeps the distinction visible.
    """
    chosen = identity or (owner.identity if owner is not None else None)
    if chosen is None:
        return None
    return chosen.model_copy(
        update={
            "stale": False,
            "provenance": f"{chosen.provenance}; confirmed by user",
        }
    )
