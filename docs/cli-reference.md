# CLI reference

All commands expect the lexaloud daemon to be running. Use
`lexaloud setup` for first-time configuration and
`systemctl --user enable --now lexaloud.service` to start the daemon.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | success |
| 1 | generic error |
| 2 | empty selection / clipboard |
| 3 | daemon not running |
| 4 | oversized payload rejected by daemon |
| 5 | capture tool missing or subprocess timed out |

## Subcommands

### `lexaloud speak-selection`
Capture the X11/Wayland PRIMARY selection and POST it to `/speak`.
Returns `2` if the primary selection is empty. Use this when you can
rely on PRIMARY working in your target app.

### `lexaloud speak-clipboard`
Capture the CLIPBOARD (populated by Ctrl+C) and POST it to `/speak`.
More reliable across app categories than PRIMARY, especially on
Electron apps under GNOME Wayland.

Flags:
- `--max-bytes N` — override `capture.max_bytes` for this one call.

### `lexaloud pause`
Pause playback at the next sub-chunk boundary (~100 ms latency).

### `lexaloud resume`
Resume paused playback.

### `lexaloud toggle`
Flip between speaking and paused. No-op when idle or warming. Useful
for a single-keystroke pause/resume hotkey.

### `lexaloud stop`
Stop the current job, flush the audio sink, drop all pending sentences.

### `lexaloud skip`
Skip the currently-playing sentence. Pre-fetched ready chunks are
preserved so the next sentence plays immediately.

### `lexaloud back`
Rewind to the previously-finished sentence (or restart the current one
if no previous sentence exists).

### `lexaloud status`
Print the daemon's `/state` response as indented JSON. Example:

```json
{
  "state": "speaking",
  "current_sentence": "The first sentence of the selection.",
  "pending_count": 4,
  "ready_count": 2,
  "provider_name": "kokoro",
  "session_providers": ["CUDAExecutionProvider", "CPUExecutionProvider"],
  "last_error": null
}
```

### `lexaloud download-models`
Fetch the Kokoro model artifacts into `~/.cache/lexaloud/models/`.
Idempotent — skips files that already pass the SHA256 check. Run this
if `lexaloud setup` didn't have network access at first install.

### `lexaloud setup`
Run post-install configuration: models + systemd unit + hotkey
walkthrough. Pass `--force` to overwrite an existing systemd unit.

### `lexaloud bug-report`
Print a markdown-formatted diagnostic report to stdout. Paste into a
GitHub issue. Default output redacts `$HOME` paths and TOML keys
matching `(?i)(key|token|secret|pass)`. Pass `--full` to disable
redaction (for private analysis only).

Example:

```bash
lexaloud bug-report > /tmp/lexaloud-bug.md
cat /tmp/lexaloud-bug.md | head -30
```

### `lexaloud daemon`
Run the FastAPI daemon in the foreground. Normally invoked via
systemd-user — you should not run this by hand unless you're
debugging a daemon-startup issue.

## Environment variables

- `LEXALOUD_REAL_TTS=1` — used only by
  `tests/test_real_kokoro_smoke.py` to opt into a real-model test run.
  No effect on the runtime CLI or daemon.
- `PYTHONPATH` — the systemd unit scrubs this at daemon startup, but if
  you invoke the CLI directly from a shell that sourced ROS 2 (or similar),
  unset `PYTHONPATH` first or prefix the command with `env -u PYTHONPATH`.
