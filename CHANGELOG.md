# Changelog

All notable changes to Lexaloud are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] - 2026-04-13

### Added
- **Desktop-aware keybinding backends** — the control window auto-detects
  the desktop environment and uses the appropriate keybinding mechanism:
  - GNOME: gsettings custom-keybindings (existing behavior)
  - XFCE: `xfconf-query` subprocess
  - KDE Plasma 6+: read-only display (shortcuts managed via XDG
    GlobalShortcuts portal, registered by the daemon)
  - Other desktops: buttons greyed out with tooltip

### Changed
- **`setuptools_scm`** for automatic versioning — version is now derived
  from git tags. Dev builds show the distance from the latest tag.
  `fallback_version = "0.0.0"` handles shallow clones and tarballs.
- **`gui_control.py` decomposed** into a package with focused submodules:
  `_gi_shim`, `voices`, `config_io`, `keybindings`, `control_window`.
  Entry point `lexaloud.gui_control:main` is unchanged.
- **mypy strict enforcement** — all 47 errors fixed. The mypy CI job now
  fails the build (removed `continue-on-error`). dbus-fast's runtime
  string annotations handled via mypy overrides.

## [0.2.1] - 2026-04-13

### Changed
- **Supply-chain integrity**: both lockfiles now include SHA-256 hashes
  (762 hashes for CPU, 769 for CUDA 12). `scripts/install.sh` passes
  `--require-hashes` to pip, verifying every wheel against PyPI-published
  digests.
- **Python 3.13 CI**: test matrix now includes Python 3.13. Tests that
  depend on `python3-gi` (system GTK bindings) skip gracefully when the
  bindings are unavailable for the running Python version.
- Added `scripts/record-demo.sh` for recording demo GIFs via
  `wf-recorder` (Wayland) or `ffmpeg x11grab` (X11).

## [0.2.0] - 2026-04-13

### Added
- **MPRIS2 media player interface** via `dbus-fast` — desktop media keys,
  GNOME's top-bar media indicator, KDE's media widget, Bluetooth headphone
  buttons, and `playerctl` all control Lexaloud playback with zero
  configuration.
- **Floating overlay** — an always-on-top GTK3 sentence caption bar with
  dual Wayland backend (`gtk-layer-shell` for wlroots/KWin, `NOTIFICATION`
  type hint for X11/GNOME Wayland). Off by default; enable via
  `[advanced] overlay = true` or the control window's Settings tab.
- **XDG GlobalShortcuts portal** — Wayland-native global hotkeys on KDE
  Plasma 6+, Hyprland, and Sway (with `xdg-desktop-portal-wlr`). GNOME
  does not support this portal and continues using the gsettings path.
- Player state-change callbacks — property setters for `_state` and
  `_current_sentence` auto-fire a callback used by MPRIS2 to emit
  `PropertiesChanged` signals.
- `[advanced]` config section with `overlay` toggle.

### Changed
- `dbus-fast` is an optional dependency (`pip install lexaloud[dbus]`). The
  daemon works normally without it.
- Overlay toggle added to the control window's Settings tab.

### Fixed
- `_full_stop` no longer kills the warm audio stream when the player is
  idle, preventing the first-use audio clipping bug from recurring after
  a stop.
- Daemon log level override now works correctly when `cli.main()` sets
  the root logger to WARNING before `cmd_daemon`.

## [0.1.1] - 2026-04-12

### Fixed
- **First-use audio clipping**: the first 1-2 seconds of speech were cut
  on the initial hotkey press because PipeWire's 24000-to-44100 Hz
  resampler took ~1-2s to initialize. The daemon now pre-warms the audio
  stream during startup (writes 2s of silence alongside the Kokoro CUDA
  JIT warmup), so the stream is already hot when the user first presses
  the hotkey.
- **Audio stream stays alive across /stop**: `stop()` now aborts buffered
  audio without closing the PortAudio stream. The next `speak` reuses
  the warm stream with a 20ms restart prime instead of paying the full
  resampler cost again.
- **Event-loop stall on cold open**: `begin_stream()` now runs the
  blocking PortAudio constructor in an executor instead of blocking the
  asyncio event loop.

### Changed
- Removed 10 stale `# type: ignore` comments that mypy's
  `warn_unused_ignores` was flagging (the `[[tool.mypy.overrides]]`
  config already silences these modules).

[Unreleased]: https://github.com/Gustavjiversen01/lexaloud/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/Gustavjiversen01/lexaloud/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/Gustavjiversen01/lexaloud/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/Gustavjiversen01/lexaloud/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/Gustavjiversen01/lexaloud/compare/v0.1.0...v0.1.1

## [0.1.0] - 2026-04-09

### Added
- Initial public release.
- FastAPI daemon exposing a local HTTP API over a Unix domain socket at
  `$XDG_RUNTIME_DIR/lexaloud/lexaloud.sock` (mode 0700).
- Thin CLI: `lexaloud speak-selection / speak-clipboard / pause / resume /
  toggle / stop / skip / back / status / setup / daemon / download-models /
  bug-report`.
- GTK3 tray indicator (Ayatana AppIndicator3) and GTK3 control window
  launchable from GNOME Activities.
- Kokoro-82M ONNX provider via `kokoro-onnx` 0.5.0, on `onnxruntime-gpu`
  1.24.4 with CUDA execution provider and CPU fallback.
- Sentence-granularity streaming with bounded ready-queue backpressure
  and cooperative job-id cancellation.
- SHA256-pinned model artifact download with ORT environment guard.
- Platform detection helpers (`src/lexaloud/platform.py`) for distro,
  desktop environment, GPU vendor, and system site-packages path.
- Distro-aware installer (`scripts/install.sh --backend cpu|cuda12|auto`)
  for Ubuntu/Debian, Fedora, and Arch (Tier 1 and Tier 2).
- Comprehensive docs under `docs/`: install guides per distro,
  configuration, CLI reference, troubleshooting, FAQ, architecture,
  design rationale, model provenance, uninstall, HTTP API reference,
  per-DE hotkey guides.
- 166 unit tests, passing in under 3 seconds, with no GPU or audio
  device required at test time.

### Security
- Daemon listens on a Unix domain socket only (no TCP loopback).
- Selection-text log lines replaced with SHA-1 fingerprint + length so
  no user content leaks to `journalctl`.
- `/speak` rejects null bytes and caps per-sentence length at 4096 chars.
- `XDG_CONFIG_HOME` path is `.resolve()`'d to prevent traversal via
  malicious environment.

[0.1.0]: https://github.com/Gustavjiversen01/lexaloud/releases/tag/v0.1.0
