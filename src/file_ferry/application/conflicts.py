"""Conflict detection and keep-both allocation (spec §6.4, P4).

The rule this whole module serves: **nothing is overwritten and nothing
disappears.** Two files wanting one name is not an error to resolve by
picking a winner; it is a fact to record, and either both land under
distinct names or a person decides.

The conflicts are kept *distinct* rather than collapsed into "name
taken", because they mean different things to whoever reviews them:

``same_name_different_content``
    Two sources, or a source and the destination, disagree about what
    lives at a name. The common case, and the reason keep-both exists.
``case_only``
    ``IMG_001.JPG`` and ``img_001.jpg``. On a case-insensitive target
    these are one file and the second silently replaces the first; on a
    case-sensitive one they are two. Ferry cannot always tell which kind
    of filesystem it is writing to, so it treats the ambiguity as a
    finding instead of guessing.
``unicode_normalization``
    ``é`` as one code point versus ``e`` plus a combining accent. macOS
    and Linux disagree about this by default. Visually identical, and on
    one of those systems one file overwrites the other.
``file_vs_directory``
    A file wants a name a directory already holds, or the reverse. No
    suffix fixes this; it needs a decision.
``ancestor_path``
    One entry's destination is a *parent directory* of another's. Writing
    the file makes the other's directory impossible.
``existing_destination``
    Something is already at the target that this plan did not put there.

``skip_identical`` is still not issued anywhere. It requires proof of
full content equality (§6.4) and the checksums that prove it belong to
the P5 runner; this module records the conflict so that decision can be
made later, and never asserts identity it has not verified.
"""

from __future__ import annotations

import os
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

#: Conflict kinds, as they appear on plan entries and in receipts.
SAME_NAME_DIFFERENT_CONTENT = "same_name_different_content"
CASE_ONLY = "case_only"
UNICODE_NORMALIZATION = "unicode_normalization"
FILE_VS_DIRECTORY = "file_vs_directory"
ANCESTOR_PATH = "ancestor_path"
EXISTING_DESTINATION = "existing_destination"
EXISTING_SYMLINK = "existing_destination_symlink"
EXISTING_SPECIAL = "existing_destination_special"
EXISTING_UNREADABLE = "existing_destination_unreadable"

#: How many keep-both suffixes to try before giving up and asking.
MAX_KEEP_BOTH_ATTEMPTS = 10_000


def comparison_key(rel_path: str) -> str:
    """The key two paths collide on, conservatively.

    Unicode-normalized (NFC) and case-folded, because the target may
    well be a case-insensitive, normalization-folding filesystem — and
    when Ferry cannot know, treating two names as *possibly* the same
    file is the answer that cannot lose data. The actual filename is
    never changed; only the comparison is normalized (spec §6.2).
    """
    return unicodedata.normalize("NFC", rel_path).casefold()


def distinguish(left: str, right: str) -> str | None:
    """How two colliding paths differ, or ``None`` if they are identical.

    Naming the *kind* of collision is what lets the review screen say
    something useful instead of "duplicate".
    """
    if left == right:
        return None
    if unicodedata.normalize("NFC", left) == unicodedata.normalize("NFC", right):
        return UNICODE_NORMALIZATION
    if left.casefold() == right.casefold():
        return CASE_ONLY
    return SAME_NAME_DIFFERENT_CONTENT


@dataclass
class Allocation:
    """One entry's resolved destination and what had to happen to get it."""

    dest_rel: str
    conflict: str | None = None
    detail: str | None = None
    renamed_from: str | None = None


@dataclass
class Reservations:
    """Destination names claimed so far, plus what is already on disk.

    Keep-both allocation has to reserve against *both*, or two sources
    each pick the same "free" suffix and one overwrites the other at
    publication (spec §6.4).
    """

    dest_root: Path
    #: comparison key -> the actual path first claimed under it
    claimed: dict[str, str] = field(default_factory=dict)
    #: directories this plan will create, for file-vs-directory detection
    directories: set[str] = field(default_factory=set)
    _existing_cache: dict[str, bool] = field(default_factory=dict)
    _symlink_cache: dict[str, bool] = field(default_factory=dict)

    def claim(self, dest_rel: str) -> None:
        self.claimed.setdefault(comparison_key(dest_rel), dest_rel)

    def claim_directory(self, dest_rel: str) -> None:
        self.directories.add(comparison_key(dest_rel))
        self.claim(dest_rel)

    def holder(self, dest_rel: str) -> str | None:
        """The path already claimed under this comparison key, if any."""
        return self.claimed.get(comparison_key(dest_rel))

    def exists_on_disk(self, dest_rel: str) -> bool:
        """Whether anything occupies this name at the destination.

        ``lstat`` rather than ``exists`` so a broken symlink counts: it
        does not resolve, but the name is taken and publication will
        fail on it.

        The cache is keyed by the *folded* comparison key, which on a
        case-sensitive destination means the answer for ``foo.txt`` is
        reused for ``Foo.txt``. That is deliberate and safe in one
        direction only: it can report a name as taken when it is free,
        which costs a keep-both suffix, and never reports a taken name as
        free, which would cost a file. The planner's own ordering makes
        the two paths collide on that same key anyway.
        """
        key = comparison_key(dest_rel)
        cached = self._existing_cache.get(key)
        if cached is not None:
            return cached
        target = self.dest_root / dest_rel
        try:
            os.lstat(target)
            present = True
        except OSError:
            present = False
        self._existing_cache[key] = present
        return present

    def symlink_ancestor(self, dest_rel: str) -> str | None:
        """The first existing symlink among this path's parent directories.

        Writing a file into ``Sources/card/Photos/a.jpg`` when ``Photos``
        is a symlink writes it wherever that link points — outside the
        destination root, as far as the user is concerned, while the plan
        and the receipt both name a path inside it. ``is_dir()`` follows
        links and so reports such a parent as an ordinary directory, and
        the leaf check never sees it because the leaf does not exist yet
        (R16).

        Checking the whole ancestor chain rather than only a planned
        directory entry matters because the planner does not emit a
        directory entry for every parent — a directory implied by its
        routed children has none (spec §6.2). Results are cached per
        directory, so a plan with one hundred thousand files under one
        tree pays for the depth of the tree, not its size.
        """
        parts = PurePosixPath(dest_rel).parts
        for depth in range(1, len(parts)):
            ancestor = "/".join(parts[:depth])
            key = comparison_key(ancestor)
            found = self._symlink_cache.get(key)
            if found is None:
                found = os.path.islink(self.dest_root / ancestor)
                self._symlink_cache[key] = found
            if found:
                return ancestor
        return None

    def is_free(self, dest_rel: str) -> bool:
        return self.holder(dest_rel) is None and not self.exists_on_disk(dest_rel)


def allocate(
    dest_rel: str,
    reservations: Reservations,
    *,
    policy: str,
    entry_type: str = "file",
) -> Allocation:
    """Place one entry, keeping both names when that is safe (spec §6.4).

    ``keep_both`` is the default and the only policy that can resolve a
    collision without a person: it allocates a deterministic suffixed
    name that is free against every other planned entry *and* the
    existing destination contents. ``needs_review`` and
    ``skip_identical`` both stop here — the first by design, the second
    because proving identity needs checksums this layer does not have.
    """
    linked = reservations.symlink_ancestor(dest_rel)
    if linked is not None:
        return Allocation(
            dest_rel=dest_rel,
            conflict=EXISTING_SYMLINK,
            detail=(
                f"{dest_rel} would be written through {linked}, which exists at the "
                "destination as a symbolic link. Its target is not inspected and it is "
                "never written through: the plan would name a path inside the "
                "destination while the bytes landed wherever the link points"
            ),
        )

    ancestor = _ancestor_conflict(dest_rel, reservations)
    if ancestor is not None:
        return ancestor

    if entry_type == "dir":
        # Several sources contributing the same directory is ordinary;
        # directories are created, not written over one another. A *file*
        # already holding that name is not ordinary — and neither is a
        # symlink, which ``is_dir()`` would happily report as a directory
        # while pointing somewhere else entirely (R16).
        if reservations.exists_on_disk(dest_rel):
            target = reservations.dest_root / dest_rel
            if os.path.islink(target):
                return Allocation(
                    dest_rel=dest_rel,
                    conflict=EXISTING_SYMLINK,
                    detail=(
                        f"{dest_rel} exists at the destination as a symbolic link, not a "
                        "directory; its target is not inspected and this transfer will "
                        "not write through it"
                    ),
                )
            if not target.is_dir():
                return Allocation(
                    dest_rel=dest_rel,
                    conflict=FILE_VS_DIRECTORY,
                    detail=f"{dest_rel} already exists at the destination and is not a directory",
                )
        reservations.claim_directory(dest_rel)
        return Allocation(dest_rel=dest_rel)

    if comparison_key(dest_rel) in reservations.directories:
        return Allocation(
            dest_rel=dest_rel,
            conflict=FILE_VS_DIRECTORY,
            detail=f"{dest_rel} is also a directory this transfer will create",
        )

    holder = reservations.holder(dest_rel)
    on_disk = reservations.exists_on_disk(dest_rel)
    if holder is None and not on_disk:
        reservations.claim(dest_rel)
        return Allocation(dest_rel=dest_rel)

    kind, detail = _describe_collision(dest_rel, holder, on_disk, reservations)
    if policy != "keep_both":
        return Allocation(dest_rel=dest_rel, conflict=kind, detail=detail)

    allocated = _next_free_name(dest_rel, reservations)
    if allocated is None:
        return Allocation(
            dest_rel=dest_rel,
            conflict=kind,
            detail=(
                f"{detail}; no free keep-both name was available after "
                f"{MAX_KEEP_BOTH_ATTEMPTS} attempts"
            ),
        )
    reservations.claim(allocated)
    return Allocation(
        dest_rel=allocated,
        conflict=kind,
        detail=f"{detail}; kept both — this copy lands at {allocated}",
        renamed_from=dest_rel,
    )


@dataclass
class GroupAllocation:
    """Where a whole keep-together group goes, and what it cost."""

    dest_root: str
    conflict: str | None = None
    detail: str | None = None
    renamed_from: str | None = None


def allocate_group_root(
    dest_root_rel: str, reservations: Reservations, *, policy: str
) -> GroupAllocation:
    """Place a keep-together group by moving its **root**, never a member.

    A group exists because its internal layout matters — a project
    referencing its media by relative path, a package whose contents are
    addressed by name. Suffixing one member to dodge a collision
    therefore breaks the very thing the group was marked to protect,
    which is why the examples forbid it outright (E16, decision 5).

    So the collision is resolved one level up: if anything already
    occupies the group's destination root, the *whole group* moves to a
    new root name and every internal relative path is carried over
    unchanged. Merging into an existing tree is deliberately not
    attempted — proving that a merge is safe needs per-file evidence and
    reviewed decisions, and guessing instead is how an existing project
    quietly acquires foreign files.
    """
    linked = reservations.symlink_ancestor(dest_root_rel)
    if linked is not None:
        return GroupAllocation(
            dest_root=dest_root_rel,
            conflict=EXISTING_SYMLINK,
            detail=(
                f"the group would be written through {linked}, which exists at the "
                "destination as a symbolic link and is never written through"
            ),
        )
    ancestor = _ancestor_conflict(dest_root_rel, reservations)
    if ancestor is not None:
        return GroupAllocation(
            dest_root=dest_root_rel, conflict=ancestor.conflict, detail=ancestor.detail
        )

    holder = reservations.holder(dest_root_rel)
    on_disk = reservations.exists_on_disk(dest_root_rel)
    if holder is None and not on_disk:
        reservations.claim_directory(dest_root_rel)
        return GroupAllocation(dest_root=dest_root_rel)

    if on_disk and holder is None and os.path.islink(reservations.dest_root / dest_root_rel):
        return GroupAllocation(
            dest_root=dest_root_rel,
            conflict=EXISTING_SYMLINK,
            detail=(
                f"{dest_root_rel} exists at the destination as a symbolic link; the group "
                "is not written through it and its target is not inspected"
            ),
        )

    occupant = (
        f"{dest_root_rel} is already claimed by {holder} in this transfer"
        if holder is not None
        else f"{dest_root_rel} already exists at the destination"
    )
    if policy != "keep_both":
        return GroupAllocation(
            dest_root=dest_root_rel,
            conflict=EXISTING_DESTINATION,
            detail=(
                f"{occupant}, and the conflict policy is {policy!r}; a preserved group is "
                "never merged into existing content without a decision"
            ),
        )

    allocated = _next_free_name(dest_root_rel, reservations)
    if allocated is None:
        return GroupAllocation(
            dest_root=dest_root_rel,
            conflict=EXISTING_DESTINATION,
            detail=(
                f"{occupant}; no free group-root name was available after "
                f"{MAX_KEEP_BOTH_ATTEMPTS} attempts"
            ),
        )
    reservations.claim_directory(allocated)
    return GroupAllocation(
        dest_root=allocated,
        conflict=EXISTING_DESTINATION,
        detail=(
            f"{occupant}, so the whole group was kept together at {allocated} with every "
            "internal path unchanged; no member was renamed individually"
        ),
        renamed_from=dest_root_rel,
    )


def _describe_collision(
    dest_rel: str, holder: str | None, on_disk: bool, reservations: Reservations
) -> tuple[str, str]:
    """Name the collision precisely, so review shows what actually happened."""
    if holder is not None and holder != dest_rel:
        kind = distinguish(holder, dest_rel) or SAME_NAME_DIFFERENT_CONTENT
        return kind, (
            f"{dest_rel} collides with {holder}, already planned in this transfer "
            f"({_explain(kind)})"
        )
    if holder is not None:
        return SAME_NAME_DIFFERENT_CONTENT, (
            f"{dest_rel} is already claimed by another file in this transfer"
        )
    target = reservations.dest_root / dest_rel
    try:
        if target.is_symlink():
            return EXISTING_SYMLINK, (
                f"{dest_rel} exists at the destination as a symlink; its target is not "
                "inspected and it is never replaced"
            )
        if target.is_dir():
            return FILE_VS_DIRECTORY, f"{dest_rel} exists at the destination as a directory"
        if target.is_file():
            return EXISTING_DESTINATION, (
                f"{dest_rel} already exists at the destination; Ferry never replaces "
                "existing content"
            )
        return EXISTING_SPECIAL, (
            f"{dest_rel} exists at the destination as an unsupported filesystem object"
        )
    except OSError as exc:
        return EXISTING_UNREADABLE, f"{dest_rel} exists at the destination but is unreadable: {exc}"


def _explain(kind: str) -> str:
    return {
        CASE_ONLY: "the two names differ only by letter case, which many destinations "
        "treat as one file",
        UNICODE_NORMALIZATION: "the two names are the same text in different Unicode "
        "normal forms, which some destinations treat as one file",
        SAME_NAME_DIFFERENT_CONTENT: "same destination name, different source files",
    }.get(kind, kind)


def _ancestor_conflict(dest_rel: str, reservations: Reservations) -> Allocation | None:
    """Detect an entry whose destination is inside another entry's file.

    ``Media/report.pdf`` and ``Media/report.pdf/page1.png`` cannot both
    exist. No suffix resolves it, so it is always a review item.
    """
    parts = PurePosixPath(dest_rel).parts
    for depth in range(1, len(parts)):
        ancestor = "/".join(parts[:depth])
        key = comparison_key(ancestor)
        if key in reservations.directories:
            continue
        holder = reservations.claimed.get(key)
        if holder is not None:
            return Allocation(
                dest_rel=dest_rel,
                conflict=ANCESTOR_PATH,
                detail=(
                    f"{dest_rel} would have to be created inside {holder}, which this "
                    "transfer is planning as a file"
                ),
            )
    return None


def _next_free_name(dest_rel: str, reservations: Reservations) -> str | None:
    """The first free ``name (n).ext`` for a taken destination.

    Deterministic: the same plan produces the same names every time, so a
    receipt is reproducible and a re-run does not shuffle files. Counting
    starts at 2 because the original is conceptually copy 1.
    """
    path = PurePosixPath(dest_rel)
    parent = str(path.parent)
    stem = path.stem
    suffix = path.suffix
    prefix = "" if parent == "." else f"{parent}/"
    for index in range(2, MAX_KEEP_BOTH_ATTEMPTS + 2):
        candidate = f"{prefix}{stem} ({index}){suffix}"
        if reservations.is_free(candidate):
            return candidate
    return None


def group_by_destination(entries: list[tuple[int, str]]) -> dict[str, list[int]]:
    """Index entry ids by the comparison key of their destination."""
    out: dict[str, list[int]] = defaultdict(list)
    for entry_id, dest in entries:
        out[comparison_key(dest)].append(entry_id)
    return dict(out)


__all__ = [
    "ANCESTOR_PATH",
    "CASE_ONLY",
    "EXISTING_DESTINATION",
    "EXISTING_SPECIAL",
    "EXISTING_SYMLINK",
    "EXISTING_UNREADABLE",
    "FILE_VS_DIRECTORY",
    "MAX_KEEP_BOTH_ATTEMPTS",
    "SAME_NAME_DIFFERENT_CONTENT",
    "UNICODE_NORMALIZATION",
    "Allocation",
    "GroupAllocation",
    "Reservations",
    "allocate",
    "allocate_group_root",
    "comparison_key",
    "distinguish",
    "group_by_destination",
]
