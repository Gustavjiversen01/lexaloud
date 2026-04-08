# Uninstall

This guide completely removes Lexaloud and all its artifacts.

## 1. Stop and disable the daemon

```bash
systemctl --user disable --now lexaloud.service
systemctl --user daemon-reload
```

## 2. Remove the venv

```bash
rm -rf ~/.local/share/lexaloud
```

This deletes the CPython venv and everything pip installed into it.

## 3. Remove the systemd unit

```bash
rm -f ~/.config/systemd/user/lexaloud.service
```

## 4. Remove the tray `.desktop` file

```bash
rm -f ~/.local/share/applications/lexaloud.desktop
```

(Only present if you installed the tray indicator — safe to run either
way.)

## 5. Remove config + model cache (optional)

```bash
# Configuration (~1 KB)
rm -rf ~/.config/lexaloud

# Model weights cache (~340 MB) — only if you want the disk back
rm -rf ~/.cache/lexaloud
```

If you're planning to reinstall Lexaloud later, you can leave
`~/.cache/lexaloud/models/` in place — the next install will SHA256-
verify the existing files and skip the download.

## 6. Remove GNOME custom shortcuts (optional)

Lexaloud installs custom keybindings via `gsettings` at
`/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/lexaloud/`
and `/lexaloud-toggle/`. To remove them:

```bash
# List current custom shortcuts
gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings

# Remove lexaloud entries from the array
gsettings reset org.gnome.settings-daemon.plugins.media-keys custom-keybindings
# (This wipes ALL custom shortcuts — re-add any non-Lexaloud ones you had.)
```

Or use the GNOME Settings GUI: Settings → Keyboard → View and
Customize Shortcuts → Custom Shortcuts → click the entry → Remove.

## 7. Remove the source checkout

```bash
rm -rf /path/to/lexaloud
```

## 8. Verify

```bash
which lexaloud  # should be empty
systemctl --user list-unit-files | grep lexaloud  # should be empty
ls ~/.local/share/lexaloud 2>&1  # "No such file or directory"
ls ~/.config/lexaloud 2>&1       # same, or left alone if you skipped step 5
ls ~/.cache/lexaloud 2>&1        # same, or left alone if you skipped step 5
```

That's it. Lexaloud is gone.

## Leftover `/run/user/<uid>/lexaloud/` directory

systemd-logind creates `$XDG_RUNTIME_DIR` at login and tears it down
at logout. The `lexaloud` subdirectory inside it was owned by the
service unit via `RuntimeDirectory=lexaloud` and will be removed
automatically when the service stops. If for some reason it persists:

```bash
rmdir "/run/user/$(id -u)/lexaloud" 2>/dev/null
```
