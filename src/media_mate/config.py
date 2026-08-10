"""Configuration loader and persistence for media-mate.

Loads a media-mate.toml file into a MediaMateConfig pydantic model. When no
config file is found, returns MediaMateConfig() (all defaults).

Also owns the write-side: atomic TOML save that preserves comments and
unrelated layout, plus the target-path resolver used by both the CLI
and the Textual settings screen.
"""

from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path

from media_mate.models import MediaMateConfig


def load_config(path: Path | None = None) -> MediaMateConfig:
    """Load config from a TOML file.

    Search order:
    1. Explicit path argument (if provided)
    2. ./media-mate.toml
    3. ~/.media-mate/config.toml
    4. Defaults (MediaMateConfig())

    Missing files are not errors — defaults are returned.
    Invalid TOML raises ValueError so the CLI can surface it cleanly.
    """
    candidates: list[Path] = []
    if path is not None:
        candidates.append(path)
    else:
        candidates.append(Path.cwd() / "media-mate.toml")
        home_config = Path.home() / ".media-mate" / "config.toml"
        if home_config.is_file():
            candidates.append(home_config)

    for candidate in candidates:
        if candidate.is_file():
            with open(candidate, "rb") as f:
                data = tomllib.load(f)

            # Support a [proxy] sub-table in TOML as a convenience for the
            # proxy settings. Promote recognized keys to the top level (where
            # the model expects them) and pop the table so Pydantic's
            # extra="forbid" policy does not reject the leftover key.
            proxy_sub = data.pop("proxy", None)
            if isinstance(proxy_sub, dict):
                for key in ("proxy_codec", "proxy_height"):
                    if key in proxy_sub:
                        data.setdefault(key, proxy_sub[key])

            return MediaMateConfig.model_validate(data)

    return MediaMateConfig()


def config_target(explicit: Path | None) -> Path:
    """Resolve which config file to use when none is explicitly given.

    Search order:
    1. Explicit path argument (if provided)
    2. ./media-mate.toml (if it exists)
    3. ~/.media-mate/config.toml
    """
    if explicit:
        return explicit
    local = Path.cwd() / "media-mate.toml"
    return local if local.exists() else Path.home() / ".media-mate" / "config.toml"


def save_config(config: MediaMateConfig, path: Path) -> None:
    """Persist the existing TOML schema atomically while retaining comments."""

    def q(value: str) -> str:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

    values = {
        ("", "proxy_codec"): q(config.proxy_codec),
        ("", "proxy_height"): str(config.proxy_height),
        ("", "checksum_algo"): q(config.checksum_algo.value),
        ("", "resolve_path"): q(config.resolve_path) if config.resolve_path else None,
        ("", "ffmpeg_path"): q(config.ffmpeg_path) if config.ffmpeg_path else None,
        ("organize", "template"): q(config.organize.template),
        ("organize", "on_conflict"): q(config.organize.on_conflict),
        ("organize", "mode"): q(config.organize.mode),
    }
    content = (
        _merge_config_text(path.read_text(encoding="utf-8"), values)
        if path.exists()
        else _default_config_text(values)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def _default_config_text(values: dict[tuple[str, str], str | None]) -> str:
    lines = [
        f"proxy_codec = {values[('', 'proxy_codec')]}",
        f"proxy_height = {values[('', 'proxy_height')]}",
        f"checksum_algo = {values[('', 'checksum_algo')]}",
        f"resolve_path = {values[('', 'resolve_path')]}" if values[("", "resolve_path")] else "",
        f"ffmpeg_path = {values[('', 'ffmpeg_path')]}" if values[("", "ffmpeg_path")] else "",
        "",
        "[organize]",
        f"template = {values[('organize', 'template')]}",
        f"on_conflict = {values[('organize', 'on_conflict')]}",
        f"mode = {values[('organize', 'mode')]}",
        "",
    ]
    return "\n".join(line for line in lines if line != "") + "\n"


def _merge_config_text(existing: str, values: dict[tuple[str, str], str | None]) -> str:
    """Update known TOML values without discarding comments or unrelated layout."""
    if not existing.strip():
        return _default_config_text(values)

    section = ""
    seen: set[tuple[str, str]] = set()
    lines: list[str] = []
    section_re = re.compile(r"^\s*\[([^]]+)\]\s*(?:#.*)?$")
    assignment_re = re.compile(r"^(\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*=\s*)(.*?)(\s+#.*)?$")
    for line in existing.splitlines():
        section_match = section_re.match(line)
        if section_match:
            section = section_match.group(1)
            lines.append(line)
            continue
        assignment_match = assignment_re.match(line)
        if assignment_match:
            indent, key, equals, _old_value, inline_comment = assignment_match.groups()
            target = (section, key)
            if target in values:
                seen.add(target)
                value = values[target]
                if value is not None:
                    lines.append(f"{indent}{key}{equals}{value}{inline_comment or ''}")
                continue
        lines.append(line)

    missing_top = [
        f"{key} = {value}"
        for (section_name, key), value in values.items()
        if section_name == "" and value is not None and (section_name, key) not in seen
    ]
    first_section = next((i for i, line in enumerate(lines) if section_re.match(line)), len(lines))
    lines[first_section:first_section] = missing_top

    missing_organize = [
        f"{key} = {value}"
        for (section_name, key), value in values.items()
        if section_name == "organize" and value is not None and (section_name, key) not in seen
    ]
    if missing_organize:
        organize_start = next(
            (
                i
                for i, line in enumerate(lines)
                if section_re.match(line) and line.strip().startswith("[organize]")
            ),
            None,
        )
        if organize_start is None:
            if lines and lines[-1]:
                lines.append("")
            lines.extend(["[organize]", *missing_organize])
        else:
            organize_end = next(
                (i for i in range(organize_start + 1, len(lines)) if section_re.match(lines[i])),
                len(lines),
            )
            lines[organize_end:organize_end] = missing_organize
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "config_target",
    "load_config",
    "save_config",
]
