"""Tests for lexaloud.bug_report — diagnostic collector for `lexaloud bug-report`."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from lexaloud.bug_report import (
    _redact_home,
    _redact_toml_values,
    collect_bug_report,
)

# ---------- redaction ----------


def test_redact_home_replaces_home_with_tilde(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    text = f"see {tmp_path}/config/lexaloud/config.toml for details"
    redacted = _redact_home(text)
    assert str(tmp_path) not in redacted
    assert "~" in redacted


def test_redact_toml_values_hides_secret_keys():
    toml_text = """[api]
key = "sk-abc123"
endpoint = "https://example.com"
access_token = "very-secret"
[provider]
voice = "af_heart"
"""
    redacted = _redact_toml_values(toml_text)
    assert "sk-abc123" not in redacted
    assert "very-secret" not in redacted
    assert '"<REDACTED>"' in redacted
    # Non-secret values survive unchanged
    assert "https://example.com" in redacted
    assert "af_heart" in redacted


def test_redact_toml_values_case_insensitive_key_match():
    toml_text = 'API_KEY = "leaked"\nPassword = "p"\n'
    redacted = _redact_toml_values(toml_text)
    assert "leaked" not in redacted
    assert '"p"' not in redacted


# ---------- collect_bug_report smoke ----------


def test_collect_bug_report_produces_markdown(monkeypatch):
    """Smoke: the collector doesn't crash and emits something markdown-ish."""
    # Avoid touching the real daemon / journalctl / /etc/os-release
    with (
        patch("lexaloud.bug_report._get_daemon_state", return_value={}),
        patch("lexaloud.bug_report._get_journalctl_tail", return_value=""),
        patch("lexaloud.bug_report._get_model_cache_info", return_value=["- (stubbed)"]),
        patch("lexaloud.bug_report._get_config_contents", return_value="(stubbed)"),
        patch("lexaloud.bug_report._run", return_value="5.15.0"),
    ):
        text = collect_bug_report(redact=True)
    assert text.startswith("# Lexaloud bug report")
    assert "## Versions" in text
    assert "## Distro" in text
    assert "## Desktop session" in text
    assert "## GPU" in text
    assert "## Daemon state" in text
    assert "## Model cache" in text


def test_collect_bug_report_redaction_off_no_notice():
    with (
        patch("lexaloud.bug_report._get_daemon_state", return_value={}),
        patch("lexaloud.bug_report._get_journalctl_tail", return_value=""),
        patch("lexaloud.bug_report._get_model_cache_info", return_value=[]),
        patch("lexaloud.bug_report._get_config_contents", return_value=""),
        patch("lexaloud.bug_report._run", return_value=""),
    ):
        text = collect_bug_report(redact=False)
    assert "Redaction is on by default" not in text


# ---------- H1 regression: current_sentence must be redacted ----------


_SECRET = "the user's actual selected sentence about sensitive topic"


def _daemon_state_stub_with_sentence() -> dict:
    return {
        "state": "speaking",
        "current_sentence": _SECRET,
        "pending_count": 0,
        "ready_count": 1,
        "provider_name": "kokoro",
        "session_providers": ["CUDAExecutionProvider"],
        "last_error": None,
    }


def test_redacted_state_replaces_current_sentence():
    """current_sentence must never appear verbatim in redacted output."""
    with (
        patch(
            "lexaloud.bug_report._get_daemon_state",
            return_value=_daemon_state_stub_with_sentence(),
        ),
        patch("lexaloud.bug_report._get_journalctl_tail", return_value=""),
        patch("lexaloud.bug_report._get_model_cache_info", return_value=[]),
        patch("lexaloud.bug_report._get_config_contents", return_value=""),
        patch("lexaloud.bug_report._run", return_value=""),
    ):
        text = collect_bug_report(redact=True)
    assert _SECRET not in text
    assert "<redacted:" in text
    # Tokens are <sha1[:8]> (<N>ch) — quick sanity: the length marker appears
    assert f"({len(_SECRET)}ch)" in text


def test_full_mode_keeps_current_sentence():
    """``--full`` mode (redact=False) preserves the raw sentence for the user."""
    with (
        patch(
            "lexaloud.bug_report._get_daemon_state",
            return_value=_daemon_state_stub_with_sentence(),
        ),
        patch("lexaloud.bug_report._get_journalctl_tail", return_value=""),
        patch("lexaloud.bug_report._get_model_cache_info", return_value=[]),
        patch("lexaloud.bug_report._get_config_contents", return_value=""),
        patch("lexaloud.bug_report._run", return_value=""),
    ):
        text = collect_bug_report(redact=False)
    assert _SECRET in text
    assert "<redacted:" not in text
