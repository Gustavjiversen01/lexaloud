"""GTK3 control window for Lexaloud.

Lets the user change the default Kokoro voice and the three GNOME custom
keyboard shortcuts (speak selection, pause/resume, daemon start/stop).

Voice changes are written to ~/.config/lexaloud/config.toml and take
effect on the next daemon (re)start. The window offers a "Restart daemon
to apply" button for convenience.

Keybind changes are written to gsettings immediately and take effect
without a daemon restart.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import tomllib
from pathlib import Path

from .config import config_path as _shared_config_path

log = logging.getLogger(__name__)

# Reuse the same system-site-packages prepend trick as the indicator.
try:
    import gi  # type: ignore
except ImportError:
    from .platform import system_site_packages_candidates

    for _candidate in system_site_packages_candidates():
        sys.path.append(str(_candidate))
        try:
            import gi  # type: ignore  # noqa: F811

            break
        except ImportError:
            continue
    else:
        raise  # re-raise the original ImportError if no candidate worked

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
KB_ARRAY_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
KB_ARRAY_KEY = "custom-keybindings"

KB_BASE = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings"

# (path_suffix, human label, command tail to invoke lexaloud <tail>)
SHORTCUTS: list[tuple[str, str, str]] = [
    ("lexaloud", "Speak highlighted selection", "speak-selection"),
    ("lexaloud-toggle", "Pause / resume", "toggle"),
    # Note: daemon start/stop is handled by the tray indicator, not a hotkey.
]


def _lexaloud_binary() -> str:
    """Resolve the absolute `lexaloud` binary path for use in custom
    shortcut commands. Kept stable across sessions so the binding survives
    venv reinstalls at the same path."""
    venv_bin = Path(sys.executable).parent
    return str(venv_bin / "lexaloud")


# --- config.toml read/write ---------------------------------------------


def _config_path() -> Path:
    """Shared with `lexaloud.config.config_path`; kept as a local
    re-export so existing callers don't need to change."""
    return _shared_config_path()


def _load_config_dict() -> dict:
    p = _config_path()
    if not p.exists():
        return {}
    try:
        with p.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        # Don't let a broken config.toml crash the control window when
        # the user clicks "Control window…" from the tray. Log and
        # return an empty dict; the GUI will show defaults, and Apply
        # will rewrite a clean file.
        log.error("Config file %s has a syntax error: %s", p, e)
        return {}
    except OSError as e:
        log.error("Could not read %s: %s", p, e)
        return {}


def _toml_escape(s: str) -> str:
    """Escape a Python str for TOML basic-string syntax.

    Handles the full control-character set that TOML requires escaped:
    backslash, double-quote, \\b, \\t, \\n, \\f, \\r, plus any other
    code point in U+0000..U+001F or U+007F as a \\uXXXX escape. The
    hand-rolled replacer used earlier (only `\\\\` + `\\"`) would
    corrupt strings containing tabs or newlines and cause tomllib to
    refuse to re-load the file.
    """
    out: list[str] = []
    for ch in s:
        cp = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\b":
            out.append("\\b")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\f":
            out.append("\\f")
        elif ch == "\r":
            out.append("\\r")
        elif cp < 0x20 or cp == 0x7F:
            out.append(f"\\u{cp:04X}")
        else:
            out.append(ch)
    return "".join(out)


def _save_config_dict(data: dict) -> None:
    """Serialize `data` back to config.toml.

    Known limitation: only scalars (str, bool, int, float) are preserved.
    Arrays and nested tables present in the input dict are dropped with a
    WARNING log entry rather than silently corrupted. For v1 this is
    acceptable because the only dict we round-trip through the GUI is one
    that the GUI itself wrote — all scalars. Users with custom TOML
    features should edit config.toml directly (the control window never
    writes those sections) and avoid re-saving via Apply.
    """
    p = _config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for section, fields in data.items():
        if not isinstance(fields, dict):
            continue
        section_lines: list[str] = []
        for key, value in fields.items():
            if isinstance(value, bool):
                section_lines.append(f"{key} = {'true' if value else 'false'}")
            elif isinstance(value, (int, float)):
                section_lines.append(f"{key} = {value}")
            elif isinstance(value, str):
                section_lines.append(f'{key} = "{_toml_escape(value)}"')
            else:
                log.warning(
                    "Dropping config key [%s].%s with unsupported type %s "
                    "during GUI save",
                    section,
                    key,
                    type(value).__name__,
                )
        # Skip writing an empty [section] header if nothing valid survived.
        if section_lines:
            lines.append(f"[{section}]")
            lines.extend(section_lines)
            lines.append("")
    p.write_text("\n".join(lines))


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
    """Return True on success, False on failure. Log details on failure."""
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
    """Read the gsettings custom-keybindings array, returning path suffixes
    (including trailing slashes). Returns an empty list on any failure or
    if the array is empty/unset."""
    raw = _gsettings_get(KB_ARRAY_SCHEMA, KB_ARRAY_KEY)
    if not raw or raw in ("@as []", "[]"):
        return []
    # gsettings prints the array as GVariant literal: ['/path1/', '/path2/']
    try:
        # Strip "@as " type prefix if present.
        if raw.startswith("@as "):
            raw = raw[4:]
        # GVariant string literals use single quotes; Python's eval would
        # work but is unsafe. Parse manually: split on ', ' inside [ ].
        inner = raw.strip("[]").strip()
        if not inner:
            return []
        parts = [p.strip().strip("'").strip('"') for p in inner.split(",")]
        return [p for p in parts if p]
    except Exception as e:  # noqa: BLE001
        log.warning("Could not parse custom-keybindings array %r: %s", raw, e)
        return []


def _ensure_keybinding_registered(path_suffix: str, label: str, command_tail: str) -> bool:
    """Ensure a custom-keybinding exists in the `custom-keybindings`
    array AND has `name` and `command` set on its schema path. Returns
    True on success.

    Without this, `set_shortcut_binding` would write the `binding` key
    on a schema:path that GNOME never reads — because GNOME only
    honors custom keybindings whose path is in the array. The result
    was a code-review-reported bug: the "Change…" button in the control
    window updated the label but the shortcut did nothing system-wide.
    """
    path = f"{KB_BASE}/{path_suffix}/"

    # 1. Make sure the path is in the array; append it if missing.
    current = _custom_keybindings_array()
    if path not in current:
        new_list = current + [path]
        gvariant = "[" + ", ".join(f"'{p}'" for p in new_list) + "]"
        if not _gsettings_set(KB_ARRAY_SCHEMA, KB_ARRAY_KEY, gvariant):
            return False

    # 2. Make sure the name and command are set on the schema:path.
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
    """Write a new binding for a Lexaloud custom keybinding.

    Ensures the path is registered in the `custom-keybindings` array
    and has `name` and `command` set, then writes the new `binding`.
    Returns True on success, False on any gsettings failure. The
    control window uses the return value to show an error dialog
    instead of silently claiming success.
    """
    path = f"{KB_BASE}/{path_suffix}/"
    # Look up the label and command tail from SHORTCUTS.
    for suffix, label, tail in SHORTCUTS:
        if suffix == path_suffix:
            if not _ensure_keybinding_registered(path_suffix, label, tail):
                return False
            break
    return _gsettings_set(KB_SCHEMA, "binding", gsettings_binding, path)


def _binding_to_human(raw: str) -> str:
    """Convert gsettings binding syntax to a friendly display string.

    Uses Gtk.accelerator_parse + Gtk.accelerator_get_label which handles
    every X keysym (including NumPad keys, function keys, punctuation,
    international layouts) and normalizes modifier order. Falls back
    to the raw gsettings string if parsing fails.
    """
    if not raw:
        return "(unset)"
    try:
        keyval, mods = Gtk.accelerator_parse(raw)
        if keyval == 0:
            return raw  # parse failed; show raw as a diagnostic
        label = Gtk.accelerator_get_label(keyval, mods)
        return label if label else raw
    except Exception:  # noqa: BLE001
        return raw


def _event_to_binding(event) -> str | None:
    """Turn a Gdk key-press event into a gsettings binding string.

    Returns None for modifier-only presses, dead keys, and combinations
    Gtk doesn't consider valid accelerators. Uses Gtk.accelerator_name
    + Gtk.accelerator_valid to handle caps-lock, AltGr, level-3 chords,
    and uppercase normalization correctly — this is what the hand-rolled
    previous version was getting wrong per review feedback.
    """
    keyval = event.keyval
    state = event.state
    keyname = Gdk.keyval_name(keyval) or ""

    # Modifier-only presses: keep waiting for the real key.
    if keyname in (
        "Control_L", "Control_R",
        "Shift_L", "Shift_R",
        "Alt_L", "Alt_R",
        "Super_L", "Super_R",
        "Meta_L", "Meta_R",
        "Hyper_L", "Hyper_R",
        "ISO_Level3_Shift", "ISO_Level5_Shift",
    ):
        return None

    # Normalize state to only the modifier bits Gtk cares about.
    mods = state & Gtk.accelerator_get_default_mod_mask()

    # Reject combinations Gtk doesn't consider valid accelerators (e.g.,
    # dead keys, plain letter with no modifier, etc.). This stops the
    # user from "setting" a binding that GNOME will silently ignore.
    if not Gtk.accelerator_valid(keyval, mods):
        return None

    name = Gtk.accelerator_name(keyval, mods)
    return name if name else None


# --- the window ---------------------------------------------------------


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

        # Speed slider. Range 0.5-2.0, step 0.05, default 1.0.
        # Per the plan's research, the genuinely safe range for dense academic
        # prose is ~0.85-1.3; outside that the slider still works but the
        # hint label below tells the user they're in risky territory.
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
        # Tick marks at common anchors so the user has a sense of the range.
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
            # Current voice isn't in the curated list; select nothing and
            # show a note in the status label.
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

        # Clamp the stored speed to the slider's legal range and set it.
        clamped = max(0.5, min(2.0, current_speed))
        self.speed_adjustment.set_value(clamped)
        # Priming the hint label (the value-changed signal also fires).
        self._on_speed_changed(self.speed_adjustment)

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
        try:
            _save_config_dict(cfg)
        except Exception as e:  # noqa: BLE001
            self.status_label.set_text(f"Saving config failed: {e}")
            return

        # Restart the daemon to pick up the new voice/speed (config is loaded
        # at daemon startup). If the daemon wasn't running, just leave it off.
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
            self.status_label.set_text(
                f"Saved {summary}; couldn't restart daemon: {e}"
            )

    def _on_change_binding(self, _btn, path_suffix: str) -> None:
        dialog = _CaptureDialog(self, path_suffix)
        response = dialog.run()
        captured = dialog.captured_binding
        write_ok = dialog.write_ok
        dialog.destroy()
        # Refresh the label after the dialog closes.
        self.hotkey_labels[path_suffix].set_text(get_shortcut_binding(path_suffix))
        # Post-write verification: if the user pressed a key and we
        # thought we wrote it, make sure gsettings actually took the
        # new value. Silent failures (schema missing, dbus down) would
        # otherwise leave the label showing the OLD value after an
        # apparently-successful capture.
        if response == Gtk.ResponseType.OK and captured:
            if not write_ok:
                self.status_label.set_text(
                    f"Failed to write hotkey binding to gsettings. "
                    f"Check `journalctl --user` for details."
                )
                return
            actual = _gsettings_get(KB_SCHEMA, "binding", f"{KB_BASE}/{path_suffix}/")
            if actual != captured:
                self.status_label.set_text(
                    f"Hotkey write did not stick: expected {captured!r}, "
                    f"gsettings still reports {actual!r}. Is the GNOME schema "
                    f"registered?"
                )


class _CaptureDialog(Gtk.Dialog):
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
            label="Press the new key combination.\n"
            "(Esc to cancel, or just press Cancel.)"
        )
        box.pack_start(msg, True, True, 0)

        self.show_all()
        self._handler_id = self.connect("key-press-event", self._on_key_press)

    def _on_key_press(self, _widget, event) -> bool:
        if self._captured:
            # A subsequent key-repeat event — we already committed the
            # binding; ignore extras until the dialog tears down.
            return True
        if event.keyval == Gdk.KEY_Escape:
            self.response(Gtk.ResponseType.CANCEL)
            return True
        binding = _event_to_binding(event)
        if binding is None:
            # Modifier-only, dead key, or otherwise-invalid — keep waiting.
            return True
        self._captured = True
        self.captured_binding = binding
        self.write_ok = set_shortcut_binding(self.path_suffix, binding)
        # Disconnect so key-repeat events after write don't re-trigger.
        self.disconnect(self._handler_id)
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
