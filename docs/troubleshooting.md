# Troubleshooting

The fastest way to get help is to run `lexaloud bug-report` and paste
the output into a GitHub issue. The rest of this file covers common
symptoms you can fix yourself.

## `lexaloud: command not found`

The installer puts `lexaloud` inside the venv at
`~/.local/share/lexaloud/venv/bin/lexaloud`. Either invoke the full
path or symlink it into `~/.local/bin`:

```bash
ln -s ~/.local/share/lexaloud/venv/bin/lexaloud ~/.local/bin/lexaloud
```

Then ensure `~/.local/bin` is on your `PATH`.

## `exit 3: Lexaloud daemon is not running`

```bash
systemctl --user status lexaloud.service
journalctl --user -u lexaloud.service -n 50 --no-pager
```

Common causes:
- The daemon crashed on startup. Look at the tail of the journal for a
  Python traceback.
- systemd --user isn't running for your session (rare on modern GNOME
  but possible in minimal environments). Check with `systemctl --user`.
- The unit file is stale. Run `lexaloud setup --force` to regenerate it,
  then `systemctl --user daemon-reload && systemctl --user restart
  lexaloud.service`.

## `exit 2: Select text first` (but I DID select text)

You're probably on GNOME Wayland and the app you're selecting text in
doesn't publish to the PRIMARY selection. Workaround: use
`lexaloud speak-clipboard` and press `Ctrl+C` before the hotkey. See
[`gotchas.md`](gotchas.md) for the full list of known-bad apps.

## CUDA silently fell back to CPU

In the daemon logs:

```
Requested CUDAExecutionProvider but session reports ['CPUExecutionProvider'].
```

Means `onnxruntime.preload_dlls(cuda=True, cudnn=True)` couldn't load
the CUDA runtime wheels. Check that the installer pulled them in:

```bash
env -u PYTHONPATH ~/.local/share/lexaloud/venv/bin/python -m pip list | grep -i nvidia
```

You should see `nvidia-cublas-cu12`, `nvidia-cudnn-cu12`, etc. If not,
you may have installed the `cpu` backend by mistake; re-run
`./scripts/install.sh --backend cuda12`.

## `Multiple ONNX Runtime distributions installed`

This is the Spike 0 coexistence landmine. The fix is always the same:

```bash
rm -rf ~/.local/share/lexaloud/venv
./scripts/install.sh
```

Do NOT try `pip uninstall onnxruntime` — the two distributions share
files and the uninstall will corrupt both.

## Voice sounds robotic / glitchy

Check `lexaloud status`: the `provider_name` should be `kokoro`. If
it's anything else you fell back to a different TTS (that shouldn't
happen in v0.1.x but worth verifying).

If it's `kokoro` but the audio is choppy, your CPU is probably
struggling to keep up. Try lowering `speed` in `config.toml` to 1.0 or
below, or install the `cuda12` backend if you have an NVIDIA GPU.

## Model download failed

```bash
rm -rf ~/.cache/lexaloud/models
lexaloud download-models
```

If the download hangs, the artifact URL may have moved. File an issue
with the error message — the pinned URL + SHA256 hash is in
`src/lexaloud/models.py` and needs to be updated if upstream moves
the files.

## Pause / skip / back doesn't work

- The daemon must be running.
- Pause takes effect at the next sub-chunk boundary (~100 ms).
- `skip`/`back` only work while the state is `speaking` or `paused`
  (not `idle` or `warming`).

## Tray indicator doesn't appear

On GNOME 46+ you need the `ubuntu-appindicators` Shell Extension
(installed and enabled by default on Ubuntu, optional on Fedora / Arch).
Install it from https://extensions.gnome.org/extension/615/ if it's
missing.

To launch the indicator manually:

```bash
~/.local/share/lexaloud/venv/bin/lexaloud-indicator
```

Watch the terminal for errors — the most common is missing
`gir1.2-ayatanaappindicator3-0.1` (or the Fedora/Arch equivalent).

## `Selection too large for the daemon to accept` (exit 4)

The default selection cap is 200 KB. Raise `capture.max_bytes` in
`config.toml` and restart the daemon, or use
`lexaloud speak-selection --max-bytes 500000`.

## Absolutely nothing works

```bash
lexaloud bug-report > /tmp/lexaloud-bug.md
```

Open a GitHub issue and paste the output. Include what you tried.
