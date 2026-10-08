"""Tests for the configuration loader in config.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from file_ferry.config import load_config
from file_ferry.models import ChecksumAlgo, FerryConfig


class TestLoadConfig:
    def test_returns_defaults_when_no_file(self, tmp_path: Path, monkeypatch) -> None:
        # Change cwd so ./ferry.toml doesn't accidentally exist
        monkeypatch.chdir(tmp_path)
        # And patch home so ~/.ferry/config.toml doesn't exist
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        cfg = load_config()
        assert isinstance(cfg, FerryConfig)
        assert cfg.proxy_codec == "ProRes422Proxy"
        assert cfg.proxy_height == 1080
        assert cfg.checksum_algo == ChecksumAlgo.XXHASH

    def test_loads_explicit_path(self, tmp_path: Path) -> None:
        path = tmp_path / "ferry.toml"
        path.write_text(
            """
proxy_codec = "ProRes422HQ"
proxy_height = 720
checksum_algo = "sha256"
"""
        )
        cfg = load_config(path)
        assert cfg.proxy_codec == "ProRes422HQ"
        assert cfg.proxy_height == 720
        assert cfg.checksum_algo == ChecksumAlgo.SHA256

    def test_loads_organize_section(self, tmp_path: Path) -> None:
        path = tmp_path / "ferry.toml"
        path.write_text(
            """
[organize]
template = "{root}/{filename}{ext}"
on_conflict = "rename"
"""
        )
        cfg = load_config(path)
        assert cfg.organize.template == "{root}/{filename}{ext}"
        assert cfg.organize.on_conflict == "rename"

    def test_loads_resolve_path(self, tmp_path: Path) -> None:
        path = tmp_path / "ferry.toml"
        path.write_text(
            """
resolve_path = "/Applications/DaVinci Resolve.app"
ffmpeg_path = "/opt/homebrew/bin/ffmpeg"
"""
        )
        cfg = load_config(path)
        assert cfg.resolve_path == "/Applications/DaVinci Resolve.app"
        assert cfg.ffmpeg_path == "/opt/homebrew/bin/ffmpeg"

    def test_extra_fields_rejected(self, tmp_path: Path) -> None:
        """FerryConfig has extra='forbid' so typos blow up."""
        path = tmp_path / "ferry.toml"
        path.write_text('unknown_field = "boom"\n')
        with pytest.raises(ValueError):
            load_config(path)

    def test_invalid_toml_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "ferry.toml"
        path.write_text("this is not valid = toml = syntax [[[")
        with pytest.raises(ValueError):
            load_config(path)

    def test_default_search_finds_cwd_config(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "ferry.toml").write_text("proxy_height = 540\n")
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "no-such-home")
        cfg = load_config()
        assert cfg.proxy_height == 540

    def test_default_search_finds_home_config(self, tmp_path: Path, monkeypatch) -> None:
        home = tmp_path / "home"
        home.mkdir()
        (home / ".ferry").mkdir()
        (home / ".ferry" / "config.toml").write_text("proxy_height = 480\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", lambda: home)
        cfg = load_config()
        assert cfg.proxy_height == 480

    def test_explicit_path_takes_precedence_over_cwd(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "ferry.toml").write_text("proxy_height = 100\n")
        explicit = tmp_path / "override.toml"
        explicit.write_text("proxy_height = 999\n")
        cfg = load_config(explicit)
        assert cfg.proxy_height == 999

    def test_invalid_enum_value_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "ferry.toml"
        path.write_text('checksum_algo = "not-a-real-algo"\n')
        with pytest.raises(ValueError):
            load_config(path)


class TestProxySubTable:
    """The [proxy] convenience sub-table must not bypass extra='forbid'.

    Regression cover for #236: the loader popped the whole table before
    validating, so unrecognized keys were discarded and a typo silently
    kept the default instead of erroring.
    """

    def test_recognized_subtable_keys_promoted(self, tmp_path: Path) -> None:
        path = tmp_path / "ferry.toml"
        path.write_text(
            """
[proxy]
proxy_codec = "H264"
proxy_height = 720
proxy_backend = "ffmpeg"
"""
        )
        cfg = load_config(path)
        assert cfg.proxy_codec == "H264"
        assert cfg.proxy_height == 720
        assert cfg.proxy_backend == "ffmpeg"

    def test_typo_under_proxy_rejected(self, tmp_path: Path) -> None:
        # The reported defect: this used to load with proxy_height=1080.
        path = tmp_path / "ferry.toml"
        path.write_text("[proxy]\nheigth = 720\n")
        with pytest.raises(ValueError):
            load_config(path)

    def test_unprefixed_backend_under_proxy_rejected(self, tmp_path: Path) -> None:
        # `backend` reads as though it works; the model wants proxy_backend.
        path = tmp_path / "ferry.toml"
        path.write_text('[proxy]\nbackend = "ffmpeg"\n')
        with pytest.raises(ValueError):
            load_config(path)

    def test_arbitrary_key_under_proxy_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "ferry.toml"
        path.write_text("[proxy]\nnonsense = 1\n")
        with pytest.raises(ValueError):
            load_config(path)

    def test_top_level_key_under_proxy_rejected(self, tmp_path: Path) -> None:
        # `organize` is a real field, but not under [proxy].
        path = tmp_path / "ferry.toml"
        path.write_text("[proxy]\norganize = 1\n")
        with pytest.raises(ValueError):
            load_config(path)

    def test_error_names_the_offending_key(self, tmp_path: Path) -> None:
        # A rejection that does not say which key is half a diagnostic.
        from pydantic import ValidationError

        path = tmp_path / "ferry.toml"
        path.write_text('[proxy]\nbackend = "ffmpeg"\n')
        with pytest.raises(ValidationError) as excinfo:
            load_config(path)
        locs = [str(loc) for err in excinfo.value.errors() for loc in err["loc"]]
        assert any("backend" in loc for loc in locs), locs

    def test_scalar_proxy_rejected(self, tmp_path: Path) -> None:
        # `proxy = 5` was popped and discarded for the same reason.
        path = tmp_path / "ferry.toml"
        path.write_text("proxy = 5\n")
        with pytest.raises(ValueError):
            load_config(path)

    def test_empty_proxy_table_is_fine(self, tmp_path: Path) -> None:
        path = tmp_path / "ferry.toml"
        path.write_text("[proxy]\n")
        cfg = load_config(path)
        assert cfg.proxy_height == 1080
        assert cfg.proxy_backend == "auto"

    def test_top_level_and_subtable_combine(self, tmp_path: Path) -> None:
        path = tmp_path / "ferry.toml"
        path.write_text(
            """
proxy_height = 720
[proxy]
proxy_backend = "ffmpeg"
"""
        )
        cfg = load_config(path)
        assert cfg.proxy_height == 720
        assert cfg.proxy_backend == "ffmpeg"
