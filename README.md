# Lexaloud

A Linux text-to-speech tool for academic reading-along. Select text in any
application, press a global hotkey, and hear it spoken with a local neural
voice running on your GPU.

**Status:** v0.1.0 public release. 145 tests passing. Ships with a GTK3
tray indicator and control window; floating overlay and MPRIS2 integration
are planned for v0.2+.

## Design in one sentence

A FastAPI daemon running as a `systemd --user` unit, driven by a thin CLI
(`lexaloud speak-selection` / `lexaloud speak-clipboard`) bound to a GNOME
custom shortcut, synthesizes sentence-at-a-time via Kokoro-82M on the local
GPU and streams through a lazily-opened `sounddevice` sink.

Full technical design: see `docs/design-rationale.md` and `docs/architecture.md`.

## Why not a right-click menu?

Linux has no system-level context-menu API. Unlike Windows shell extensions
or macOS Services, there is no hook to add a "Lexaloud" item to every
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

git clone https://github.com/Gustavjiversen01/lexaloud.git
cd lexaloud
./scripts/install.sh

~/.local/share/lexaloud/venv/bin/lexaloud setup

systemctl --user daemon-reload
systemctl --user enable --now lexaloud.service
```

Then bind `lexaloud speak-selection` (or `lexaloud speak-clipboard`) to a
GNOME Custom Shortcut. `lexaloud setup` prints the exact command path for
your install and an app-by-app walkthrough.

Full walkthrough: `docs/install-ubuntu-gnome.md`.

## CLI

```
lexaloud speak-selection    # capture PRIMARY, POST to daemon
lexaloud speak-clipboard    # capture CLIPBOARD, POST to daemon
lexaloud pause
lexaloud resume
lexaloud skip               # skip current sentence
lexaloud back               # rewind one sentence
lexaloud stop
lexaloud status
lexaloud download-models    # idempotent artifact fetch
lexaloud setup              # first-time configuration
lexaloud daemon             # run the FastAPI daemon (usually invoked by systemd)
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
src/lexaloud/        # the package
  cli.py              # argparse entry point
  daemon.py           # FastAPI app + uvicorn runner
  player.py           # job lifecycle, bounded queue, pause/skip/back
  providers/          # SpeechProvider protocol + Kokoro + FakeProvider
  audio.py            # AudioSink + SoundDeviceSink / WavSink / NullSink
  preprocessor/       # PDF cleanup, sentence segmentation, abbreviations, citations
  selection.py        # PRIMARY and CLIPBOARD capture with timeouts
  session.py          # XDG_SESSION_TYPE detection
  config.py           # ~/.config/lexaloud/config.toml loader
  models.py           # model download + SHA256 verify + ORT env guard
  setup.py            # `lexaloud setup` implementation

scripts/install.sh    # Phase A bootstrap (venv + pip install)
requirements-lock.txt # pinned runtime dependencies (from Spike 0)
spikes/               # Spike 0 (Kokoro) + Spike 1 (selection capture)
docs/                 # install walkthrough, gotchas, capture-matrix
tests/                # 145 passing tests, no GPU or audio device required
```

## Tests

```bash
env -u PYTHONPATH .venv-spike0/bin/python -m pytest tests/ --ignore=tests/test_real_kokoro_smoke.py
```

145 tests run in ~2.3 seconds. None require the GPU or an audio device.

The daemon smoke tests use `httpx.AsyncClient` + `ASGITransport` driving
FastAPI's lifespan manually, instead of `fastapi.testclient.TestClient`.
TestClient relies on anyio's portal to bridge sync test code into the
ASGI app on a worker thread; we observed it hang in this lockfile's
combination of `fastapi==0.135.3 / starlette==1.0.0 / anyio==4.13.0`,
and the async approach is closer to how the app actually runs anyway.

The optional real-Kokoro smoke test uses the real model and the real
`sounddevice` stack (1 extra test, brings the total to 146):

```bash
LEXALOUD_REAL_TTS=1 .venv-spike0/bin/python -m pytest tests/test_real_kokoro_smoke.py -s
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

MIT. See `LICENSE` for the full text and `THIRD_PARTY_LICENSES.md` for
the runtime dependency disclosures (kokoro-onnx, phonemizer-fork,
espeakng-loader).
