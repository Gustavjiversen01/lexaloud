"""Selection capture functions.

`read_primary()` reads the X11 PRIMARY / Wayland primary selection.
`read_clipboard()` reads the CLIPBOARD / Wayland clipboard.

Neither function falls back to the other — that would be a silent footgun
(speaking a stale clipboard when the primary is empty). Callers decide which
source is meaningful in context.

Both functions apply:
- A per-subprocess timeout via `subprocess.run(..., timeout=...)` that
  terminates hung `wl-paste` / `xclip` cleanly.
- UTF-8 safe truncation to a configurable byte cap.
- An argument-list subprocess invocation (no shell=True).

Exit-code-relevant errors are raised as `SelectionError` so the CLI can map
them to exit codes 2 (empty) / 4 (oversized) / 5 (timeout or missing tool).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass

from .session import detect_session

log = logging.getLogger(__name__)


class SelectionError(RuntimeError):
    """Base class for capture failures."""


class SelectionEmpty(SelectionError):
    """Selection or clipboard was empty."""


class SelectionToolMissing(SelectionError):
    """Required capture tool (wl-paste/xclip) is not installed."""


class SelectionTimeout(SelectionError):
    """Capture subprocess exceeded its timeout."""


class SelectionDisplayUnavailable(SelectionError):
    """Display server is unreachable (no DISPLAY, X auth failure, etc.).

    This is distinct from `SelectionEmpty` because the CLI should tell the
    user "ReadAloud can't reach your display server" rather than the
    misleading "Select text first" notification.
    """


@dataclass
class CaptureResult:
    text: str
    truncated: bool
    original_byte_length: int
    source: str  # "primary" | "clipboard"
    tool: str  # e.g. "wl-paste --primary"


def _utf8_safe_truncate(data: bytes, max_bytes: int) -> bytes:
    """Truncate `data` to at most `max_bytes` on a UTF-8 character boundary.

    Walks back from `max_bytes` across any UTF-8 continuation bytes
    (0b10xxxxxx) so the final slice doesn't contain a partial multi-byte
    sequence. Python's slice upper bound is exclusive, so stopping at a
    lead byte cleanly excludes it. The caller additionally decodes with
    `errors="ignore"` as a belt-and-suspenders for any pre-existing
    corruption in the captured bytes.
    """
    if len(data) <= max_bytes:
        return data
    cut = max_bytes
    while cut > 0 and (data[cut] & 0xC0) == 0x80:
        cut -= 1
    return data[:cut]


# Substrings that indicate the capture tool couldn't reach the display
# server at all — as opposed to "there was no selection to read". Matched
# case-insensitively against the tool's stderr. Entries come from real
# `xclip`, `xsel`, and `wl-paste` failure messages.
_DISPLAY_FAILURE_MARKERS = (
    "can't open display",
    "cannot open display",
    "unable to open display",
    "no display",
    "display name is missing",
    "authorization",
    "not authorized",
    "wayland_display",
    "no wayland connection",
    "compositor doesn't support",
    "could not connect",
    "failed to connect",
)


def _run_capture(cmd: list[str], timeout_s: float) -> bytes:
    if shutil.which(cmd[0]) is None:
        raise SelectionToolMissing(f"{cmd[0]} is not installed")
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise SelectionTimeout(f"{' '.join(cmd)} timed out after {timeout_s}s")
    if proc.returncode != 0:
        # xclip/wl-paste return non-zero BOTH for "the selection is empty"
        # AND for real failures like "can't open display". Distinguish by
        # matching the stderr against known display-failure markers; real
        # empty selections produce an empty (or no) stderr. This kills the
        # "hit hotkey, get 'Select text first' — but I did select text!"
        # confusion reported by Agent 4.
        stderr = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
        lowered = stderr.lower()
        if any(marker in lowered for marker in _DISPLAY_FAILURE_MARKERS):
            raise SelectionDisplayUnavailable(
                f"{cmd[0]} cannot reach the display server: {stderr}"
            )
        if stderr:
            log.debug("%s exited %d with stderr: %s", cmd[0], proc.returncode, stderr)
        return b""
    return proc.stdout or b""


def _finalize(raw: bytes, max_bytes: int, source: str, tool: str) -> CaptureResult:
    original_length = len(raw)
    truncated = False
    if original_length > max_bytes:
        raw = _utf8_safe_truncate(raw, max_bytes)
        truncated = True
    text = raw.decode("utf-8", errors="ignore")
    if not text.strip():
        raise SelectionEmpty(f"{source} selection is empty")
    return CaptureResult(
        text=text,
        truncated=truncated,
        original_byte_length=original_length,
        source=source,
        tool=tool,
    )


def _pick_primary_tool(info) -> list[str]:
    """Pick the right PRIMARY capture command for the current session.

    Refuses to fall back across display servers: on Wayland without
    wl-paste, we raise `SelectionToolMissing` rather than silently using
    xclip against XWayland (which has unrelated clipboard state).
    """
    if info.is_wayland:
        if not info.wl_paste:
            raise SelectionToolMissing(
                "wl-paste is not installed. "
                "Install wl-clipboard: `sudo apt install wl-clipboard`"
            )
        return ["wl-paste", "--primary", "--no-newline"]
    if info.is_x11:
        if not info.xclip:
            raise SelectionToolMissing(
                "xclip is not installed. "
                "Install it: `sudo apt install xclip`"
            )
        return ["xclip", "-o", "-selection", "primary"]
    # session_type == "unknown"
    if info.wl_paste:
        return ["wl-paste", "--primary", "--no-newline"]
    if info.xclip:
        return ["xclip", "-o", "-selection", "primary"]
    raise SelectionToolMissing(
        "neither wl-paste nor xclip is installed; "
        "run `sudo apt install wl-clipboard xclip`"
    )


def _pick_clipboard_tool(info) -> list[str]:
    """Pick the right CLIPBOARD capture command for the current session."""
    if info.is_wayland:
        if not info.wl_paste:
            raise SelectionToolMissing(
                "wl-paste is not installed. "
                "Install wl-clipboard: `sudo apt install wl-clipboard`"
            )
        return ["wl-paste", "--no-newline"]
    if info.is_x11:
        if not info.xclip:
            raise SelectionToolMissing(
                "xclip is not installed. "
                "Install it: `sudo apt install xclip`"
            )
        return ["xclip", "-o", "-selection", "clipboard"]
    if info.wl_paste:
        return ["wl-paste", "--no-newline"]
    if info.xclip:
        return ["xclip", "-o", "-selection", "clipboard"]
    raise SelectionToolMissing(
        "neither wl-paste nor xclip is installed; "
        "run `sudo apt install wl-clipboard xclip`"
    )


def read_primary(max_bytes: int, timeout_s: float) -> CaptureResult:
    """Read the PRIMARY selection. Never touches the clipboard."""
    info = detect_session()
    cmd = _pick_primary_tool(info)
    raw = _run_capture(cmd, timeout_s)
    return _finalize(raw, max_bytes, source="primary", tool=" ".join(cmd))


def read_clipboard(max_bytes: int, timeout_s: float) -> CaptureResult:
    """Read the CLIPBOARD. Never touches the primary selection."""
    info = detect_session()
    cmd = _pick_clipboard_tool(info)
    raw = _run_capture(cmd, timeout_s)
    return _finalize(raw, max_bytes, source="clipboard", tool=" ".join(cmd))


def try_notify(summary: str, body: str | None = None, timeout_s: float = 1.0) -> None:
    """Best-effort `notify-send`. Never raises; logs on failure."""
    notify = shutil.which("notify-send")
    if not notify:
        log.debug("notify-send not available; falling back to stderr")
        return
    # `--` terminates option parsing so a summary starting with `-` won't be
    # misinterpreted as another flag.
    args = [notify, "--app-name", "ReadAloud", "--expire-time", "3000", "--", summary]
    if body:
        args.append(body)
    try:
        subprocess.run(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout_s,
            check=False,
        )
    except Exception as e:  # noqa: BLE001 — explicit best-effort swallow
        log.debug("notify-send failed: %s", e)
