"""Tests for config.toml loader."""

from __future__ import annotations

from pathlib import Path

from lexaloud.config import Config, load_config


def test_load_config_missing_file_returns_defaults(tmp_path: Path):
    cfg = load_config(tmp_path / "nonexistent.toml")
    assert isinstance(cfg, Config)
    assert cfg.capture.max_bytes == 200 * 1024
    assert cfg.daemon.host == "127.0.0.1"
    assert cfg.daemon.port == 5487
    assert cfg.provider.voice == "af_heart"
    assert cfg.provider.lang == "en-us"
    assert cfg.provider.speed == 1.0
    assert cfg.preprocessor.strip_numeric_bracket_citations is True
    assert cfg.preprocessor.strip_parenthetical_citations is False


def test_load_config_speed_override(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        """
[provider]
voice = "af_bella"
speed = 1.15
""".strip()
    )
    cfg = load_config(path)
    assert cfg.provider.voice == "af_bella"
    assert cfg.provider.speed == 1.15
    # Unchanged
    assert cfg.provider.lang == "en-us"


def test_load_config_partial_override(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        """
[daemon]
port = 9999

[provider]
voice = "bf_emma"
""".strip()
    )
    cfg = load_config(path)
    assert cfg.daemon.port == 9999
    # Unchanged defaults
    assert cfg.daemon.host == "127.0.0.1"
    assert cfg.provider.voice == "bf_emma"
    assert cfg.provider.lang == "en-us"


def test_load_config_unknown_keys_ignored(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        """
[daemon]
nonexistent_key = "value"
port = 8080
""".strip()
    )
    # Should not raise, should pick up known key and ignore the other.
    cfg = load_config(path)
    assert cfg.daemon.port == 8080


def test_load_config_loads_preprocessor_section(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        """
[preprocessor]
strip_parenthetical_citations = true
""".strip()
    )
    cfg = load_config(path)
    assert cfg.preprocessor.strip_parenthetical_citations is True


def test_load_config_capture_section(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        """
[capture]
max_bytes = 1000
subprocess_timeout_s = 5.0
""".strip()
    )
    cfg = load_config(path)
    assert cfg.capture.max_bytes == 1000
    assert cfg.capture.subprocess_timeout_s == 5.0
