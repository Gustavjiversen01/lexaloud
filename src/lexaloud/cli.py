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
    """Fetch model artifacts into ~/.cache/lexaloud/models/.

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

    if getattr(args, "llm", False) or getattr(args, "all", False):
        result = _download_llm_model()
        if result != EXIT_OK:
            return result

    return EXIT_OK


def _download_llm_model() -> int:
    """Download the LLM normalizer model (GGUF) from HuggingFace."""
    import os

    from .config import NormalizerConfig, load_config
    from .models import MAX_MODEL_DOWNLOAD_BYTES, default_cache_dir

    cfg = load_config()
    nc = cfg.normalizer if cfg.normalizer.model_file else NormalizerConfig()

    # Path-containment check (M3): reject model_file values that resolve
    # outside the cache dir (e.g. ``"../../.bashrc"``). Without this,
    # a hostile or broken config.toml could cause the daemon to write
    # the downloaded bytes to an arbitrary user-writable location.
    cache = default_cache_dir().resolve()
    try:
        dest = (cache / nc.model_file).resolve()
    except (OSError, ValueError) as e:
        print(f"ERROR: invalid model_file path: {e}", file=sys.stderr)
        return EXIT_GENERIC_ERROR
    if not str(dest).startswith(str(cache) + os.sep):
        print(
            f"ERROR: model_file '{nc.model_file}' escapes the cache dir. "
            f"Refusing to download outside {cache}/.",
            file=sys.stderr,
        )
        return EXIT_GENERIC_ERROR

    if dest.exists():
        print(f"LLM model already exists: {dest}")
        return EXIT_OK

    url = f"https://huggingface.co/{nc.model_repo}/resolve/main/{nc.model_file}"
    print(f"Downloading LLM model: {nc.model_file}")
    print(f"  from: {url}")
    print(f"  to:   {dest}")
    print()

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".partial")

    try:
        from urllib.request import Request, urlopen

        req = Request(url, headers={"User-Agent": "lexaloud"})
        with urlopen(req) as resp, tmp.open("wb") as f:
            # Size-cap pre-check (M4): if the server announces a
            # Content-Length greater than our cap, refuse upfront.
            total = resp.headers.get("Content-Length")
            if total is not None:
                try:
                    announced = int(total)
                except ValueError:
                    announced = -1  # malformed; fall through to streaming cap
                if announced > MAX_MODEL_DOWNLOAD_BYTES:
                    print(
                        f"\nERROR: server reports Content-Length {announced} > "
                        f"cap {MAX_MODEL_DOWNLOAD_BYTES}. Refusing.",
                        file=sys.stderr,
                    )
                    # Let the except BaseException path clean up tmp.
                    raise RuntimeError("Content-Length exceeds cap")
            total_mb = int(total) / (1024 * 1024) if total else None
            downloaded = 0
            while True:
                block = resp.read(1 << 20)
                if not block:
                    break
                downloaded += len(block)
                # Size-cap streaming check (M4): even with a missing or
                # lying Content-Length, abort once downloaded exceeds cap.
                if downloaded > MAX_MODEL_DOWNLOAD_BYTES:
                    raise RuntimeError(
                        f"download exceeded {MAX_MODEL_DOWNLOAD_BYTES} bytes; "
                        "server may be streaming unbounded data. Aborting."
                    )
                f.write(block)
                mb = downloaded / (1024 * 1024)
                if total_mb:
                    pct = (downloaded / int(total)) * 100
                    print(
                        f"\r  Downloaded {mb:.0f} / {total_mb:.0f} MB ({pct:.0f}%)",
                        end="",
                        flush=True,
                    )
                else:
                    print(f"\r  Downloaded {mb:.0f} MB", end="", flush=True)
        print()  # newline after progress
        tmp.replace(dest)
    except BaseException:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise

    print(f"LLM model downloaded: {dest}")
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
        ("daemon", cmd_daemon),
    ]:
        sp = sub.add_parser(name, help=f"{name}")
        sp.set_defaults(func=handler)

    sp = sub.add_parser("download-models", help="fetch model artifacts")
    sp.add_argument(
        "--llm", action="store_true", help="also download the LLM normalizer model (~1 GB)"
    )
    sp.add_argument("--all", action="store_true", help="download all models (Kokoro + LLM)")
    sp.set_defaults(func=cmd_download_models)

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
