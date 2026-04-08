"""GTK3 control window for ReadAloud.

Lets the user change the default Kokoro voice and the three GNOME custom
keyboard shortcuts (speak selection, pause/resume, daemon start/stop).

Voice changes are written to ~/.config/readaloud/config.toml and take
effect on the next daemon (re)start. The window offers a "Restart daemon
to apply" button for convenience.

Keybind changes are written to gsettings immediately and take effect
without a daemon restart.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path

# Reuse the same system-site-packages prepend trick as the indicator.
try:  # pragma: no cover
    import gi  # type: ignore
except ImportError:  # pragma: no cover
    sys.path.append("/usr/lib/python3/dist-packages")
    import gi  # type: ignore

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk  # type: ignore  # noqa: E402


# --- curated Kokoro voice list (v1.0 voices pack) -----------------------
#
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

# --- GNOME custom-keybinding schema paths --------------------------------

KB_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"
KB_ARRAY = "org.gnome.settings-daemon.plugins.media-keys"
KB_ARRAY_KEY = "custom-keybindings"

KB_BASE = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings"

SHORTCUTS: list[tuple[str, str, str]] = [
    # (key: path_suffix, label, default-command-tail-for-readaloud)
    ("readaloud", "Speak highlighted selection", "speak-selection"),
    ("readaloud-toggle", "Pause / resume", "toggle"),
    # Note: daemon start/stop is handled by the tray indicator, not a hotkey.
]


# --- config.toml read/write ---------------------------------------------


def _config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "readaloud" / "config.toml"


def _load_config_dict() -> dict:
    p = _config_path()
    if not p.exists():
        return {}
    with p.open("rb") as f:
        return tomllib.load(f)


def _save_config_dict(data: dict) -> None:
    p = _config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for section, fields in data.items():
        if not isinstance(fields, dict):
            continue
        lines.append(f"[{section}]")
        for key, value in fields.items():
            if isinstance(value, str):
                # Basic escaping: double-quote wrap, escape backslash/quote.
                esc = value.replace("\\", "\\\\").replace('"', '\\"')
                lines.append(f'{key} = "{esc}"')
            elif isinstance(value, bool):
                lines.append(f"{key} = {'true' if value else 'false'}")
            elif isinstance(value, (int, float)):
                lines.append(f"{key} = {value}")
            else:
                # Skip unsupported types rather than corrupting the file.
                continue
        lines.append("")
    p.write_text("\n".join(lines))


# --- gsettings helpers --------------------------------------------------


def _gsettings_get(schema: str, key: str, path: str | None = None) -> str:
    schema_arg = f"{schema}:{path}" if path else schema
    r = subprocess.run(
        ["gsettings", "get", schema_arg, key],
        capture_output=True,
        text=True,
        timeout=2,
    )
    return r.stdout.strip().strip("'").strip('"')


def _gsettings_set(schema: str, key: str, value: str, path: str | None = None) -> None:
    schema_arg = f"{schema}:{path}" if path else schema
    subprocess.run(
        ["gsettings", "set", schema_arg, key, value],
        check=False,
        capture_output=True,
        timeout=2,
    )


def get_shortcut_binding(path_suffix: str) -> str:
    """Return the human-readable binding for a ReadAloud custom keybinding."""
    path = f"{KB_BASE}/{path_suffix}/"
    raw = _gsettings_get(KB_SCHEMA, "binding", path)
    return _binding_to_human(raw)


def set_shortcut_binding(path_suffix: str, gsettings_binding: str) -> None:
    path = f"{KB_BASE}/{path_suffix}/"
    _gsettings_set(KB_SCHEMA, "binding", gsettings_binding, path)


def _binding_to_human(raw: str) -> str:
    """Convert gsettings binding syntax to a friendly display string.

    '<Primary>0' -> 'Ctrl+0'
    '<Primary><Shift>period' -> 'Ctrl+Shift+.'
    """
    if not raw:
        return "(unset)"
    s = raw
    mods = []
    for tag, name in [
        ("<Primary>", "Ctrl"),
        ("<Control>", "Ctrl"),
        ("<Shift>", "Shift"),
        ("<Alt>", "Alt"),
        ("<Super>", "Super"),
    ]:
        if tag in s:
            mods.append(name)
            s = s.replace(tag, "")
    key_map = {"period": ".", "comma": ",", "slash": "/", "semicolon": ";"}
    key = key_map.get(s, s)
    return "+".join(mods + [key]) if mods else key


def _event_to_binding(event) -> str | None:
    """Turn a Gdk key-press event into a gsettings binding string.

    Returns None if the user only pressed a modifier (no actual key).
    """
    keyname = Gdk.keyval_name(event.keyval)
    if keyname is None:
        return None
    # Ignore modifier-only presses so the user can hold mods without
    # locking in an invalid binding.
    if keyname in (
        "Control_L", "Control_R",
        "Shift_L", "Shift_R",
        "Alt_L", "Alt_R",
        "Super_L", "Super_R",
        "Meta_L", "Meta_R",
    ):
        return None
    parts: list[str] = []
    mods = event.state
    if mods & Gdk.ModifierType.CONTROL_MASK:
        parts.append("<Primary>")
    if mods & Gdk.ModifierType.SHIFT_MASK:
        parts.append("<Shift>")
    if mods & Gdk.ModifierType.MOD1_MASK:
        parts.append("<Alt>")
    if mods & Gdk.ModifierType.SUPER_MASK:
        parts.append("<Super>")
    parts.append(keyname)
    return "".join(parts)


# --- the window ---------------------------------------------------------


class ControlWindow(Gtk.Window):
    def __init__(self) -> None:
        super().__init__(title="ReadAloud — Control")
        self.set_default_size(480, 360)
        self.set_border_width(16)
        self.set_position(Gtk.WindowPosition.CENTER)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.add(outer)

        # Voice section
        voice_frame = Gtk.Frame(label="Voice")
        voice_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        voice_box.set_border_width(12)
        voice_frame.add(voice_box)
        outer.pack_start(voice_frame, False, False, 0)

        self.voice_store = Gtk.ListStore(str, str)
        for value, label in KOKORO_VOICES:
            self.voice_store.append([value, label])
        self.voice_combo = Gtk.ComboBox(model=self.voice_store)
        renderer = Gtk.CellRendererText()
        self.voice_combo.pack_start(renderer, True)
        self.voice_combo.add_attribute(renderer, "text", 1)
        voice_box.pack_start(self.voice_combo, False, False, 0)

        lang_label = Gtk.Label(label="Language", xalign=0)
        voice_box.pack_start(lang_label, False, False, 0)
        self.lang_store = Gtk.ListStore(str, str)
        for value, label in LANGUAGES:
            self.lang_store.append([value, label])
        self.lang_combo = Gtk.ComboBox(model=self.lang_store)
        lang_renderer = Gtk.CellRendererText()
        self.lang_combo.pack_start(lang_renderer, True)
        self.lang_combo.add_attribute(lang_renderer, "text", 1)
        voice_box.pack_start(self.lang_combo, False, False, 0)

        # Hotkeys section
        keys_frame = Gtk.Frame(label="Hotkeys (GNOME custom shortcuts)")
        keys_grid = Gtk.Grid(column_spacing=12, row_spacing=8)
        keys_grid.set_border_width(12)
        keys_frame.add(keys_grid)
        outer.pack_start(keys_frame, False, False, 0)

        self.hotkey_labels: dict[str, Gtk.Label] = {}
        for row, (path_suffix, label, _cmd) in enumerate(SHORTCUTS):
            name_lbl = Gtk.Label(label=f"{label}:", xalign=0)
            current_lbl = Gtk.Label(
                label=get_shortcut_binding(path_suffix), xalign=0
            )
            self.hotkey_labels[path_suffix] = current_lbl
            change_btn = Gtk.Button(label="Change…")
            change_btn.connect("clicked", self._on_change_binding, path_suffix)
            keys_grid.attach(name_lbl, 0, row, 1, 1)
            keys_grid.attach(current_lbl, 1, row, 1, 1)
            keys_grid.attach(change_btn, 2, row, 1, 1)

        # Buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        button_box.set_halign(Gtk.Align.END)
        outer.pack_end(button_box, False, False, 0)

        self.status_label = Gtk.Label(label="", xalign=0)
        self.status_label.get_style_context().add_class("dim-label")
        outer.pack_end(self.status_label, False, False, 0)

        apply_btn = Gtk.Button(label="Apply voice + restart daemon")
        apply_btn.connect("clicked", self._on_apply_voice)
        button_box.pack_start(apply_btn, False, False, 0)

        close_btn = Gtk.Button(label="Close")
        close_btn.connect("clicked", lambda _: self.destroy())
        button_box.pack_start(close_btn, False, False, 0)

        self._load_current_config()
        self.show_all()

    # ---------- load current values ----------

    def _load_current_config(self) -> None:
        cfg = _load_config_dict()
        provider = cfg.get("provider", {}) if isinstance(cfg, dict) else {}
        current_voice = provider.get("voice", "af_heart")
        current_lang = provider.get("lang", "en-us")

        for i, (value, _label) in enumerate(KOKORO_VOICES):
            if value == current_voice:
                self.voice_combo.set_active(i)
                break
        else:
            # Current voice isn't in the curated list; select nothing and
            # show a note in the status label.
            self.status_label.set_text(
                f"Note: current voice '{current_voice}' is outside the curated list; "
                "edit ~/.config/readaloud/config.toml directly to keep it."
            )

        for i, (value, _label) in enumerate(LANGUAGES):
            if value == current_lang:
                self.lang_combo.set_active(i)
                break
        else:
            self.lang_combo.set_active(0)

    # ---------- handlers ----------

    def _selected_voice(self) -> str | None:
        it = self.voice_combo.get_active_iter()
        if it is None:
            return None
        return self.voice_store.get_value(it, 0)

    def _selected_lang(self) -> str | None:
        it = self.lang_combo.get_active_iter()
        if it is None:
            return None
        return self.lang_store.get_value(it, 0)

    def _on_apply_voice(self, _btn) -> None:
        voice = self._selected_voice()
        lang = self._selected_lang()
        if voice is None or lang is None:
            self.status_label.set_text("Pick a voice and a language first.")
            return

        cfg = _load_config_dict()
        if not isinstance(cfg, dict):
            cfg = {}
        provider = cfg.setdefault("provider", {})
        provider["voice"] = voice
        provider["lang"] = lang
        try:
            _save_config_dict(cfg)
        except Exception as e:  # noqa: BLE001
            self.status_label.set_text(f"Saving config failed: {e}")
            return

        # Restart the daemon to pick up the new voice (config is loaded at
        # daemon startup). If the daemon wasn't running, just leave it off.
        try:
            r = subprocess.run(
                ["systemctl", "--user", "is-active", "readaloud.service"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if r.stdout.strip() == "active":
                subprocess.run(
                    ["systemctl", "--user", "restart", "readaloud.service"],
                    capture_output=True,
                    timeout=10,
                )
                self.status_label.set_text(
                    f"Saved voice={voice}, lang={lang}; daemon restarted."
                )
            else:
                self.status_label.set_text(
                    f"Saved voice={voice}, lang={lang}. Daemon is stopped; "
                    "it will use the new voice on the next start."
                )
        except Exception as e:  # noqa: BLE001
            self.status_label.set_text(
                f"Saved voice={voice}, lang={lang}; couldn't restart daemon: {e}"
            )

    def _on_change_binding(self, _btn, path_suffix: str) -> None:
        dialog = _CaptureDialog(self, path_suffix)
        dialog.run()
        dialog.destroy()
        # Refresh the label after the dialog closes.
        self.hotkey_labels[path_suffix].set_text(get_shortcut_binding(path_suffix))


class _CaptureDialog(Gtk.Dialog):
    """Modal dialog that captures the next keypress as a new binding."""

    def __init__(self, parent: Gtk.Window, path_suffix: str) -> None:
        super().__init__(title="Press a new shortcut", transient_for=parent, flags=0)
        self.set_default_size(360, 120)
        self.path_suffix = path_suffix
        self.set_modal(True)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)

        box = self.get_content_area()
        box.set_border_width(16)
        box.set_spacing(8)
        msg = Gtk.Label(
            label="Press the new key combination.\n"
            "(Esc to cancel, or just press Cancel.)"
        )
        box.pack_start(msg, True, True, 0)

        self.show_all()
        self.connect("key-press-event", self._on_key_press)

    def _on_key_press(self, _widget, event) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            self.response(Gtk.ResponseType.CANCEL)
            return True
        binding = _event_to_binding(event)
        if binding is None:
            # Modifier-only, keep waiting.
            return True
        set_shortcut_binding(self.path_suffix, binding)
        self.response(Gtk.ResponseType.OK)
        return True


def main() -> int:
    """Standalone entry: open the control window without the indicator."""
    win = ControlWindow()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
