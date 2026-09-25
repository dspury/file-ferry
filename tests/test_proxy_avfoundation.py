"""The AVFoundation proxy backend: selection, fallback, and real encodes.

The real-encode tests use a synthetic H.264 High 4:2:2 10-bit clip — the
format Sony XAVC S 4:2:2 cameras record and ffmpeg cannot hardware-decode —
and run only on macOS with ffmpeg and a Swift compiler present.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from file_ferry import avfoundation
from file_ferry.models import ProxyRequest
from file_ferry.probe import probe_file
from file_ferry.proxy import ProxyError, generate_proxy, resolve_backend


def _request(tmp_path: Path, **kw) -> ProxyRequest:
    src = tmp_path / "in.mp4"
    src.write_bytes(b"x")
    return ProxyRequest(source_path=str(src), output_path=str(tmp_path / "out.mov"), **kw)


# ── selection ─────────────────────────────────────────────────────────


def test_explicit_backend_is_honoured(tmp_path, monkeypatch):
    monkeypatch.delenv("FERRY_PROXY_BACKEND", raising=False)
    assert resolve_backend(_request(tmp_path, backend="ffmpeg")) == ("ffmpeg", None)
    assert resolve_backend(_request(tmp_path, backend="avfoundation")) == ("avfoundation", None)


def test_auto_prefers_avfoundation_when_available(tmp_path, monkeypatch):
    monkeypatch.delenv("FERRY_PROXY_BACKEND", raising=False)
    with patch.object(avfoundation, "available", return_value=(True, "ok")):
        assert resolve_backend(_request(tmp_path)) == ("avfoundation", None)
    with patch.object(avfoundation, "available", return_value=(False, "macOS-only")):
        assert resolve_backend(_request(tmp_path)) == ("ffmpeg", "macOS-only")


def test_environment_overrides_auto_only(tmp_path, monkeypatch):
    monkeypatch.setenv("FERRY_PROXY_BACKEND", "ffmpeg")
    assert resolve_backend(_request(tmp_path))[0] == "ffmpeg"
    assert resolve_backend(_request(tmp_path, backend="avfoundation"))[0] == "avfoundation"


def test_unknown_backend_is_an_error(tmp_path):
    with pytest.raises(ProxyError):
        resolve_backend(_request(tmp_path, backend="gpu"))


def test_non_prores_codec_is_not_avfoundation():
    ok, why = avfoundation.available("DNxHR")
    assert not ok and "ProRes" in why


def test_auto_falls_back_to_ffmpeg_and_says_so(tmp_path, monkeypatch):
    monkeypatch.delenv("FERRY_PROXY_BACKEND", raising=False)
    request = _request(tmp_path)

    def fake_ffmpeg(cmd, **kwargs):
        Path(cmd[-1]).write_bytes(b"prores")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    with (
        patch.object(avfoundation, "available", return_value=(True, "ok")),
        patch.object(avfoundation, "generate", side_effect=avfoundation.AVFoundationError("boom")),
        patch("file_ferry.proxy.find_ffmpeg", return_value="/usr/bin/ffmpeg"),
        patch("file_ferry.proxy.subprocess.run", side_effect=fake_ffmpeg),
        patch("file_ferry.proxy._probe_output_metadata", return_value=(1280, 720, 1.0)),
    ):
        result = generate_proxy(request)
    assert result.backend == "ffmpeg"
    assert "AVFoundation failed" in (result.note or "")


def test_explicit_avfoundation_failure_is_not_hidden(tmp_path, monkeypatch):
    request = _request(tmp_path, backend="avfoundation")
    with (
        patch.object(avfoundation, "generate", side_effect=avfoundation.AVFoundationError("boom")),
        pytest.raises(ProxyError, match="AVFoundation: boom"),
    ):
        generate_proxy(request)


# ── real encodes ──────────────────────────────────────────────────────

needs_mac_media = pytest.mark.skipif(
    platform.system() != "Darwin"
    or shutil.which("ffmpeg") is None
    or avfoundation.helper()[0] is None,
    reason="needs macOS, ffmpeg and a Swift compiler",
)


def _xavc_like(path: Path, *, timecode: str | None) -> Path:
    """H.264 High 4:2:2 10-bit, 4 s, 1920x1080 29.97, stereo PCM."""
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=duration=4:size=1920x1080:rate=30000/1001",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=4:sample_rate=48000",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv422p10le",
        "-profile:v",
        "high422",
        "-c:a",
        "pcm_s16le",
        "-ac",
        "2",
    ]
    if timecode:
        cmd += ["-timecode", timecode]
    subprocess.run([*cmd, str(path)], check=True, capture_output=True)
    return path


def _streams(path: Path) -> str:
    return subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_name,profile,width,height,channels:stream_tags=timecode",
            "-of",
            "compact",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


@needs_mac_media
def test_real_encode_copies_a_source_timecode_track(tmp_path):
    src = _xavc_like(tmp_path / "A001.mov", timecode="11:22:01:12")
    out = tmp_path / "proxy" / "A001.mov"
    result = generate_proxy(
        ProxyRequest(
            source_path=str(src),
            output_path=str(out),
            target_height=720,
            backend="avfoundation",
            probe=probe_file(src),
        )
    )
    assert result.backend == "avfoundation"
    assert (result.width, result.height) == (1280, 720)
    streams = _streams(out)
    assert "codec_name=prores|profile=Proxy" in streams
    assert "timecode=11:22:01:12" in streams
    assert "channels=2" in streams


@needs_mac_media
def test_real_encode_writes_timecode_the_source_only_declares(tmp_path):
    """Sony MP4s carry timecode in `rtmd`, which AVFoundation cannot read:
    the probed label must become a real timecode track in the proxy."""
    src = _xavc_like(tmp_path / "C001.mp4", timecode=None)
    probe = probe_file(src).model_copy(update={"timecode": "19:27:49:10"})
    out = tmp_path / "C001.mov"
    generate_proxy(
        ProxyRequest(
            source_path=str(src),
            output_path=str(out),
            target_height=720,
            backend="avfoundation",
            probe=probe,
        )
    )
    assert "timecode=19:27:49:10" in _streams(out)
    duration = float(
        subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                str(out),
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )
    assert duration == pytest.approx(4.0, abs=0.05)
