"""Tests for the Phase B setup command."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

from lexaloud.setup import (
    SYSTEMD_UNIT_TEMPLATE,
    _hotkey_walkthrough,
    _render_unit,
    _resolve_binary,
    _systemd_quote,
    _systemd_user_dir,
    run_setup,
)


def test_systemd_unit_template_has_required_lines():
    rendered = _render_unit(Path("/fake/path/lexaloud"))
    assert 'ExecStart="/fake/path/lexaloud" daemon' in rendered
    assert "UnsetEnvironment=PYTHONPATH" in rendered  # scrubs ROS/etc pollution
    assert "Restart=on-failure" in rendered
    assert "TimeoutStopSec=10" in rendered
    assert "[Install]" in rendered


def test_systemd_unit_handles_paths_with_spaces():
    rendered = _render_unit(Path("/home/me/My Projects/venv/bin/lexaloud"))
    assert 'ExecStart="/home/me/My Projects/venv/bin/lexaloud" daemon' in rendered


def test_systemd_quote_escapes_backslashes_and_quotes():
    assert _systemd_quote('/tmp/x') == '"/tmp/x"'
    assert _systemd_quote('/tmp/a b') == '"/tmp/a b"'
    assert _systemd_quote('/tmp/a"b') == '"/tmp/a\\"b"'
    assert _systemd_quote('/tmp/a\\b') == '"/tmp/a\\\\b"'


def test_resolve_binary_uses_which(tmp_path: Path):
    fake = tmp_path / "lexaloud"
    fake.write_text("")
    with patch("lexaloud.setup.shutil.which", return_value=str(fake)):
        result = _resolve_binary()
    assert result == fake.resolve()


def test_resolve_binary_falls_back_to_sys_executable(tmp_path: Path, monkeypatch):
    # Create a fake venv layout with a `lexaloud` sibling to sys.executable.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_python = bin_dir / "python"
    fake_python.write_text("")
    fake_lexaloud = bin_dir / "lexaloud"
    fake_lexaloud.write_text("")

    monkeypatch.setattr(sys, "executable", str(fake_python))
    with patch("lexaloud.setup.shutil.which", return_value=None):
        result = _resolve_binary()
    assert result == fake_lexaloud


def test_resolve_binary_does_not_follow_venv_python_symlink(
    tmp_path: Path, monkeypatch
):
    """Regression: in a venv, sys.executable is a symlink to the system python
    (e.g. /usr/bin/python3). _resolve_binary must NOT .resolve() it, otherwise
    it looks for /usr/bin/lexaloud instead of the venv's bin dir.
    """
    venv_bin = tmp_path / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    system_bin = tmp_path / "system"
    system_bin.mkdir()
    system_python = system_bin / "python3"
    system_python.write_text("")
    venv_python = venv_bin / "python"
    venv_python.symlink_to(system_python)
    venv_lexaloud = venv_bin / "lexaloud"
    venv_lexaloud.write_text("")

    monkeypatch.setattr(sys, "executable", str(venv_python))
    with patch("lexaloud.setup.shutil.which", return_value=None):
        result = _resolve_binary()
    assert result == venv_lexaloud


def test_resolve_binary_raises_when_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "executable", str(tmp_path / "nonexistent" / "python"))
    with patch("lexaloud.setup.shutil.which", return_value=None):
        import pytest

        with pytest.raises(RuntimeError, match="Could not resolve"):
            _resolve_binary()


def test_hotkey_walkthrough_gnome(monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")
    with patch("lexaloud.session.shutil.which", return_value="/usr/bin/wl-paste"):
        out = _hotkey_walkthrough(Path("/fake/lexaloud"))
    assert "GNOME" in out
    assert "Custom Shortcut" in out
    assert "/fake/lexaloud speak-selection" in out


def test_hotkey_walkthrough_kde(monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    with patch("lexaloud.session.shutil.which", return_value="/usr/bin/xclip"):
        out = _hotkey_walkthrough(Path("/fake/lexaloud"))
    assert "KDE" in out
    assert "/fake/lexaloud speak-selection" in out


def test_systemd_user_dir_creates_path(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    d = _systemd_user_dir()
    assert d == tmp_path / "systemd" / "user"
    assert d.exists()
