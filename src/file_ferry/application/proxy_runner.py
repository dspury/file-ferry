"""Proxy generation as a durable per-asset derivative job (plan §7.4).

Wraps the legacy ``file_ferry.proxy`` capability as a scheduler runner so
proxy generation is a durable job with per-asset derivative state and
progress events. Proxies are generated from the verified working replica
(plan §7.4). Every run writes an operation receipt, whatever its outcome.
The ``proxy_fn`` is injectable so tests do not require ffmpeg.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from file_ferry import APP_VERSION
from file_ferry.application.assets import AssetService
from file_ferry.application.derivatives import DerivativeService
from file_ferry.application.intake import IntakeService
from file_ferry.application.jobs import JobService
from file_ferry.application.receipts import ReceiptWriter, build_receipt
from file_ferry.application.scheduler import JobScheduler
from file_ferry.service.protocol import PROTOCOL_VERSION, JobDetail

ProxyFn = Callable[[str, str], object]

_log = logging.getLogger(__name__)

_PROXY_CODEC = "ProRes422Proxy"
_TARGET_HEIGHT = 1080

# Half of the receipts table's UNIQUE key, so a re-run of the same job
# supersedes its own previous receipt and not the offload's.
_RECEIPT_KIND = "proxy"


@dataclass
class _Attempt:
    """What one proxy run produced, accumulated for the receipt."""

    planned: list[dict[str, Any]] = field(default_factory=list)
    actual: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def default_proxy_fn(source_path: str, output_path: str) -> object:
    """Generate a proxy via the legacy ffmpeg capability."""
    from file_ferry.models import ProxyRequest
    from file_ferry.proxy import generate_proxy

    return generate_proxy(
        ProxyRequest(
            source_path=source_path,
            output_path=output_path,
            codec=_PROXY_CODEC,
            target_height=_TARGET_HEIGHT,
        )
    )


def settings_fingerprint(*, codec: str = _PROXY_CODEC, target_height: int = _TARGET_HEIGHT) -> str:
    canonical = f"{codec}|{target_height}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ProxyRunner:
    """A scheduler runner that generates proxies for a session's assets."""

    def __init__(
        self,
        assets: AssetService,
        derivatives: DerivativeService,
        intake: IntakeService,
        jobs: JobService,
        proxy_fn: ProxyFn | None = None,
        *,
        receipt_writer: ReceiptWriter | None = None,
    ) -> None:
        self._assets = assets
        self._derivatives = derivatives
        self._intake = intake
        self._jobs = jobs
        self._proxy_fn = proxy_fn or default_proxy_fn
        self._fp = settings_fingerprint()
        # Injected for the same reason as the offload runner's: writing a
        # receipt needs a database connection, and this runner is built
        # from services. No policy resolver -- a transcode has no
        # replication policy to be judged against.
        self._receipt_writer = receipt_writer

    def __call__(self, job: JobDetail, scheduler: JobScheduler) -> str:
        """Generate the session's proxies and write the run's receipt."""
        attempt = _Attempt()
        try:
            outcome = self._run(job, scheduler, attempt)
        except Exception as exc:
            attempt.errors.append(f"unexpected error: {exc}")
            self._write_receipt(job.id, attempt, "failed")
            raise
        self._write_receipt(job.id, attempt, outcome)
        return outcome

    def _run(self, job: JobDetail, scheduler: JobScheduler, attempt: _Attempt) -> str:
        if job.session_id is None:
            return self._fail(attempt, "job has no intake session")
        session = self._intake.get_session(job.session_id)
        if session.source_id is None:
            return self._fail(attempt, "intake session has no source")
        working_root = self._working_root(job.session_id)
        if working_root is None:
            return self._fail(attempt, "intake session has no working destination")

        assets = self._assets.list_by_source(session.source_id)
        if not assets:
            return "succeeded"  # nothing to proxy

        output_dir = working_root / "proxies"
        output_dir.mkdir(parents=True, exist_ok=True)

        # Insert every item before generating any of them. This runner used
        # to call `update_item_progress` without ever calling `add_item`, so
        # each update matched zero rows and a proxy job reported no progress
        # at all -- silently, because the helpers suppressed every exception
        # and an UPDATE that matches nothing is not an exception.
        for asset in assets:
            self._add_item(job.id, asset.id, asset.source_relative_path)
            attempt.planned.append({"relPath": asset.source_relative_path, "codec": _PROXY_CODEC})
        scheduler.notify_progress(job.id)

        for asset in assets:
            if scheduler.should_cancel(job.id):
                attempt.warnings.append("cancelled during proxy generation")
                return "cancelled"
            source_file = working_root / asset.source_relative_path
            output = output_dir / (Path(asset.source_relative_path).stem + "_proxy.mov")
            try:
                self._proxy_fn(str(source_file), str(output))
            except Exception as exc:
                self._record(asset.id, str(output), "failed", 0.0)
                self._mark_item_failed(job.id, asset.id)
                return self._fail(attempt, f"{asset.source_relative_path}: {exc}")
            self._record(asset.id, str(output), "ready", 1.0)
            attempt.actual.append(
                {"relPath": asset.source_relative_path, "outputPath": str(output)}
            )
            self._mark_item_done(job.id, asset.id)
            scheduler.notify_progress(job.id)
        return "succeeded"

    # ---- helpers -----------------------------------------------------

    def _working_root(self, session_id: str) -> Path | None:
        for dest in self._intake.get_destinations(session_id):
            if dest.kind == "working":
                return Path(dest.root_path)
        return None

    def _record(self, asset_id: str, output: str, status: str, readiness: float) -> None:
        self._derivatives.record(
            asset_id,
            kind="proxy",
            output_path=output,
            settings_fingerprint=self._fp,
            status=status,
            readiness=readiness,
        )

    def _add_item(self, job_id: str, asset_id: str, rel_path: str) -> None:
        # ffmpeg gives no usable byte count for the output, so an item is
        # weighted as one unit of work. Progress is therefore per file,
        # which is the honest granularity for transcoding.
        self._safely(
            "add item",
            self._jobs.add_item,
            job_id,
            step="proxy",
            asset_id=asset_id,
            source_path=rel_path,
            dest_path=rel_path,
            total_bytes=1,
        )

    def _mark_item_done(self, job_id: str, asset_id: str) -> None:
        self._safely(
            "item done",
            self._jobs.update_item_progress,
            job_id,
            asset_id,
            byte_progress=1,
            state="succeeded",
        )

    def _mark_item_failed(self, job_id: str, asset_id: str) -> None:
        self._safely(
            "item failed",
            self._jobs.update_item_progress,
            job_id,
            asset_id,
            state="failed",
            error="proxy generation failed",
        )

    @staticmethod
    def _safely(what: str, fn: Callable[..., object], *args: object, **kwargs: object) -> None:
        """Record progress without letting it fail the job.

        A bare ``suppress(Exception)`` is how this runner spent its life
        updating rows it had never inserted -- nothing failed and nothing
        was recorded. Logging at debug keeps the same posture while
        leaving a trail when it does go wrong.
        """
        try:
            fn(*args, **kwargs)
        except Exception:  # pragma: no cover - progress is never load-bearing
            _log.debug("proxy could not record %s", what, exc_info=True)

    # ---- receipt -----------------------------------------------------

    @staticmethod
    def _fail(attempt: _Attempt, reason: str) -> str:
        _log.info("proxy job failed: %s", reason)
        attempt.errors.append(reason)
        return "failed"

    def _write_receipt(self, job_id: str, attempt: _Attempt, final_state: str) -> None:
        """Persist this run's receipt (best-effort, as with the offload)."""
        writer = self._receipt_writer
        if writer is None:
            return
        try:
            writer(
                build_receipt(
                    operation_id=job_id,
                    kind=_RECEIPT_KIND,
                    app_version=APP_VERSION,
                    protocol_version=PROTOCOL_VERSION,
                    planned=attempt.planned,
                    actual=attempt.actual,
                    warnings=attempt.warnings,
                    errors=attempt.errors,
                    final_state=final_state,
                )
            )
        except Exception:
            _log.warning(
                "proxy job %s finished %s but its receipt could not be written",
                job_id,
                final_state,
                exc_info=True,
            )
