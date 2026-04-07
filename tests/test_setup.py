"""Tests for the Phase B setup command."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

from readaloud.setup import (
    SYSTEMD_UNIT_TEMPLATE,
    _hotkey_walkthrough,
    _render_unit,
    _resolve_binary,
    _systemd_quote,
    _systemd_user_dir,
    run_setup,
)


def test_systemd_unit_template_has_required_lines():
    rendered = _render_unit(Path("/fake/path/readaloud"))
    assert 'ExecStart="/fake/path/readaloud" daemon' in rendered
    assert "UnsetEnvironment=PYTHONPATH" in rendered  # scrubs ROS/etc pollution
    assert "Restart=on-failure" in rendered
    assert "TimeoutStopSec=10" in rendered
    assert "[Install]" in rendered


def test_systemd_unit_handles_paths_with_spaces():
    rendered = _render_unit(Path("/home/me/My Projects/venv/bin/readaloud"))
    assert 'ExecStart="/home/me/My Projects/venv/bin/readaloud" daemon' in rendered


def test_systemd_quote_escapes_backslashes_and_quotes():
    assert _systemd_quote('/tmp/x') == '"/tmp/x"'
    assert _systemd_quote('/tmp/a b') == '"/tmp/a b"'
    assert _systemd_quote('/tmp/a"b') == '"/tmp/a\\"b"'
    assert _systemd_quote('/tmp/a\\b') == '"/tmp/a\\\\b"'


def test_resolve_binary_uses_which(tmp_path: Path):
    fake = tmp_path / "readaloud"
    fake.write_text("")
    with patch("readaloud.setup.shutil.which", return_value=str(fake)):
        result = _resolve_binary()
    assert result == fake.resolve()


def test_resolve_binary_falls_back_to_sys_executable(tmp_path: Path, monkeypatch):
    # Create a fake venv layout with a `readaloud` sibling to sys.executable.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_python = bin_dir / "python"
    fake_python.write_text("")
    fake_readaloud = bin_dir / "readaloud"
    fake_readaloud.write_text("")

    monkeypatch.setattr(sys, "executable", str(fake_python))
    with patch("readaloud.setup.shutil.which", return_value=None):
        result = _resolve_binary()
    assert result == fake_readaloud


def test_resolve_binary_raises_when_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "executable", str(tmp_path / "nonexistent" / "python"))
    with patch("readaloud.setup.shutil.which", return_value=None):
        import pytest

        with pytest.raises(RuntimeError, match="Could not resolve"):
            _resolve_binary()


def test_hotkey_walkthrough_gnome(monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")
    with patch("readaloud.session.shutil.which", return_value="/usr/bin/wl-paste"):
        out = _hotkey_walkthrough(Path("/fake/readaloud"))
    assert "GNOME" in out
    assert "Custom Shortcut" in out
    assert "/fake/readaloud speak-selection" in out


def test_hotkey_walkthrough_kde(monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    with patch("readaloud.session.shutil.which", return_value="/usr/bin/xclip"):
        out = _hotkey_walkthrough(Path("/fake/readaloud"))
    assert "KDE" in out
    assert "/fake/readaloud speak-selection" in out


def test_systemd_user_dir_creates_path(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    d = _systemd_user_dir()
    assert d == tmp_path / "systemd" / "user"
    assert d.exists()
