"""Tests for the overlay module logic.

These tests exercise the state-driven logic (auto-hide, label text,
button sensitivity) WITHOUT instantiating real GTK windows -- no display
server required.

Strategy: we import the OverlayWindow class (the module-level gi imports
succeed because python3-gi is installed system-wide) but never call its
__init__ (which needs a live display). Instead, we create a lightweight
SimpleNamespace that carries the same attributes the methods expect, then
call the *unbound* class methods with it as ``self``.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

pytest.importorskip("lexaloud.overlay", reason="python3-gi not available for this Python version")

from lexaloud.overlay import (  # noqa: E402
    LABEL_PAUSE,
    LABEL_PLAY,
    OverlayWindow,
)


def _make_overlay() -> SimpleNamespace:
    """Build a fake ``self`` namespace that mirrors OverlayWindow's instance attrs."""
    mock_client = MagicMock()
    mock_client.is_closed = False  # prevent _ensure_client from replacing it
    ns = SimpleNamespace(
        _desktop=MagicMock(is_wayland=False, is_gnome=True),
        _use_layer=False,
        _client=mock_client,
        _last_state=None,
        _visible=False,
        _label=MagicMock(),
        _btn_pause=MagicMock(),
        _btn_skip=MagicMock(),
        _btn_stop=MagicMock(),
        # GTK-level methods called by _update_visibility
        show_all=MagicMock(),
        hide=MagicMock(),
        _position_window=MagicMock(),
    )
    # Bind internal methods that other methods call via self.xxx().
    # _post_action calls _ensure_client; _poll_state calls _fetch_state,
    # _update_label, _update_buttons, _update_visibility.
    ns._ensure_client = lambda: OverlayWindow._ensure_client(ns)
    ns._fetch_state = lambda: OverlayWindow._fetch_state(ns)
    ns._update_label = lambda state, sentence: OverlayWindow._update_label(ns, state, sentence)
    ns._update_buttons = lambda state: OverlayWindow._update_buttons(ns, state)
    ns._update_visibility = lambda state: OverlayWindow._update_visibility(ns, state)
    return ns


def _update_label(ns, state, sentence):
    OverlayWindow._update_label(ns, state, sentence)


def _update_buttons(ns, state):
    OverlayWindow._update_buttons(ns, state)


def _update_visibility(ns, state):
    OverlayWindow._update_visibility(ns, state)


def _post_action(ns, path):
    OverlayWindow._post_action(ns, path)


def _poll_state(ns):
    return OverlayWindow._poll_state(ns)


def _ensure_client(ns):
    OverlayWindow._ensure_client(ns)


# --- auto-hide tests ------------------------------------------------------


class TestAutoHide:
    def test_shows_when_speaking(self):
        ns = _make_overlay()
        _update_visibility(ns, "speaking")
        assert ns._visible is True
        ns.show_all.assert_called_once()

    def test_shows_when_paused(self):
        ns = _make_overlay()
        _update_visibility(ns, "paused")
        assert ns._visible is True

    def test_hides_when_idle(self):
        ns = _make_overlay()
        # First show, then hide.
        _update_visibility(ns, "speaking")
        _update_visibility(ns, "idle")
        assert ns._visible is False
        ns.hide.assert_called_once()

    def test_hides_when_warming(self):
        ns = _make_overlay()
        _update_visibility(ns, "speaking")
        _update_visibility(ns, "warming")
        assert ns._visible is False

    def test_no_double_show(self):
        ns = _make_overlay()
        _update_visibility(ns, "speaking")
        _update_visibility(ns, "speaking")
        # show_all should be called only once.
        assert ns.show_all.call_count == 1

    def test_no_double_hide(self):
        ns = _make_overlay()
        # Never shown, so hide should not be called.
        _update_visibility(ns, "idle")
        ns.hide.assert_not_called()


# --- label text tests -----------------------------------------------------


class TestLabelText:
    def test_shows_sentence_text(self):
        ns = _make_overlay()
        _update_label(ns, "speaking", "Hello world")
        ns._label.set_text.assert_called_with("Hello world")

    def test_preparing_when_sentence_is_none(self):
        ns = _make_overlay()
        _update_label(ns, "speaking", None)
        ns._label.set_text.assert_called_with("Preparing\u2026")

    def test_preparing_when_sentence_is_empty(self):
        ns = _make_overlay()
        _update_label(ns, "speaking", "")
        ns._label.set_text.assert_called_with("Preparing\u2026")

    def test_paused_shows_sentence(self):
        ns = _make_overlay()
        _update_label(ns, "paused", "Some sentence")
        ns._label.set_text.assert_called_with("Some sentence")

    def test_idle_clears_label(self):
        ns = _make_overlay()
        _update_label(ns, "idle", None)
        ns._label.set_text.assert_called_with("")


# --- button state tests ---------------------------------------------------


class TestButtons:
    def test_buttons_active_when_speaking(self):
        ns = _make_overlay()
        _update_buttons(ns, "speaking")
        ns._btn_pause.set_sensitive.assert_called_with(True)
        ns._btn_skip.set_sensitive.assert_called_with(True)
        ns._btn_stop.set_sensitive.assert_called_with(True)

    def test_buttons_inactive_when_idle(self):
        ns = _make_overlay()
        _update_buttons(ns, "idle")
        ns._btn_pause.set_sensitive.assert_called_with(False)
        ns._btn_skip.set_sensitive.assert_called_with(False)
        ns._btn_stop.set_sensitive.assert_called_with(False)

    def test_pause_label_toggles_to_play_when_paused(self):
        ns = _make_overlay()
        _update_buttons(ns, "paused")
        ns._btn_pause.set_label.assert_called_with(LABEL_PLAY)

    def test_pause_label_toggles_to_pause_when_speaking(self):
        ns = _make_overlay()
        _update_buttons(ns, "speaking")
        ns._btn_pause.set_label.assert_called_with(LABEL_PAUSE)


# --- button POST path tests ----------------------------------------------


class TestButtonActions:
    def test_pause_posts_toggle(self):
        ns = _make_overlay()
        _post_action(ns, "/toggle")
        ns._client.post.assert_called_with("/toggle")

    def test_skip_posts_skip(self):
        ns = _make_overlay()
        _post_action(ns, "/skip")
        ns._client.post.assert_called_with("/skip")

    def test_stop_posts_stop(self):
        ns = _make_overlay()
        _post_action(ns, "/stop")
        ns._client.post.assert_called_with("/stop")

    def test_post_action_swallows_errors(self):
        ns = _make_overlay()
        ns._client.post.side_effect = httpx.ConnectError("refused")
        # Should not raise.
        _post_action(ns, "/toggle")


# --- poll_state integration tests -----------------------------------------


class TestPollState:
    def test_poll_hides_on_daemon_down(self):
        ns = _make_overlay()
        ns._visible = True  # pretend it was showing
        ns._client.get.side_effect = httpx.ConnectError("refused")
        result = _poll_state(ns)
        assert result is True  # keeps polling
        assert ns._visible is False

    def test_poll_shows_on_speaking(self):
        ns = _make_overlay()
        resp_mock = MagicMock()
        resp_mock.json.return_value = {"state": "speaking", "current_sentence": "Test text"}
        ns._client.get.return_value = resp_mock
        _poll_state(ns)
        assert ns._visible is True
        ns._label.set_text.assert_called_with("Test text")

    def test_poll_returns_true_to_keep_polling(self):
        ns = _make_overlay()
        ns._client.get.side_effect = httpx.ConnectError("refused")
        assert _poll_state(ns) is True
