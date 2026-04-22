"""Phase B setup command: post-install configuration.

Runs AFTER scripts/install.sh has created the venv and installed the package.
Responsibilities:

1. Resolve the absolute path to the `lexaloud` binary via `shutil.which`
   (falling back to `sys.executable`'s directory). Print it prominently —
   it's what the user pastes into GNOME Custom Shortcuts and into the
   systemd unit.
2. Run `lexaloud download-models` (idempotent).
3. Detect session type and print the hotkey-binding walkthrough.
4. Render a systemd `--user` unit file to
   `~/.config/systemd/user/lexaloud.service`. Does NOT overwrite existing
   unless `--force` is set, but if the on-disk content differs from what
   we'd render, print a clear message telling the user to pass --force.
5. Print the exact activate commands including `daemon-reload` BEFORE
   `enable --now`.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from importlib.resources import files
from pathlib import Path

from .cli import EXIT_GENERIC_ERROR, EXIT_OK
from .models import default_cache_dir, ensure_artifacts
from .session import detect_session

# Pip install timeout. Generous enough for a slow connection to fetch
# a markdown-it-py-sized package; bounded so an unreachable PyPI
# doesn't hang ``lexaloud setup`` indefinitely.
_PIP_TIMEOUT_SECONDS: int = 600  # 10 minutes

# Declared runtime deps (as in pyproject.toml [project.dependencies]),
# mapped to the importable module name. This is the small set we
# spot-check on `lexaloud setup` so that a user who upgrades the repo
# without reinstalling the venv gets a clear diagnostic instead of a
# cryptic ImportError from the daemon.
#
# pyproject-name → import-name
_RUNTIME_DEPS: dict[str, str] = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "numpy": "numpy",
    "sounddevice": "sounddevice",
    "pysbd": "pysbd",
    "httpx": "httpx",
    "pydantic": "pydantic",
    "markdown-it-py": "markdown_it",
}


def _missing_runtime_deps() -> list[str]:
    """Return the pyproject names of declared deps that can't be imported.

    Uses ``importlib.util.find_spec`` rather than actually importing, so
    we don't pay the startup cost of heavyweight modules (e.g. numpy)
    and don't risk partial module state when the user has a mixed venv.
    """
    missing: list[str] = []
    for pkg, module in _RUNTIME_DEPS.items():
        if importlib.util.find_spec(module) is None:
            missing.append(pkg)
    return missing


def _detect_repo_root() -> Path | None:
    """Return the repo root if we're running from an editable install.

    ``scripts/install.sh`` installs Lexaloud with ``pip install -e .``, so
    the module's ``__file__`` is inside the source tree. Walking up a few
    parents, the repo root is identifiable by the presence of BOTH
    ``pyproject.toml`` AND a ``requirements-lock.*.txt``. Returns ``None``
    for non-editable installs where the code lives in ``site-packages``.
    """
    here = Path(__file__).resolve()
    for candidate in list(here.parents)[:5]:
        if (candidate / "pyproject.toml").is_file() and any(
            candidate.glob("requirements-lock.*.txt")
        ):
            return candidate
    return None


def _detect_backend() -> str:
    """Return "cuda12" if onnxruntime-gpu is installed, else "cpu".

    Used to pick the right ``requirements-lock.*.txt`` as a constraints
    file for hash-verified installs of missing deps.
    """
    if importlib.util.find_spec("onnxruntime") is not None:
        # Both distributions register as the ``onnxruntime`` module.
        # Distinguish via dist metadata.
        try:
            import importlib.metadata as md

            md.version("onnxruntime-gpu")
            return "cuda12"
        except md.PackageNotFoundError:
            return "cpu"
    return "cpu"


def _install_missing_deps(
    packages: list[str],
    *,
    venv_pip: Path | None = None,
    repo_root: Path | None = None,
    backend: str | None = None,
) -> int:
    """Install missing runtime deps into the current venv.

    Prefers ``--require-hashes`` with the repo's lockfile as a
    constraints file when we're running from an editable install (the
    lockfile pins every package with wheel + sdist SHA-256 hashes).
    Falls back to an unhashed ``pip install <pkg>`` with a printed
    warning when no lockfile is reachable (e.g. site-packages install).

    Returns 0 on success, non-zero on failure.
    """
    if not packages:
        return 0

    pip_bin = venv_pip or Path(sys.executable).parent / "pip"
    if not pip_bin.is_file():
        print(f"  ERROR: cannot find pip at {pip_bin}", file=sys.stderr)
        print(
            f"  Install manually: <venv>/bin/pip install {' '.join(packages)}",
            file=sys.stderr,
        )
        return 1

    # Scrub PYTHONPATH for the install call so ROS / ComfyUI pollution
    # can't leak into dependency resolution (mirrors scripts/install.sh).
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}

    root = repo_root if repo_root is not None else _detect_repo_root()
    back = backend if backend is not None else _detect_backend()

    def _timeout_msg() -> str:
        return (
            f"  ERROR: pip install timed out after {_PIP_TIMEOUT_SECONDS}s. "
            "Network may be unreachable. Run manually: "
            f"{pip_bin} install {' '.join(packages)}"
        )

    if root is not None:
        lockfile = root / f"requirements-lock.{back}.txt"
        if lockfile.is_file():
            print(f"  using lockfile constraints: {lockfile.name}")
            cmd = [
                str(pip_bin),
                "install",
                "--require-hashes",
                "--constraint",
                str(lockfile),
                *packages,
            ]
            try:
                proc = subprocess.run(cmd, env=env, check=False, timeout=_PIP_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                print(_timeout_msg(), file=sys.stderr)
                return 1
            except OSError as e:
                print(f"  pip invocation failed: {e}", file=sys.stderr)
                return 1
            if proc.returncode == 0:
                return 0
            print(
                "  hash-verified install failed — falling back to unhashed install",
                file=sys.stderr,
            )

    # Fallback: plain pip install. Lose supply-chain integrity, warn.
    print("  (no lockfile found or hash-verified install failed — installing without hash pinning)")
    cmd = [str(pip_bin), "install", *packages]
    try:
        proc = subprocess.run(cmd, env=env, check=False, timeout=_PIP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        print(_timeout_msg(), file=sys.stderr)
        return 1
    except OSError as e:
        print(f"  pip invocation failed: {e}", file=sys.stderr)
        return 1
    return proc.returncode


def _check_and_install_runtime_deps() -> int:
    """Spot-check declared runtime deps; install any that are missing.

    Returns ``EXIT_OK`` on success (including when nothing was missing)
    or ``EXIT_GENERIC_ERROR`` if installation failed.
    """
    missing = _missing_runtime_deps()
    if not missing:
        return EXIT_OK

    print()
    print(f"Detected missing runtime dependencies: {', '.join(missing)}")
    print("  (venv is out of date relative to pyproject.toml —")
    print("   this typically happens after `git pull` without a venv refresh)")

    rc = _install_missing_deps(missing)
    if rc != 0:
        pip_bin = Path(sys.executable).parent / "pip"
        print(
            f"\n  ERROR: automatic install failed. Run manually:\n"
            f"    {pip_bin} install {' '.join(missing)}\n"
            f"  Or reinstall from the lockfile:\n"
            f"    ./scripts/install.sh",
            file=sys.stderr,
        )
        return EXIT_GENERIC_ERROR

    # Re-check: confirm the install actually landed.
    still_missing = _missing_runtime_deps()
    if still_missing:
        print(
            f"\n  ERROR: still missing after install: {', '.join(still_missing)}",
            file=sys.stderr,
        )
        return EXIT_GENERIC_ERROR
    print("  all runtime dependencies are now available.")
    return EXIT_OK


# systemd unit template loaded from src/lexaloud/templates/ via
# importlib.resources. This lets the package ship the template as a
# data file (see [tool.setuptools.package-data] in pyproject.toml)
# instead of baking it into a Python string literal.
#
# Key choices documented inline in the template file:
# - UnsetEnvironment=PYTHONPATH cleans inherited PYTHONPATH
#   (ROS, ComfyUI, etc.)
# - TimeoutStopSec=10 keeps systemd SIGTERM responsive
# - RuntimeDirectory=lexaloud + RuntimeDirectoryMode=0700 creates the
#   parent dir for the daemon's Unix domain socket with the correct
#   permissions; systemd cleans it up on service stop
# - After=default.target only (sound.target isn't in the user manager)
def _load_systemd_template() -> str:
    return (
        files("lexaloud.templates").joinpath("systemd.service.template").read_text(encoding="utf-8")
    )


def _systemd_quote(s: str) -> str:
    """Quote a path for a systemd ExecStart line.

    systemd accepts C-style escape sequences inside double quotes for the
    ExecStart= value. This matters when the binary path contains spaces.
    """
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _resolve_binary() -> Path:
    which = shutil.which("lexaloud")
    if which:
        return Path(which).resolve()
    # Fallback: assume we're running inside the target venv. Do NOT call
    # `.resolve()` on sys.executable — in a venv, that symlink points back
    # to the system python (e.g., /usr/bin/python3) and we'd end up looking
    # for /usr/bin/lexaloud instead of the venv's bin dir.
    exe_dir = Path(sys.executable).parent
    candidate = exe_dir / "lexaloud"
    if candidate.exists():
        return candidate
    raise RuntimeError(
        "Could not resolve the `lexaloud` binary. Is the package installed? "
        "Run scripts/install.sh first."
    )


def _systemd_user_dir() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    root = Path(xdg) if xdg else Path.home() / ".config"
    d = root / "systemd" / "user"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _render_unit(binary: Path) -> str:
    return _load_systemd_template().format(binary_quoted=_systemd_quote(str(binary)))


def _hotkey_walkthrough(binary: Path) -> str:
    info = detect_session()
    desktop = info.desktop
    is_wayland = info.is_wayland

    lines: list[str] = []
    lines.append("")
    lines.append("===== Hotkey binding walkthrough =====")
    lines.append("")
    lines.append(f"Desktop: {desktop}")
    lines.append(f"Session: {info.session_type}")
    lines.append("")
    if "GNOME" in desktop.upper():
        lines.append("GNOME Custom Shortcut:")
        lines.append("  1. Open Settings -> Keyboard -> View and Customize Shortcuts")
        lines.append("     -> Custom Shortcuts -> + (Add shortcut)")
        lines.append("  2. Name:    Lexaloud: speak selection")
        lines.append(f"     Command: {binary} speak-selection")
        lines.append("     Shortcut: press Super+R (or any binding you prefer)")
        lines.append("  3. Add a second shortcut for speak-clipboard if you want")
        lines.append("     a Ctrl+C-then-hotkey workflow (recommended on GNOME Wayland,")
        lines.append("     where the primary selection may be empty for some apps).")
        if is_wayland:
            lines.append("")
            lines.append("  Note: GNOME Wayland does not always expose the PRIMARY selection")
            lines.append("  via wl-paste --primary. If `speak-selection` comes up empty for")
            lines.append("  apps like VS Code or Obsidian, bind `speak-clipboard` instead")
            lines.append("  and use Ctrl+C before the hotkey.")
    elif "KDE" in desktop.upper() or "PLASMA" in desktop.upper():
        lines.append("KDE Plasma Custom Shortcut:")
        lines.append("  1. Open System Settings -> Shortcuts -> Custom Shortcuts")
        lines.append("  2. Edit -> New -> Global Shortcut -> Command/URL")
        lines.append(f"     Command: {binary} speak-selection")
    else:
        lines.append(f"For {desktop}: bind `{binary} speak-selection` to your preferred")
        lines.append("global shortcut. See your window manager's documentation.")
    lines.append("")
    return "\n".join(lines)


def run_setup(force: bool = False) -> int:
    # Spot-check runtime deps FIRST. If the venv is stale relative to
    # pyproject.toml (common after `git pull` without a reinstall),
    # auto-install the missing ones before we hit any `from lexaloud.X
    # import ...` in the rest of setup. Without this, users see a
    # cryptic ImportError from systemd after enabling the service.
    dep_rc = _check_and_install_runtime_deps()
    if dep_rc != EXIT_OK:
        return dep_rc

    try:
        binary = _resolve_binary()
    except RuntimeError as e:
        print(f"lexaloud setup failed: {e}", file=sys.stderr)
        return EXIT_GENERIC_ERROR

    print(f"lexaloud binary: {binary}")

    # Warn about PYTHONPATH pollution (e.g. ROS sourcing at login).
    if os.environ.get("PYTHONPATH"):
        print(
            "\nNote: your shell has PYTHONPATH set:\n"
            f"  PYTHONPATH={os.environ['PYTHONPATH']}\n"
            "The systemd unit we render will scrub this at daemon startup "
            "so it won't leak into the Python environment.",
        )

    print(f"\nModel cache: {default_cache_dir()}")
    try:
        ensure_artifacts(download_if_missing=True)
        print("  models present and verified.")
    except Exception as e:  # noqa: BLE001
        print(f"  model download/verify failed: {e}", file=sys.stderr)
        return EXIT_GENERIC_ERROR

    unit_dir = _systemd_user_dir()
    unit_path = unit_dir / "lexaloud.service"
    new_content = _render_unit(binary)

    if unit_path.exists():
        existing = unit_path.read_text()
        if existing == new_content:
            print(f"\nsystemd unit at {unit_path} already up to date.")
        elif force:
            unit_path.write_text(new_content)
            print(f"\nOverwrote systemd unit: {unit_path}")
        else:
            print(
                f"\nsystemd unit at {unit_path} differs from the rendered template "
                "(the binary path or other fields may have changed).\n"
                "Pass --force to overwrite."
            )
    else:
        unit_path.write_text(new_content)
        print(f"\nWrote systemd unit: {unit_path}")

    print(_hotkey_walkthrough(binary))

    print("Activate the daemon:")
    print("  systemctl --user daemon-reload")
    print("  systemctl --user enable --now lexaloud.service")
    print("")
    print("Then verify with:")
    print("  systemctl --user status lexaloud.service")
    print(f"  {binary} status")

    return EXIT_OK
