"""Audit service — append-only events and legacy ``runs`` backfill.

Package 2 step 4: link legacy audit history where evidence is
unambiguous, and preserve everything else as legacy. A legacy ``runs``
row is *unambiguous* when it has a started timestamp and a command
(both NOT NULL in the legacy schema); we mirror it into ``audit_events``
with a ``run_id`` link and its command/status/error as data — we never
manufacture project facts. Runs already linked are skipped (idempotent).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from file_ferry.persistence.connection import transaction
from file_ferry.persistence.repositories import audit as audit_repo
from file_ferry.service.protocol import AuditEvent, ListAuditParams


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class AuditService:
    """Read audit events and backfill unambiguous legacy runs."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)

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
                import json

                audit_repo.insert_event(
                    conn,
                    audit_repo.AuditEventRow(
                        id=0,
                        occurred_at=run["started_at"] or _now_iso(),
                        actor=None,
                        event_type=f"run.{run['status'] or 'unknown'}",
                        entity_type="run",
                        entity_id=str(run["id"]),
                        data=json.dumps(data, sort_keys=True),
                        run_id=run["id"],
                    ),
                )
                count += 1
        return count

    def list(self, params: ListAuditParams) -> list[AuditEvent]:
        with transaction(self._db_path) as conn:
            rows = audit_repo.list_events(conn, params.entity_id, params.limit)
        out: list[AuditEvent] = []
        for r in rows:
            import json

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
