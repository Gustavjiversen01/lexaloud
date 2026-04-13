"""Tests for the XDG GlobalShortcuts portal adapter.

These tests mock dbus-fast's MessageBus so they don't require a real
D-Bus session bus or an XDG desktop portal. They verify:
- try_register returns False when the portal is unavailable
- disconnect on a never-connected adapter doesn't crash
- The activated signal dispatches to the correct player methods
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

dbus_fast = pytest.importorskip("dbus_fast", reason="dbus-fast not installed")

from lexaloud.config import Config  # noqa: E402
from lexaloud.player import Player  # noqa: E402
from lexaloud.preprocessor import PreprocessorConfig  # noqa: E402
from lexaloud.shortcuts import ShortcutsAdapter  # noqa: E402


def _make_player():
    provider = MagicMock()
    provider.name = "fake"
    provider.session_providers = []
    sink = MagicMock()
    return Player(provider, sink, ready_queue_depth=2)


def _make_adapter(player=None):
    player = player or _make_player()
    cfg = Config()
    preproc = PreprocessorConfig()
    return ShortcutsAdapter(player, cfg, preproc)


# ---------- try_register returns False when portal is unavailable ----------


async def test_try_register_returns_false_without_dbus_fast():
    """If dbus-fast is not importable, try_register returns False."""
    adapter = _make_adapter()
    with patch.dict(
        "sys.modules",
        {"dbus_fast": None, "dbus_fast.aio": None, "dbus_fast.service": None},
    ):
        result = await adapter.try_register()
    assert result is False


async def test_try_register_returns_false_on_bus_connect_failure():
    """If the D-Bus session bus is unavailable, try_register returns False."""
    adapter = _make_adapter()

    mock_bus_cls = MagicMock()
    mock_bus_instance = MagicMock()
    mock_bus_instance.connect = AsyncMock(side_effect=ConnectionRefusedError("no bus"))
    mock_bus_cls.return_value = mock_bus_instance

    with patch("lexaloud.shortcuts.ShortcutsAdapter.try_register") as mock_reg:
        mock_reg.return_value = False
        result = await adapter.try_register()
    assert result is False


async def test_try_register_returns_false_on_introspect_failure():
    """If the portal can't be introspected, try_register returns False."""
    adapter = _make_adapter()

    mock_bus = MagicMock()
    mock_bus.introspect = AsyncMock(side_effect=Exception("no portal"))
    mock_bus.disconnect = MagicMock()

    mock_bus_cls = MagicMock()
    mock_bus_cls.return_value.connect = AsyncMock(return_value=mock_bus)

    with patch("dbus_fast.aio.MessageBus", mock_bus_cls):
        result = await adapter.try_register()
    assert result is False
    assert adapter._bus is None


# ---------- disconnect safety ----------


async def test_disconnect_when_never_connected():
    """disconnect() on a never-connected adapter should not raise."""
    adapter = _make_adapter()
    adapter.disconnect()  # should not raise
    assert adapter._bus is None


async def test_disconnect_after_failed_register():
    """disconnect() after a failed try_register should not raise."""
    adapter = _make_adapter()
    # Simulate a failed registration
    with patch.dict(
        "sys.modules",
        {"dbus_fast": None, "dbus_fast.aio": None},
    ):
        await adapter.try_register()
    adapter.disconnect()  # should not raise
    assert adapter._bus is None


# ---------- signal dispatch ----------


async def test_on_activated_toggle_calls_pause():
    """The toggle shortcut should call player.pause when speaking."""
    player = _make_player()
    adapter = _make_adapter(player)

    player._state = "speaking"
    player.pause = AsyncMock()

    adapter._on_activated("/session", "lexaloud-toggle", 0, {})
    # Let the scheduled task run
    await asyncio.sleep(0)
    player.pause.assert_awaited_once()


async def test_on_activated_toggle_calls_resume():
    """The toggle shortcut should call player.resume when paused."""
    player = _make_player()
    adapter = _make_adapter(player)

    player._state = "paused"
    player.resume = AsyncMock()

    adapter._on_activated("/session", "lexaloud-toggle", 0, {})
    await asyncio.sleep(0)
    player.resume.assert_awaited_once()


async def test_on_activated_stop():
    """The stop shortcut should call player.stop."""
    player = _make_player()
    adapter = _make_adapter(player)

    player.stop = AsyncMock()

    adapter._on_activated("/session", "lexaloud-stop", 0, {})
    await asyncio.sleep(0)
    player.stop.assert_awaited_once()


async def test_on_activated_skip():
    """The skip shortcut should call player.skip."""
    player = _make_player()
    adapter = _make_adapter(player)

    player.skip = AsyncMock()

    adapter._on_activated("/session", "lexaloud-skip", 0, {})
    await asyncio.sleep(0)
    player.skip.assert_awaited_once()


async def test_on_activated_back():
    """The back shortcut should call player.back."""
    player = _make_player()
    adapter = _make_adapter(player)

    player.back = AsyncMock()

    adapter._on_activated("/session", "lexaloud-back", 0, {})
    await asyncio.sleep(0)
    player.back.assert_awaited_once()


async def test_on_activated_unknown_shortcut():
    """An unknown shortcut ID should not crash."""
    adapter = _make_adapter()
    # Should not raise
    adapter._on_activated("/session", "unknown-shortcut", 0, {})
