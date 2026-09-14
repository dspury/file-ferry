"""Canonical checksum-label handling (issue #120).

The legacy config enum spells the algorithm ``"xxhash"``; the vNext
protocol and transfer runner spell it ``"xxhash64"``. Both must resolve to
the same hasher, on every path that hands the label to a checksum.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import xxhash

from file_ferry.application.transfer_safety import copy_file_verified
from file_ferry.checksum import normalize_checksum_algo


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("xxhash", "xxhash64"),
        ("XXHASH", "xxhash64"),
        ("xxhash64", "xxhash64"),
        ("sha256", "sha256"),
        ("SHA256", "sha256"),
    ],
)
def test_normalize_checksum_algo(given: str, expected: str) -> None:
    assert normalize_checksum_algo(given) == expected


def test_normalize_checksum_algo_passes_unknown_through_lowercased() -> None:
    """Unknown labels survive for the caller to reject with its own error."""
    assert normalize_checksum_algo("MD5") == "md5"


def test_copy_file_verified_accepts_legacy_label(tmp_path: Path) -> None:
    src = tmp_path / "src.bin"
    src.write_bytes(b"hello world")
    dest = tmp_path / "dest.bin"

    result = copy_file_verified(src, dest, algo="xxhash")

    assert result.checksum_algo == "xxhash64"
    assert result.source_checksum == xxhash.xxh64(b"hello world").hexdigest()
    assert result.dest_checksum == result.source_checksum
    assert dest.read_bytes() == b"hello world"
