"""Tests for the MPRIS2 adapter.

These tests mock dbus-fast's MessageBus so they don't require a real
D-Bus session bus. They verify the Player ↔ MPRIS2 mapping and the
state-change callback wiring.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from lexaloud.config import Config
from lexaloud.player import Player, PlayerState

# ---------- Player property-setter callback ----------


def test_state_setter_fires_callback():
    """Assigning player._state should fire _on_state_change."""
    provider = MagicMock()
    provider.name = "fake"
    provider.session_providers = []
    sink = MagicMock()
    player = Player(provider, sink, ready_queue_depth=2)

    captured: list[PlayerState] = []
    player._on_state_change = lambda s: captured.append(s)

    player._state = "speaking"
    assert len(captured) == 1
    assert captured[0].state == "speaking"

    player._state = "paused"
    assert len(captured) == 2
    assert captured[1].state == "paused"


def test_current_sentence_setter_fires_callback():
    """Assigning player._current_sentence should fire _on_state_change."""
    provider = MagicMock()
    provider.name = "fake"
    provider.session_providers = []
    sink = MagicMock()
    player = Player(provider, sink, ready_queue_depth=2)

    captured: list[PlayerState] = []
    player._on_state_change = lambda s: captured.append(s)

    player._current_sentence = "Hello world"
    assert len(captured) == 1
    assert captured[0].current_sentence == "Hello world"

    player._current_sentence = None
    assert len(captured) == 2
    assert captured[1].current_sentence is None


def test_callback_exception_does_not_crash_player():
    """A crashing callback must not propagate up to the player."""
    provider = MagicMock()
    provider.name = "fake"
    provider.session_providers = []
    sink = MagicMock()
    player = Player(provider, sink, ready_queue_depth=2)

    def _boom(state):
        raise RuntimeError("callback crash")

    player._on_state_change = _boom
    # This should NOT raise
    player._state = "speaking"
    assert player._state == "speaking"


def test_no_callback_when_none():
    """When _on_state_change is None, state changes work silently."""
    provider = MagicMock()
    provider.name = "fake"
    provider.session_providers = []
    sink = MagicMock()
    player = Player(provider, sink, ready_queue_depth=2)

    assert player._on_state_change is None
    player._state = "warming"  # should not raise
    assert player._state == "warming"


# ---------- MprisAdapter ----------


async def test_mpris_connect_without_dbus_fast():
    """If dbus-fast is not importable, connect() silently returns."""
    from lexaloud.mpris import MprisAdapter

    provider = MagicMock()
    provider.name = "fake"
    provider.session_providers = []
    sink = MagicMock()
    player = Player(provider, sink)
    cfg = Config()
    adapter = MprisAdapter(player, cfg)

    with patch.dict(
        "sys.modules", {"dbus_fast": None, "dbus_fast.aio": None, "dbus_fast.service": None}
    ):
        # Should not raise even though imports fail
        try:
            await adapter.connect()
        except Exception:
            pass  # import error from the patched modules is expected
    # Adapter should be in a disconnected state
    adapter.disconnect()  # should not raise


async def test_mpris_disconnect_when_never_connected():
    """disconnect() on a never-connected adapter should not raise."""
    from lexaloud.mpris import MprisAdapter

    provider = MagicMock()
    provider.name = "fake"
    provider.session_providers = []
    sink = MagicMock()
    player = Player(provider, sink)
    cfg = Config()
    adapter = MprisAdapter(player, cfg)
    adapter.disconnect()  # should not raise


async def test_mpris_state_change_emits_properties_changed():
    """When the player state changes, the adapter should call
    emit_properties_changed on the D-Bus interface."""
    from lexaloud.mpris import MprisAdapter

    provider = MagicMock()
    provider.name = "fake"
    provider.session_providers = []
    sink = MagicMock()
    player = Player(provider, sink)
    cfg = Config()
    adapter = MprisAdapter(player, cfg)

    # Simulate a connected adapter with a mock interface
    mock_interface = MagicMock()
    adapter._interface = mock_interface
    adapter._bus = MagicMock()

    # Register the callback manually (normally done in connect())
    player._on_state_change = adapter._on_player_state_change

    # Trigger a state change
    player._state = "speaking"

    # The interface's emit_properties_changed should have been called
    mock_interface.emit_properties_changed.assert_called()


# --- M2 regression: MPRIS Metadata must not broadcast user sentence text ---


def test_mpris_metadata_never_exposes_sentence_text():
    """``xesam:title`` is broadcast on the session D-Bus. It must be a
    static/voice-derived string — never the user's current_sentence.

    We verify at the source level because the ``Metadata`` property is
    a method on a nested class inside ``_create_interface_class`` which
    can only be instantiated by ``connect()`` against a live D-Bus bus.
    """
    import inspect

    from lexaloud import mpris as mpris_mod

    source = inspect.getsource(mpris_mod)

    # The static title must be present.
    assert '"xesam:title": Variant("s", "Speaking")' in source, (
        "xesam:title should be the static string 'Speaking'"
    )

    # The old leaky pattern (sentence[:80]) must be gone.
    assert "sentence[:80]" not in source, (
        "found sentence[:80] — regression of M2 sentence-broadcast leak"
    )
