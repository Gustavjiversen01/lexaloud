# KDE Plasma hotkey binding

**Status:** Stub. PRs welcome.

KDE Plasma has the XDG `org.freedesktop.portal.GlobalShortcuts` portal
(unlike GNOME). Lexaloud v0.1.0 does not integrate with the portal yet;
the recommended path is KDE's built-in Custom Shortcuts mechanism.

## Via System Settings UI

1. **System Settings** → **Shortcuts** → **Custom Shortcuts**.
2. Click **Edit** → **New** → **Global Shortcut** → **Command/URL**.
3. Set:
   - **Trigger**: press your desired combination
   - **Action**: `/home/YOU/.local/share/lexaloud/venv/bin/lexaloud speak-selection`

Repeat for `toggle`, `speak-clipboard`, etc.

## Notes

- PRIMARY selection is usually reliable across KDE native apps thanks
  to Qt's clipboard abstraction.
- The Lexaloud Control window's **Change…** button for hotkeys is
  currently a no-op off-GNOME (it writes to the GNOME-specific
  gsettings schema). Planned fix: grey out the button on non-GNOME, or
  write to KGlobalAccel on KDE. Planned for v0.2.

## Contributions welcome

If you're a KDE user and want to expand this into a full walkthrough
(including KGlobalAccel scripting), please open a PR.
