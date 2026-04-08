# XFCE / Cinnamon / MATE hotkey binding

**Status:** Stub. PRs welcome.

XFCE, Cinnamon, and MATE use their own keybinding systems (xfconf for
XFCE; gsettings under different schemas for Cinnamon/MATE) rather than
the GNOME-specific keybindings Lexaloud's Control window writes to.

## XFCE

Open **Settings** → **Keyboard** → **Application Shortcuts** tab →
**Add**.

- **Command**: `/home/YOU/.local/share/lexaloud/venv/bin/lexaloud speak-selection`
- **Shortcut**: press your desired combination

Or via `xfconf-query`:

```bash
BIN="$HOME/.local/share/lexaloud/venv/bin/lexaloud"
xfconf-query -c xfce4-keyboard-shortcuts \
    -p "/commands/custom/<Primary>0" \
    -n -t string -s "$BIN speak-selection"
```

## Cinnamon

**System Settings** → **Keyboard** → **Shortcuts** tab → **Custom
Shortcuts**. Add a new entry pointing to your lexaloud binary.

## MATE

**System** → **Preferences** → **Hardware** → **Keyboard Shortcuts**.
Follow the same pattern.

## Notes

- PRIMARY selection behavior depends on the toolkit. GTK-based apps
  under X11 publish to PRIMARY reliably.
- The Lexaloud Control window's **Change…** hotkey button is a no-op
  outside GNOME in v0.1.0.

## Contributions welcome

Please PR improvements, especially if you know the exact
`xfconf`/`gsettings` schema paths for each desktop.
