# Selection capture compatibility matrix (Spike 1)

This document is populated by running `./spikes/spike1_selection.sh` on the
target machine. Until then, it shows the expected columns and the behaviors
we have prior evidence for (from the plan's research, not from the target
box itself).

**Current status:** not yet run on the target machine. Run the spike script
from the repo root, then distill the results into the table below.

The raw output is written to `docs/capture-matrix.raw.md` by the spike
script; this file is the distilled summary a user can scan.

## Session under test

- Distribution: Ubuntu 24.04
- Session type: TBD (detect with `echo $XDG_SESSION_TYPE`)
- Desktop: GNOME 46
- Display server packages: wl-clipboard, xclip

## Columns

| App | `speak-selection` (PRIMARY) | `speak-clipboard` (CLIPBOARD after Ctrl+C) | Notes |
|---|---|---|---|
| Firefox (regular text) | ? | ? | |
| Firefox (PDF.js viewer) | ? | ? | |
| Chromium | ? | ? | |
| VS Code (editor) | ? | ? | Electron; primary known to be unreliable on some builds |
| Obsidian | ? | ? | Electron; similar concerns |
| Okular (PDF) | ? | ? | KDE app; KIO clipboard |
| Zathura (PDF) | ? | ? | Requires `set selection-clipboard primary` in zathurarc |
| Evince (PDF) | ? | ? | |
| LibreOffice Writer | ? | ? | |
| gnome-terminal | ? | ? | VTE-based |
| Konsole | ? | ? | |
| Kate | ? | ? | |

## Expected v1 binding

Once Spike 1 has populated the table, fill in the recommendation:

- **Primary command to bind on `Super+R`:** TBD
- **Secondary command (if needed):** TBD
- **Workarounds required:** TBD (e.g., "use Ctrl+C before the hotkey on app X")

## How to update this file

1. Run `./spikes/spike1_selection.sh` from the repo root. It will write a
   raw log to `docs/capture-matrix.raw.md` (or a timestamped archive if
   one already exists).
2. Walk through the raw log and fill in the table above.
3. Decide which command each session should bind to and update the
   "Expected v1 binding" section.
4. If the raw log reveals any consistent quirks (e.g., "PRIMARY is always
   empty in Electron apps on GNOME Wayland"), add an entry to `docs/gotchas.md`.
