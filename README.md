# LocalReadAloud (LRA)

A Linux text-to-speech tool for academic reading-along. Select text in any
application, press a global hotkey, and hear it spoken with a local neural
voice running on your GPU.

**Status:** Core MVP. Spike 0 (Kokoro on target hardware) complete. Spike 1
(per-application selection capture matrix) pending on the target machine.
No shipping polish (overlay, tray, MPRIS) yet.

## Design in one sentence

A FastAPI daemon running as a `systemd --user` unit, driven by a thin CLI
(`readaloud speak-selection` / `readaloud speak-clipboard`) bound to a GNOME
custom shortcut, synthesizes sentence-at-a-time via Kokoro-82M on the local
GPU and streams through a lazily-opened `sounddevice` sink.

Full technical design: `~/.claude/plans/peppy-sprouting-knuth.md`.

## Why not a right-click menu?

Linux has no system-level context-menu API. Unlike Windows shell extensions
or macOS Services, there is no hook to add a "ReadAloud" item to every
application's right-click menu. The industry-standard replacement — and what
every similar Linux tool uses — is a global keyboard shortcut. See
`docs/gotchas.md` for the details.

## Requirements

- Ubuntu 24.04 (other distros may work but not tested)
- Python 3.11+
- NVIDIA GPU with CUDA 12-compatible driver (optional; CPU fallback runs at
  ~10× real-time, which is fine for reading-along)
- ~400 MB disk for model artifacts and dependencies

## Install

```bash
sudo apt install python3-venv wl-clipboard xclip libportaudio2 libnotify-bin

git clone <repo-url> LocalReadAloud
cd LocalReadAloud
./scripts/install.sh

~/.local/share/readaloud/venv/bin/readaloud setup

systemctl --user daemon-reload
systemctl --user enable --now readaloud.service
```

Then bind `readaloud speak-selection` (or `readaloud speak-clipboard`) to a
GNOME Custom Shortcut. `readaloud setup` prints the exact command path for
your install and an app-by-app walkthrough.

Full walkthrough: `docs/install-ubuntu-gnome.md`.

## CLI

```
readaloud speak-selection    # capture PRIMARY, POST to daemon
readaloud speak-clipboard    # capture CLIPBOARD, POST to daemon
readaloud pause
readaloud resume
readaloud skip               # skip current sentence
readaloud back               # rewind one sentence
readaloud stop
readaloud status
readaloud download-models    # idempotent artifact fetch
readaloud setup              # first-time configuration
readaloud daemon             # run the FastAPI daemon (usually invoked by systemd)
```

Exit codes:

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | generic error |
| 2 | empty selection / clipboard |
| 3 | daemon not running |
| 4 | oversized payload rejected by daemon |
| 5 | capture tool missing or subprocess timed out |

## Repository layout

```
src/readaloud/        # the package
  cli.py              # argparse entry point
  daemon.py           # FastAPI app + uvicorn runner
  player.py           # job lifecycle, bounded queue, pause/skip/back
  providers/          # SpeechProvider protocol + Kokoro + FakeProvider
  audio.py            # AudioSink + SoundDeviceSink / WavSink / NullSink
  preprocessor/       # PDF cleanup, sentence segmentation, abbreviations, citations
  selection.py        # PRIMARY and CLIPBOARD capture with timeouts
  session.py          # XDG_SESSION_TYPE detection
  config.py           # ~/.config/readaloud/config.toml loader
  models.py           # model download + SHA256 verify + ORT env guard
  setup.py            # `readaloud setup` implementation

scripts/install.sh    # Phase A bootstrap (venv + pip install)
requirements-lock.txt # pinned runtime dependencies (from Spike 0)
spikes/               # Spike 0 (Kokoro) + Spike 1 (selection capture)
docs/                 # install walkthrough, gotchas, capture-matrix
tests/                # 73 passing tests, no GPU or audio device required
```

## Tests

```bash
env -u PYTHONPATH .venv-spike0/bin/python -m pytest tests/
```

73 tests run in ~1 second. None require the GPU or an audio device.

The optional real-Kokoro smoke test uses the real model and the real
`sounddevice` stack:

```bash
READALOUD_REAL_TTS=1 .venv-spike0/bin/python -m pytest tests/test_real_kokoro_smoke.py -s
```

## Known limitations (v1)

- No UI — pause/skip/stop are CLI only. A floating overlay, tray icon, and
  MPRIS2 integration are planned for polish.
- No karaoke word-level highlighting. Kokoro's core API doesn't expose
  word timings, and wiring a forced aligner is deferred.
- No browser extension. Deferred.
- No LLM-based text normalization — acronyms and equations may be mis-pronounced.
- Sentence-level pause (not mid-sentence). The last ~100 ms of the current
  sentence may play out of the OS audio buffer after pressing `pause`.
- GNOME Wayland primary-selection coverage depends on the app. See
  `docs/gotchas.md` and `docs/capture-matrix.md`.

## License

TBD.
