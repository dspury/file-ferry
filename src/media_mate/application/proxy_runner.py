"""Proxy generation as a durable per-asset derivative job (plan §7.4).

Wraps the legacy ``media_mate.proxy`` capability as a scheduler runner so
proxy generation is a durable job with per-asset derivative state and
progress events. Proxies are generated from the verified working replica
(plan §7.4). The ``proxy_fn`` is injectable so tests do not require
ffmpeg.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

from media_mate.application.assets import AssetService
from media_mate.application.derivatives import DerivativeService
from media_mate.application.intake import IntakeService
from media_mate.application.jobs import JobService
from media_mate.application.scheduler import JobScheduler
from media_mate.service.protocol import JobDetail

ProxyFn = Callable[[str, str], object]

_PROXY_CODEC = "ProRes422Proxy"
_TARGET_HEIGHT = 1080


def default_proxy_fn(source_path: str, output_path: str) -> object:
    """Generate a proxy via the legacy ffmpeg capability."""
    from media_mate.models import ProxyRequest
    from media_mate.proxy import generate_proxy

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

    def _mark_item_done(self, job_id: str, asset_id: str) -> None:
        from contextlib import suppress

        with suppress(Exception):
            self._jobs.update_item_progress(job_id, asset_id, byte_progress=1, state="succeeded")

    def _mark_item_failed(self, job_id: str, asset_id: str) -> None:
        from contextlib import suppress

        with suppress(Exception):
            self._jobs.update_item_progress(
                job_id, asset_id, state="failed", error="proxy generation failed"
            )
