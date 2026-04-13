"""Curated Kokoro voice and language constants for the control window."""

from __future__ import annotations

# The full voices pack ships ~50+ voices. We surface a curated subset in
# the dropdown to keep the UI usable; users can still set any voice via
# config.toml directly.

KOKORO_VOICES: list[tuple[str, str]] = [
    ("af_heart", "Heart — American female, warm (default)"),
    ("af_bella", "Bella — American female, bright"),
    ("af_nova", "Nova — American female, energetic"),
    ("af_sarah", "Sarah — American female, calm"),
    ("af_sky", "Sky — American female, light"),
    ("am_adam", "Adam — American male, deep"),
    ("am_michael", "Michael — American male, conversational"),
    ("am_onyx", "Onyx — American male, serious"),
    ("bf_emma", "Emma — British female"),
    ("bf_isabella", "Isabella — British female"),
    ("bm_george", "George — British male"),
    ("bm_lewis", "Lewis — British male"),
]

LANGUAGES: list[tuple[str, str]] = [
    ("en-us", "English (US)"),
    ("en-gb", "English (UK)"),
]
