"""GTK3 control window for Lexaloud.

Lets the user change the default Kokoro voice, playback speed, and the
GNOME custom keyboard shortcuts.
"""

from __future__ import annotations

import logging
import subprocess

from ._gi_shim import Gtk
from .config_io import _load_config_dict, _save_config_dict
from .keybindings import (
    KB_BASE,
    KB_SCHEMA,
    SHORTCUTS,
    CaptureDialog,
    _gsettings_get,
    get_shortcut_binding,
)
from .voices import KOKORO_VOICES, LANGUAGES

log = logging.getLogger(__name__)


class ControlWindow(Gtk.Window):
    def __init__(self) -> None:
        super().__init__(title="Lexaloud — Control")
        self.set_default_size(520, 480)
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

        # Speed slider
        speed_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        voice_box.pack_start(speed_row, False, False, 0)
        speed_label = Gtk.Label(label="Speed", xalign=0)
        speed_row.pack_start(speed_label, False, False, 0)

        self.speed_adjustment = Gtk.Adjustment(
            value=1.0, lower=0.5, upper=2.0, step_increment=0.05, page_increment=0.1
        )
        self.speed_scale = Gtk.Scale(
            orientation=Gtk.Orientation.HORIZONTAL, adjustment=self.speed_adjustment
        )
        self.speed_scale.set_digits(2)
        self.speed_scale.set_value_pos(Gtk.PositionType.RIGHT)
        for mark, label in [
            (0.5, "0.5"),
            (1.0, "1.0"),
            (1.3, "1.3"),
            (1.5, "1.5"),
            (2.0, "2.0"),
        ]:
            self.speed_scale.add_mark(mark, Gtk.PositionType.BOTTOM, label)
        self.speed_scale.set_hexpand(True)
        speed_row.pack_start(self.speed_scale, True, True, 0)

        self.speed_hint = Gtk.Label(label="", xalign=0)
        self.speed_hint.get_style_context().add_class("dim-label")
        voice_box.pack_start(self.speed_hint, False, False, 0)
        self.speed_adjustment.connect("value-changed", self._on_speed_changed)

        # Hotkeys section
        keys_frame = Gtk.Frame(label="Hotkeys (GNOME custom shortcuts)")
        keys_grid = Gtk.Grid(column_spacing=12, row_spacing=8)
        keys_grid.set_border_width(12)
        keys_frame.add(keys_grid)
        outer.pack_start(keys_frame, False, False, 0)

        self.hotkey_labels: dict[str, Gtk.Label] = {}
        for row, (path_suffix, label, _cmd) in enumerate(SHORTCUTS):
            name_lbl = Gtk.Label(label=f"{label}:", xalign=0)
            current_lbl = Gtk.Label(label=get_shortcut_binding(path_suffix), xalign=0)
            self.hotkey_labels[path_suffix] = current_lbl
            change_btn = Gtk.Button(label="Change…")
            change_btn.connect("clicked", self._on_change_binding, path_suffix)
            keys_grid.attach(name_lbl, 0, row, 1, 1)
            keys_grid.attach(current_lbl, 1, row, 1, 1)
            keys_grid.attach(change_btn, 2, row, 1, 1)

        # Advanced section
        advanced_frame = Gtk.Frame(label="Advanced")
        advanced_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        advanced_box.set_border_width(12)
        advanced_frame.add(advanced_box)
        outer.pack_start(advanced_frame, False, False, 0)

        self.overlay_toggle = Gtk.CheckButton(label="Show floating overlay when speaking")
        self.overlay_toggle.set_tooltip_text(
            "Displays a small translucent bar at the bottom of the screen "
            "showing the current sentence with pause/skip/stop buttons."
        )
        advanced_box.pack_start(self.overlay_toggle, False, False, 0)

        # Buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        button_box.set_halign(Gtk.Align.END)
        outer.pack_end(button_box, False, False, 0)

        self.status_label = Gtk.Label(label="", xalign=0)
        self.status_label.get_style_context().add_class("dim-label")
        outer.pack_end(self.status_label, False, False, 0)

        apply_btn = Gtk.Button(label="Apply & restart daemon")
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
        current_speed = float(provider.get("speed", 1.0))

        for i, (value, _label) in enumerate(KOKORO_VOICES):
            if value == current_voice:
                self.voice_combo.set_active(i)
                break
        else:
            self.status_label.set_text(
                f"Note: current voice '{current_voice}' is outside the curated list; "
                "edit ~/.config/lexaloud/config.toml directly to keep it."
            )

        for i, (value, _label) in enumerate(LANGUAGES):
            if value == current_lang:
                self.lang_combo.set_active(i)
                break
        else:
            self.lang_combo.set_active(0)

        clamped = max(0.5, min(2.0, current_speed))
        self.speed_adjustment.set_value(clamped)
        self._on_speed_changed(self.speed_adjustment)

        # Advanced settings
        advanced = cfg.get("advanced", {}) if isinstance(cfg, dict) else {}
        self.overlay_toggle.set_active(bool(advanced.get("overlay", False)))

    def _on_speed_changed(self, adjustment) -> None:
        v = adjustment.get_value()
        if 0.85 <= v <= 1.3:
            self.speed_hint.set_text(f"{v:.2f}× — safe range for dense reading.")
        elif v < 0.85:
            self.speed_hint.set_text(f"{v:.2f}× — slower than natural; may feel dragged.")
        elif v <= 1.5:
            self.speed_hint.set_text(
                f"{v:.2f}× — fine for familiar material, may strain comprehension on new dense text."
            )
        else:
            self.speed_hint.set_text(
                f"{v:.2f}× — risky for unfamiliar academic material; comprehension drops."
            )

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
        speed = round(self.speed_adjustment.get_value(), 2)
        if voice is None or lang is None:
            self.status_label.set_text("Pick a voice and a language first.")
            return

        cfg = _load_config_dict()
        if not isinstance(cfg, dict):
            cfg = {}
        provider = cfg.setdefault("provider", {})
        provider["voice"] = voice
        provider["lang"] = lang
        provider["speed"] = speed
        advanced = cfg.setdefault("advanced", {})
        advanced["overlay"] = self.overlay_toggle.get_active()
        try:
            _save_config_dict(cfg)
        except Exception as e:  # noqa: BLE001
            self.status_label.set_text(f"Saving config failed: {e}")
            return

        summary = f"voice={voice}, lang={lang}, speed={speed:.2f}×"
        try:
            r = subprocess.run(
                ["systemctl", "--user", "is-active", "lexaloud.service"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if r.stdout.strip() == "active":
                subprocess.run(
                    ["systemctl", "--user", "restart", "lexaloud.service"],
                    capture_output=True,
                    timeout=10,
                )
                self.status_label.set_text(f"Saved {summary}; daemon restarted.")
            else:
                self.status_label.set_text(
                    f"Saved {summary}. Daemon is stopped; "
                    "it will use the new settings on the next start."
                )
        except Exception as e:  # noqa: BLE001
            self.status_label.set_text(f"Saved {summary}; couldn't restart daemon: {e}")

    def _on_change_binding(self, _btn, path_suffix: str) -> None:
        dialog = CaptureDialog(self, path_suffix)
        response = dialog.run()
        captured = dialog.captured_binding
        write_ok = dialog.write_ok
        dialog.destroy()
        self.hotkey_labels[path_suffix].set_text(get_shortcut_binding(path_suffix))
        if response == Gtk.ResponseType.OK and captured:
            if not write_ok:
                self.status_label.set_text(
                    "Failed to write hotkey binding to gsettings. "
                    "Check `journalctl --user` for details."
                )
                return
            actual = _gsettings_get(KB_SCHEMA, "binding", f"{KB_BASE}/{path_suffix}/")
            if actual != captured:
                self.status_label.set_text(
                    f"Hotkey write did not stick: expected {captured!r}, "
                    f"gsettings still reports {actual!r}. Is the GNOME schema "
                    f"registered?"
                )


def main() -> int:
    """Standalone entry: open the control window without the indicator."""
    win = ControlWindow()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()
    return 0
