# Lexaloud Roadmap

This document buckets features and improvements into upcoming versions.
Items are non-binding estimates; priorities may shift based on user
feedback.

## v0.1.1 (done)

- Audio clipping fix (sink warmup, abort-only stop, PipeWire keepalive)

## v0.2.0 (done)

- ~~**Floating overlay UI**~~ -- shipped in v0.2.0
- ~~**MPRIS2 integration**~~ -- shipped in v0.2.0
- ~~**XDG GlobalShortcuts portal**~~ -- shipped in v0.2.0

## v0.2.1 (done)

- Lockfiles regenerated with SHA-256 hashes + `--require-hashes`
- Python 3.13 CI matrix support
- Demo GIF recording script (`scripts/record-demo.sh`)

## v0.3.0 (done)

- ~~**`setuptools_scm`**~~ — version derived from git tags
- ~~**`gui_control.py` decomposition**~~ — split into focused submodules
- ~~**Strict mypy**~~ — 0 errors, CI enforcement (no continue-on-error)
- ~~**Desktop-aware keybindings**~~ — GNOME, XFCE, KDE (read-only), null backend

## v0.3.x (done)

- ~~**Expanded rule-based preprocessing**~~ — academic abbreviations,
  number-to-words, URL/email, Unicode math symbols
- ~~**LLM-based text normalization**~~ — optional local LLM (Qwen2.5-1.5B)
  for domain acronyms, complex math, OCR artifacts, tables

## v0.4.0

Remaining items and new work.

- **Spike 1** — per-application capture compatibility matrix on real hardware
- **Fedora 41 VM smoke test** — documented + CI job (if feasible)
- **Codecov integration** — line/branch coverage reporting

## v0.4.0+

Speculative. Please file a discussion if you'd like to work on any of
these.

- **Karaoke word-level highlighting** — forced-align Kokoro output against
  the input text and highlight the currently-spoken word in the floating
  overlay
- **Browser extension** — page-level selection bridge for Firefox and
  Chromium that doesn't depend on the PRIMARY selection protocol
- **Additional providers** — Piper (CPU-friendly), Chatterbox, other
  local neural TTS backends
- **Flatpak / Snap / AppImage / AUR / COPR** packaging — assuming
  maintainer volunteers
- **PDF reading mode** — direct PDF input, sentence-by-sentence navigation

## Explicitly NOT on the roadmap

- Cloud TTS (Google, Azure, OpenAI, ElevenLabs) — Lexaloud is a
  privacy-first local tool
- Telemetry, usage statistics, crash reporting — see the privacy
  paragraph in README.md
- Mobile (Android, iOS) — Linux desktop only
- Windows or macOS — Linux only
