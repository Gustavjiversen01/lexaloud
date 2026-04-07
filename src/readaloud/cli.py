"""Command-line entry points for ReadAloud.

Subcommands:
    readaloud speak-selection    # capture PRIMARY, POST to daemon
    readaloud speak-clipboard    # capture CLIPBOARD, POST to daemon
    readaloud pause
    readaloud resume
    readaloud stop
    readaloud skip
    readaloud back
    readaloud status
    readaloud download-models
    readaloud setup
    readaloud daemon             # run the FastAPI daemon

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
from pathlib import Path

from . import __version__
from .config import load_config
from .selection import (
    CaptureResult,
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


log = logging.getLogger("readaloud.cli")


# ---------- daemon client helpers ----------


def _daemon_url(path: str) -> str:
    cfg = load_config()
    return f"http://{cfg.daemon.host}:{cfg.daemon.port}{path}"


def _daemon_down_error(msg: str) -> None:
    print(msg, file=sys.stderr)
    try_notify(
        "ReadAloud daemon not running",
        "Run `systemctl --user start readaloud.service`",
    )
    sys.exit(EXIT_DAEMON_DOWN)


def _parse_json_or_exit(resp) -> dict:
    import json

    if not resp.text:
        return {}
    try:
        return resp.json()
    except (json.JSONDecodeError, ValueError) as e:
        print(f"ReadAloud daemon returned malformed JSON: {e}", file=sys.stderr)
        sys.exit(EXIT_GENERIC_ERROR)


# connect: 1.5s (tolerates brief contention on busy systems);
# read: 5s (routes should return fast; Player.speak is non-blocking).
_DAEMON_TIMEOUT = None  # built lazily in _client()


def _client():
    import httpx

    global _DAEMON_TIMEOUT
    if _DAEMON_TIMEOUT is None:
        _DAEMON_TIMEOUT = httpx.Timeout(5.0, connect=1.5)
    return httpx.Client(timeout=_DAEMON_TIMEOUT)


def _post_to_daemon(path: str, json_body: dict | None = None) -> dict:
    import httpx

    url = _daemon_url(path)
    try:
        with _client() as client:
            resp = client.post(url, json=json_body or {})
    except (
        httpx.ConnectError,
        httpx.ConnectTimeout,
        httpx.NetworkError,
        httpx.ReadTimeout,
        httpx.RemoteProtocolError,
    ):
        _daemon_down_error(
            "ReadAloud daemon is not running or unresponsive. Start it with: "
            "systemctl --user start readaloud.service "
            "(or run `readaloud setup` if you haven't yet)."
        )
        return {}  # unreachable; placates type checkers
    except httpx.HTTPError as e:
        print(f"ReadAloud daemon request failed: {e}", file=sys.stderr)
        sys.exit(EXIT_GENERIC_ERROR)

    if resp.status_code == 413:
        print("Selection too large for the daemon to accept.", file=sys.stderr)
        try_notify("Selection too large", "ReadAloud refused an oversized payload.")
        sys.exit(EXIT_OVERSIZED)
    if resp.status_code >= 400:
        print(
            f"ReadAloud daemon returned {resp.status_code}: {resp.text}",
            file=sys.stderr,
        )
        sys.exit(EXIT_GENERIC_ERROR)
    return _parse_json_or_exit(resp)


def _get_from_daemon(path: str) -> dict:
    import httpx

    url = _daemon_url(path)
    try:
        with _client() as client:
            resp = client.get(url)
    except (
        httpx.ConnectError,
        httpx.ConnectTimeout,
        httpx.NetworkError,
        httpx.ReadTimeout,
        httpx.RemoteProtocolError,
    ):
        _daemon_down_error(
            "ReadAloud daemon is not running or unresponsive. Start it with: "
            "systemctl --user start readaloud.service"
        )
        return {}  # unreachable
    except httpx.HTTPError as e:
        print(f"ReadAloud daemon request failed: {e}", file=sys.stderr)
        sys.exit(EXIT_GENERIC_ERROR)
    if resp.status_code >= 400:
        print(
            f"ReadAloud daemon returned {resp.status_code}: {resp.text}",
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
    except SelectionEmpty as e:
        print(str(e), file=sys.stderr)
        if source_label == "primary":
            try_notify("Select text first", "ReadAloud: no primary selection found.")
        else:
            try_notify("Copy text first", "ReadAloud: clipboard is empty. Press Ctrl+C first.")
        return EXIT_EMPTY_SELECTION
    except SelectionToolMissing as e:
        print(str(e), file=sys.stderr)
        try_notify("ReadAloud: capture tool missing", str(e))
        return EXIT_TOOL_MISSING_OR_TIMEOUT
    except SelectionTimeout as e:
        print(str(e), file=sys.stderr)
        try_notify("ReadAloud: capture timed out", str(e))
        return EXIT_TOOL_MISSING_OR_TIMEOUT
    except SelectionError as e:
        print(str(e), file=sys.stderr)
        return EXIT_GENERIC_ERROR

    if result.truncated:
        try_notify(
            "Selection truncated",
            f"ReadAloud captured the first {max_bytes} bytes of a larger selection.",
        )

    _post_to_daemon("/speak", {"text": result.text, "mode": "replace"})
    return EXIT_OK


def cmd_speak_selection(args) -> int:
    return _do_capture_and_speak(read_primary, "primary", args)


def cmd_speak_clipboard(args) -> int:
    return _do_capture_and_speak(read_clipboard, "clipboard", args)


def cmd_pause(args) -> int:
    _post_to_daemon("/pause")
    return EXIT_OK


def cmd_resume(args) -> int:
    _post_to_daemon("/resume")
    return EXIT_OK


def cmd_stop(args) -> int:
    _post_to_daemon("/stop")
    return EXIT_OK


def cmd_skip(args) -> int:
    _post_to_daemon("/skip")
    return EXIT_OK


def cmd_back(args) -> int:
    _post_to_daemon("/back")
    return EXIT_OK


def cmd_status(args) -> int:
    state = _get_from_daemon("/state")
    import json

    print(json.dumps(state, indent=2))
    return EXIT_OK


def cmd_download_models(args) -> int:
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
    from .setup import run_setup

    return run_setup(force=args.force)


def cmd_daemon(args) -> int:
    from .daemon import run

    run()
    return EXIT_OK


# ---------- argument parser ----------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="readaloud",
        description="Universal Linux text-to-speech tool for reading-along.",
    )
    p.add_argument("--version", action="version", version=f"readaloud {__version__}")
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

    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
