"""Shared pytest fixtures for ferry tests."""

from __future__ import annotations

import pytest


@pytest.fixture
def tmp_data_dir(tmp_path: pytest.TempPathFactory) -> str:
    """Return a temporary directory path for test data."""
    return str(tmp_path)


@pytest.fixture(autouse=True)
def _pin_proxy_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin "auto" proxy generation to ffmpeg so mocked-ffmpeg tests stay
    deterministic on macOS, where "auto" would otherwise pick AVFoundation.
    AVFoundation tests opt back in by clearing or overriding the variable."""
    monkeypatch.setenv("FERRY_PROXY_BACKEND", "ffmpeg")
