# Lexaloud

> A local, private Linux text-to-speech tool. Select text in any app, press
> a hotkey, hear it read by Kokoro-82M on your GPU.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![test](https://github.com/Gustavjiversen01/lexaloud/actions/workflows/test.yml/badge.svg)](https://github.com/Gustavjiversen01/lexaloud/actions/workflows/test.yml)
[![lint](https://github.com/Gustavjiversen01/lexaloud/actions/workflows/lint.yml/badge.svg)](https://github.com/Gustavjiversen01/lexaloud/actions/workflows/lint.yml)

Lexaloud reads academic prose, articles, and PDFs aloud while you follow along
on screen. It runs locally on your own GPU, uses the open-weights
[Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) neural voice model,
and sends nothing to the cloud.

## Features

- **Global hotkey** — bind `lexaloud speak-selection` or `speak-clipboard`
  to any GNOME Custom Shortcut. One keystroke from selecting text to
  hearing it.
- **Local GPU-accelerated neural TTS** — Kokoro-82M via `kokoro-onnx` on
  `onnxruntime-gpu` with CUDA execution provider. CPU fallback runs at
  ~10× real-time on modern CPUs, which is fine for reading along.
- **Sentence-granularity streaming** with bounded ready-queue backpressure
  and cooperative cancellation. Press a hotkey to pause, skip, rewind,
  or stop without clipping.
- **GTK3 tray indicator + control window** — launchable from GNOME
  Activities; voice/language/speed selection and hotkey remapping.
- **Privacy-first** — no telemetry, no cloud calls, no account required.
  See the Privacy section below.
- **Open-source stack** — MIT-licensed code, open-weights model.

## Requirements

- Linux. Tier 1: Ubuntu 24.04 / Debian 13. Tier 2: Fedora 41, Arch,
  Linux Mint, Pop!_OS (install paths documented but not CI-tested).
- Python 3.11 or newer
- ~400 MB disk for model artifacts
- NVIDIA GPU with CUDA 12-compatible driver (optional; CPU fallback
  works and is fine for reading-along speed)
- GNOME for the integrated hotkey + tray experience. Other desktops
  work via manual hotkey binding — see `docs/hotkeys/`.

## Quick start (Ubuntu / Debian)

```bash
sudo apt install python3-venv wl-clipboard xclip libportaudio2 libnotify-bin \
                 python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1

git clone https://github.com/Gustavjiversen01/lexaloud.git
cd lexaloud
./scripts/install.sh

~/.local/share/lexaloud/venv/bin/lexaloud setup

systemctl --user daemon-reload
systemctl --user enable --now lexaloud.service
```

Then bind `~/.local/share/lexaloud/venv/bin/lexaloud speak-selection` to a
GNOME Custom Shortcut (Settings → Keyboard → View and Customize Shortcuts
→ Custom Shortcuts → +). The `lexaloud setup` command prints the exact
binary path for your install and a full walkthrough.

Full walkthrough: [`docs/install/ubuntu-debian.md`](docs/install/ubuntu-debian.md).

### Other distros

- Fedora: [`docs/install/fedora.md`](docs/install/fedora.md)
- Arch: [`docs/install/arch.md`](docs/install/arch.md)
- Anything else: file a PR against `docs/install/` — the differences are
  mostly package names.

### Not via `pip install`

`pip install lexaloud` will NOT give you a working installation. The
runtime stack requires a specific `kokoro-onnx` + `onnxruntime-gpu`
install sequence (documented in `spikes/spike0_results.md`) that can't be
expressed in a single `pip install` command. `scripts/install.sh` is the
only supported install path for v0.1.x. A PyPI namespace placeholder
exists to reserve the name; installing it will print install instructions
and exit.

## CLI

```
lexaloud speak-selection      # capture PRIMARY selection, POST to daemon
lexaloud speak-clipboard      # capture CLIPBOARD (after Ctrl+C), POST to daemon
lexaloud pause
lexaloud resume
lexaloud toggle               # pause if speaking, resume if paused
lexaloud skip                 # skip the current sentence
lexaloud back                 # rewind one sentence
lexaloud stop
lexaloud status               # daemon state as JSON
lexaloud download-models      # idempotent artifact fetch
lexaloud setup                # first-time configuration walkthrough
lexaloud bug-report           # collect system info for a bug report
lexaloud daemon               # run the FastAPI daemon (usually via systemd)
```

Exit codes:

| Code | Meaning                                        |
|------|------------------------------------------------|
| 0    | success                                        |
| 1    | generic error                                  |
| 2    | empty selection / clipboard                    |
| 3    | daemon not running                             |
| 4    | oversized payload rejected by daemon           |
| 5    | capture tool missing or subprocess timed out   |

Full reference: [`docs/cli-reference.md`](docs/cli-reference.md).

## Why a hotkey, not a right-click menu?

Linux has no system-level context-menu API. Unlike Windows shell extensions
or macOS Services, there is no hook to add a "Lexaloud" item to every
application's right-click menu. The industry-standard replacement — and
what every similar Linux tool uses — is a global keyboard shortcut.

See [`docs/gotchas.md`](docs/gotchas.md) for the details and workarounds.

## Privacy

**Lexaloud performs no telemetry.** No text, metadata, or usage
statistics are transmitted anywhere. The only outbound network calls are
the one-time model downloads on first setup, fetched over HTTPS from the
[`kokoro-onnx`](https://github.com/thewh1teagle/kokoro-onnx) GitHub
releases page and SHA256-verified against pins in
[`src/lexaloud/models.py`](src/lexaloud/models.py).

The daemon listens on a Unix domain socket at
`$XDG_RUNTIME_DIR/lexaloud/lexaloud.sock` with mode 0700 (enforced by
systemd's `RuntimeDirectoryMode=`). Only processes running as your user
can reach it.

Selection text passed through the daemon is never written to disk and
never logged at any level higher than DEBUG. Log-level entries that
mention a sentence replace the content with a SHA-1 fingerprint and a
length so that `journalctl --user -u lexaloud.service` never contains
readable user text. See [`docs/troubleshooting.md`](docs/troubleshooting.md).

## Repository layout

```
src/lexaloud/         # the package
  cli.py              # argparse entry point + subcommand wiring
  daemon.py           # FastAPI app + uvicorn on Unix socket
  player.py           # job lifecycle, ready queue, pause/skip/back
  providers/          # SpeechProvider protocol + Kokoro + FakeProvider
  audio.py            # AudioSink / SoundDeviceSink / WavSink / NullSink
  preprocessor/       # PDF cleanup, segmentation, abbreviations, citations
  selection.py        # PRIMARY and CLIPBOARD capture with timeouts
  session.py          # XDG_SESSION_TYPE detection
  config.py           # ~/.config/lexaloud/config.toml loader
  models.py           # SHA256-pinned download + ORT environment guard
  setup.py            # `lexaloud setup` implementation
  platform.py         # distro / desktop / GPU detection helpers
  indicator.py        # GNOME tray indicator
  gui_control.py      # GTK3 control window
  bug_report.py       # `lexaloud bug-report` implementation
  templates/          # systemd unit + .desktop + config example templates

scripts/install.sh    # Phase A bootstrap (venv + pip install + smoke)
requirements-lock.*.txt  # pinned runtime (cuda12 and cpu variants)
spikes/               # Spike 0 (Kokoro) + Spike 1 (selection capture)
docs/                 # install guides, architecture, API, hotkeys, etc.
tests/                # 145 passing tests, no GPU or audio device required
```

## Tests

```bash
env -u PYTHONPATH .venv-spike0/bin/python -m pytest tests/ \
    --ignore=tests/test_real_kokoro_smoke.py -q
```

145 tests run in ~2 seconds. None require the GPU or an audio device.

The daemon smoke tests use `httpx.AsyncClient` + `ASGITransport` driving
FastAPI's lifespan manually instead of `fastapi.testclient.TestClient`.
TestClient relies on anyio's portal to bridge sync test code into the
ASGI app on a worker thread; we observed it hang in this lockfile's
combination of `fastapi==0.135.3 / starlette==1.0.0 / anyio==4.13.0`,
and the async approach is closer to how the app actually runs.

The optional real-Kokoro smoke test uses the real model and the real
`sounddevice` stack (1 extra test, brings the total to 146):

```bash
LEXALOUD_REAL_TTS=1 .venv-spike0/bin/python -m pytest tests/test_real_kokoro_smoke.py -s
```

## Architecture

The design philosophy and key decisions (why a FastAPI daemon, why
sentence-granularity streaming, why `onnxruntime-gpu` with CUDA EP, why
the ONNX Runtime coexistence landmine matters) are documented in
[`docs/design-rationale.md`](docs/design-rationale.md). For a higher-level
component diagram, see [`docs/architecture.md`](docs/architecture.md).

## Known limitations (v0.1.0)

- **No floating overlay UI** — the current CLI + tray is the extent of
  the visual feedback. A floating caption overlay is planned for v0.2.
- **No karaoke word-level highlighting** — Kokoro's core API doesn't
  expose word timings; wiring a forced aligner is deferred.
- **No browser extension.** Deferred.
- **No LLM text normalization** — acronyms and equations may be
  mis-pronounced. Use the `speak-clipboard` + Ctrl+C workflow and edit
  the text before copying if needed.
- **Sentence-level pause** — the last ~100 ms of the current sentence
  may play out of the OS audio buffer after pressing `pause`.
- **GNOME Wayland primary-selection coverage depends on the app.**
  Some Electron apps (VS Code, Obsidian, Slack) don't publish to the
  PRIMARY selection. Workaround: use `speak-clipboard` + Ctrl+C. See
  [`docs/gotchas.md`](docs/gotchas.md).

Full list and v0.2+ roadmap: [`ROADMAP.md`](ROADMAP.md).

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Pull requests should be signed
off with `git commit -s` (DCO).

Please read [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) before
participating.

Security vulnerabilities: please use
[GitHub private vulnerability reporting](https://github.com/Gustavjiversen01/lexaloud/security/advisories/new)
rather than public issues. See [`SECURITY.md`](SECURITY.md).

## Acknowledgments

- **[Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M)** by hexgrad —
  the open-weights neural TTS model that makes this project practical.
- **[`kokoro-onnx`](https://github.com/thewh1teagle/kokoro-onnx)** by
  thewh1teagle — the ONNX wrapper and build pipeline.
- **[ONNX Runtime](https://onnxruntime.ai/)** and the NVIDIA CUDA team
  for making CUDA-accelerated inference accessible from Python.
- **[`phonemizer-fork`](https://github.com/kokoro-tts/phonemizer-fork)**,
  **[pysbd](https://github.com/nipunsadvilkar/pySBD)**, and
  **[`sounddevice`](https://python-sounddevice.readthedocs.io/)** — the
  quiet heroes of this dependency tree.
- **The GNOME and freedesktop.org communities** for the GTK, libnotify,
  systemd-user, and AppIndicator infrastructure that wire everything
  together.

Significant portions of this codebase were developed in collaboration with
[Claude](https://claude.ai) (Anthropic), primarily via Claude Code. Code
review and final editorial decisions are the author's.

## License

MIT. See [`LICENSE`](LICENSE) for the full text and
[`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md) for the runtime
dependency disclosures (notably: the TTS stack pulls in a GPL-3.0 dynamic
dependency chain via `phonemizer-fork` → `espeakng-loader` → `espeak-ng`).
