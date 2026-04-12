# Changelog

All notable changes to Lexaloud are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/Gustavjiversen01/lexaloud/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Gustavjiversen01/lexaloud/releases/tag/v0.1.0
