"""Shared transfer-safety primitives (destination-presets spec §7.2).

Every mutating path in the new workflow — and the legacy organize and
offload runners, via the shared safeguards the spec demands of them —
routes its writes through this module so that one implementation owns:

- **Containment.** A rendered destination must live beneath the selected
  destination root. Absolute paths, ``..`` components, NUL bytes, and
  symlink escapes are rejected before any bytes move.
- **Exclusive publication.** A file is published by creating a hard link
  from a job-owned temporary sibling to the final name. Link creation is
  atomic and fails if the target exists, so an externally created file at
  a planned path can never be replaced. Where the filesystem cannot
  support that, the failure is explicit — there is no overwrite fallback.
- **Verified copy.** Bytes are streamed through an incremental checksum,
  flushed and fsynced, read back from the temporary file, and compared
  before publication. The source is stat-checked before and after so a
  file edited mid-copy fails rather than half-succeeds.

This module is deliberately free of database and IPC dependencies: it is
the pure filesystem boundary under the services.
"""

from __future__ import annotations

import contextlib
import errno
import hashlib
import os
import stat as stat_module
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CHUNK_BYTES = 1024 * 1024

# The suffix for job-owned temporary siblings. Publication code owns
# files with this suffix; unrelated files are never touched.
TEMP_SUFFIX = ".ferry-part"


class UnsafeDestinationError(ValueError):
    """A rendered destination escapes or cannot live under its root."""


class DestinationExistsError(FileExistsError):
    """Publication refused because the target already exists."""


class PublicationUnsupportedError(OSError):
    """The filesystem cannot provide exclusive publication."""

    def __init__(self, dest: Path, reason: str) -> None:
        super().__init__(errno.EOPNOTSUPP, reason, str(dest))
        self.dest = dest
        self.reason = reason


class SourceChangedError(OSError):
    """The source changed while it was being copied."""

    def __init__(self, source: Path, before: os.stat_result, after: os.stat_result) -> None:
        detail = (
            f"size {before.st_size}->{after.st_size}"
            if before.st_size != after.st_size
            else f"mtime {before.st_mtime_ns}->{after.st_mtime_ns}"
        )
        super().__init__(errno.EBUSY, f"source changed during copy ({detail})", str(source))
        self.source = source
        self.before = before
        self.after = after


@dataclass(frozen=True)
class CopyVerification:
    """The durable evidence one verified copy produced."""

    bytes_copied: int
    checksum_algo: str
    source_checksum: str
    dest_checksum: str
    mtime_preserved: bool


def _hasher_for(algo: str) -> Any:
    lower = algo.lower()
    if lower == "sha256":
        return hashlib.sha256()
    if lower == "xxhash64":
        import xxhash

        return xxhash.xxh64()
    raise ValueError(f"unsupported checksum algorithm: {algo}")


def validate_relpath(rel: str | Path) -> PureRel:
    """Validate that ``rel`` is a safe relative path for a destination.

    Rejects absolute paths, ``..`` components, empty components (except a
    single "." result), NUL bytes, and drive-letter/UNC-style prefixes
    before any filesystem access. Returns the validated parts.
    """
    raw = str(rel)
    if "\x00" in raw:
        raise UnsafeDestinationError(f"destination path contains NUL: {raw!r}")
    candidate = Path(raw)
    if candidate.is_absolute() or raw.startswith("/") or raw.startswith("\\"):
        raise UnsafeDestinationError(f"destination must be relative: {raw!r}")
    if len(raw) >= 2 and raw[1] == ":" and raw[0].isalpha():
        raise UnsafeDestinationError(f"destination must not be a drive path: {raw!r}")
    parts = candidate.parts
    if any(p == ".." for p in parts):
        raise UnsafeDestinationError(f"destination must not contain '..': {raw!r}")
    if any(p == "/" or p == "\\" or p == "\x00" for p in parts):
        raise UnsafeDestinationError(f"destination component is not a name: {raw!r}")
    return PureRel(tuple(p for p in parts if p not in (".",)))


@dataclass(frozen=True)
class PureRel:
    """Validated relative path parts."""

    parts: tuple[str, ...]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return "/".join(self.parts)


def render_destination(dest_root: Path, rel: str | Path) -> Path:
    """Return ``dest_root / rel`` after validating containment.

    Containment is checked twice: lexically on the relative path (before
    any I/O), and against the *resolved* parent chain (so a symlinked
    directory under the root cannot aim a write outside it). The root's
    own resolved form is the reference; the destination file itself does
    not need to exist yet.
    """
    safe = validate_relpath(rel)
    root = Path(dest_root)
    candidate = root.joinpath(*safe.parts) if safe.parts else root
    resolved_root = root.resolve(strict=False)
    resolved_parent = candidate.parent.resolve(strict=False)
    try:
        resolved_parent.relative_to(resolved_root)
    except ValueError as exc:
        raise UnsafeDestinationError(
            f"destination {candidate} escapes root {root} (resolved {resolved_parent} "
            f"outside {resolved_root})"
        ) from exc
    return candidate


def publish_exclusive(tmp: Path, dest: Path) -> None:
    """Publish ``tmp`` at ``dest`` without replacing existing content.

    Uses ``os.link`` so publication is atomic and fails with
    ``DestinationExistsError`` if ``dest`` already exists; the temporary
    sibling is then removed. A filesystem that cannot support hard links
    raises ``PublicationUnsupportedError`` rather than falling back to an
    overwrite-capable rename.
    """
    try:
        os.link(tmp, dest)
    except FileExistsError as exc:
        raise DestinationExistsError(
            errno.EEXIST, f"destination already exists: {dest}", str(dest)
        ) from exc
    except OSError as exc:
        if exc.errno in (errno.EXDEV, errno.EMLINK, errno.ENOSYS, errno.EPERM, errno.EACCES):
            # EPERM/EACCES can be a hard-link restriction (some network
            # filesystems, restricted directories) rather than a missing
            # write permission; distinguish only what we can prove.
            raise PublicationUnsupportedError(
                dest, f"filesystem does not support exclusive publication via link: {exc}"
            ) from exc
        raise
    finally:
        # The link either succeeded (tmp content now has two names) or the
        # publication failed for reasons unrelated to tmp's content.
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            # Leaving the job-owned temp behind is recoverable (it carries
            # the TEMP_SUFFIX and is never adopted by name), so a failure
            # to clean it must not mask the publication outcome.
            pass


def copy_file_verified(
    source: Path,
    dest: Path,
    *,
    algo: str = "xxhash64",
    on_progress: Callable[[int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> CopyVerification:
    """Copy ``source`` to ``dest`` verified and without replacing content.

    The copy is streamed into a temporary sibling of ``dest``, hashed as
    it streams, fsynced, read back and compared, and only then published
    exclusively. The source's stat signature (device, inode, size, mtime)
    is checked before and after; a mid-copy edit raises
    :class:`SourceChangedError`. Basic mtime is preserved on the
    published file where the platform allows; failure to do so is
    reported in the result, not silently dropped.

    Cancellation is checked at least once per chunk. A cancellation (or
    any other failure) leaves the source untouched, publishes nothing,
    and removes the temporary sibling.
    """
    source = Path(source)
    dest = Path(dest)
    before = source.stat()
    if not os.path.isfile(source):
        raise UnsafeDestinationError(f"source is not a regular file: {source}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{dest.name}.", suffix=TEMP_SUFFIX, dir=dest.parent)
    tmp = Path(tmp_name)
    try:
        read_hash = _hasher_for(algo)
        with os.fdopen(fd, "wb") as out:
            with open(source, "rb") as src:
                total = 0
                while True:
                    if cancel_check is not None and cancel_check():
                        raise _Cancelled()
                    chunk = src.read(CHUNK_BYTES)
                    if not chunk:
                        break
                    read_hash.update(chunk)
                    out.write(chunk)
                    total += len(chunk)
                    if on_progress is not None:
                        on_progress(total)
            out.flush()
            os.fsync(out.fileno())

        # Verify the bytes that were written, not the bytes we remember
        # writing: read the temporary file back through the same hasher.
        write_hash = _hasher_for(algo)
        with open(tmp, "rb") as written:
            while True:
                if cancel_check is not None and cancel_check():
                    raise _Cancelled()
                chunk = written.read(CHUNK_BYTES)
                if not chunk:
                    break
                write_hash.update(chunk)
        source_digest = read_hash.hexdigest()
        written_digest = write_hash.hexdigest()
        if source_digest != written_digest:
            raise OSError(
                errno.EIO,
                f"checksum mismatch during verified copy of {source}",
                str(source),
            )

        after = source.stat()
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise SourceChangedError(source, before, after)

        mtime_preserved = _preserve_mtime(source, tmp)
        publish_exclusive(tmp, dest)
        return CopyVerification(
            bytes_copied=total,
            checksum_algo=algo.lower(),
            source_checksum=source_digest,
            dest_checksum=written_digest,
            mtime_preserved=mtime_preserved,
        )
    except BaseException:
        # Cleanup for every failure path, including cancellation. The
        # published destination is never touched by a failure here.
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def _preserve_mtime(source: Path, tmp: Path) -> bool:
    """Copy the source's mtime onto ``tmp``; report whether it worked."""
    try:
        st = source.stat()
        os.utime(tmp, ns=(st.st_atime_ns, st.st_mtime_ns))
        return True
    except OSError:
        return False


class _Cancelled(BaseException):
    """Internal control-flow signal for cooperative cancellation."""


def destination_exists(dest: Path) -> bool:
    """Cheap existence probe used by planners (never by publication)."""
    try:
        os.lstat(dest)
        return True
    except OSError:
        return False


def copy_tree_verified(
    source_root: Path,
    dest_root: Path,
    *,
    rel_paths: list[str],
    algo: str = "xxhash64",
    on_file_done: Callable[[str, CopyVerification], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> list[tuple[str, CopyVerification | BaseException]]:
    """Copy explicit ``rel_paths`` from ``source_root`` to ``dest_root``.

    Each destination is validated for containment and published
    exclusively; per-file outcomes are returned as
    ``(rel_path, verification-or-exception)`` so a caller can build an
    honest receipt instead of a boolean. An error on one file does not
    stop the others (spec §7.2: per-item outcomes, no false success).
    """
    results: list[tuple[str, CopyVerification | BaseException]] = []
    for rel in rel_paths:
        try:
            dest = render_destination(dest_root, rel)
            verification = copy_file_verified(
                source_root / rel, dest, algo=algo, cancel_check=cancel_check
            )
            if on_file_done is not None:
                on_file_done(rel, verification)
            results.append((rel, verification))
        except _Cancelled:
            results.append((rel, _Cancelled()))
            break
        except BaseException as exc:  # per-file boundary
            results.append((rel, exc))
    return results


def existing_destination_collisions(dest_root: Path, dest_paths: list[str]) -> dict[str, str]:
    """Map each destination path that already exists to a reason.

    Planners use this to surface conflicts *before* approval (spec §6.4).
    A path that exists as a directory is reported differently from a
    file, and a symlink is reported as itself — never followed, so an
    adversarial link is never mistaken for the file it points at.

    Ancestor conflicts count too: a planned path ``a/b`` whose parent
    ``a`` already exists as a *file* can never be created, so the
    ancestor is reported rather than letting the copy fail opaquely.
    """
    collisions: dict[str, str] = {}
    root = Path(dest_root)
    for raw in dest_paths:
        candidate = Path(raw)
        try:
            st = os.lstat(candidate)
        except OSError:
            st = None
        if st is not None:
            if stat_module.S_ISLNK(st.st_mode):
                collisions[raw] = "existing_symlink"
            elif stat_module.S_ISDIR(st.st_mode):
                collisions[raw] = "existing_directory"
            elif stat_module.S_ISREG(st.st_mode):
                collisions[raw] = "existing_file"
            else:
                collisions[raw] = "existing_special"
            continue
        # The exact path is free; a non-directory ancestor still blocks it.
        for ancestor in candidate.parents:
            if ancestor == root:
                break
            try:
                ast = os.lstat(ancestor)
            except OSError:
                continue
            if not stat_module.S_ISDIR(ast.st_mode):
                collisions[str(ancestor)] = (
                    "existing_symlink" if stat_module.S_ISLNK(ast.st_mode) else "ancestor_is_file"
                )
                break
    return collisions


def validate_dest_root(dest_root: Path) -> Path:
    """Validate a destination root for writing; returns the resolved path."""
    root = Path(dest_root)
    if not root.exists():
        raise UnsafeDestinationError(f"destination root does not exist: {root}")
    if not root.is_dir():
        raise UnsafeDestinationError(f"destination root is not a directory: {root}")
    if not os.access(root, os.W_OK | os.X_OK):
        raise UnsafeDestinationError(f"destination root is not writable: {root}")
    resolved = root.resolve(strict=False)
    # The root itself may be a symlink (a mount alias, say); what matters
    # is that writes beneath the *resolved* root are what the user chose.
    return resolved


__all__ = [
    "CHUNK_BYTES",
    "TEMP_SUFFIX",
    "CopyVerification",
    "DestinationExistsError",
    "PublicationUnsupportedError",
    "PureRel",
    "SourceChangedError",
    "UnsafeDestinationError",
    "copy_file_verified",
    "copy_tree_verified",
    "destination_exists",
    "existing_destination_collisions",
    "publish_exclusive",
    "render_destination",
    "validate_dest_root",
    "validate_relpath",
]
