"""Tests for the Unix domain socket path helper."""

from __future__ import annotations

from pathlib import Path

from lexaloud.config import runtime_dir, socket_path


def test_socket_path_under_xdg_runtime_dir(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    rt = runtime_dir()
    sock = socket_path()
    assert rt == tmp_path
    assert sock == tmp_path / "lexaloud" / "lexaloud.sock"
    assert str(sock).startswith(str(rt))


def test_socket_path_fallback_to_run_user_uid(monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    import os
    rt = runtime_dir()
    sock = socket_path()
    assert rt == Path(f"/run/user/{os.getuid()}")
    assert sock == rt / "lexaloud" / "lexaloud.sock"


def test_socket_parent_directory_name(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    sock = socket_path()
    # The parent dir must be the `lexaloud` subdir (matches
    # RuntimeDirectory=lexaloud in the systemd unit)
    assert sock.parent.name == "lexaloud"
    assert sock.name == "lexaloud.sock"
