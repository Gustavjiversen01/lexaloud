"""Tests for the Phase B setup command."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

from lexaloud.setup import (
    _check_and_install_runtime_deps,
    _detect_backend,
    _detect_repo_root,
    _hotkey_walkthrough,
    _install_missing_deps,
    _missing_runtime_deps,
    _render_unit,
    _resolve_binary,
    _systemd_quote,
    _systemd_user_dir,
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
    assert _systemd_quote("/tmp/x") == '"/tmp/x"'
    assert _systemd_quote("/tmp/a b") == '"/tmp/a b"'
    assert _systemd_quote('/tmp/a"b') == '"/tmp/a\\"b"'
    assert _systemd_quote("/tmp/a\\b") == '"/tmp/a\\\\b"'


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


def test_resolve_binary_does_not_follow_venv_python_symlink(tmp_path: Path, monkeypatch):
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


# --- runtime-dep spot check (the "git pull without venv refresh" fix) ---


def test_missing_runtime_deps_empty_when_all_present():
    """In the dev venv we ran tests from, every declared dep is present."""
    assert _missing_runtime_deps() == []


def test_missing_runtime_deps_detects_gap(monkeypatch):
    """A missing module name shows up in the returned list."""
    import lexaloud.setup as setup_mod

    real_find_spec = setup_mod.importlib.util.find_spec  # capture before patch

    def _fake_find_spec(name: str):
        if name == "markdown_it":
            return None
        return real_find_spec(name)

    monkeypatch.setattr(setup_mod.importlib.util, "find_spec", _fake_find_spec)
    missing = _missing_runtime_deps()
    assert missing == ["markdown-it-py"]


def test_detect_repo_root_finds_editable_install():
    """Running from the dev venv with an editable install locates the repo."""
    root = _detect_repo_root()
    assert root is not None
    assert (root / "pyproject.toml").is_file()
    assert any(root.glob("requirements-lock.*.txt"))


def test_detect_backend_gpu_when_onnxruntime_gpu_installed(monkeypatch):
    import lexaloud.setup as setup_mod

    # onnxruntime module spec is present (importable)
    class _DummySpec:
        pass

    monkeypatch.setattr(
        setup_mod.importlib.util,
        "find_spec",
        lambda name: _DummySpec() if name == "onnxruntime" else None,
    )
    # Dist metadata says onnxruntime-gpu IS installed
    import importlib.metadata as md

    def _version(name: str):
        if name == "onnxruntime-gpu":
            return "1.24.4"
        raise md.PackageNotFoundError(name)

    monkeypatch.setattr(md, "version", _version)
    assert _detect_backend() == "cuda12"


def test_detect_backend_cpu_when_onnxruntime_missing(monkeypatch):
    import lexaloud.setup as setup_mod

    monkeypatch.setattr(setup_mod.importlib.util, "find_spec", lambda name: None)
    assert _detect_backend() == "cpu"


def test_install_missing_deps_noop_for_empty_list(tmp_path):
    """Empty package list returns 0 without touching pip."""
    fake_pip = tmp_path / "pip"
    # Deliberately not creating the file — if the code tried to call it,
    # the subprocess invocation would fail and return non-zero. Instead,
    # empty list should short-circuit.
    assert _install_missing_deps([], venv_pip=fake_pip) == 0


def test_install_missing_deps_errors_when_pip_absent(tmp_path, capsys):
    fake_pip = tmp_path / "nonexistent-pip"
    rc = _install_missing_deps(["foo"], venv_pip=fake_pip)
    assert rc == 1
    err = capsys.readouterr().err
    assert "cannot find pip" in err


def test_install_missing_deps_hash_verified_path(tmp_path, monkeypatch):
    """When a lockfile is reachable, pip is invoked with --require-hashes."""
    import lexaloud.setup as setup_mod

    fake_pip = tmp_path / "pip"
    fake_pip.write_text("")
    fake_pip.chmod(0o755)

    fake_repo = tmp_path / "repo"
    fake_repo.mkdir()
    (fake_repo / "pyproject.toml").write_text("")
    lockfile = fake_repo / "requirements-lock.cpu.txt"
    lockfile.write_text("")

    captured: dict = {}

    def _fake_run(cmd, *, env, check, timeout=None):
        captured["cmd"] = cmd
        captured["env_clean"] = "PYTHONPATH" not in env

        class _Result:
            returncode = 0

        return _Result()

    monkeypatch.setattr(setup_mod.subprocess, "run", _fake_run)

    rc = _install_missing_deps(
        ["markdown-it-py"],
        venv_pip=fake_pip,
        repo_root=fake_repo,
        backend="cpu",
    )
    assert rc == 0
    assert "--require-hashes" in captured["cmd"]
    assert "--constraint" in captured["cmd"]
    assert str(lockfile) in captured["cmd"]
    assert "markdown-it-py" in captured["cmd"]
    assert captured["env_clean"] is True


def test_install_missing_deps_falls_back_when_no_lockfile(tmp_path, monkeypatch):
    """Without a reachable lockfile, pip is invoked without hash pinning."""
    import lexaloud.setup as setup_mod

    fake_pip = tmp_path / "pip"
    fake_pip.write_text("")
    fake_pip.chmod(0o755)

    # Simulate a non-editable install: _detect_repo_root returns None.
    monkeypatch.setattr(setup_mod, "_detect_repo_root", lambda: None)

    captured: dict = {}

    def _fake_run(cmd, *, env, check, timeout=None):
        captured["cmd"] = cmd

        class _Result:
            returncode = 0

        return _Result()

    monkeypatch.setattr(setup_mod.subprocess, "run", _fake_run)

    rc = _install_missing_deps(
        ["markdown-it-py"],
        venv_pip=fake_pip,
        backend="cpu",
    )
    assert rc == 0
    assert "--require-hashes" not in captured["cmd"]
    assert "markdown-it-py" in captured["cmd"]


def test_install_missing_deps_falls_back_when_hashed_install_fails(tmp_path, monkeypatch):
    """If hash-verified install fails, fall through to an unhashed retry."""
    import lexaloud.setup as setup_mod

    fake_pip = tmp_path / "pip"
    fake_pip.write_text("")
    fake_pip.chmod(0o755)

    fake_repo = tmp_path / "repo"
    fake_repo.mkdir()
    (fake_repo / "pyproject.toml").write_text("")
    (fake_repo / "requirements-lock.cpu.txt").write_text("")

    calls: list[list[str]] = []

    def _fake_run(cmd, *, env, check, timeout=None):
        calls.append(list(cmd))

        class _Result:
            # First call (hashed) fails; second call (unhashed) succeeds
            returncode = 1 if "--require-hashes" in cmd else 0

        return _Result()

    monkeypatch.setattr(setup_mod.subprocess, "run", _fake_run)

    rc = _install_missing_deps(
        ["markdown-it-py"],
        venv_pip=fake_pip,
        repo_root=fake_repo,
        backend="cpu",
    )
    assert rc == 0
    assert len(calls) == 2
    assert "--require-hashes" in calls[0]
    assert "--require-hashes" not in calls[1]


def test_check_and_install_no_op_when_deps_present(monkeypatch):
    """If nothing is missing, the wrapper short-circuits without spawning pip."""
    import lexaloud.setup as setup_mod

    monkeypatch.setattr(setup_mod, "_missing_runtime_deps", lambda: [])

    def _bomb(*a, **kw):
        raise AssertionError("subprocess.run should not be invoked")

    monkeypatch.setattr(setup_mod.subprocess, "run", _bomb)

    from lexaloud.cli import EXIT_OK

    assert _check_and_install_runtime_deps() == EXIT_OK


def test_install_missing_deps_timeout_graceful(tmp_path, monkeypatch, capsys):
    """L2 regression: TimeoutExpired must exit 1 with a manual-recovery
    message (not raise or hang)."""
    import subprocess as real_subprocess

    import lexaloud.setup as setup_mod

    fake_pip = tmp_path / "pip"
    fake_pip.write_text("")
    fake_pip.chmod(0o755)

    # Force the fallback (no lockfile) path so there's exactly one
    # subprocess.run invocation to mock.
    monkeypatch.setattr(setup_mod, "_detect_repo_root", lambda: None)

    def _timeout(cmd, **kw):
        raise real_subprocess.TimeoutExpired(cmd=cmd, timeout=kw.get("timeout", 0))

    monkeypatch.setattr(setup_mod.subprocess, "run", _timeout)

    rc = _install_missing_deps(["markdown-it-py"], venv_pip=fake_pip)
    assert rc == 1
    err = capsys.readouterr().err
    assert "timed out" in err
    assert "markdown-it-py" in err


def test_check_and_install_reports_residual_missing(monkeypatch, capsys):
    """If the install 'succeeds' but the dep is still missing, return error."""
    import lexaloud.setup as setup_mod

    # First call reports missing; second call (after install) still missing.
    monkeypatch.setattr(setup_mod, "_missing_runtime_deps", lambda: ["markdown-it-py"])
    monkeypatch.setattr(setup_mod, "_install_missing_deps", lambda pkgs, **kw: 0)

    from lexaloud.cli import EXIT_GENERIC_ERROR

    assert _check_and_install_runtime_deps() == EXIT_GENERIC_ERROR
    err = capsys.readouterr().err
    assert "still missing after install" in err
