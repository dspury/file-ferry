"""Tests for the sidecar CLI entry point (``file_ferry.service.cli``).

The entry point is what the desktop shell spawns. It is thin, but two
things about it are load-bearing: the default app-data location it picks
when the host passes no ``--db``, and the protocol-version handshake the
host declares through the environment.
"""

from __future__ import annotations

import io

from file_ferry.service import PROTOCOL_VERSION
from file_ferry.service.cli import _default_db_path, warn_on_host_protocol_mismatch


class TestHostProtocolMismatch:
    """`FERRY_PROTOCOL_VERSION` is set by Electron when it spawns the sidecar.

    Negotiation itself is per-frame (ADR-0002); this is the startup diagnostic
    that keeps a mismatch from showing up only as every request failing.
    """

    def test_matching_version_is_silent(self) -> None:
        stream = io.StringIO()
        assert warn_on_host_protocol_mismatch(str(PROTOCOL_VERSION), stream) is False
        assert stream.getvalue() == ""

    def test_unset_is_silent(self) -> None:
        stream = io.StringIO()
        assert warn_on_host_protocol_mismatch(None, stream) is False
        assert stream.getvalue() == ""

    def test_blank_is_silent(self) -> None:
        stream = io.StringIO()
        assert warn_on_host_protocol_mismatch("   ", stream) is False
        assert stream.getvalue() == ""

    def test_surrounding_whitespace_still_matches(self) -> None:
        stream = io.StringIO()
        assert warn_on_host_protocol_mismatch(f" {PROTOCOL_VERSION} ", stream) is False
        assert stream.getvalue() == ""

    def test_mismatch_warns_naming_both_versions(self) -> None:
        stream = io.StringIO()
        assert warn_on_host_protocol_mismatch(str(PROTOCOL_VERSION + 1), stream) is True
        written = stream.getvalue()
        assert "warning:" in written
        assert str(PROTOCOL_VERSION + 1) in written
        assert str(PROTOCOL_VERSION) in written
        assert "version_mismatch" in written

    def test_garbage_warns_rather_than_raising(self) -> None:
        stream = io.StringIO()
        assert warn_on_host_protocol_mismatch("not-a-number", stream) is True
        assert "not-a-number" in stream.getvalue()


class TestDefaultDbPath:
    def test_lands_under_a_ferry_app_data_dir(self) -> None:
        path = _default_db_path()
        assert path.name == "ferry.db"
        # The Electron shell computes the same location from its userData dir,
        # which electron-builder derives from productName (`ferry`).
        assert path.parent.name == "ferry"
