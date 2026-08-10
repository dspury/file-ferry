"""Configuration loader and persistence for media-mate.

Loads a media-mate.toml file into a MediaMateConfig pydantic model. When no
config file is found, returns MediaMateConfig() (all defaults).

Also owns the write-side: atomic TOML save that preserves comments and
unrelated layout, plus the target-path resolver used by both the CLI
and the Textual settings screen.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

import tomlkit

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
    if explicit:
        return explicit
    local = Path.cwd() / "media-mate.toml"
    return local if local.exists() else Path.home() / ".media-mate" / "config.toml"


def save_config(config: MediaMateConfig, path: Path) -> None:
    """Persist the existing TOML schema atomically while retaining comments.

    Uses tomlkit so that comments, whitespace, and unrelated layout in
    the user's existing config file are preserved across saves.
    """

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


def _coerce_toml_value(raw: str) -> object:
    """Re-parse a string-encoded TOML value into its native Python type.

    Used after `_save_config`'s stringification round-trip so the
    document written by `_default_config_text` matches what
    `_merge_config_text` would have produced from a real TOML parse.

    `raw` is always quoted (the caller wraps strings in `"…"`), so
    a single-line `tomllib.loads(f'_ = {raw}\\n')` is sufficient for
    the flat values we use today.
    """
    parsed = tomllib.loads(f"_ = {raw}\n")["_"]
    return parsed


def _default_config_text(values: dict[tuple[str, str], str | None]) -> str:
    """Render a fresh TOML document for a fresh config file."""
    doc = tomlkit.document()
    for (section, key), raw in values.items():
        if raw is None:
            continue
        value = _coerce_toml_value(raw)
        if section:
            if section not in doc:
                doc[section] = tomlkit.table()
            doc[section][key] = value
        else:
            doc[key] = value
    return tomlkit.dumps(doc)


def _merge_config_text(existing: str, values: dict[tuple[str, str], str | None]) -> str:
    """Update known TOML values without discarding comments or unrelated layout.

    Uses tomlkit to parse `existing` into a mutable document, writes
    each entry in `values` to its (section, key), and emits the
    resulting document as a string. Comments and unknown layout are
    preserved by tomlkit's round-trip machinery.

    Values mapped to `None` are *removed* from the document. This
    matches the prior regex-based behavior, which treated `None` as
    "delete this key."
    """
    if not existing.strip():
        return _default_config_text(values)

    doc = tomlkit.parse(existing)
    for (section, key), raw in values.items():
        if raw is None:
            if section and section in doc and key in doc[section]:
                del doc[section][key]
            elif not section and key in doc:
                del doc[key]
            continue
        value = _coerce_toml_value(raw)
        if section:
            if section not in doc:
                doc[section] = tomlkit.table()
            doc[section][key] = value
        else:
            doc[key] = value
    return tomlkit.dumps(doc)


__all__ = [
    "config_target",
    "load_config",
    "save_config",
]
