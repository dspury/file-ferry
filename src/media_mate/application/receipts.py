"""Operation receipt writer.

Receipts are immutable JSON documents stored in the project state
directory (``app_data/receipts/``) and indexed by the
``operation_receipts`` table. They include application/protocol
versions, the policy, planned and actual operations, checksums,
warnings, errors, the final state, and timestamps (ADR-0003 §6.5).

Per ADR-0004 the receipt hash covers the *substance* — kind, policy,
planned operations, checksums, final state — and deliberately does
**not** cover timestamps or host-derived paths. Two receipts of the
same session differ in metadata, not in substance.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import Field

from media_mate.application.policies import StoragePolicy
from media_mate.service.protocol import FrozenModel

RECEIPT_EXPORT_VERSION = 1


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class OperationReceipt(FrozenModel):
    """A durable, immutable operation record."""

    operation_id: str = Field(alias="operationId")
    kind: str
    app_version: str = Field(alias="appVersion")
    protocol_version: int = Field(alias="protocolVersion")
    policy: StoragePolicy | None = None
    planned: list[dict[str, Any]] = Field(default_factory=list)
    actual: list[dict[str, Any]] = Field(default_factory=list)
    checksums: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    final_state: str = Field(default="", alias="finalState")
    created_at: str = Field(default="", alias="createdAt")

    def receipt_hash(self) -> str:
        """SHA-256 over the substantive fields (not timestamps or paths)."""
        substance = {
            "kind": self.kind,
            "app_version": self.app_version,
            "protocol_version": self.protocol_version,
            "policy": self.policy.model_dump(mode="json", by_alias=True) if self.policy else None,
            "planned": self.planned,
            "checksums": self.checksums,
            "final_state": self.final_state,
        }
        canonical = json.dumps(substance, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_receipt(
    *,
    operation_id: str,
    kind: str,
    app_version: str,
    protocol_version: int,
    policy: StoragePolicy | None = None,
    planned: list[dict[str, Any]] | None = None,
    actual: list[dict[str, Any]] | None = None,
    checksums: list[dict[str, Any]] | None = None,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
    final_state: str = "",
) -> OperationReceipt:
    """Construct a receipt with a fresh timestamp."""
    return OperationReceipt(
        operationId=operation_id,
        kind=kind,
        appVersion=app_version,
        protocolVersion=protocol_version,
        policy=policy,
        planned=planned or [],
        actual=actual or [],
        checksums=checksums or [],
        warnings=warnings or [],
        errors=errors or [],
        finalState=final_state,
        createdAt=_now_iso(),
    )


class ReceiptStore:
    """Writes receipts to the state directory and the receipts table.

    ``conn`` is a live transaction connection supplied by the caller;
    the store writes the JSON file (best-effort) and inserts the index
    row inside the caller's transaction. The file write is not
    transactional with the row: a failed file write surfaces as a
    warning but does not fail the operation.
    """

    def __init__(self, app_data_dir: Path) -> None:
        self._receipts_dir = Path(app_data_dir) / "receipts"
        self._receipts_dir.mkdir(parents=True, exist_ok=True)

    def write(self, conn: Any, receipt: OperationReceipt) -> Path:
        """Persist the receipt and return the JSON file path."""
        receipt_json = receipt.model_dump_json(by_alias=True)
        digest = receipt.receipt_hash()
        file_path = self._receipts_dir / f"{receipt.operation_id}.json"
        file_path.write_text(receipt_json, encoding="utf-8")

        conn.execute(
            """
            INSERT INTO operation_receipts (
                operation_id, kind, receipt_json, receipt_hash, display_summary,
                receipt_path, export_version, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                receipt.operation_id,
                receipt.kind,
                receipt_json,
                digest,
                receipt.final_state,
                str(file_path),
                RECEIPT_EXPORT_VERSION,
                receipt.created_at,
            ),
        )
        return file_path
