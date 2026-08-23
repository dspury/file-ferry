"""Proxy generation as a durable per-asset derivative job (plan §7.4).

Wraps the legacy ``file_ferry.proxy`` capability as a scheduler runner so
proxy generation is a durable job with per-asset derivative state and
progress events. Proxies are generated from the verified working replica
(plan §7.4). The ``proxy_fn`` is injectable so tests do not require
ffmpeg.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

from file_ferry.application.assets import AssetService
from file_ferry.application.derivatives import DerivativeService
from file_ferry.application.intake import IntakeService
from file_ferry.application.jobs import JobService
from file_ferry.application.scheduler import JobScheduler
from file_ferry.service.protocol import JobDetail

ProxyFn = Callable[[str, str], object]

_PROXY_CODEC = "ProRes422Proxy"
_TARGET_HEIGHT = 1080


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
    ) -> None:
        self._assets = assets
        self._derivatives = derivatives
        self._intake = intake
        self._jobs = jobs
        self._proxy_fn = proxy_fn or default_proxy_fn
        self._fp = settings_fingerprint()

    def __call__(self, job: JobDetail, scheduler: JobScheduler) -> str:
        if job.session_id is None:
            return "failed"
        session = self._intake.get_session(job.session_id)
        if session.source_id is None:
            return "failed"
        working_root = self._working_root(job.session_id)
        if working_root is None:
            return "failed"

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
        scheduler.notify_progress(job.id)

        for asset in assets:
            if scheduler.should_cancel(job.id):
                return "cancelled"
            source_file = working_root / asset.source_relative_path
            output = output_dir / (Path(asset.source_relative_path).stem + "_proxy.mov")
            try:
                self._proxy_fn(str(source_file), str(output))
            except Exception:
                self._record(asset.id, str(output), "failed", 0.0)
                self._mark_item_failed(job.id, asset.id)
                return "failed"
            self._record(asset.id, str(output), "ready", 1.0)
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
        with suppress(Exception):
            # ffmpeg gives no usable byte count for the output, so an item is
            # weighted as one unit of work. Progress is therefore per file,
            # which is the honest granularity for transcoding.
            self._jobs.add_item(
                job_id,
                step="proxy",
                asset_id=asset_id,
                source_path=rel_path,
                dest_path=rel_path,
                total_bytes=1,
            )

    def _mark_item_done(self, job_id: str, asset_id: str) -> None:
        with suppress(Exception):
            self._jobs.update_item_progress(job_id, asset_id, byte_progress=1, state="succeeded")

    def _mark_item_failed(self, job_id: str, asset_id: str) -> None:
        with suppress(Exception):
            self._jobs.update_item_progress(
                job_id, asset_id, state="failed", error="proxy generation failed"
            )
