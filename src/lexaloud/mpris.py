"""MPRIS2 media player interface for Lexaloud.

Exports `org.mpris.MediaPlayer2` and `org.mpris.MediaPlayer2.Player` on
the D-Bus session bus so that desktop media keys, GNOME's top-bar media
indicator, KDE's media widget, Bluetooth headphone buttons, and
`playerctl` all control Lexaloud playback with zero user configuration.

Uses `dbus-fast` (asyncio-native) so the adapter runs in the daemon's
event loop and calls Player methods directly — no HTTP round-trip.

dbus-fast is an optional dependency. If it is not installed or the
D-Bus session bus is unavailable, the adapter silently disables itself
and the daemon works normally without media-key integration.
"""

# NOTE: do NOT use `from __future__ import annotations` in this module.
# dbus-fast reads return-type annotations at runtime to determine D-Bus
# signatures. With PEP 563 (stringified annotations), dbus-fast cannot
# distinguish our D-Bus type codes ("b", "s", "d") from forward refs.

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .config import Config
    from .player import Player, PlayerState

log = logging.getLogger(__name__)

# MPRIS2 well-known bus name and object path
BUS_NAME = "org.mpris.MediaPlayer2.lexaloud"
OBJECT_PATH = "/org/mpris/MediaPlayer2"

# D-Bus introspection XML for the two MPRIS2 interfaces.
# We declare only the subset we implement; clients discover capabilities
# via the Can* properties.
INTROSPECTION_XML = """
<!DOCTYPE node PUBLIC "-//freedesktop//DTD D-BUS Object Introspection 1.0//EN"
  "http://www.freedesktop.org/standards/dbus/1.0/introspect.dtd">
<node>
  <interface name="org.mpris.MediaPlayer2">
    <method name="Raise" />
    <method name="Quit" />
    <property name="CanQuit" type="b" access="read" />
    <property name="CanRaise" type="b" access="read" />
    <property name="HasTrackList" type="b" access="read" />
    <property name="Identity" type="s" access="read" />
    <property name="SupportedUriSchemes" type="as" access="read" />
    <property name="SupportedMimeTypes" type="as" access="read" />
  </interface>
  <interface name="org.mpris.MediaPlayer2.Player">
    <method name="Next" />
    <method name="Previous" />
    <method name="Pause" />
    <method name="PlayPause" />
    <method name="Stop" />
    <method name="Play" />
    <method name="Seek">
      <arg direction="in" name="Offset" type="x" />
    </method>
    <method name="SetPosition">
      <arg direction="in" name="TrackId" type="o" />
      <arg direction="in" name="Position" type="x" />
    </method>
    <method name="OpenUri">
      <arg direction="in" name="Uri" type="s" />
    </method>
    <property name="PlaybackStatus" type="s" access="read" />
    <property name="Metadata" type="a{sv}" access="read" />
    <property name="Rate" type="d" access="readwrite" />
    <property name="MinimumRate" type="d" access="read" />
    <property name="MaximumRate" type="d" access="read" />
    <property name="Volume" type="d" access="readwrite" />
    <property name="Position" type="x" access="read" />
    <property name="CanGoNext" type="b" access="read" />
    <property name="CanGoPrevious" type="b" access="read" />
    <property name="CanPlay" type="b" access="read" />
    <property name="CanPause" type="b" access="read" />
    <property name="CanSeek" type="b" access="read" />
    <property name="CanControl" type="b" access="read" />
  </interface>
</node>
"""


class MprisAdapter:
    """Bridges Lexaloud's Player to the MPRIS2 D-Bus interface.

    Lifecycle:
        adapter = MprisAdapter(player, cfg)
        await adapter.connect()    # in daemon lifespan startup
        ...
        adapter.disconnect()       # in daemon lifespan shutdown
    """

    def __init__(self, player: "Player", cfg: "Config") -> None:
        self._player = player
        self._cfg = cfg
        self._bus: Any = None  # dbus_fast.aio.MessageBus | None
        self._interface: Any = None

    async def connect(self) -> None:
        """Connect to the session bus and export the MPRIS2 interfaces."""
        try:
            from dbus_fast import Variant
            from dbus_fast.aio import MessageBus
            from dbus_fast.service import PropertyAccess, ServiceInterface, dbus_property, method
        except ImportError:
            log.info("dbus-fast not installed; MPRIS2 integration disabled")
            return

        # Build the service interface class dynamically so the dbus_fast
        # import is fully deferred.
        adapter = self

        class _RootInterface(ServiceInterface):
            def __init__(self):
                super().__init__("org.mpris.MediaPlayer2")

            @method()
            def Raise(self) -> None:
                pass  # no GUI to raise

            @method()
            def Quit(self) -> None:
                pass  # daemon lifecycle is managed by systemd

            @dbus_property(access=PropertyAccess.READ)
            def CanQuit(self) -> "b":  # noqa: F821
                return False

            @dbus_property(access=PropertyAccess.READ)
            def CanRaise(self) -> "b":  # noqa: F821
                return False

            @dbus_property(access=PropertyAccess.READ)
            def HasTrackList(self) -> "b":  # noqa: F821
                return False

            @dbus_property(access=PropertyAccess.READ)
            def Identity(self) -> "s":  # noqa: F821
                return "Lexaloud"

            @dbus_property(access=PropertyAccess.READ)
            def SupportedUriSchemes(self) -> "as":  # noqa: F821, F722
                return []

            @dbus_property(access=PropertyAccess.READ)
            def SupportedMimeTypes(self) -> "as":  # noqa: F821, F722
                return []

        class _PlayerInterface(ServiceInterface):
            def __init__(self):
                super().__init__("org.mpris.MediaPlayer2.Player")

            @method()
            async def Play(self) -> None:
                await adapter._player.resume()

            @method()
            async def Pause(self) -> None:
                await adapter._player.pause()

            @method()
            async def PlayPause(self) -> None:
                s = adapter._player.state.state
                if s == "speaking":
                    await adapter._player.pause()
                elif s == "paused":
                    await adapter._player.resume()

            @method()
            async def Stop(self) -> None:
                await adapter._player.stop()

            @method()
            async def Next(self) -> None:
                await adapter._player.skip()

            @method()
            async def Previous(self) -> None:
                await adapter._player.back()

            @method()
            def Seek(self, offset: "x") -> None:  # noqa: F821
                pass  # TTS has no seek

            @method()
            def SetPosition(self, track_id: "o", position: "x") -> None:  # noqa: F821
                pass

            @method()
            def OpenUri(self, uri: "s") -> None:  # noqa: F821
                pass

            @dbus_property(access=PropertyAccess.READ)
            def PlaybackStatus(self) -> "s":  # noqa: F821
                s = adapter._player.state.state
                if s == "speaking":
                    return "Playing"
                if s == "paused":
                    return "Paused"
                return "Stopped"

            @dbus_property(access=PropertyAccess.READ)
            def Metadata(self) -> "a{sv}":  # noqa: F821, F722
                sentence = adapter._player.state.current_sentence
                if sentence is None:
                    return {
                        "mpris:trackid": Variant("o", "/org/mpris/MediaPlayer2/TrackList/NoTrack"),
                    }
                title = sentence[:80] + "..." if len(sentence) > 80 else sentence
                voice = adapter._cfg.provider.voice
                return {
                    "mpris:trackid": Variant("o", "/org/lexaloud/sentence"),
                    "xesam:title": Variant("s", title),
                    "xesam:artist": Variant("as", [f"Kokoro — {voice}"]),
                }

            @dbus_property()
            def Rate(self) -> "d":  # noqa: F821
                return 1.0

            @Rate.setter
            def Rate(self, value: "d") -> None:  # noqa: F821, F811
                pass  # speed is controlled via config, not MPRIS

            @dbus_property(access=PropertyAccess.READ)
            def MinimumRate(self) -> "d":  # noqa: F821
                return 1.0

            @dbus_property(access=PropertyAccess.READ)
            def MaximumRate(self) -> "d":  # noqa: F821
                return 1.0

            @dbus_property()
            def Volume(self) -> "d":  # noqa: F821
                return 1.0

            @Volume.setter
            def Volume(self, value: "d") -> None:  # noqa: F821, F811
                pass  # volume is OS-level

            @dbus_property(access=PropertyAccess.READ)
            def Position(self) -> "x":  # noqa: F821
                return 0  # no meaningful position for TTS

            @dbus_property(access=PropertyAccess.READ)
            def CanGoNext(self) -> "b":  # noqa: F821
                return adapter._player.state.pending_count > 0

            @dbus_property(access=PropertyAccess.READ)
            def CanGoPrevious(self) -> "b":  # noqa: F821
                return True  # back always restarts current if no previous

            @dbus_property(access=PropertyAccess.READ)
            def CanPlay(self) -> "b":  # noqa: F821
                return adapter._player.state.state == "paused"

            @dbus_property(access=PropertyAccess.READ)
            def CanPause(self) -> "b":  # noqa: F821
                return adapter._player.state.state == "speaking"

            @dbus_property(access=PropertyAccess.READ)
            def CanSeek(self) -> "b":  # noqa: F821
                return False

            @dbus_property(access=PropertyAccess.READ)
            def CanControl(self) -> "b":  # noqa: F821
                return True

        try:
            bus = await MessageBus().connect()
        except Exception as e:
            log.warning("could not connect to D-Bus session bus: %s", e)
            return

        self._bus = bus
        root_iface = _RootInterface()
        player_iface = _PlayerInterface()
        self._interface = player_iface

        bus.export(OBJECT_PATH, root_iface)
        bus.export(OBJECT_PATH, player_iface)

        try:
            await bus.request_name(BUS_NAME)
        except Exception as e:
            log.warning("could not claim MPRIS2 bus name %s: %s", BUS_NAME, e)
            try:
                bus.disconnect()
            except Exception:
                pass
            self._bus = None
            return

        # Register the state-change callback so property changes are
        # emitted on D-Bus whenever the player transitions state.
        self._player._on_state_change = self._on_player_state_change
        log.info("MPRIS2 interface exported at %s", BUS_NAME)

    def _on_player_state_change(self, state: "PlayerState") -> None:
        """Called by the Player property setters whenever state or
        current_sentence changes. Emits PropertiesChanged on D-Bus."""
        if self._interface is None or self._bus is None:
            return
        try:
            self._interface.emit_properties_changed()
        except Exception:  # noqa: BLE001
            pass  # best-effort; never crash the player

    def disconnect(self) -> None:
        """Disconnect from the session bus. Safe to call if never connected."""
        if self._player._on_state_change is self._on_player_state_change:
            self._player._on_state_change = None
        if self._bus is not None:
            try:
                self._bus.disconnect()
            except Exception:  # noqa: BLE001
                pass
            self._bus = None
            self._interface = None
            log.info("MPRIS2 disconnected")
