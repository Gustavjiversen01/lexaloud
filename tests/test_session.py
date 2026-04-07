"""Tests for session detection."""

from __future__ import annotations

from unittest.mock import patch

from readaloud.session import SessionInfo, detect_session


def test_detect_wayland(monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")
    with patch("readaloud.session.shutil.which", side_effect=lambda cmd: f"/usr/bin/{cmd}"):
        info = detect_session()
    assert info.is_wayland
    assert not info.is_x11
    assert info.session_type == "wayland"
    assert info.desktop == "GNOME"
    assert info.wl_paste == "/usr/bin/wl-paste"
    assert info.xclip == "/usr/bin/xclip"
    assert info.notify_send == "/usr/bin/notify-send"


def test_detect_x11(monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    with patch("readaloud.session.shutil.which", return_value=None):
        info = detect_session()
    assert info.is_x11
    assert not info.is_wayland
    assert info.session_type == "x11"
    assert info.desktop == "KDE"
    assert info.wl_paste is None


def test_detect_unknown_session(monkeypatch):
    monkeypatch.delenv("XDG_SESSION_TYPE", raising=False)
    monkeypatch.delenv("XDG_CURRENT_DESKTOP", raising=False)
    monkeypatch.delenv("DESKTOP_SESSION", raising=False)
    with patch("readaloud.session.shutil.which", return_value=None):
        info = detect_session()
    assert info.session_type == "unknown"
    assert info.desktop == "unknown"
    assert not info.is_wayland
    assert not info.is_x11


def test_detect_weird_session_type_falls_back_to_unknown(monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "tty")
    with patch("readaloud.session.shutil.which", return_value=None):
        info = detect_session()
    assert info.session_type == "unknown"
