"""Floating overlay bar for Lexaloud — shows current sentence + playback controls.

A separate GTK3 process (like the indicator) that displays a small
translucent bar at the bottom-center of the primary monitor while
Lexaloud is speaking. Auto-hides when idle/warming, auto-shows when
speaking/paused.

Requires the system packages ``python3-gi`` and ``gir1.2-gtk-3.0``.
Optionally uses ``gtk-layer-shell`` for proper overlay stacking on
non-GNOME Wayland compositors (sway, Hyprland, KDE).

Do NOT use ``from __future__ import annotations`` — GTK gi introspection
needs runtime type annotations to resolve GObject types correctly.
"""

import logging
import math
import sys

log = logging.getLogger(__name__)

# --- make the system-level gi module importable from inside the venv ------

try:
    import gi
except ImportError:
    from .platform import system_site_packages_candidates

    for _candidate in system_site_packages_candidates():
        sys.path.append(str(_candidate))
        try:
            import gi  # noqa: F811

            break
        except ImportError:
            continue
    else:
        raise ImportError(
            "Lexaloud overlay: cannot import the 'gi' Python bindings.\n"
            "Install them with one of:\n"
            "  sudo apt install python3-gi gir1.2-gtk-3.0  # Debian/Ubuntu\n"
            "  sudo dnf install python3-gobject gtk3        # Fedora\n"
            "  sudo pacman -S python-gobject gtk3            # Arch"
        )

try:
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
except ValueError as e:
    raise ImportError(
        f"Lexaloud overlay: missing GIR typelib: {e}. "
        "Install with `sudo apt install gir1.2-gtk-3.0`."
    ) from e

from gi.repository import Gdk, GLib, Gtk  # noqa: E402

# --- optional gtk-layer-shell for Wayland compositors ---------------------

HAS_LAYER_SHELL = False
try:
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import GtkLayerShell  # noqa: E402

    HAS_LAYER_SHELL = True
except (ValueError, ImportError):
    pass  # optional — fall back to type hints

# --- httpx import (deferred to method bodies for lighter startup) ---------

import httpx  # noqa: E402

from .config import socket_path  # noqa: E402
from .platform import detect_desktop  # noqa: E402

# --- constants ------------------------------------------------------------

POLL_INTERVAL_MS = 200
BAR_WIDTH = 500
BAR_HEIGHT = 80
CORNER_RADIUS = 16
BG_RGBA = (0.1, 0.1, 0.1, 0.85)
TEXT_COLOR_RGBA = (1.0, 1.0, 1.0, 1.0)
BUTTON_TEXT_COLOR = (1.0, 1.0, 1.0, 0.9)
BOTTOM_MARGIN = 24

# Unicode button labels
LABEL_PAUSE = "\u23f8"  # ⏸
LABEL_PLAY = "\u23f5"  # ⏵ (resume)
LABEL_SKIP = "\u23ed"  # ⏭
LABEL_STOP = "\u23f9"  # ⏹

# --- CSS for buttons and label --------------------------------------------

_CSS = b"""
.overlay-label {
    font-size: 14px;
    font-weight: 500;
}
.overlay-btn {
    background: transparent;
    border: none;
    box-shadow: none;
    padding: 4px 10px;
    min-width: 0;
    min-height: 0;
    font-size: 20px;
}
.overlay-btn:hover {
    background: rgba(255, 255, 255, 0.15);
    border-radius: 6px;
}
"""


def _use_layer_shell(desktop) -> bool:
    """Decide whether to use GtkLayerShell for overlay stacking.

    Use it on Wayland when the desktop is NOT GNOME (GNOME's Mutter
    does not support the wlr-layer-shell protocol) and when
    gtk-layer-shell is available.
    """
    return HAS_LAYER_SHELL and desktop.is_wayland and not desktop.is_gnome


class OverlayWindow(Gtk.Window):
    """Translucent floating bar with sentence text and playback controls."""

    def __init__(self) -> None:
        super().__init__(type=Gtk.WindowType.TOPLEVEL)

        self._desktop = detect_desktop()
        self._use_layer = _use_layer_shell(self._desktop)

        # Persistent httpx client for UDS polling + button actions.
        self._client: httpx.Client | None = None
        self._ensure_client()

        # Track last known state to avoid redundant show/hide calls.
        self._last_state: str | None = None
        self._visible = False

        self._setup_window()
        self._setup_css()
        self._build_ui()
        self._position_window()

        # Start polling daemon state.
        GLib.timeout_add(POLL_INTERVAL_MS, self._poll_state)

    # --- httpx client management ------------------------------------------

    def _ensure_client(self) -> None:
        """Create the persistent httpx.Client if not already open."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(
                transport=httpx.HTTPTransport(uds=str(socket_path())),
                base_url="http://lexaloud",
                timeout=httpx.Timeout(0.5, connect=0.5),
            )

    def _close_client(self) -> None:
        """Cleanly close the httpx client."""
        if self._client is not None and not self._client.is_closed:
            try:
                self._client.close()
            except Exception:  # noqa: BLE001
                pass
            self._client = None

    # --- window setup -----------------------------------------------------

    def _setup_window(self) -> None:
        self.set_decorated(False)
        self.set_accept_focus(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_app_paintable(True)
        self.set_default_size(BAR_WIDTH, BAR_HEIGHT)
        self.set_resizable(False)
        self.set_title("Lexaloud Overlay")

        # RGBA visual for translucency.
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual is not None:
            self.set_visual(visual)

        if self._use_layer:
            self._setup_layer_shell()
        else:
            self._setup_fallback_hints()

        self.connect("draw", self._on_draw)
        self.connect("destroy", self._on_destroy)

    def _setup_layer_shell(self) -> None:
        """Configure GtkLayerShell for proper Wayland overlay stacking."""
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, True)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.BOTTOM, BOTTOM_MARGIN)
        GtkLayerShell.set_exclusive_zone(self, -1)  # don't push other windows
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)

    def _setup_fallback_hints(self) -> None:
        """Use X11/GNOME-Wayland fallback: type hint + keep above."""
        self.set_type_hint(Gdk.WindowTypeHint.NOTIFICATION)
        self.set_keep_above(True)

    def _setup_css(self) -> None:
        provider = Gtk.CssProvider()
        provider.load_from_data(_CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    # --- UI construction --------------------------------------------------

    def _build_ui(self) -> None:
        # Main horizontal layout with some internal padding.
        main_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        main_box.set_margin_start(16)
        main_box.set_margin_end(12)
        main_box.set_margin_top(8)
        main_box.set_margin_bottom(8)

        # Sentence label — takes most of the width.
        self._label = Gtk.Label(label="")
        self._label.set_xalign(0.0)
        self._label.set_ellipsize(3)  # Pango.EllipsizeMode.END = 3
        self._label.set_max_width_chars(50)
        self._label.set_line_wrap(False)
        self._label.get_style_context().add_class("overlay-label")
        main_box.pack_start(self._label, True, True, 0)

        # Button box — right-aligned.
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)

        self._btn_pause = self._make_button(LABEL_PAUSE, self._on_pause_resume)
        self._btn_skip = self._make_button(LABEL_SKIP, self._on_skip)
        self._btn_stop = self._make_button(LABEL_STOP, self._on_stop)

        btn_box.pack_start(self._btn_pause, False, False, 0)
        btn_box.pack_start(self._btn_skip, False, False, 0)
        btn_box.pack_start(self._btn_stop, False, False, 0)

        main_box.pack_end(btn_box, False, False, 0)
        self.add(main_box)

    def _make_button(self, label: str, callback) -> Gtk.Button:
        btn = Gtk.Button(label=label)
        btn.set_relief(Gtk.ReliefStyle.NONE)
        btn.get_style_context().add_class("overlay-btn")
        btn.set_can_focus(False)
        btn.connect("clicked", callback)
        return btn

    # --- window positioning -----------------------------------------------

    def _position_window(self) -> None:
        """Center the bar at the bottom of the primary monitor.

        For layer-shell, positioning is handled by anchors/margins. For
        the fallback path, we compute the position manually.
        """
        if self._use_layer:
            return  # layer shell handles it via anchors

        display = Gdk.Display.get_default()
        if display is None:
            return
        monitor = display.get_primary_monitor()
        if monitor is None:
            monitor = display.get_monitor(0)
        if monitor is None:
            return
        geom = monitor.get_geometry()
        x = geom.x + (geom.width - BAR_WIDTH) // 2
        y = geom.y + geom.height - BAR_HEIGHT - BOTTOM_MARGIN
        self.move(x, y)

    # --- Cairo drawing (rounded rect + translucent bg) --------------------

    def _on_draw(self, widget, cr) -> bool:
        alloc = widget.get_allocation()
        w, h = alloc.width, alloc.height
        r = CORNER_RADIUS

        # Clear to fully transparent.
        cr.set_operator(0)  # cairo.OPERATOR_CLEAR = 0
        cr.paint()
        cr.set_operator(2)  # cairo.OPERATOR_OVER = 2

        # Rounded rectangle path.
        cr.new_sub_path()
        cr.arc(w - r, r, r, -math.pi / 2, 0)
        cr.arc(w - r, h - r, r, 0, math.pi / 2)
        cr.arc(r, h - r, r, math.pi / 2, math.pi)
        cr.arc(r, r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()

        # Fill with semi-transparent dark background.
        cr.set_source_rgba(*BG_RGBA)
        cr.fill()

        return False  # propagate to child widgets

    # --- state polling ----------------------------------------------------

    def _poll_state(self) -> bool:
        """Fetch daemon state and update the overlay. Returns True to keep polling."""
        state_data = self._fetch_state()
        if state_data is None:
            self._update_visibility("idle")
            return True

        state = state_data.get("state", "idle")
        sentence = state_data.get("current_sentence")

        self._update_label(state, sentence)
        self._update_buttons(state)
        self._update_visibility(state)

        return True  # keep polling

    def _fetch_state(self) -> dict | None:
        """GET /state from the daemon. Returns parsed JSON or None on error."""
        try:
            self._ensure_client()
            assert self._client is not None
            resp = self._client.get("/state")
            return resp.json()
        except Exception:  # noqa: BLE001
            # Daemon down, socket missing, JSON error — all are expected.
            return None

    def _update_label(self, state: str, sentence: str | None) -> None:
        """Update the sentence label text based on daemon state."""
        if state in ("speaking", "paused"):
            if sentence:
                self._label.set_text(sentence)
            else:
                self._label.set_text("Preparing\u2026")
        else:
            self._label.set_text("")

    def _update_buttons(self, state: str) -> None:
        """Enable/disable buttons and toggle pause/resume label."""
        active = state in ("speaking", "paused")
        self._btn_pause.set_sensitive(active)
        self._btn_skip.set_sensitive(active)
        self._btn_stop.set_sensitive(active)

        # Toggle the pause button label.
        if state == "paused":
            self._btn_pause.set_label(LABEL_PLAY)
        else:
            self._btn_pause.set_label(LABEL_PAUSE)

    def _update_visibility(self, state: str) -> None:
        """Show the overlay when speaking/paused, hide otherwise."""
        should_show = state in ("speaking", "paused")
        if should_show and not self._visible:
            self.show_all()
            self._visible = True
            # Re-position in case monitor layout changed.
            self._position_window()
        elif not should_show and self._visible:
            self.hide()
            self._visible = False
        self._last_state = state

    # --- button handlers --------------------------------------------------

    def _post_action(self, path: str) -> None:
        """POST to the daemon. Fire-and-forget; errors are silently ignored."""
        try:
            self._ensure_client()
            assert self._client is not None
            self._client.post(path)
        except Exception:  # noqa: BLE001
            log.debug("POST %s failed", path)

    def _on_pause_resume(self, _btn) -> None:
        self._post_action("/toggle")

    def _on_skip(self, _btn) -> None:
        self._post_action("/skip")

    def _on_stop(self, _btn) -> None:
        self._post_action("/stop")

    # --- cleanup ----------------------------------------------------------

    def _on_destroy(self, _widget) -> None:
        self._close_client()
        Gtk.main_quit()


# --- single-instance lock ------------------------------------------------


def _acquire_single_instance_lock():
    """Take an exclusive flock on $XDG_RUNTIME_DIR/lexaloud-overlay.lock.

    Returns the open file descriptor (int) on success, None if another
    overlay is already running, or "skip" if we couldn't create the
    runtime dir.
    """
    import fcntl
    import os

    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/lexaloud-{os.getuid()}"
    try:
        os.makedirs(runtime, exist_ok=True)
    except OSError:
        return "skip"
    lock_path = os.path.join(runtime, "lexaloud-overlay.lock")
    try:
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    except OSError:
        return "skip"
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    try:
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
    except OSError:
        pass
    return fd


# --- entry point ----------------------------------------------------------


def main() -> int:
    """Entry point for ``lexaloud-overlay``."""
    lock = _acquire_single_instance_lock()
    if lock is None:
        print(
            "Lexaloud overlay is already running. Exiting.",
            file=sys.stderr,
        )
        return 0
    if isinstance(lock, int):
        globals()["_instance_lock_fd"] = lock

    overlay = OverlayWindow()  # noqa: F841 — prevent GC
    try:
        Gtk.main()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
