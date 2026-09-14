"""Canonical checksum-algorithm labels.

One algorithm has two spellings in this tree. The legacy config/TUI enum
(:class:`file_ferry.models.ChecksumAlgo`) writes ``"xxhash"``; the vNext
protocol, persistence and transfer runner use ``"xxhash64"``. Both name the
same algorithm (``xxhash.xxh64``) and produce identical digests, but a label
written by one path and handed to the other used to raise.

Every checksum entry point resolves its label through
:func:`normalize_checksum_algo`, so the legacy spelling cannot reach a hasher
that only knows the canonical name.
"""

from __future__ import annotations

CANONICAL_CHECKSUM_ALGOS = frozenset({"xxhash64", "sha256"})

# Legacy spelling -> canonical. Keys are lower-cased.
_ALIASES = {"xxhash": "xxhash64"}


def normalize_checksum_algo(algo: str) -> str:
    """Return the canonical label for *algo*.

    Unknown labels are returned lower-cased and unvalidated, so callers keep
    control of the error they raise for an unsupported algorithm.
    """
    lowered = algo.lower()
    return _ALIASES.get(lowered, lowered)


__all__ = ["CANONICAL_CHECKSUM_ALGOS", "normalize_checksum_algo"]
