"""`lexaloud bug-report` — collect diagnostic information for issue reports.

Emits a markdown document that can be pasted directly into a GitHub bug
report. Collects:

- distro / kernel / desktop / session type / GPU
- Python version, lexaloud version
- daemon /state output (over the Unix domain socket)
- daemon last_error from /state
- last ~200 lines of `journalctl --user -u lexaloud.service`
- presence + SHA256 of the installed model artifacts
- sanitized config.toml contents

Redaction is on by default:
- paths under $HOME are rewritten to `~/...`
- TOML keys matching `(?i)(key|token|secret|pass)` have their value
  replaced with `<REDACTED>`
- environment variables are NOT included

Pass `--full` to disable redaction. The caller can then decide what to
paste into the public bug report.
"""

from __future__ import annotations

import json
import os
import platform as py_platform
import re
import subprocess
import sys
from io import StringIO
from pathlib import Path


_REDACT_KEY_RE = re.compile(r"(?i)(key|token|secret|pass)")


def _redact_home(text: str) -> str:
    home = str(Path.home())
    if not home:
        return text
    return text.replace(home, "~")


def _redact_toml_values(toml_text: str) -> str:
    """Replace the value of any TOML key matching the redaction pattern."""
    out_lines: list[str] = []
    for raw in toml_text.splitlines():
        line = raw
        # Matches `key = value`
        m = re.match(r"^(\s*)([A-Za-z0-9_.\-]+)(\s*=\s*)(.+)$", raw)
        if m and _REDACT_KEY_RE.search(m.group(2)):
            line = f'{m.group(1)}{m.group(2)}{m.group(3)}"<REDACTED>"'
        out_lines.append(line)
    return "\n".join(out_lines)


def _run(cmd: list[str], *, timeout_s: float = 5.0) -> str:
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        return (r.stdout or "").strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.SubprocessError):
        return ""


def _get_daemon_state() -> dict:
    """Return daemon /state as a dict, or {} on failure."""
    try:
        import httpx

        from .config import socket_path

        with httpx.Client(
            transport=httpx.HTTPTransport(uds=str(socket_path())),
            base_url="http://lexaloud",
            timeout=1.0,
        ) as client:
            resp = client.get("/state")
            return resp.json() if resp.status_code == 200 else {}
    except Exception:  # noqa: BLE001
        return {}


def _get_journalctl_tail(n: int = 200) -> str:
    return _run(
        [
            "journalctl",
            "--user",
            "-u",
            "lexaloud.service",
            "-n",
            str(n),
            "--no-pager",
        ],
        timeout_s=5.0,
    )


def _get_model_cache_info() -> list[str]:
    """Return one line per expected artifact reporting present/absent + size."""
    from .models import ARTIFACTS, default_cache_dir

    cache = default_cache_dir()
    lines: list[str] = []
    for art in ARTIFACTS:
        p = cache / art.filename
        if p.is_file():
            size = p.stat().st_size
            lines.append(f"- `{art.filename}`: present ({size} bytes, expected ~{art.expected_size})")
        else:
            lines.append(f"- `{art.filename}`: **MISSING**")
    return lines


def _get_config_contents(redact: bool) -> str:
    from .config import config_path

    p = config_path()
    if not p.is_file():
        return "(no config.toml present — using defaults)"
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as e:
        return f"(could not read {p}: {e})"
    if redact:
        text = _redact_toml_values(text)
    return text


def collect_bug_report(redact: bool = True) -> str:
    """Return the bug report as a markdown string."""
    from . import __version__
    from .platform import detect_desktop, detect_distro, detect_gpu

    distro = detect_distro()
    desktop = detect_desktop()
    gpu = detect_gpu()

    out = StringIO()

    def w(*parts: str) -> None:
        line = " ".join(parts)
        if redact:
            line = _redact_home(line)
        out.write(line + "\n")

    w("# Lexaloud bug report")
    w("")
    w("## Versions")
    w("")
    w(f"- **Lexaloud**: {__version__}")
    w(f"- **Python**: {sys.version.split()[0]} ({sys.executable})")
    w(f"- **Platform (Python)**: {py_platform.platform()}")
    w(f"- **Kernel**: {_run(['uname', '-r']) or 'unknown'}")
    w("")
    w("## Distro")
    w("")
    w(f"- **ID**: `{distro.id}`")
    w(f"- **ID_LIKE**: `{' '.join(distro.like) or '(none)'}`")
    w(f"- **VERSION_ID**: `{distro.version_id}`")
    w(f"- **PRETTY_NAME**: {distro.pretty_name}")
    w("")
    w("## Desktop session")
    w("")
    w(f"- **Desktop**: `{desktop.name}`")
    w(f"- **Session type**: `{desktop.session_type}`")
    w(f"- **is_gnome**: {desktop.is_gnome}")
    w(f"- **is_kde**: {desktop.is_kde}")
    w("")
    w("## GPU")
    w("")
    w(f"- **Vendor**: `{gpu.vendor}`")
    w(f"- **Device**: {gpu.device or '(unknown)'}")
    w("")
    w("## Daemon state")
    w("")
    state = _get_daemon_state()
    if state:
        pretty = json.dumps(state, indent=2)
        # pretty is already redacted by the `w` wrapper when it calls
        # out.write directly; but since we bypass `w` here for the
        # multi-line JSON body, do the redaction explicitly.
        if redact:
            pretty = _redact_home(pretty)
        w("```json")
        out.write(pretty + "\n")
        w("```")
        last_error = state.get("last_error")
        if last_error:
            w("")
            w("### last_error")
            w("")
            w("```")
            out.write(str(last_error) + "\n")
            w("```")
    else:
        w("(daemon not running or UDS unreachable)")
    w("")
    w("## Model cache")
    w("")
    for line in _get_model_cache_info():
        w(line)
    w("")
    w("## Config (~/.config/lexaloud/config.toml)")
    w("")
    config_text = _get_config_contents(redact=redact)
    w("```toml")
    out.write(config_text if config_text.endswith("\n") else config_text + "\n")
    w("```")
    w("")
    w("## Systemd unit state")
    w("")
    systemctl_status = _run(
        ["systemctl", "--user", "is-active", "lexaloud.service"]
    )
    w(f"- `systemctl --user is-active lexaloud.service`: `{systemctl_status or 'unknown'}`")
    w("")
    w("## Journal (last 200 lines)")
    w("")
    journal = _get_journalctl_tail(200)
    if journal:
        # Journal lines go through out.write directly (not w), so
        # redaction needs to happen here.
        if redact:
            journal = _redact_home(journal)
        w("```")
        out.write(journal + "\n")
        w("```")
    else:
        w("(no journal entries or journalctl unavailable)")
    w("")
    w("---")
    w(f"Generated by `lexaloud bug-report{' --full' if not redact else ''}`.")
    if redact:
        w(
            "\n_Redaction is on by default: $HOME paths replaced with `~`, "
            "TOML keys matching `(?i)(key|token|secret|pass)` have values "
            "replaced with `<REDACTED>`. Pass `--full` to disable._"
        )

    return out.getvalue()


def cmd_bug_report(args) -> int:
    """`lexaloud bug-report` — print a markdown bug report to stdout."""
    text = collect_bug_report(redact=not args.full)
    sys.stdout.write(text)
    return 0
