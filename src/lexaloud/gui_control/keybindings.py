"""Keybinding backend abstraction and the capture dialog.

Supports GNOME (gsettings), XFCE (xfconf-query), KDE (read-only portal
display), and a NullBackend for unsupported desktops.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Protocol

from ._gi_shim import Gdk, Gtk

log = logging.getLogger(__name__)

# (shortcut_id, human label, command tail to invoke lexaloud <tail>)
SHORTCUTS: list[tuple[str, str, str]] = [
    ("lexaloud", "Speak highlighted selection", "speak-selection"),
    ("lexaloud-toggle", "Pause / resume", "toggle"),
]


def _lexaloud_binary() -> str:
    """Resolve the absolute ``lexaloud`` binary path."""
    venv_bin = Path(sys.executable).parent
    return str(venv_bin / "lexaloud")


# --- backend protocol ---------------------------------------------------


class KeybindingBackend(Protocol):
    def get_binding(self, shortcut_id: str) -> str: ...
    def set_binding(self, shortcut_id: str, binding: str) -> bool: ...
    def is_available(self) -> bool: ...
    @property
    def frame_label(self) -> str: ...


# --- GNOME gsettings backend --------------------------------------------

KB_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"
KB_ARRAY_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
KB_ARRAY_KEY = "custom-keybindings"
KB_BASE = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings"


def _gsettings_get(schema: str, key: str, path: str | None = None) -> str:
    schema_arg = f"{schema}:{path}" if path else schema
    try:
        r = subprocess.run(
            ["gsettings", "get", schema_arg, key],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.SubprocessError) as e:
        log.debug("gsettings get %s %s failed: %s", schema_arg, key, e)
        return ""
    if r.returncode != 0:
        log.debug(
            "gsettings get %s %s exited %d: %s",
            schema_arg,
            key,
            r.returncode,
            (r.stderr or "").strip(),
        )
        return ""
    return r.stdout.strip().strip("'").strip('"')


def _gsettings_set(schema: str, key: str, value: str, path: str | None = None) -> bool:
    schema_arg = f"{schema}:{path}" if path else schema
    try:
        r = subprocess.run(
            ["gsettings", "set", schema_arg, key, value],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.SubprocessError) as e:
        log.error("gsettings set %s %s failed: %s", schema_arg, key, e)
        return False
    if r.returncode != 0:
        log.error(
            "gsettings set %s %s exited %d: %s",
            schema_arg,
            key,
            r.returncode,
            (r.stderr or "").strip(),
        )
        return False
    return True


def _custom_keybindings_array() -> list[str]:
    raw = _gsettings_get(KB_ARRAY_SCHEMA, KB_ARRAY_KEY)
    if not raw or raw in ("@as []", "[]"):
        return []
    try:
        if raw.startswith("@as "):
            raw = raw[4:]
        inner = raw.strip("[]").strip()
        if not inner:
            return []
        parts = [p.strip().strip("'").strip('"') for p in inner.split(",")]
        return [p for p in parts if p]
    except Exception as e:  # noqa: BLE001
        log.warning("Could not parse custom-keybindings array %r: %s", raw, e)
        return []


def _ensure_keybinding_registered(path_suffix: str, label: str, command_tail: str) -> bool:
    path = f"{KB_BASE}/{path_suffix}/"
    current = _custom_keybindings_array()
    if path not in current:
        new_list = current + [path]
        gvariant = "[" + ", ".join(f"'{p}'" for p in new_list) + "]"
        if not _gsettings_set(KB_ARRAY_SCHEMA, KB_ARRAY_KEY, gvariant):
            return False
    command = f"{_lexaloud_binary()} {command_tail}"
    ok_name = _gsettings_set(KB_SCHEMA, "name", label, path)
    ok_cmd = _gsettings_set(KB_SCHEMA, "command", command, path)
    return ok_name and ok_cmd


class GnomeBackend:
    """GNOME custom-keybinding backend via gsettings."""

    def get_binding(self, shortcut_id: str) -> str:
        path = f"{KB_BASE}/{shortcut_id}/"
        raw = _gsettings_get(KB_SCHEMA, "binding", path)
        return _binding_to_human(raw)

    def set_binding(self, shortcut_id: str, binding: str) -> bool:
        path = f"{KB_BASE}/{shortcut_id}/"
        for suffix, label, tail in SHORTCUTS:
            if suffix == shortcut_id:
                if not _ensure_keybinding_registered(shortcut_id, label, tail):
                    return False
                break
        return _gsettings_set(KB_SCHEMA, "binding", binding, path)

    def is_available(self) -> bool:
        return shutil.which("gsettings") is not None

    @property
    def frame_label(self) -> str:
        return "Hotkeys (GNOME)"


# --- XFCE xfconf-query backend ------------------------------------------


class XfceBackend:
    """XFCE keybinding backend via xfconf-query."""

    _CHANNEL = "xfce4-keyboard-shortcuts"

    def _property_path(self, shortcut_id: str) -> str:
        for suffix, _label, tail in SHORTCUTS:
            if suffix == shortcut_id:
                return f"/commands/custom/lexaloud-{tail}"
        return f"/commands/custom/{shortcut_id}"

    def get_binding(self, shortcut_id: str) -> str:
        prop = self._property_path(shortcut_id)
        try:
            r = subprocess.run(
                ["xfconf-query", "-c", self._CHANNEL, "-p", prop],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.SubprocessError):
            pass
        return "(unset)"

    def set_binding(self, shortcut_id: str, binding: str) -> bool:
        for suffix, _label, tail in SHORTCUTS:
            if suffix == shortcut_id:
                command = f"{_lexaloud_binary()} {tail}"
                break
        else:
            return False
        # XFCE stores shortcuts as property → command mappings
        prop = f"/commands/custom/{binding}"
        try:
            r = subprocess.run(
                [
                    "xfconf-query",
                    "-c",
                    self._CHANNEL,
                    "-p",
                    prop,
                    "-n",
                    "-t",
                    "string",
                    "-s",
                    command,
                ],
                capture_output=True,
                text=True,
                timeout=2,
            )
            return r.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.SubprocessError) as e:
            log.error("xfconf-query set failed: %s", e)
            return False

    def is_available(self) -> bool:
        return shutil.which("xfconf-query") is not None

    @property
    def frame_label(self) -> str:
        return "Hotkeys (XFCE)"


# --- KDE / portal read-only backend -------------------------------------


class PortalReadOnly:
    """Read-only display for KDE Plasma 6+ / Sway / Hyprland.

    Shortcuts are managed via the XDG GlobalShortcuts portal (registered
    by the daemon via shortcuts.py). The GUI shows them read-only with a
    note to use System Settings.
    """

    def get_binding(self, shortcut_id: str) -> str:
        return "(managed via System Settings)"

    def set_binding(self, shortcut_id: str, binding: str) -> bool:
        return False  # read-only

    def is_available(self) -> bool:
        return False  # "Change..." button should be greyed out

    @property
    def frame_label(self) -> str:
        return "Hotkeys (System Settings)"


# --- null backend (unsupported DEs) -------------------------------------


class NullBackend:
    """Fallback for desktops without integrated keybinding support."""

    def get_binding(self, shortcut_id: str) -> str:
        return "(manual setup)"

    def set_binding(self, shortcut_id: str, binding: str) -> bool:
        return False

    def is_available(self) -> bool:
        return False

    @property
    def frame_label(self) -> str:
        return "Hotkeys (manual setup)"


# --- backend selection ---------------------------------------------------


def detect_backend() -> KeybindingBackend:
    """Pick the right keybinding backend for the current desktop."""
    from ..platform import detect_desktop

    desktop = detect_desktop()
    if desktop.is_gnome:
        return GnomeBackend()
    if desktop.is_xfce:
        return XfceBackend()
    if desktop.is_kde:
        return PortalReadOnly()
    return NullBackend()


# --- shared helpers (used by CaptureDialog and control_window) ----------


def _binding_to_human(raw: str) -> str:
    """Convert gsettings binding syntax to a friendly display string."""
    if not raw:
        return "(unset)"
    try:
        keyval, mods = Gtk.accelerator_parse(raw)
        if keyval == 0:
            return raw
        label = Gtk.accelerator_get_label(keyval, mods)
        return label if label else raw
    except Exception:  # noqa: BLE001
        return raw


def _event_to_binding(event) -> str | None:
    """Turn a Gdk key-press event into a gsettings binding string."""
    keyval = event.keyval
    state = event.state
    keyname = Gdk.keyval_name(keyval) or ""

    if keyname in (
        "Control_L",
        "Control_R",
        "Shift_L",
        "Shift_R",
        "Alt_L",
        "Alt_R",
        "Super_L",
        "Super_R",
        "Meta_L",
        "Meta_R",
        "Hyper_L",
        "Hyper_R",
        "ISO_Level3_Shift",
        "ISO_Level5_Shift",
    ):
        return None

    mods = state & Gtk.accelerator_get_default_mod_mask()

    if not Gtk.accelerator_valid(keyval, mods):
        return None

    name = Gtk.accelerator_name(keyval, mods)
    return name if name else None


# --- capture dialog (shared across backends that support set_binding) ---


class CaptureDialog(Gtk.Dialog):
    """Modal dialog that captures the next keypress as a new binding."""

    def __init__(self, parent: Gtk.Window, shortcut_id: str, backend: KeybindingBackend) -> None:
        super().__init__(title="Press a new shortcut", transient_for=parent, flags=0)
        self.set_default_size(360, 120)
        self.shortcut_id = shortcut_id
        self._backend = backend
        self.captured_binding: str | None = None
        self.write_ok: bool = False
        self._captured = False
        self.set_modal(True)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)

        box = self.get_content_area()
        box.set_border_width(16)
        box.set_spacing(8)
        msg = Gtk.Label(
            label="Press the new key combination.\n(Esc to cancel, or just press Cancel.)"
        )
        box.pack_start(msg, True, True, 0)

        self.show_all()
        self._handler_id = self.connect("key-press-event", self._on_key_press)

    def _on_key_press(self, _widget, event) -> bool:
        if self._captured:
            return True
        if event.keyval == Gdk.KEY_Escape:
            self.response(Gtk.ResponseType.CANCEL)
            return True
        binding = _event_to_binding(event)
        if binding is None:
            return True
        self._captured = True
        self.captured_binding = binding
        self.write_ok = self._backend.set_binding(self.shortcut_id, binding)
        self.disconnect(self._handler_id)
        self.response(Gtk.ResponseType.OK)
        return True


# Legacy module-level functions for backwards compatibility with tests and
# indicator imports. These delegate to GnomeBackend.
_gnome = GnomeBackend()


def get_shortcut_binding(path_suffix: str) -> str:
    return _gnome.get_binding(path_suffix)


def set_shortcut_binding(path_suffix: str, gsettings_binding: str) -> bool:
    return _gnome.set_binding(path_suffix, gsettings_binding)
