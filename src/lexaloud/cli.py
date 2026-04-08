"""Command-line entry points for Lexaloud.

Subcommands:
    lexaloud speak-selection    # capture PRIMARY, POST to daemon
    lexaloud speak-clipboard    # capture CLIPBOARD, POST to daemon
    lexaloud pause
    lexaloud resume
    lexaloud stop
    lexaloud skip
    lexaloud back
    lexaloud status
    lexaloud download-models
    lexaloud setup
    lexaloud daemon             # run the FastAPI daemon

Exit codes:
    0  success
    2  empty selection / clipboard
    3  daemon not running
    4  oversized selection (rejected by daemon after truncation failed)
    5  capture tool missing or subprocess timeout
    1  any other error
"""

from __future__ import annotations

import argparse
import logging
import sys

from . import __version__
from .config import load_config, socket_path
from .selection import (
    CaptureResult,
    SelectionDisplayUnavailable,
    SelectionEmpty,
    SelectionError,
    SelectionTimeout,
    SelectionToolMissing,
    read_clipboard,
    read_primary,
    try_notify,
)

EXIT_OK = 0
EXIT_GENERIC_ERROR = 1
EXIT_EMPTY_SELECTION = 2
EXIT_DAEMON_DOWN = 3
EXIT_OVERSIZED = 4
EXIT_TOOL_MISSING_OR_TIMEOUT = 5


log = logging.getLogger("lexaloud.cli")


# ---------- daemon client helpers ----------


def _daemon_down_error(msg: str) -> None:
    print(msg, file=sys.stderr)
    try_notify(
        "Lexaloud daemon not running",
        "Run `systemctl --user start lexaloud.service`",
    )
    sys.exit(EXIT_DAEMON_DOWN)


def _parse_json_or_exit(resp) -> dict:
    import json

    if not resp.text:
        return {}
    try:
        return resp.json()
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Lexaloud daemon returned malformed JSON: {e}", file=sys.stderr)
        sys.exit(EXIT_GENERIC_ERROR)


def _client():
    # Unix domain socket transport. base_url is a dummy host that uvicorn
    # and httpx agree on; the actual connection is over the socket at
    # `socket_path()`. Timeouts mirror the previous TCP client:
    # connect: 3s (tolerates brief systemd startup window after enable --now);
    # read: 5s (routes return fast, Player.speak is non-blocking).
    import httpx

    return httpx.Client(
        transport=httpx.HTTPTransport(uds=str(socket_path())),
        base_url="http://lexaloud",
        timeout=httpx.Timeout(5.0, connect=3.0),
    )


def _post_to_daemon(path: str, json_body: dict | None = None) -> dict:
    import httpx

    try:
        with _client() as client:
            resp = client.post(path, json=json_body or {})
    except (
        httpx.ConnectError,
        httpx.ConnectTimeout,
        httpx.NetworkError,
        httpx.ReadTimeout,
        httpx.RemoteProtocolError,
    ):
        _daemon_down_error(
            "Lexaloud daemon is not running or unresponsive. Start it with: "
            "systemctl --user start lexaloud.service "
            "(or run `lexaloud setup` if you haven't yet)."
        )
        return {}  # unreachable; placates type checkers
    except httpx.HTTPError as e:
        print(f"Lexaloud daemon request failed: {e}", file=sys.stderr)
        sys.exit(EXIT_GENERIC_ERROR)

    if resp.status_code == 413:
        print("Selection too large for the daemon to accept.", file=sys.stderr)
        try_notify("Selection too large", "Lexaloud refused an oversized payload.")
        sys.exit(EXIT_OVERSIZED)
    if resp.status_code >= 400:
        print(
            f"Lexaloud daemon returned {resp.status_code}: {resp.text}",
            file=sys.stderr,
        )
        sys.exit(EXIT_GENERIC_ERROR)
    return _parse_json_or_exit(resp)


def _get_from_daemon(path: str) -> dict:
    import httpx

    try:
        with _client() as client:
            resp = client.get(path)
    except (
        httpx.ConnectError,
        httpx.ConnectTimeout,
        httpx.NetworkError,
        httpx.ReadTimeout,
        httpx.RemoteProtocolError,
    ):
        _daemon_down_error(
            "Lexaloud daemon is not running or unresponsive. Start it with: "
            "systemctl --user start lexaloud.service"
        )
        return {}  # unreachable
    except httpx.HTTPError as e:
        print(f"Lexaloud daemon request failed: {e}", file=sys.stderr)
        sys.exit(EXIT_GENERIC_ERROR)
    if resp.status_code >= 400:
        print(
            f"Lexaloud daemon returned {resp.status_code}: {resp.text}",
            file=sys.stderr,
        )
        sys.exit(EXIT_GENERIC_ERROR)
    return _parse_json_or_exit(resp)


# ---------- subcommand bodies ----------


def _do_capture_and_speak(capture_fn, source_label: str, args) -> int:
    cfg = load_config()
    max_bytes = args.max_bytes or cfg.capture.max_bytes
    try:
        result: CaptureResult = capture_fn(max_bytes, cfg.capture.subprocess_timeout_s)
    except SelectionDisplayUnavailable as e:
        # Distinct from "empty selection" — the capture tool could not
        # reach the display server. Tell the user what to actually check
        # instead of the misleading "Select text first".
        print(str(e), file=sys.stderr)
        try_notify(
            "Lexaloud: cannot reach display server",
            "Is DISPLAY set? Are you running from a session that can talk to X/Wayland?",
        )
        return EXIT_TOOL_MISSING_OR_TIMEOUT
    except SelectionEmpty as e:
        print(str(e), file=sys.stderr)
        if source_label == "primary":
            try_notify("Select text first", "Lexaloud: no primary selection found.")
        else:
            try_notify("Copy text first", "Lexaloud: clipboard is empty. Press Ctrl+C first.")
        return EXIT_EMPTY_SELECTION
    except SelectionToolMissing as e:
        print(str(e), file=sys.stderr)
        try_notify("Lexaloud: capture tool missing", str(e))
        return EXIT_TOOL_MISSING_OR_TIMEOUT
    except SelectionTimeout as e:
        print(str(e), file=sys.stderr)
        try_notify("Lexaloud: capture timed out", str(e))
        return EXIT_TOOL_MISSING_OR_TIMEOUT
    except SelectionError as e:
        print(str(e), file=sys.stderr)
        return EXIT_GENERIC_ERROR

    if result.truncated:
        try_notify(
            "Selection truncated",
            f"Lexaloud captured the first {max_bytes} bytes of a larger selection.",
        )

    _post_to_daemon("/speak", {"text": result.text, "mode": "replace"})
    return EXIT_OK


def cmd_speak_selection(args) -> int:
    """Capture the PRIMARY selection and POST it to the daemon's /speak endpoint.

    Returns EXIT_EMPTY_SELECTION (2) if the primary selection is empty,
    EXIT_TOOL_MISSING_OR_TIMEOUT (5) if wl-paste/xclip is missing or hung.
    """
    return _do_capture_and_speak(read_primary, "primary", args)


def cmd_speak_clipboard(args) -> int:
    """Capture the CLIPBOARD (after Ctrl+C) and POST it to /speak.

    Use this when PRIMARY is empty (common on GNOME Wayland Electron apps).
    """
    return _do_capture_and_speak(read_clipboard, "clipboard", args)


def cmd_pause(args) -> int:
    """Pause the current playback at the next sub-chunk boundary (~100 ms)."""
    _post_to_daemon("/pause")
    return EXIT_OK


def cmd_resume(args) -> int:
    """Resume paused playback."""
    _post_to_daemon("/resume")
    return EXIT_OK


def cmd_toggle(args) -> int:
    """Flip between speaking and paused. No-op when idle or warming."""
    _post_to_daemon("/toggle")
    return EXIT_OK


def cmd_stop(args) -> int:
    """Stop the current job, flush the audio sink, drop all pending sentences."""
    _post_to_daemon("/stop")
    return EXIT_OK


def cmd_skip(args) -> int:
    """Skip the currently-playing sentence. Pre-fetched ready chunks are preserved."""
    _post_to_daemon("/skip")
    return EXIT_OK


def cmd_back(args) -> int:
    """Rewind to the previously-finished sentence (or restart current if none)."""
    _post_to_daemon("/back")
    return EXIT_OK


def cmd_status(args) -> int:
    """Print the daemon's /state response as indented JSON."""
    state = _get_from_daemon("/state")
    import json

    print(json.dumps(state, indent=2))
    return EXIT_OK


def cmd_download_models(args) -> int:
    """Fetch the Kokoro model artifacts into ~/.cache/lexaloud/models/.

    Idempotent — skips files that already pass the SHA256 check.
    """
    from .models import ensure_artifacts

    try:
        paths = ensure_artifacts(download_if_missing=True)
    except Exception as e:  # noqa: BLE001
        print(f"model download failed: {e}", file=sys.stderr)
        return EXIT_GENERIC_ERROR
    for name, path in paths.items():
        print(f"{name} -> {path}")
    return EXIT_OK


def cmd_setup(args) -> int:
    """Run post-install setup: download models, render systemd unit, print hotkey walkthrough."""
    from .setup import run_setup

    return run_setup(force=args.force)


def cmd_daemon(args) -> int:
    """Run the FastAPI daemon in the foreground. Normally invoked via systemd --user."""
    from .daemon import run

    run()
    return EXIT_OK


def cmd_bug_report(args) -> int:
    """Print a markdown-formatted bug report to stdout for pasting into an issue.

    Collects distro/kernel/desktop/GPU/Python/Lexaloud versions, daemon
    state, last_error, model cache state, sanitized config.toml, systemd
    unit status, and the last 200 journalctl lines. Redaction is on by
    default; pass `--full` to disable it.
    """
    from .bug_report import cmd_bug_report as _impl

    return _impl(args)


# ---------- argument parser ----------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lexaloud",
        description="Universal Linux text-to-speech tool for reading-along.",
    )
    p.add_argument("--version", action="version", version=f"lexaloud {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    def _add_capture_cmd(name: str, handler) -> None:
        sp = sub.add_parser(name, help=f"{name}: capture and speak")
        sp.add_argument("--max-bytes", type=int, default=None, help="override capture.max_bytes")
        sp.set_defaults(func=handler)

    _add_capture_cmd("speak-selection", cmd_speak_selection)
    _add_capture_cmd("speak-clipboard", cmd_speak_clipboard)

    for name, handler in [
        ("pause", cmd_pause),
        ("resume", cmd_resume),
        ("toggle", cmd_toggle),
        ("stop", cmd_stop),
        ("skip", cmd_skip),
        ("back", cmd_back),
        ("status", cmd_status),
        ("download-models", cmd_download_models),
        ("daemon", cmd_daemon),
    ]:
        sp = sub.add_parser(name, help=f"{name}")
        sp.set_defaults(func=handler)

    sp = sub.add_parser("setup", help="run first-time setup (post-install)")
    sp.add_argument("--force", action="store_true", help="overwrite existing systemd unit")
    sp.set_defaults(func=cmd_setup)

    sp = sub.add_parser(
        "bug-report",
        help="print a markdown-formatted bug report for pasting into a GitHub issue",
    )
    sp.add_argument(
        "--full",
        action="store_true",
        help="disable redaction (show $HOME paths and secret-looking config keys verbatim)",
    )
    sp.set_defaults(func=cmd_bug_report)

    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
