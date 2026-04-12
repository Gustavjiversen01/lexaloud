# Lexaloud Roadmap

This document buckets features and improvements into upcoming versions.
Items are non-binding estimates; priorities may shift based on user
feedback.

## v0.1.1 (patch)

Bug fixes and small quality-of-life items based on early user feedback.

- `requirements-lock.*.txt` regenerated with `--generate-hashes` and
  `scripts/install.sh --require-hashes`
- Spike 1 per-application capture compatibility matrix populated from a
  real run on the target hardware; committed to `spikes/spike1_matrix.md`
- Python 3.13 CI matrix support once `phonemizer-fork` and `pysbd` ship
  compatible wheels
- Fedora 41 VM smoke test documented + CI job (if feasible)
- Demo GIF in the README

## v0.2.0

Larger features that require design discussion first.

- **Floating overlay UI** — always-on-top captions that highlight the
  current sentence, with mouse-through so underlying windows stay
  interactive
- **MPRIS2 integration** — media keys and system media widgets control
  lexaloud playback
- **XDG GlobalShortcuts portal** — Wayland-native global hotkey binding
  without GNOME gsettings hacks
- **`setuptools_scm`** — single-source version from git tags instead of
  hand-bumping `__init__.py` and `pyproject.toml`
- **`gui_control.py` decomposition** — split the 691-LOC single file into
  focused submodules (voice, hotkeys, speed, preview)
- **Strict mypy** — tighten CI so mypy errors fail the lint job
- **KDE and XFCE keybinding registration** — teach the Control window to
  write to the KDE KGlobalAccel daemon and XFCE's `xfconf` instead of
  greying out
- **Codecov integration** — line/branch coverage reporting (decision
  pending — may stay off for privacy)

## v0.3.0+

Speculative. Please file a discussion if you'd like to work on any of
these.

- **Karaoke word-level highlighting** — forced-align Kokoro output against
  the input text and highlight the currently-spoken word in the floating
  overlay
- **Browser extension** — page-level selection bridge for Firefox and
  Chromium that doesn't depend on the PRIMARY selection protocol
- **LLM-based text normalization** — local-only expansion of acronyms,
  equations, and edge-case abbreviations before TTS
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
