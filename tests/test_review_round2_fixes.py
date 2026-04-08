"""Regression tests for the Round-2 review findings fixed after the
audio-pipeline commit. Covers:

- Silent Kokoro synthesis failure -> last_error surfaced via /state
- SelectionDisplayUnavailable vs SelectionEmpty
- config.toml TOMLDecodeError -> graceful fallback
- Pause-from-warming zombie state -> pause is a no-op during warming
- TOML writer proper control-character escaping
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from lexaloud.audio import NullSink
from lexaloud.config import Config, load_config
from lexaloud.player import Player
from lexaloud.providers.fake import FakeProvider
from lexaloud.selection import (
    SelectionDisplayUnavailable,
    _run_capture,
)


# ---------------------------------------------------------------------
# last_error propagation
# ---------------------------------------------------------------------


class _AlwaysFailingProvider:
    """Provider that returns None for every synthesize call, simulating a
    systemic synthesis failure (bad voice name, GPU OOM, etc.)."""

    name = "failing-silent"

    async def warmup(self) -> None:
        pass

    async def synthesize(self, sentence, job_id, is_current_job):
        # Pretend to try but return None (the "provider failed" signal).
        if not is_current_job(job_id):
            return None
        return None


@pytest.mark.asyncio
async def test_last_error_set_when_all_synthesis_fails():
    """If every sentence in a job returns None from the provider, the
    player must set last_error so the user sees WHY they got silence."""
    provider = _AlwaysFailingProvider()
    sink = NullSink()
    player = Player(provider, sink, ready_queue_depth=2)

    await player.speak(["one.", "two.", "three."])
    for _ in range(200):
        if player.state.state == "idle":
            break
        await asyncio.sleep(0.01)
    assert player.state.state == "idle"
    # No audio reached the sink.
    assert sink.samples_received == 0
    # last_error was populated with an actionable message.
    assert player.state.last_error is not None
    assert "journalctl" in player.state.last_error.lower() or "synthesis" in player.state.last_error.lower()


@pytest.mark.asyncio
async def test_last_error_cleared_on_new_speak():
    """A fresh /speak must clear the previous job's last_error so stale
    errors don't stick around forever."""
    provider = _AlwaysFailingProvider()
    sink = NullSink()
    player = Player(provider, sink, ready_queue_depth=2)

    await player.speak(["fails."])
    for _ in range(200):
        if player.state.state == "idle":
            break
        await asyncio.sleep(0.01)
    assert player.state.last_error is not None

    # Now swap in a working provider and start a new job.
    working = FakeProvider(seconds_per_sentence=0.02, synth_delay_ms=2)
    player._provider = working  # simulate provider change for test
    await player.speak(["this works."])
    for _ in range(200):
        if player.state.state == "idle":
            break
        await asyncio.sleep(0.01)
    assert player.state.last_error is None


@pytest.mark.asyncio
async def test_last_error_not_set_for_cancellation():
    """Cancelling a job (via stop or replace) must NOT set last_error —
    that's the user's explicit action, not a failure."""
    provider = FakeProvider(seconds_per_sentence=0.1, synth_delay_ms=50)
    sink = NullSink()
    player = Player(provider, sink, ready_queue_depth=2)

    await player.speak(["one.", "two.", "three.", "four.", "five."])
    await asyncio.sleep(0.02)
    await player.stop()
    assert player.state.state == "idle"
    assert player.state.last_error is None


# ---------------------------------------------------------------------
# SelectionDisplayUnavailable
# ---------------------------------------------------------------------


def _completed(returncode: int, stdout: bytes = b"", stderr: bytes = b""):
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_display_unavailable_raised_on_xclip_cant_open_display():
    with patch("lexaloud.selection.shutil.which", return_value="/usr/bin/xclip"):
        with patch(
            "lexaloud.selection.subprocess.run",
            return_value=_completed(
                1, stdout=b"", stderr=b"Error: Can't open display: \n"
            ),
        ):
            with pytest.raises(SelectionDisplayUnavailable):
                _run_capture(["xclip", "-o", "-selection", "primary"], 1.0)


def test_display_unavailable_raised_on_wl_paste_no_connection():
    with patch("lexaloud.selection.shutil.which", return_value="/usr/bin/wl-paste"):
        with patch(
            "lexaloud.selection.subprocess.run",
            return_value=_completed(
                1, stderr=b"failed to connect to wayland display\n"
            ),
        ):
            with pytest.raises(SelectionDisplayUnavailable):
                _run_capture(["wl-paste", "--primary", "--no-newline"], 1.0)


def test_empty_selection_still_returns_empty_bytes_not_display_error():
    """An empty selection (xclip exit 1 with empty stderr) must still
    produce an empty bytes result, not a SelectionDisplayUnavailable."""
    with patch("lexaloud.selection.shutil.which", return_value="/usr/bin/xclip"):
        with patch(
            "lexaloud.selection.subprocess.run",
            return_value=_completed(1, stdout=b"", stderr=b""),
        ):
            result = _run_capture(["xclip", "-o", "-selection", "primary"], 1.0)
    assert result == b""


# ---------------------------------------------------------------------
# config.toml TOMLDecodeError recovery
# ---------------------------------------------------------------------


def test_load_config_recovers_from_toml_syntax_error(tmp_path: Path):
    path = tmp_path / "broken.toml"
    path.write_text("[provider\nvoice = af_heart\n")  # missing closing bracket

    cfg = load_config(path)
    assert isinstance(cfg, Config)
    assert cfg.provider.voice == "af_heart"  # default


def test_load_config_recovers_from_read_error(tmp_path: Path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text("[provider]\nvoice = \"af_bella\"\n")

    # Simulate a permission-denied read.
    real_open = Path.open

    def blocking_open(self, *args, **kwargs):
        if self == path:
            raise PermissionError("nope")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", blocking_open)
    cfg = load_config(path)
    assert cfg.provider.voice == "af_heart"  # default


# ---------------------------------------------------------------------
# TOML escape — control chars are properly escaped
# ---------------------------------------------------------------------


def test_toml_escape_handles_control_chars():
    from lexaloud.gui_control import _toml_escape

    escaped = _toml_escape("line1\nline2\twith tab\tand \"quotes\"")
    # Every control char and quote is escaped.
    assert "\\n" in escaped
    assert "\\t" in escaped
    assert '\\"' in escaped
    # No literal newlines or tabs remain in the output.
    assert "\n" not in escaped
    assert "\t" not in escaped


def test_toml_save_load_round_trip(tmp_path, monkeypatch):
    from lexaloud.gui_control import _save_config_dict, _load_config_dict

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    data = {
        "provider": {
            "voice": "af_heart",
            "lang": "en-us",
            "speed": 1.15,
        },
    }
    _save_config_dict(data)
    loaded = _load_config_dict()
    assert loaded == data


def test_toml_save_warns_and_drops_unsupported_types(tmp_path, monkeypatch, caplog):
    from lexaloud.gui_control import _save_config_dict, _load_config_dict

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    data = {
        "provider": {"voice": "af_heart", "speed": 1.0},
        "weird": {"array_field": ["a", "b"], "voice": "af_bella"},
    }
    with caplog.at_level("WARNING"):
        _save_config_dict(data)
    # The unsupported array was dropped and warned.
    assert any("array_field" in rec.getMessage() for rec in caplog.records)
    loaded = _load_config_dict()
    # Scalar values in both sections survived.
    assert loaded["provider"] == {"voice": "af_heart", "speed": 1.0}
    assert loaded["weird"] == {"voice": "af_bella"}


def test_toml_save_does_not_write_empty_sections(tmp_path, monkeypatch):
    from lexaloud.gui_control import _save_config_dict

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    data = {"empty": {}, "provider": {"voice": "af_heart"}}
    _save_config_dict(data)
    content = (tmp_path / "lexaloud" / "config.toml").read_text()
    assert "[empty]" not in content
    assert "[provider]" in content
