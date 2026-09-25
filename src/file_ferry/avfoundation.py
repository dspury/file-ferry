"""The macOS proxy backend: AVFoundation, on the media engine.

ffmpeg's VideoToolbox hwaccel rejects H.264 High 4:2:2 10-bit (Sony XAVC S
4:2:2 — FX3, FX6, a7S III), so ffmpeg decodes it in software: measured on an
M4 Pro, ~200 CPU-seconds and ~60 s wall for a 95 s 4K clip, plus a CPU ProRes
encode. AVFoundation sends the same stream to the hardware decoder and the
ProRes encoder: the same clip to a 720p ProRes Proxy in 11 s wall and under
one second of CPU.

The work is done by `native/avproxy.swift`, compiled once per source revision
into the user cache with the Xcode command-line tools (`xcrun swiftc`) and
reused. No Python dependency is added; on a host without Swift, or not on
macOS, `available()` says why and the ffmpeg backend is used instead.
"""

from __future__ import annotations

import hashlib
import json
import platform
import shutil
import subprocess
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

#: ProRes variants the helper can encode, by file-ferry codec name.
CODECS: dict[str, str] = {
    "prores422proxy": "proxy",
    "prores422lt": "lt",
    "prores422": "422",
    "prores422hq": "hq",
    "prores4444": "4444",
}

_SOURCE = "avproxy.swift"


class AVFoundationError(RuntimeError):
    pass


def _source_bytes() -> bytes:
    return resources.files("file_ferry.native").joinpath(_SOURCE).read_bytes()


def _cache_dir() -> Path:
    return Path.home() / "Library" / "Caches" / "file-ferry"


@lru_cache(maxsize=1)
def helper() -> tuple[Path | None, str]:
    """(path to the compiled helper, reason) — path is None when unavailable."""
    if platform.system() != "Darwin":
        return None, "AVFoundation backend is macOS-only"
    source = _source_bytes()
    digest = hashlib.sha256(source).hexdigest()[:12]
    binary = _cache_dir() / f"ferry-avproxy-{digest}"
    if binary.is_file():
        return binary, "ok"
    compiler = (
        ["xcrun", "swiftc"]
        if shutil.which("xcrun")
        else (["swiftc"] if shutil.which("swiftc") else None)
    )
    if compiler is None:
        return None, "no Swift compiler (install the Xcode command-line tools)"
    binary.parent.mkdir(parents=True, exist_ok=True)
    src = binary.with_suffix(".swift")
    src.write_bytes(source)
    tmp = binary.with_suffix(".tmp")
    built = subprocess.run(
        [*compiler, "-O", "-o", str(tmp), str(src)], capture_output=True, text=True
    )
    if built.returncode != 0 or not tmp.is_file():
        first = next(
            (line for line in built.stderr.splitlines() if "error" in line), built.stderr[:200]
        )
        return None, f"could not compile the AVFoundation helper: {first}"
    tmp.replace(binary)
    return binary, "ok"


def available(codec: str) -> tuple[bool, str]:
    if codec.lower() not in CODECS:
        return False, f"codec {codec!r} is not a ProRes variant AVFoundation encodes"
    path, why = helper()
    return path is not None, why


def generate(
    source: Path, output: Path, *, codec: str, target_height: int, timecode: str | None
) -> dict[str, Any]:
    """Run the helper; return its JSON result. Raises AVFoundationError."""
    path, why = helper()
    if path is None:
        raise AVFoundationError(why)
    cmd = [
        str(path),
        "--in",
        str(source),
        "--out",
        str(output),
        "--height",
        str(target_height),
        "--codec",
        CODECS[codec.lower()],
    ]
    if timecode:
        cmd += ["--timecode", timecode]
    done = subprocess.run(cmd, capture_output=True, text=True)
    if done.returncode != 0:
        output.unlink(missing_ok=True)
        message = (done.stderr.strip().splitlines() or ["unknown error"])[-1]
        raise AVFoundationError(message)
    try:
        result: dict[str, Any] = json.loads(done.stdout.strip().splitlines()[-1])
        return result
    except (json.JSONDecodeError, IndexError) as exc:
        raise AVFoundationError(f"unreadable helper output: {done.stdout[:200]!r}") from exc
