# Sway / Hyprland hotkey binding

**Status:** Stub. PRs welcome.

Sway, Hyprland, and other wlroots-based compositors use their own
config files for global key bindings rather than gsettings. The
Lexaloud Control window's hotkey UI doesn't touch these — bind the
shortcuts in your compositor config directly.

## Sway

Add to `~/.config/sway/config`:

```
# Lexaloud
bindsym Ctrl+0 exec /home/YOU/.local/share/lexaloud/venv/bin/lexaloud speak-selection
bindsym Ctrl+9 exec /home/YOU/.local/share/lexaloud/venv/bin/lexaloud toggle
bindsym Ctrl+Shift+0 exec /home/YOU/.local/share/lexaloud/venv/bin/lexaloud speak-clipboard
```

Reload with `swaymsg reload`.

## Hyprland

Add to `~/.config/hypr/hyprland.conf`:

```
bind = CTRL, 0, exec, /home/YOU/.local/share/lexaloud/venv/bin/lexaloud speak-selection
bind = CTRL, 9, exec, /home/YOU/.local/share/lexaloud/venv/bin/lexaloud toggle
bind = CTRL SHIFT, 0, exec, /home/YOU/.local/share/lexaloud/venv/bin/lexaloud speak-clipboard
```

Reload with `hyprctl reload`.

## Notes

- These compositors are Wayland-native. Primary selection via
  `wl-paste --primary` works reliably across most apps.
- If you're not running a GNOME tray compatibility layer, the
  Lexaloud tray indicator won't show up. The CLI works fine; it just
  means no GUI status.

## Contributions welcome

If you use River, i3, dwl, or another compositor, please send a PR
adding your config snippet here.
