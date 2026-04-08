# Installing Lexaloud on Ubuntu 24.04 GNOME

This guide walks through a clean install on the target environment: Ubuntu
24.04, GNOME 46, RTX 5080. Other configurations should work but are not the
primary test target.

## 1. System packages

```bash
sudo apt install python3-venv wl-clipboard xclip libportaudio2 libnotify-bin
```

## 2. Clone the repo and run the installer

```bash
git clone https://github.com/Gustavjiversen01/lexaloud.git
cd lexaloud
./scripts/install.sh
```

The installer:

- creates a venv at `~/.local/share/lexaloud/venv/`
- installs the pinned dependency set from `requirements-lock.txt`
- installs the `lexaloud` package (editable) into the venv

If you have `PYTHONPATH` set in your shell (e.g., from sourcing ROS 2 Jazzy
at login), the install script will warn you. It internally scrubs
`PYTHONPATH` when running pip, and the systemd unit it will render later
also scrubs `PYTHONPATH` at daemon startup.

## 3. Run setup

```bash
~/.local/share/lexaloud/venv/bin/lexaloud setup
```

This will:

1. Resolve the absolute path of the `lexaloud` binary.
2. Download the Kokoro model artifacts (`kokoro-v1.0.onnx` ~310 MB,
   `voices-v1.0.bin` ~28 MB) into `~/.cache/lexaloud/models/` and verify
   their SHA256 hashes.
3. Write a systemd `--user` unit file to
   `~/.config/systemd/user/lexaloud.service`. If the file already exists,
   pass `--force` to overwrite it.
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

You should see `"state": "idle"` with `"session_providers": [..., "CUDAExecutionProvider", ...]` (or `"CPUExecutionProvider"` alone if CUDA setup failed — in which case check the daemon logs with `journalctl --user -u lexaloud`).

## 5. Bind a global hotkey

Open **Settings → Keyboard → View and Customize Shortcuts → Custom Shortcuts → `+` (Add shortcut)** and create:

- **Name:** `Lexaloud: speak selection`
- **Command:** `/home/<you>/.local/share/lexaloud/venv/bin/lexaloud speak-selection`
- **Shortcut:** press `Super+R` (or any binding you prefer)

(`lexaloud setup` printed the exact command path for you — copy that, do not retype.)

### Which command to bind?

- **`speak-selection`** (PRIMARY selection) — works best when your apps reliably expose primary selection. Often good on X11; mixed results on GNOME Wayland.
- **`speak-clipboard`** (CLIPBOARD only) — works from `Ctrl+C`. Reliable everywhere, but requires an extra keystroke before the hotkey.

On GNOME Wayland, until Spike 1 has been run to test the specific apps you use, we recommend `speak-clipboard` + `Ctrl+C` as the primary workflow. You can bind both to two different keys.

## 6. Test

Select some text in any application and press your hotkey. You should hear it read aloud in the `af_heart` voice.

For pause/skip/stop:

```bash
lexaloud pause
lexaloud resume
lexaloud skip
lexaloud back
lexaloud stop
```

Bind those to additional hotkeys if you want single-keystroke transport.

## 7. Troubleshooting

| Symptom | Check |
|---|---|
| `exit 3: Lexaloud daemon is not running` | `systemctl --user status lexaloud.service` and `journalctl --user -u lexaloud` |
| `exit 2: Select text first` | You pressed the hotkey with nothing selected (or empty PRIMARY on GNOME Wayland). Use `speak-clipboard` instead. |
| Voice sounds robotic | You're on a very old Kokoro version OR you fell back to speech-dispatcher+espeak. Check `lexaloud status` — the provider name should be `kokoro`. |
| `exit 1: SHA256 mismatch` | A model file is corrupt. Delete `~/.cache/lexaloud/models/` and run `lexaloud download-models`. |
| `CUDA silently fell back to CPU` | Daemon logs show "preload_dlls raised" or a session construction warning. Voice still works on CPU at ~10× real-time. |
| Daemon refuses to start with "Both onnxruntime and onnxruntime-gpu installed" | Recreate the venv: `rm -rf ~/.local/share/lexaloud/venv && ./scripts/install.sh` |
