"""Migration 006 — publish strategy and the fallback reservation (#211).

Adds the two columns the reserve-then-rename publish fallback needs to be
durable and crash-recoverable:

- ``transfer_executions.publish_strategy``: which primitive this run uses
  for the whole destination — ``link`` (the default, atomic) or
  ``reserve_rename`` (the fallback for a filesystem that refuses hard
  links). Chosen once per destination by probing the operation, and read
  back into the receipt so a fallback-published destination is
  identifiable after the fact.
- ``transfer_execution_items.reservation_path``: under the fallback, the
  final name this execution reserved with ``O_CREAT | O_EXCL`` before the
  bytes moved. Recorded before the reservation is created, the same way
  ``temp_path`` is, so startup recovery can find a zero-byte reservation
  a crash left at the destination and remove it instead of letting the
  next attempt collide with its own leftover.

Both are additive and nullable; existing rows read as unset, which means
"link", the behavior they already had. Downgrade drops the columns.
"""

from __future__ import annotations

import sqlite3

VERSION = 6

_UPGRADE_DDL = """
ALTER TABLE transfer_executions ADD COLUMN publish_strategy TEXT;
ALTER TABLE transfer_execution_items ADD COLUMN reservation_path TEXT;
"""

_DOWNGRADE_DDL = """
ALTER TABLE transfer_execution_items DROP COLUMN reservation_path;
ALTER TABLE transfer_executions DROP COLUMN publish_strategy;
"""


def upgrade(conn: sqlite3.Connection) -> None:
    conn.executescript(_UPGRADE_DDL)


def downgrade(conn: sqlite3.Connection) -> None:
    conn.executescript(_DOWNGRADE_DDL)
