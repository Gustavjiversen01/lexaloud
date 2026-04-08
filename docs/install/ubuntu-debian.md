# Installing Lexaloud on Ubuntu / Debian

This is the Tier 1 supported install path. The maintainer develops on
Ubuntu 24.04 with GNOME on X11, RTX 5080. Debian 13 and Ubuntu-derived
distros (Linux Mint, Pop!_OS, elementary, Zorin, Kali) should work with
the same package names.

## 1. System packages

```bash
sudo apt install \
    python3-venv \
    wl-clipboard \
    xclip \
    libportaudio2 \
    libnotify-bin \
    python3-gi \
    gir1.2-gtk-3.0 \
    gir1.2-ayatanaappindicator3-0.1
```

`python3-gi` and the two `gir1.2-*` packages are needed for the tray
indicator and the control window. You can skip them if you only want the
CLI.

## 2. Clone and install

```bash
git clone https://github.com/Gustavjiversen01/lexaloud.git
cd lexaloud
./scripts/install.sh
```

The installer auto-detects whether you have an NVIDIA GPU (via
`nvidia-smi -L`) and picks the `cuda12` or `cpu` backend accordingly. You
can override with `./scripts/install.sh --backend cpu` or
`--backend cuda12`.

The installer:

- Creates a venv at `~/.local/share/lexaloud/venv/`
- Installs the pinned dependency set from
  `requirements-lock.cuda12.txt` or `requirements-lock.cpu.txt`
- Installs the `lexaloud` package (editable) into the venv

If you have `PYTHONPATH` set in your shell (e.g., from sourcing ROS 2
Jazzy at login), the install script will warn you. It internally scrubs
`PYTHONPATH` when running pip, and the systemd unit it will render later
also scrubs `PYTHONPATH` at daemon startup.

## 3. Run setup

```bash
~/.local/share/lexaloud/venv/bin/lexaloud setup
```

This will:

1. Resolve the absolute path of the `lexaloud` binary.
2. Download the Kokoro model artifacts (`kokoro-v1.0.onnx` ~310 MB,
   `voices-v1.0.bin` ~28 MB) into `~/.cache/lexaloud/models/` and
   SHA256-verify them.
3. Write a systemd `--user` unit file to
   `~/.config/systemd/user/lexaloud.service`. If the file already
   exists, pass `--force` to overwrite it.
4. Print a hotkey-binding walkthrough for your session.

## 4. Start the daemon

```bash
systemctl --user daemon-reload
systemctl --user enable --now lexaloud.service
```

Verify it's running:

```bash
systemctl --user status lexaloud.service
~/.local/share/lexaloud/venv/bin/lexaloud status
```

You should see `"state": "idle"` with `"session_providers":
["CUDAExecutionProvider", "CPUExecutionProvider"]` (or
`"CPUExecutionProvider"` alone if you installed the CPU backend or if
CUDA setup failed — in which case check `journalctl --user -u
lexaloud.service`).

The daemon listens on a Unix domain socket at
`$XDG_RUNTIME_DIR/lexaloud/lexaloud.sock` (mode 0700 enforced by
systemd). There is no TCP port to firewall.

## 5. Bind a global hotkey (GNOME)

See [`../hotkeys/gnome.md`](../hotkeys/gnome.md) for the walkthrough.

For KDE, see [`../hotkeys/kde.md`](../hotkeys/kde.md); for
Sway/Hyprland see [`../hotkeys/sway-hyprland.md`](../hotkeys/sway-hyprland.md);
for XFCE/Cinnamon see [`../hotkeys/xfce-cinnamon.md`](../hotkeys/xfce-cinnamon.md).

## 6. Test

Select some text in any application and press your hotkey. You should
hear it read aloud in the default `af_heart` voice.

For pause/skip/stop:

```bash
lexaloud pause
lexaloud resume
lexaloud toggle
lexaloud skip
lexaloud back
lexaloud stop
```

Bind those to additional hotkeys for single-keystroke transport. The
owner's setup uses `Ctrl+0` for `speak-selection` and `Ctrl+9` for
`toggle`.

## 7. Troubleshooting

See [`../troubleshooting.md`](../troubleshooting.md) for common symptoms
and fixes. The fastest way to produce a bug report is:

```bash
lexaloud bug-report > /tmp/lexaloud-bug.md
```

Paste `/tmp/lexaloud-bug.md` into a new issue.
