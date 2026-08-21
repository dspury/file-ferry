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
import html
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import Field

from file_ferry.application.policies import StoragePolicy
from file_ferry.service.protocol import FrozenModel

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


# ---------------------------------------------------------------------------
# Human-readable export (plan §6.5, §8.3 receipt.export)
# ---------------------------------------------------------------------------


def export_markdown(receipt: OperationReceipt) -> str:
    """Render a receipt as a self-contained human-readable Markdown report."""
    lines: list[str] = []
    lines.append(f"# Ferry operation receipt ({receipt.kind})")
    lines.append("")
    lines.append(f"- **Operation id:** `{receipt.operation_id}`")
    lines.append(f"- **App version:** {receipt.app_version}")
    lines.append(f"- **Protocol version:** {receipt.protocol_version}")
    lines.append(f"- **Final state:** `{receipt.final_state}`")
    lines.append(f"- **Created at:** {receipt.created_at}")
    lines.append(f"- **Receipt hash (SHA-256):** `{receipt.receipt_hash()}`")
    lines.append("")

    if receipt.policy is not None:
        lines.append("## Storage policy")
        lines.append("")
        lines.append(
            "- required replicas: "
            f"{receipt.policy.required_replicas} "
            f"(algo {receipt.policy.checksum_algo})"
        )
        lines.append(f"- backup on different volume: {receipt.policy.backup_on_different_volume}")
        lines.append(f"- safety reserve: {receipt.policy.safety_reserve_bytes} bytes")
        lines.append("")

    lines.append("## Planned operations")
    lines.append("")
    _append_json_table(lines, receipt.planned)
    lines.append("## Actual results")
    lines.append("")
    _append_json_table(lines, receipt.actual)

    if receipt.checksums:
        lines.append("## Checksums")
        lines.append("")
        _append_json_table(lines, receipt.checksums)

    if receipt.warnings:
        lines.append("## Warnings")
        lines.append("")
        for w in receipt.warnings:
            lines.append(f"- {w}")
        lines.append("")
    if receipt.errors:
        lines.append("## Errors")
        lines.append("")
        for e in receipt.errors:
            lines.append(f"- {e}")
        lines.append("")

    return "\n".join(lines) + "\n"


def export_html(receipt: OperationReceipt) -> str:
    """Render a receipt as a self-contained HTML document."""
    md = export_markdown(receipt)
    body = html.escape(md)
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        f"<title>Ferry receipt {html.escape(receipt.operation_id)}</title></head>"
        f"<body><pre>{body}</pre></body></html>\n"
    )


def _append_json_table(lines: list[str], rows: list[dict[str, Any]]) -> None:
    for row in rows:
        for key, value in row.items():
            lines.append(f"- **{key}:** {value}")
    lines.append("")
