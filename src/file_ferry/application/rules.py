"""The organization rule engine (spec §6.1-6.3, P4).

Given one source entry, decide where it goes. That is the whole job, and
every rule below exists because the alternative loses a file or puts it
somewhere the user did not ask for.

**Groups first, then ordered rules, first match wins.** A "keep
together" group routes an entire subtree as a unit — a camera card, an
application bundle, a project folder, a shoot with its sidecars. Running
groups first is what stops an extension rule from pulling the `.xml` out
of a camera card into `Documents/` while its `.mov` goes to `Video/`.
The *outermost* matching group wins, so a group inside a group does not
split the parent.

**Conditions are AND within a rule, OR within a condition.** One rule
saying "extension is .mov or .mp4, and the path matches DCIM/*" is one
idea. Making it mean something else would be a footgun in a UI where the
user cannot see the evaluation.

**Nothing is routed by guessing.** Category comes from an explicit,
versioned extension map — this is extension classification, never
content verification, and it is described that way everywhere it
surfaces. There are no expressions, no plugins, no regex handed to a
shell, and no scripting: a preset is data.

**`{year}` and `{month}` are the source's modification time in UTC**,
not a capture date. A file's mtime is frequently not when it was shot,
so the UI labels it and capture-date extraction is deferred rather than
guessed from filesystem dates. When the metadata a template needs is
missing, the entry goes to the fallback *with a warning* — never to a
silently invented value such as "now", which would file last year's
footage under this year.
"""

from __future__ import annotations

import fnmatch
import posixpath
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import PurePosixPath

from file_ferry.service.protocol import (
    PresetContent,
    PresetExclusion,
    PresetGroup,
    PresetMatchConditions,
    PresetRule,
)

#: Bumping this is a visible change to how files are classified, so it is
#: versioned and recorded on every plan that used it.
CATEGORY_MAP_VERSION = 1

#: Extension → category. Deliberately conservative: an extension this map
#: does not know is ``other``, which routes to the fallback rather than
#: being guessed into a category the user would not expect.
_CATEGORIES: dict[str, frozenset[str]] = {
    "video": frozenset(
        {
            ".mov",
            ".mp4",
            ".m4v",
            ".avi",
            ".mkv",
            ".mxf",
            ".mts",
            ".m2ts",
            ".mpg",
            ".mpeg",
            ".wmv",
            ".flv",
            ".webm",
            ".r3d",
            ".braw",
            ".ari",
            ".dv",
            ".3gp",
            ".prores",
            ".vob",
            ".ogv",
            ".insv",
        }
    ),
    "audio": frozenset(
        {
            ".wav",
            ".aif",
            ".aiff",
            ".mp3",
            ".m4a",
            ".flac",
            ".aac",
            ".ogg",
            ".opus",
            ".wma",
            ".caf",
            ".bwf",
            ".dsf",
            ".ape",
            ".mid",
            ".midi",
        }
    ),
    "image": frozenset(
        {
            ".jpg",
            ".jpeg",
            ".png",
            ".gif",
            ".tif",
            ".tiff",
            ".bmp",
            ".heic",
            ".heif",
            ".webp",
            ".raw",
            ".cr2",
            ".cr3",
            ".nef",
            ".arw",
            ".dng",
            ".orf",
            ".rw2",
            ".raf",
            ".srw",
            ".pef",
            ".psd",
            ".svg",
            ".ai",
            ".eps",
            ".insp",
        }
    ),
    "document": frozenset(
        {
            ".pdf",
            ".doc",
            ".docx",
            ".odt",
            ".rtf",
            ".txt",
            ".md",
            ".pages",
            ".xls",
            ".xlsx",
            ".ods",
            ".numbers",
            ".ppt",
            ".pptx",
            ".odp",
            ".key",
            ".csv",
            ".json",
            ".xml",
            ".yaml",
            ".yml",
            ".html",
            ".htm",
            ".epub",
        }
    ),
    "archive": frozenset(
        {
            ".zip",
            ".tar",
            ".gz",
            ".tgz",
            ".bz2",
            ".xz",
            ".7z",
            ".rar",
            ".dmg",
            ".iso",
            ".pkg",
            ".sit",
            ".sitx",
            ".z",
        }
    ),
}

#: The category an unknown or absent extension gets.
FALLBACK_CATEGORY = "other"

CATEGORIES: frozenset[str] = frozenset({*_CATEGORIES, FALLBACK_CATEGORY})

_EXT_TO_CATEGORY: dict[str, str] = {
    ext: category for category, exts in _CATEGORIES.items() for ext in exts
}

#: The sentinel a user writes to match files with no extension at all.
#: Without it, "extensions: []" and "files with no extension" would be
#: indistinguishable in the editor (spec §6.1).
NO_EXTENSION = ""

_TOKEN = re.compile(r"\{([a-z_]+)\}")

#: Characters no destination component may contain. Control characters
#: are rejected rather than stripped: silently rewriting a name is how a
#: file ends up somewhere the receipt does not describe.
_ILLEGAL = re.compile(r"[\x00-\x1f\x7f]")

#: Conservative limits. The real bound belongs to the target filesystem,
#: which P5 checks at publication; these catch the obvious cases during
#: review, where the user can still do something about them.
MAX_COMPONENT_BYTES = 255
MAX_PATH_BYTES = 4096


class RuleError(ValueError):
    """Raised when a rule or template cannot be applied."""


class TemplateDataMissingError(RuleError):
    """A template needs metadata this entry does not have.

    Distinct from an invalid template: the preset is fine, this
    particular file lacks (say) a usable modification time. The planner
    routes it to the fallback and records the reason.
    """


@dataclass(frozen=True)
class FileFacts:
    """Everything a rule may look at. Deliberately small and explicit."""

    rel_path: str
    source_label: str
    size: int = 0
    mtime: float | None = None
    entry_type: str = "file"

    @property
    def basename(self) -> str:
        return PurePosixPath(self.rel_path).name

    @property
    def relative_dir(self) -> str:
        parent = str(PurePosixPath(self.rel_path).parent)
        return "" if parent == "." else parent

    @property
    def ext(self) -> str:
        """The extension including its leading dot, or empty (spec §6.2)."""
        return PurePosixPath(self.rel_path).suffix

    @property
    def stem(self) -> str:
        return PurePosixPath(self.rel_path).stem

    @property
    def category(self) -> str:
        return category_for(self.ext)


@dataclass
class Routing:
    """Where one entry goes, and how that was decided.

    When a keep-together group claimed the entry, the group's id, its
    source-relative root, and the destination that root evaluates to all
    travel with the routing. The allocator needs all three: resolving a
    group collision means moving the *root* and keeping every internal
    path, which is impossible to do from a per-file destination alone
    (spec §6.3, examples E16).
    """

    dest_rel: str
    matched_rule: str
    warnings: list[str] = field(default_factory=list)
    group_id: str | None = None
    group_root: str | None = None
    group_dest_root: str | None = None


def category_for(ext: str) -> str:
    """The category of a file extension (spec §6.1).

    Extension classification, not content verification: a `.mov` holding
    a text file is still ``video`` here, and nothing in this codebase
    claims otherwise.
    """
    return _EXT_TO_CATEGORY.get(ext.lower(), FALLBACK_CATEGORY)


def normalize_label(label: str | None) -> str:
    """Make a source label safe to use as a path component (spec §6.2).

    The rendered value is shown in review, because a label the user typed
    and a label that lands on disk being different is exactly the kind of
    surprise that makes someone distrust the whole tool.
    """
    text = unicodedata.normalize("NFC", (label or "").strip())
    text = _ILLEGAL.sub("", text)
    text = re.sub(r"[/\\:]+", "-", text)
    text = text.strip(" .")
    return text or "Source"


# ---------------------------------------------------------------------------
# matching
# ---------------------------------------------------------------------------


def matches(conditions: PresetMatchConditions, facts: FileFacts) -> bool:
    """Whether every stated condition holds (AND), each matching any value (OR).

    A condition that is absent is not a condition — it does not
    constrain. A rule with no conditions at all matches nothing and is
    rejected at save time, so it cannot silently become a catch-all that
    swallows every file ahead of the rules below it.
    """
    stated = 0
    if conditions.path_glob is not None:
        stated += 1
        if not path_glob_matches(conditions.path_glob, facts.rel_path):
            return False
    if conditions.extensions is not None:
        stated += 1
        if not _extension_matches(conditions.extensions, facts.ext):
            return False
    if conditions.categories is not None:
        stated += 1
        if facts.category not in {c.strip().lower() for c in conditions.categories}:
            return False
    if conditions.source_label is not None:
        stated += 1
        if normalize_label(conditions.source_label) != facts.source_label:
            return False
    return stated > 0


def path_glob_matches(pattern: str, rel_path: str) -> bool:
    """Glob a source-relative path (spec §6.1).

    The dialect, in full, because a preset author has to be able to
    predict it (R20):

    - **Separators are always ``/``** regardless of host, so a preset
      written on macOS behaves identically on Windows. A backslash in the
      pattern or the path is read as ``/``, and leading and trailing
      ``/`` are ignored.
    - **Matching is case-insensitive.** The sources are removable media
      formatted exFAT/FAT/HFS+ as often as not, and a pattern that
      silently stopped matching because a camera wrote ``DCIM`` instead
      of ``dcim`` would be a quiet data-routing bug rather than a visible
      error.
    - **``*`` spans ``/``.** ``DCIM/*`` matches ``DCIM/100MEDIA/a.mov``,
      and ``*.mov`` matches a ``.mov`` at any depth. There is no ``**``:
      one wildcard means "anything, including separators", which is the
      reading that cannot leave a file unmatched by a rule its author
      believed covered it.
    - ``?`` matches one character (separators included) and ``[seq]``
      matches one character from the set. Nothing else is special: no
      regex, no braces, no negation.

    A group glob is matched against *directory* paths rather than file
    paths, so ``*`` there claims the outermost single-component
    ancestor — see :func:`_group_root`.
    """
    normalized = pattern.replace("\\", "/").strip("/")
    candidate = rel_path.replace("\\", "/")
    return fnmatch.fnmatch(candidate.lower(), normalized.lower())


def _extension_matches(extensions: list[str], ext: str) -> bool:
    """Case-insensitive extension match, with explicit extensionless support."""
    wanted: set[str] = set()
    for raw in extensions:
        value = raw.strip().lower()
        if value in ("", "."):
            wanted.add(NO_EXTENSION)
            continue
        wanted.add(value if value.startswith(".") else f".{value}")
    return ext.lower() in wanted


# ---------------------------------------------------------------------------
# groups
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GroupMatch:
    """A keep-together group and the subtree root it claimed."""

    group: PresetGroup
    root: str

    def relative_within(self, rel_path: str) -> str:
        """The entry's path *inside* the group, which the group preserves."""
        if not self.root:
            return rel_path
        return posixpath.relpath(rel_path, self.root)


def find_group(
    groups: list[PresetGroup], rel_path: str, *, entry_type: str = "file"
) -> GroupMatch | None:
    """The outermost group claiming this entry, if any (spec §6.3).

    Outermost wins so a group nested inside another cannot split the
    parent apart — the parent was marked "keep together" and that has to
    mean the whole of it. Among groups claiming the *same* root, rule
    order decides, which is the order the user put them in.
    """
    best: GroupMatch | None = None
    for group in groups:
        root = _group_root(group, rel_path, entry_type=entry_type)
        if root is None:
            continue
        if best is None or len(root) < len(best.root):
            best = GroupMatch(group=group, root=root)
    return best


def _group_root(group: PresetGroup, rel_path: str, *, entry_type: str) -> str | None:
    """The directory of ``rel_path`` this group's glob claims.

    A group matches a *directory*, and then owns everything beneath it.
    So the question is not "does this file match the pattern" but "is
    this entry inside — or, for a directory, *is* — a directory that
    does". Checked from the outside in, so the shallowest claimed
    ancestor is the one returned.

    A directory entry has to consider itself and not only its ancestors.
    Leaving it out is what sent the group's own root through the fallback
    while its children went to the group destination: an empty stray
    folder, and a group that was not in fact kept together (R17).
    """
    pattern = group.match.path_glob
    if not pattern:
        return None
    parts = PurePosixPath(rel_path).parts
    depth_limit = len(parts) + 1 if entry_type == "dir" else len(parts)
    for depth in range(1, depth_limit):
        candidate = "/".join(parts[:depth])
        if path_glob_matches(pattern, candidate):
            return candidate
    return None


# ---------------------------------------------------------------------------
# templates
# ---------------------------------------------------------------------------


def render_template(template: str, facts: FileFacts) -> str:
    """Render a destination template for one entry (spec §6.2).

    Raises :class:`TemplateDataMissingError` when the template asks for
    something this file cannot supply — a date from a file with no usable
    modification time. The caller routes those to the fallback and says
    so, rather than substituting the current date and filing footage
    under the wrong year.
    """
    values = _token_values(template, facts)

    def _replace(match: re.Match[str]) -> str:
        return values[match.group(1)]

    rendered = _TOKEN.sub(_replace, template)
    return _clean_path(rendered)


def _token_values(template: str, facts: FileFacts) -> dict[str, str]:
    needed = set(_TOKEN.findall(template))
    unknown = needed - TEMPLATE_TOKENS
    if unknown:
        raise RuleError(f"unknown template token(s): {', '.join(sorted(unknown))}")
    values: dict[str, str] = {
        "source_label": facts.source_label,
        "relative_dir": facts.relative_dir,
        "filename": facts.basename,
        "stem": facts.stem,
        "ext": facts.ext,
        "category": facts.category,
    }
    if "year" in needed or "month" in needed:
        moment = _utc_moment(facts)
        values["year"] = f"{moment.year:04d}"
        values["month"] = f"{moment.month:02d}"
    return values


def _utc_moment(facts: FileFacts) -> datetime:
    """The source modification time in UTC, or a missing-data error.

    No fallback to "now". A file whose mtime is absent or nonsensical
    (zero, negative, unrepresentable) has no date Ferry can honestly
    claim, and inventing one silently misfiles it forever.
    """
    mtime = facts.mtime
    if mtime is None or mtime <= 0:
        raise TemplateDataMissingError(
            f"{facts.rel_path} has no usable modification time, so a date-based "
            "destination cannot be rendered for it"
        )
    try:
        return datetime.fromtimestamp(mtime, tz=UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise TemplateDataMissingError(
            f"{facts.rel_path} has an unrepresentable modification time ({mtime}): {exc}"
        ) from exc


TEMPLATE_TOKENS: frozenset[str] = frozenset(
    {"source_label", "relative_dir", "filename", "stem", "ext", "category", "year", "month"}
)

#: The tokens a *group* destination may use. A group destination is
#: evaluated once, against the group's root directory: ``{filename}`` is
#: that directory's complete basename and ``{relative_dir}`` is its
#: parent. The file-oriented tokens are deliberately absent — ``{ext}``,
#: ``{stem}`` and ``{category}`` are meaningless for a directory, and
#: ``{year}``/``{month}`` would let a group's location depend on metadata
#: one directory may not have, splitting or relocating a subtree the user
#: marked "keep together" (examples §4).
GROUP_TEMPLATE_TOKENS: frozenset[str] = frozenset({"source_label", "relative_dir", "filename"})


def _clean_path(rendered: str) -> str:
    """Collapse the empty segments an unset token leaves behind.

    ``Sources/{source_label}/{relative_dir}/{filename}`` on a file at the
    source root would otherwise produce ``Sources/Card//A001.MOV``. The
    collapse is the *only* rewriting done here — a component that is
    unsafe is reported, never quietly repaired (spec §6.2).
    """
    parts = [p for p in rendered.replace("\\", "/").split("/") if p not in ("", ".")]
    return "/".join(parts)


def validate_rendered(rel: str, *, dest_root_len: int = 0) -> None:
    """Reject a rendered destination that cannot be written safely.

    Containment (absolute paths, ``..``, escapes) is
    ``transfer_safety``'s job and is checked separately against the real
    root. What is checked here is what only the rendered string can tell
    us: that it is non-empty, free of control characters, and within
    length limits the target is likely to enforce.
    """
    if not rel:
        raise RuleError("the template rendered an empty destination path")
    illegal = _ILLEGAL.search(rel)
    if illegal:
        raise RuleError(
            f"rendered destination contains a control character "
            f"({illegal.group(0)!r}) and was not silently rewritten: {rel!r}"
        )
    for component in rel.split("/"):
        if len(component.encode("utf-8")) > MAX_COMPONENT_BYTES:
            raise RuleError(
                f"path component exceeds {MAX_COMPONENT_BYTES} bytes and most "
                f"filesystems will refuse it: {component[:60]!r}…"
            )
        if component != component.strip(" ") or component.endswith("."):
            # Legal on POSIX, rejected or silently trimmed on Windows and
            # some network shares. Trimming here would mean the receipt
            # names a path that is not what was written.
            raise RuleError(
                f"path component {component!r} begins or ends with a space or dot, "
                "which several filesystems silently rewrite"
            )
    if dest_root_len + len(rel.encode("utf-8")) > MAX_PATH_BYTES:
        raise RuleError(
            f"the full destination path would exceed {MAX_PATH_BYTES} bytes: {rel[:80]!r}…"
        )


# ---------------------------------------------------------------------------
# the engine
# ---------------------------------------------------------------------------


def find_exclusion(content: PresetContent, facts: FileFacts) -> PresetExclusion | None:
    """The preset exclusion rule that claims this entry, if any (spec §4.2).

    Exclusions are evaluated **before** routing, and they apply inside
    keep-together groups as well as outside them: a user who wrote
    "never copy ``.tmp``" wrote it about every ``.tmp``, and a rule that
    quietly stopped at the edge of a group would be a second silent
    behavior to discover. When the excluded entry *is* inside a group the
    planner says so in review, because losing a sidecar out of a
    preserved subtree is worth seeing before the transfer, not after
    (spec §6.3).

    Order within the list is the order the user wrote; the first match
    wins and its ``reason`` is what review and the receipt show. Nothing
    here is implicit — there are no built-in extension exclusions, and an
    excluded entry is recorded as an entry, never as an absence
    (spec §6.2, §7.3).
    """
    for exclusion in content.exclusions:
        if matches(exclusion.match, facts):
            return exclusion
    return None


def route(content: PresetContent, facts: FileFacts, *, dest_root_len: int = 0) -> Routing:
    """Decide where one entry goes (spec §6.1-6.3).

    Order is the contract: groups first so a kept-together subtree is
    never split by an extension rule, then ordinary rules in the order
    the user wrote them, first match wins, then the fallback. Nothing
    reaches the end without a destination — an entry the rules do not
    recognize goes to the fallback, never nowhere (spec §6.2).

    Exclusions are not consulted here. They decide whether an entry is
    routed *at all*, which is the planner's call to make and record, so
    :func:`find_exclusion` is separate and runs first.
    """
    group = find_group(list(content.groups), facts.rel_path, entry_type=facts.entry_type)
    if group is not None:
        return _route_group(group, facts, dest_root_len=dest_root_len)
    for rule in content.rules:
        if matches(rule.match, facts):
            return _route_rule(rule, content, facts, dest_root_len=dest_root_len)
    return _route_fallback(content, facts, dest_root_len=dest_root_len, why=None)


def _route_group(group: GroupMatch, facts: FileFacts, *, dest_root_len: int) -> Routing:
    """A group routes its root, and everything keeps its place beneath it.

    The destination template is evaluated **once**, against the group's
    root directory, and every descendant's source-relative path is
    appended to the result unchanged (examples §4). That is what "keep
    together" has to mean: the internal layout a project or a package
    depends on is the thing being preserved, so it is never re-derived
    per file.

    Group templates are restricted to directory-meaningful tokens at
    save time, so rendering the root cannot fail on missing file
    metadata.
    """
    root_facts = FileFacts(
        rel_path=group.root,
        source_label=facts.source_label,
        mtime=facts.mtime,
        entry_type="dir",
    )
    base = render_template(group.group.destination, root_facts)
    inner = group.relative_within(facts.rel_path)
    dest = _clean_path(f"{base}/{inner}")
    validate_rendered(dest, dest_root_len=dest_root_len)
    return Routing(
        dest_rel=dest,
        matched_rule=f"group:{group.group.id}",
        group_id=group.group.id,
        group_root=group.root,
        group_dest_root=base,
    )


def _route_rule(
    rule: PresetRule, content: PresetContent, facts: FileFacts, *, dest_root_len: int
) -> Routing:
    try:
        dest = render_template(rule.destination, facts)
    except TemplateDataMissingError as exc:
        return _route_fallback(
            content, facts, dest_root_len=dest_root_len, why=f"rule {rule.id!r}: {exc}"
        )
    validate_rendered(dest, dest_root_len=dest_root_len)
    return Routing(dest_rel=dest, matched_rule=f"rule:{rule.id}")


def _route_fallback(
    content: PresetContent, facts: FileFacts, *, dest_root_len: int, why: str | None
) -> Routing:
    warnings = [] if why is None else [f"{facts.rel_path} routed to the fallback — {why}"]
    try:
        dest = render_template(content.fallback_template, facts)
    except TemplateDataMissingError as exc:
        raise RuleError(
            f"the fallback template needs metadata {facts.rel_path} does not have "
            f"({exc}); a fallback must be renderable for every file"
        ) from exc
    validate_rendered(dest, dest_root_len=dest_root_len)
    return Routing(dest_rel=dest, matched_rule="fallback", warnings=warnings)


__all__ = [
    "CATEGORIES",
    "CATEGORY_MAP_VERSION",
    "FALLBACK_CATEGORY",
    "GROUP_TEMPLATE_TOKENS",
    "MAX_COMPONENT_BYTES",
    "MAX_PATH_BYTES",
    "NO_EXTENSION",
    "TEMPLATE_TOKENS",
    "FileFacts",
    "GroupMatch",
    "Routing",
    "RuleError",
    "TemplateDataMissingError",
    "category_for",
    "find_exclusion",
    "find_group",
    "matches",
    "normalize_label",
    "path_glob_matches",
    "render_template",
    "route",
    "validate_rendered",
]
