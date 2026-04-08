# GNOME hotkey binding

GNOME has no cross-application global shortcut API. The mechanism
Lexaloud uses is GNOME's built-in Custom Shortcuts, which live in
gsettings under
`/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/`.

`lexaloud setup` prints a walkthrough tailored to your session. This
document is a fallback.

## Via Settings UI

1. Open **Settings** → **Keyboard** → **View and Customize Shortcuts**.
2. Scroll to the bottom and click **Custom Shortcuts**.
3. Click the **+** button.
4. Fill in:
   - **Name**: `Lexaloud: speak selection`
   - **Command**: `/home/YOU/.local/share/lexaloud/venv/bin/lexaloud speak-selection`
   - **Shortcut**: click "Set Shortcut" and press your desired
     combination (the owner uses `Ctrl+0`)
5. Click **Add**.
6. Repeat for:
   - `Lexaloud: pause/resume` → `… lexaloud toggle` → `Ctrl+9`
   - (optional) `Lexaloud: speak clipboard` → `… lexaloud speak-clipboard`
   - (optional) `Lexaloud: stop` → `… lexaloud stop`
   - (optional) `Lexaloud: skip` → `… lexaloud skip`

Replace `/home/YOU/` with your actual home directory — `lexaloud
setup` printed the exact path.

## Via gsettings (scriptable)

```bash
BIN="$HOME/.local/share/lexaloud/venv/bin/lexaloud"
BASE="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings"

# Register both keybinding slots in the array
gsettings set org.gnome.settings-daemon.plugins.media-keys \
    custom-keybindings "['$BASE/lexaloud/', '$BASE/lexaloud-toggle/']"

# Speak selection on Ctrl+0
gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:$BASE/lexaloud/ \
    name 'Lexaloud: speak selection'
gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:$BASE/lexaloud/ \
    command "$BIN speak-selection"
gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:$BASE/lexaloud/ \
    binding '<Primary>0'

# Pause/resume on Ctrl+9
gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:$BASE/lexaloud-toggle/ \
    name 'Lexaloud: pause/resume'
gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:$BASE/lexaloud-toggle/ \
    command "$BIN toggle"
gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:$BASE/lexaloud-toggle/ \
    binding '<Primary>9'
```

## Via the control window

If the daemon and tray indicator are already running, open the Control
Window (tray menu → **Control window…** or run `lexaloud-control`).
Each hotkey has a **Change…** button. Click, press the new key combo,
done.

## PRIMARY vs CLIPBOARD: which command to bind?

- **`speak-selection`** reads the X11 PRIMARY / Wayland primary
  selection. Fast (no extra keystroke) but some apps don't publish to
  PRIMARY, especially Electron apps on Wayland (VS Code, Obsidian,
  Slack).
- **`speak-clipboard`** reads the CLIPBOARD (populated by `Ctrl+C`).
  Reliable everywhere but requires `Ctrl+C` before the hotkey.

Recommendation: bind `speak-selection` to one hotkey and
`speak-clipboard` to another. Use `speak-selection` when it works
(most native GTK/Qt apps, browsers for regular page text) and fall
back to `speak-clipboard` + `Ctrl+C` for Electron apps.

See [`../gotchas.md`](../gotchas.md) for the per-app PRIMARY reliability
notes.

## Troubleshooting

### The hotkey fires but nothing happens

- Confirm the daemon is running: `systemctl --user status lexaloud.service`
- Run `lexaloud speak-selection` directly from a terminal — the error
  message will explain (empty selection, tool missing, daemon down).
- Check the hotkey's `command` via gsettings — typos silently fail.

### The hotkey doesn't fire at all

- Some apps capture global shortcuts on their own (e.g. terminal
  emulators may intercept `Ctrl+0`). Pick a combination less likely
  to conflict, like `Super+R`.
- GNOME Shell itself claims some keys; check
  `org.gnome.settings-daemon.plugins.media-keys` and
  `org.gnome.desktop.wm.keybindings` for conflicts.

### The control window's "Change…" button doesn't update the hotkey

Fixed in the v0.1.0 UDS migration — the earlier versions had a bug
where `set_shortcut_binding` wrote to a gsettings path that GNOME
never read. If you're hitting this, you're on an older build; pull
latest and re-run `./scripts/install.sh`.
