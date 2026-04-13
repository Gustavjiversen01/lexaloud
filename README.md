# Lexaloud

> A local, private text-to-speech tool for Linux. Select text, press a
> hotkey, hear it read by a neural voice running on your own machine.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![test](https://github.com/Gustavjiversen01/lexaloud/actions/workflows/test.yml/badge.svg)](https://github.com/Gustavjiversen01/lexaloud/actions/workflows/test.yml)
[![lint](https://github.com/Gustavjiversen01/lexaloud/actions/workflows/lint.yml/badge.svg)](https://github.com/Gustavjiversen01/lexaloud/actions/workflows/lint.yml)

<!-- Record a demo with: ./scripts/record-demo.sh -->
<!-- ![demo](docs/demo.gif) -->

## How it works

1. **Select text** in any application
2. **Press a global hotkey** (e.g., `Ctrl+0`)
3. **Hear it spoken** sentence by sentence, with pause / skip / rewind controls

Lexaloud runs a small daemon on your machine that synthesizes speech
using [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M), an
open-weights neural voice model. Nothing leaves your computer — no
cloud API, no account, no telemetry.

To hear what Kokoro sounds like before installing, try the
[live demo on Hugging Face](https://huggingface.co/spaces/hexgrad/Kokoro-TTS).

## Features

- **Global hotkey on any desktop** — works on GNOME, KDE Plasma,
  Sway, Hyprland, XFCE, Cinnamon, and any window manager that
  supports custom keybindings. GNOME is the primary tested path with
  integrated tray + hotkey UI; other desktops bind the same CLI
  commands manually. See [`docs/hotkeys/`](docs/hotkeys/).
- **MPRIS2 / media keys** — desktop media keys, GNOME's top-bar
  media indicator, KDE's media widget, Bluetooth headphone buttons,
  and `playerctl` all control Lexaloud playback with zero
  configuration. Uses `dbus-fast` (optional dependency).
- **Floating overlay** — an always-on-top sentence caption bar (off
  by default). Enable via `[advanced] overlay = true` in
  `config.toml` or the control window's Settings tab. Supports both
  `gtk-layer-shell` (wlroots/KWin) and X11/GNOME Wayland fallback.
- **XDG GlobalShortcuts portal** — Wayland-native global hotkey
  binding on KDE Plasma 6+, Sway, and Hyprland via the
  `org.freedesktop.portal.GlobalShortcuts` portal. GNOME does not
  support this portal and continues using the gsettings path.
- **GPU-accelerated neural TTS** — Kokoro-82M via `kokoro-onnx` on
  `onnxruntime-gpu` with NVIDIA CUDA. CPU fallback runs at ~10x
  real-time, which is fine for reading along.
- **Sentence-granularity streaming** with bounded backpressure and
  cooperative cancellation. Pause, skip, rewind, or stop mid-article
  without audio clipping.
- **12 built-in voices** — American and British, male and female,
  from warm to serious. The control window lets you preview and switch
  voices; see the full list in [`docs/models.md`](docs/models.md).
- **GTK3 tray indicator + control window** — visible on any desktop
  that supports AppIndicator (GNOME with the `ubuntu-appindicators`
  extension, KDE, Budgie, etc.). Voice, speed, and hotkey settings.
  The CLI works without the tray on minimal setups.
- **Privacy-first** — see the [Privacy](#privacy) section.
- **Open-source** — MIT-licensed code, Apache-2.0-licensed model
  weights. See [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md).

## Requirements

| Requirement | Details |
|-------------|---------|
| **OS** | Linux only. Tier 1: Ubuntu 24.04, Debian 13. Tier 2: Fedora 41, Arch, Mint, Pop!_OS. Not supported: Windows, macOS. |
| **Init system** | systemd (for the `--user` daemon unit). Non-systemd distros (Artix, Void) can run `lexaloud daemon` manually. |
| **Python** | 3.11 or newer |
| **GPU (optional)** | NVIDIA with CUDA 12-compatible driver. AMD ROCm and Intel Arc are **not yet supported** — the daemon falls back to CPU, which runs at ~10x real-time and is fine for reading along. |
| **Audio** | PipeWire, PulseAudio, or bare ALSA (via PortAudio/`libportaudio2`). Most desktop Linux distros ship PipeWire by default. |
| **Disk** | ~400 MB for model weights (downloaded once on first setup) |
| **Desktop (optional)** | GNOME for the integrated tray + hotkey UI. KDE, Sway, XFCE, Cinnamon, and others work via manual hotkey binding — see [`docs/hotkeys/`](docs/hotkeys/). The CLI works headless. |

## Install

### Ubuntu / Debian (Tier 1)

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

Then bind a hotkey — see [`docs/hotkeys/gnome.md`](docs/hotkeys/gnome.md)
or the walkthrough `lexaloud setup` prints.

Full walkthrough: [`docs/install/ubuntu-debian.md`](docs/install/ubuntu-debian.md)

### Fedora (Tier 2)

```bash
sudo dnf install python3 python3-pip python3-gobject gtk3 \
                 wl-clipboard xclip portaudio libnotify
```

Then the same `git clone` → `./scripts/install.sh` → `lexaloud setup` →
`systemctl` flow. Full walkthrough:
[`docs/install/fedora.md`](docs/install/fedora.md)

### Arch / Manjaro (Tier 2)

```bash
sudo pacman -S python python-gobject gtk3 wl-clipboard xclip portaudio libnotify
```

Then `git clone` → `./scripts/install.sh` → `lexaloud setup` → `systemctl`.
Full walkthrough: [`docs/install/arch.md`](docs/install/arch.md)

### Other distros

The installer auto-detects your distro via `/etc/os-release` and prints
the right package names if any are missing. For distros not in the table,
file a PR against [`docs/install/`](docs/install/).

### GPU backend

The installer detects NVIDIA via `nvidia-smi` and picks the right
lockfile automatically. To force a backend:

```bash
./scripts/install.sh --backend cuda12   # NVIDIA GPU
./scripts/install.sh --backend cpu      # CPU only (AMD, Intel, or no GPU)
```

### Wayland users: read this

On GNOME Wayland (the default on Ubuntu 24.04), `speak-selection` may
return empty for some apps (VS Code, Obsidian, Slack) because Electron
apps don't always publish to the PRIMARY selection. The reliable
workflow is:

1. **Ctrl+C** to copy the selection to the clipboard
2. Press your **`speak-clipboard` hotkey**

Both commands are in the CLI — bind whichever suits your workflow, or
bind both to different keys. Details in
[`docs/gotchas.md`](docs/gotchas.md).

### Not via `pip install`

`pip install lexaloud` does **not** give you a working installation.
The TTS runtime requires a specific install sequence for `kokoro-onnx`
+ `onnxruntime-gpu` that `pip` cannot express in one command (the two
packages share an internal directory and silently break each other if
both are installed normally — see
[`docs/design-rationale.md`](docs/design-rationale.md) for the full
story). `scripts/install.sh` is the only supported install path.

## CLI

```
lexaloud speak-selection      # capture PRIMARY selection, speak it
lexaloud speak-clipboard      # capture CLIPBOARD (after Ctrl+C), speak it
lexaloud pause                # pause at the next sentence boundary
lexaloud resume
lexaloud toggle               # pause if speaking, resume if paused
lexaloud skip                 # skip the current sentence
lexaloud back                 # rewind one sentence
lexaloud stop                 # stop and clear the queue
lexaloud status               # daemon state as JSON
lexaloud download-models      # fetch model weights (~340 MB, once)
lexaloud setup                # first-time configuration walkthrough
lexaloud bug-report           # system diagnostics for filing issues
lexaloud daemon               # run the daemon (normally via systemd)
```

Exit codes: 0 success, 1 error, 2 empty selection, 3 daemon down,
4 oversized payload, 5 capture tool missing/timeout.

Full reference: [`docs/cli-reference.md`](docs/cli-reference.md)

## Privacy

**Lexaloud performs no telemetry.** No text, metadata, or usage
statistics are transmitted anywhere. The only outbound network calls
are the one-time model downloads on first setup, fetched over HTTPS
from the [`kokoro-onnx`](https://github.com/thewh1teagle/kokoro-onnx)
GitHub releases page and SHA256-verified against pins in
[`src/lexaloud/models.py`](src/lexaloud/models.py).

The daemon listens on a **Unix domain socket** at
`$XDG_RUNTIME_DIR/lexaloud/lexaloud.sock` (mode 0700 enforced by
systemd's `RuntimeDirectoryMode=`). Only processes running as your user
can reach it. There is no open TCP port.

Selection text is never written to disk. Log entries that mention a
sentence replace the content with a SHA-1 fingerprint + length, so
`journalctl` never contains readable user text.

## Known limitations (v0.2.0)

- **NVIDIA only for GPU acceleration** — AMD ROCm and Intel Arc are
  not supported. CPU fallback works on any x86_64 Linux.
- **No karaoke word-level highlighting** — deferred (Kokoro doesn't
  expose word timings).
- **No browser extension** — deferred.
- **Sentence-level pause granularity** — the last ~100 ms of the
  current sub-chunk may play out after pressing pause.
- **GNOME Wayland primary-selection gaps** — some Electron apps don't
  publish to PRIMARY. Workaround: use `speak-clipboard` + Ctrl+C.
  See [`docs/gotchas.md`](docs/gotchas.md).
- **GlobalShortcuts portal not supported on GNOME** — GNOME 46/47
  does not implement the XDG GlobalShortcuts portal. GNOME users
  continue using the gsettings-based hotkey path.

Full list: [`ROADMAP.md`](ROADMAP.md)

## Architecture

A FastAPI daemon (systemd `--user`) owns the TTS provider and audio
sink. A thin CLI sends HTTP requests over the Unix socket. A GTK3
tray indicator polls daemon state for visual feedback.

Component diagram + data-flow walkthrough:
[`docs/architecture.md`](docs/architecture.md). Design decisions:
[`docs/design-rationale.md`](docs/design-rationale.md).

## Tests

```bash
# Set up a dev environment (one-time)
python3 -m venv .venv && source .venv/bin/activate
pip install -e .[test]

# Run the suite
python -m pytest tests/ --ignore=tests/test_real_kokoro_smoke.py -q
```

206 tests, ~2.5 seconds. No GPU or audio device required — tests use
`FakeProvider` + `NullSink` + `ASGITransport`.

There is also an optional integration test that uses the real Kokoro
model and `sounddevice` (1 extra test, 207 total):

```bash
LEXALOUD_REAL_TTS=1 python -m pytest tests/test_real_kokoro_smoke.py -s
```

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Pull requests should be
signed off with `git commit -s` (DCO).

Please read [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) before
participating.

Security vulnerabilities: use
[GitHub private vulnerability reporting](https://github.com/Gustavjiversen01/lexaloud/security/advisories/new)
rather than public issues. See [`SECURITY.md`](SECURITY.md).

## Acknowledgments

- **[Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M)** by
  hexgrad — the open-weights neural TTS model.
- **[`kokoro-onnx`](https://github.com/thewh1teagle/kokoro-onnx)** by
  thewh1teagle — the ONNX wrapper.
- **[ONNX Runtime](https://onnxruntime.ai/)** + NVIDIA CUDA for
  GPU-accelerated inference from Python.
- **[`phonemizer-fork`](https://github.com/kokoro-tts/phonemizer-fork)**,
  **[pysbd](https://github.com/nipunsadvilkar/pySBD)**, and
  **[`sounddevice`](https://python-sounddevice.readthedocs.io/)**.
- The **GNOME** and **freedesktop.org** communities for GTK, libnotify,
  systemd-user, and AppIndicator.

Significant portions of this codebase were developed in collaboration
with [Claude](https://claude.ai) (Anthropic) via Claude Code. Code
review and final editorial decisions are the author's.

## License

MIT. See [`LICENSE`](LICENSE) for the full text and
[`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md) for runtime
dependency disclosures (the TTS stack includes GPL-3.0 dynamic
dependencies via `phonemizer-fork` → `espeakng-loader` → `espeak-ng`).
