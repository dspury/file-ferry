"""Audit service — the append-only event timeline.

:func:`record_event` is the only way events enter ``audit_events``. It
takes the caller's open connection so an event lands in the **same
transaction** as the state change it describes: the trail cannot claim
something that was rolled back, and it cannot silently omit something that
committed. Callers that are not already inside a transaction use
:meth:`AuditService.record` instead.

**Granularity: operations and state transitions, not files.** An offload of
a 2000-file card produces a handful of events (`job.created`,
`job.running`, `job.verifying`, `job.succeeded`, `receipt.written`) rather
than 2000 `replica.verified` rows. Per-file evidence already has two homes
that are built for it -- ``job_items`` for progress and the operation
receipt's ``checksums`` list for proof -- and duplicating it here would
make ``audit_events`` the largest table in the database while making the
timeline unreadable, which is the opposite of what it is for. So the
per-file offload path (:meth:`ReplicaService.record_verified`) stays
silent, while the operator-initiated ``replica.verify`` is recorded: it is
a deliberate act, one at a time.

Reads that can be repeated are not events either. ``intake.evaluate``
recomputes the safe-to-format gate on every call and persists nothing, so
recording it would flood the trail with the same determination; the events
that *change* the answer (destinations added, replicas verified, jobs
finishing) are recorded instead.

Legacy backfill (Package 2 step 4) links legacy audit history where the
evidence is unambiguous, and preserves everything else as legacy. A legacy
``runs`` row is *unambiguous* when it has a started timestamp and a command
(both NOT NULL in the legacy schema); we mirror it into ``audit_events``
with a ``run_id`` link and its command/status/error as data — we never
manufacture project facts. Runs already linked are skipped (idempotent).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from file_ferry.persistence.connection import transaction
from file_ferry.persistence.repositories import audit as audit_repo
from file_ferry.service.protocol import AuditEvent, ListAuditParams


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def record_event(
    conn: sqlite3.Connection,
    event_type: str,
    *,
    entity_type: str | None = None,
    entity_id: str | None = None,
    data: dict[str, Any] | None = None,
    actor: str | None = None,
    occurred_at: str | None = None,
    run_id: int | None = None,
) -> None:
    """Append one event to the timeline, on the caller's connection.

    Deliberately takes ``conn`` rather than a db path: the event is written
    inside whatever transaction the caller already holds, so it commits or
    rolls back with the state change it describes. ``audit_events`` has no
    constraint that a well-formed event can violate (``run_id`` is its only
    foreign key and defaults to NULL), so this failing means the database
    itself is failing -- in which case taking the state change down with it
    is correct, not collateral damage.

    ``data`` is serialised with sorted keys so two events describing the
    same facts are byte-identical, which keeps them diffable.
    """
    audit_repo.insert_event(
        conn,
        audit_repo.AuditEventRow(
            id=0,
            occurred_at=occurred_at or _now_iso(),
            actor=actor,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            data=json.dumps(data, sort_keys=True) if data is not None else None,
            run_id=run_id,
        ),
    )


class AuditService:
    """Read audit events and backfill unambiguous legacy runs."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)

    def record(
        self,
        event_type: str,
        *,
        entity_type: str | None = None,
        entity_id: str | None = None,
        data: dict[str, Any] | None = None,
        actor: str | None = None,
    ) -> None:
        """Append one event in its own transaction.

        For callers that are not already holding a connection. Anything
        that *is* mid-transaction should call :func:`record_event` directly
        so the event shares that transaction's fate.
        """
        with transaction(self._db_path) as conn:
            record_event(
                conn,
                event_type,
                entity_type=entity_type,
                entity_id=entity_id,
                data=data,
                actor=actor,
            )

    def backfill_legacy(self) -> int:
        """Mirror every un-linked legacy ``runs`` row into ``audit_events``.

        Returns the number of runs linked. Idempotent: re-running links
        only the runs not yet linked.
        """
        count = 0
        with transaction(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT r.* FROM runs r
                WHERE NOT EXISTS (SELECT 1 FROM audit_events a WHERE a.run_id = r.id)
                """
            ).fetchall()
            for run in rows:
                data = {"command": run["command"]}
                if run["status"] is not None:
                    data["status"] = run["status"]
                if run["config_hash"] is not None:
                    data["config_hash"] = run["config_hash"]
                if run["error"] is not None:
                    data["error"] = run["error"]
                record_event(
                    conn,
                    f"run.{run['status'] or 'unknown'}",
                    entity_type="run",
                    entity_id=str(run["id"]),
                    data=data,
                    occurred_at=run["started_at"] or _now_iso(),
                    run_id=run["id"],
                )
                count += 1
        return count

    def list(self, params: ListAuditParams) -> list[AuditEvent]:
        with transaction(self._db_path) as conn:
            rows = audit_repo.list_events(conn, params.entity_id, params.limit)
        out: list[AuditEvent] = []
        for r in rows:
            try:
                data = json.loads(r.data) if r.data else None
            except json.JSONDecodeError:
                data = None
            out.append(
                AuditEvent(
                    id=r.id,
                    occurredAt=r.occurred_at,
                    eventType=r.event_type,
                    entityType=r.entity_type,
                    entityId=r.entity_id,
                    data=data,
                    runId=r.run_id,
                )
            )
        return out
