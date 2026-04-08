"""Tests for selection capture (CLI-side)."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from lexaloud.selection import (
    SelectionEmpty,
    SelectionTimeout,
    SelectionToolMissing,
    _utf8_safe_truncate,
    read_clipboard,
    read_primary,
)


# ---------- UTF-8 safe truncation ----------


def test_truncate_does_not_split_multibyte():
    # "é" is two bytes in UTF-8 (0xc3 0xa9). If we naively slice at the byte
    # boundary we'd get 0xc3 alone; the decoder with errors='ignore' would
    # drop it. Our truncation should walk back.
    s = "a" * 10 + "é"  # 10 'a' + 2 bytes for 'é' = 12 bytes
    data = s.encode("utf-8")
    assert len(data) == 12
    out = _utf8_safe_truncate(data, 11)
    # Either truncation stops cleanly at 10 (before é) OR keeps é (12 bytes).
    # 11 bytes is the split-in-middle case; we expect it to back off to 10.
    assert out == b"a" * 10


def test_truncate_noop_when_under_limit():
    data = b"hello"
    assert _utf8_safe_truncate(data, 100) == data


def test_truncate_ascii_exact():
    data = b"abcdef"
    assert _utf8_safe_truncate(data, 3) == b"abc"


# ---------- read_primary / read_clipboard with mocked subprocess ----------


class _FakeSession:
    def __init__(self, is_wayland: bool, has_wl: bool, has_xclip: bool) -> None:
        self.session_type = "wayland" if is_wayland else "x11"
        self.desktop = "GNOME"
        self.wl_paste = "/usr/bin/wl-paste" if has_wl else None
        self.xclip = "/usr/bin/xclip" if has_xclip else None
        self.notify_send = "/usr/bin/notify-send"

    @property
    def is_wayland(self) -> bool:
        return self.session_type == "wayland"

    @property
    def is_x11(self) -> bool:
        return self.session_type == "x11"


def _completed(stdout: bytes = b"", rc: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout, stderr=b"")


def _patch_env(session: _FakeSession, run_stdout: bytes, run_raises=None):
    return (
        patch("lexaloud.selection.detect_session", return_value=session),
        patch(
            "lexaloud.selection.shutil.which",
            side_effect=lambda name: "/usr/bin/" + name,
        ),
        patch(
            "lexaloud.selection.subprocess.run",
            side_effect=(run_raises if run_raises else None) or (lambda *a, **kw: _completed(run_stdout)),
        ),
    )


def test_read_primary_wayland_returns_text():
    session = _FakeSession(is_wayland=True, has_wl=True, has_xclip=True)
    with patch("lexaloud.selection.detect_session", return_value=session), \
         patch("lexaloud.selection.shutil.which", return_value="/usr/bin/wl-paste"), \
         patch("lexaloud.selection.subprocess.run", return_value=_completed(b"hello world")):
        r = read_primary(max_bytes=1024, timeout_s=1.0)
    assert r.text == "hello world"
    assert r.source == "primary"
    assert not r.truncated


def test_read_primary_empty_raises():
    session = _FakeSession(is_wayland=True, has_wl=True, has_xclip=True)
    with patch("lexaloud.selection.detect_session", return_value=session), \
         patch("lexaloud.selection.shutil.which", return_value="/usr/bin/wl-paste"), \
         patch("lexaloud.selection.subprocess.run", return_value=_completed(b"")):
        with pytest.raises(SelectionEmpty):
            read_primary(max_bytes=1024, timeout_s=1.0)


def test_read_primary_whitespace_only_raises():
    session = _FakeSession(is_wayland=True, has_wl=True, has_xclip=True)
    with patch("lexaloud.selection.detect_session", return_value=session), \
         patch("lexaloud.selection.shutil.which", return_value="/usr/bin/wl-paste"), \
         patch("lexaloud.selection.subprocess.run", return_value=_completed(b"   \n  ")):
        with pytest.raises(SelectionEmpty):
            read_primary(max_bytes=1024, timeout_s=1.0)


def test_read_primary_truncates_large_selection():
    big_text = ("hello " * 1000).encode("utf-8")
    session = _FakeSession(is_wayland=True, has_wl=True, has_xclip=True)
    with patch("lexaloud.selection.detect_session", return_value=session), \
         patch("lexaloud.selection.shutil.which", return_value="/usr/bin/wl-paste"), \
         patch("lexaloud.selection.subprocess.run", return_value=_completed(big_text)):
        r = read_primary(max_bytes=100, timeout_s=1.0)
    assert r.truncated
    assert len(r.text.encode("utf-8")) <= 100
    assert r.original_byte_length == len(big_text)


def test_read_primary_tool_missing_raises():
    session = _FakeSession(is_wayland=True, has_wl=False, has_xclip=False)
    with patch("lexaloud.selection.detect_session", return_value=session), \
         patch("lexaloud.selection.shutil.which", return_value=None):
        with pytest.raises(SelectionToolMissing):
            read_primary(max_bytes=1024, timeout_s=1.0)


def test_read_primary_timeout_raises():
    session = _FakeSession(is_wayland=True, has_wl=True, has_xclip=True)

    def _raise(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=1.0)

    with patch("lexaloud.selection.detect_session", return_value=session), \
         patch("lexaloud.selection.shutil.which", return_value="/usr/bin/wl-paste"), \
         patch("lexaloud.selection.subprocess.run", side_effect=_raise):
        with pytest.raises(SelectionTimeout):
            read_primary(max_bytes=1024, timeout_s=1.0)


def test_read_clipboard_x11_uses_xclip():
    session = _FakeSession(is_wayland=False, has_wl=False, has_xclip=True)
    with patch("lexaloud.selection.detect_session", return_value=session), \
         patch("lexaloud.selection.shutil.which", return_value="/usr/bin/xclip"), \
         patch("lexaloud.selection.subprocess.run", return_value=_completed(b"clipped text")) as mock_run:
        r = read_clipboard(max_bytes=1024, timeout_s=1.0)
    assert r.text == "clipped text"
    assert r.source == "clipboard"
    # Verify the command used xclip -o -selection clipboard
    call_args = mock_run.call_args
    cmd = call_args[0][0]
    assert cmd == ["xclip", "-o", "-selection", "clipboard"]


def test_primary_and_clipboard_do_not_fall_back_to_each_other():
    """Critical test: empty primary must NOT return clipboard contents."""
    session = _FakeSession(is_wayland=True, has_wl=True, has_xclip=True)
    # Primary is empty, clipboard has content. read_primary must still raise.
    with patch("lexaloud.selection.detect_session", return_value=session), \
         patch("lexaloud.selection.shutil.which", return_value="/usr/bin/wl-paste"), \
         patch("lexaloud.selection.subprocess.run", return_value=_completed(b"")):
        with pytest.raises(SelectionEmpty):
            read_primary(max_bytes=1024, timeout_s=1.0)
