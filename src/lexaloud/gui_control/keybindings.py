"""GNOME gsettings keybinding helpers and the capture dialog."""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

from ._gi_shim import Gdk, Gtk

log = logging.getLogger(__name__)

# --- GNOME custom-keybinding schema paths --------------------------------

KB_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"
KB_ARRAY_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
KB_ARRAY_KEY = "custom-keybindings"

KB_BASE = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings"

# (path_suffix, human label, command tail to invoke lexaloud <tail>)
SHORTCUTS: list[tuple[str, str, str]] = [
    ("lexaloud", "Speak highlighted selection", "speak-selection"),
    ("lexaloud-toggle", "Pause / resume", "toggle"),
]


def _lexaloud_binary() -> str:
    """Resolve the absolute ``lexaloud`` binary path."""
    venv_bin = Path(sys.executable).parent
    return str(venv_bin / "lexaloud")


# --- gsettings helpers --------------------------------------------------


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
    """Read the gsettings custom-keybindings array."""
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
    """Ensure a custom-keybinding is in the array and has name/command set."""
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


def get_shortcut_binding(path_suffix: str) -> str:
    """Return the human-readable binding for a Lexaloud custom keybinding."""
    path = f"{KB_BASE}/{path_suffix}/"
    raw = _gsettings_get(KB_SCHEMA, "binding", path)
    return _binding_to_human(raw)


def set_shortcut_binding(path_suffix: str, gsettings_binding: str) -> bool:
    """Write a new binding for a Lexaloud custom keybinding."""
    path = f"{KB_BASE}/{path_suffix}/"
    for suffix, label, tail in SHORTCUTS:
        if suffix == path_suffix:
            if not _ensure_keybinding_registered(path_suffix, label, tail):
                return False
            break
    return _gsettings_set(KB_SCHEMA, "binding", gsettings_binding, path)


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


class CaptureDialog(Gtk.Dialog):
    """Modal dialog that captures the next keypress as a new binding."""

    def __init__(self, parent: Gtk.Window, path_suffix: str) -> None:
        super().__init__(title="Press a new shortcut", transient_for=parent, flags=0)
        self.set_default_size(360, 120)
        self.path_suffix = path_suffix
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
        self.write_ok = set_shortcut_binding(self.path_suffix, binding)
        self.disconnect(self._handler_id)
        self.response(Gtk.ResponseType.OK)
        return True
