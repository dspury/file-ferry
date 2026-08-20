"""Migration 003 — safe-to-format volume-fingerprint capture.

Adds ``volume_fingerprint_at_scan`` to ``intake_sessions`` so that
ADR-0004 condition (4) ("no uncertain warning is open: e.g., a peer
sidecar noted the source's volume fingerprint changed since the scan
began") can be evaluated. The pure gate already supports the
``uncertain_warning`` parameter; this migration makes the data
available to feed it.

The column is nullable for sessions created before this migration
ran (the comparison degrades to "no scan-time fingerprint, cannot
prove no change" — the gate stays at its pre-PR behavior for legacy
sessions, and new sessions get the real check on first evaluate).

See ADR-0004 (safe-to-format policy).
"""

from __future__ import annotations

import sqlite3

VERSION = 3


def upgrade(conn: sqlite3.Connection) -> None:
    """Add the scan-time fingerprint column. Idempotent."""
    # SQLite >= 3.35 supports IF NOT EXISTS on ADD COLUMN; older
    # versions raise a duplicate-column error. We tolerate that
    # because the runner invokes us at most once per version.
    try:
        conn.execute(
            "ALTER TABLE intake_sessions "
            "ADD COLUMN volume_fingerprint_at_scan TEXT"
        )
    except sqlite3.OperationalError as exc:
        msg = str(exc).lower()
        if "duplicate column" in msg:
            return
        raise


def downgrade(conn: sqlite3.Connection) -> None:
    """Drop the scan-time fingerprint column.

    Requires SQLite >= 3.35 (DROP COLUMN was added in that release).
    The runner only invokes this in development; production rollbacks
    follow ADR-0003 and are out of scope for a single migration.
    """
    conn.execute("ALTER TABLE intake_sessions DROP COLUMN volume_fingerprint_at_scan")
