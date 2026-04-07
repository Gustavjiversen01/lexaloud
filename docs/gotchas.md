# Known gotchas

Things that will trip users (or future-you). Recorded here so nobody has to
rediscover them.

## GNOME Wayland + primary selection

On Ubuntu GNOME Wayland, `wl-paste --primary` may return empty for some
applications (notably Electron apps like VS Code, Obsidian, Slack). The
protocol support varies across Mutter releases. Spike 1 produces an
empirical compatibility matrix for the target machine — see
`docs/capture-matrix.md`.

**Workaround:** bind `readaloud speak-clipboard` to your hotkey instead of
`readaloud speak-selection` and use `Ctrl+C` before pressing the hotkey.
The `speak-clipboard` command intentionally never falls back to the
primary selection (and vice versa) so that empty sources never silently
read the wrong content.

## GNOME has no GlobalShortcuts portal

GNOME 46 does not implement the XDG `org.freedesktop.portal.GlobalShortcuts`
portal as of this writing. The v1 hotkey binding path is manual: use
Settings → Keyboard → View and Customize Shortcuts → Custom Shortcuts.
`readaloud setup` prints the exact walkthrough.

## KDE Plasma differences

On KDE Plasma, the GlobalShortcuts portal is available, but v1 still uses
manual KDE Custom Shortcuts for consistency. A future spike may add the
portal path.

## Zathura requires config change

Zathura does not publish selections to the PRIMARY selection by default.
Add this line to `~/.config/zathura/zathurarc`:

```
set selection-clipboard primary
```

After restarting Zathura, `wl-paste --primary` (or xclip -sel primary)
will return the highlighted PDF text.

## Firefox as a Flatpak cannot see the clipboard

If Firefox is installed as a Flatpak, its sandbox restricts clipboard
access. Workaround: use the deb/apt version of Firefox, or grant the
clipboard portal via `flatpak override --user --talk-name=org.freedesktop.portal.Clipboard org.mozilla.firefox`.

## ROS 2 (or any PYTHONPATH-polluting tool) sourced at login

If you source ROS 2 Jazzy (or Isaac, ComfyUI, etc.) in your shell rc file,
`PYTHONPATH` gets set to `/opt/ros/jazzy/lib/python3.12/site-packages`.
This leaks into any venv Python invocation, despite
`include-system-site-packages=false` in the venv's `pyvenv.cfg`.

**Symptoms:**
- `pip freeze` inside the venv picks up ROS packages.
- Daemon imports may resolve unexpectedly to the ROS-provided version of a
  package.

**Mitigations already in place:**
- `scripts/install.sh` scrubs `PYTHONPATH` for all pip calls (`env -u PYTHONPATH`).
- The systemd unit rendered by `readaloud setup` sets `Environment=PYTHONPATH=`
  so the daemon starts with a clean Python environment.

**What to do manually** if you invoke the daemon or CLI from a shell that
sourced ROS: run `unset PYTHONPATH` first, or launch via systemd.

## CUDA cold start is ~30 seconds

The first `Kokoro.create()` call after `InferenceSession` construction
takes ~30 seconds on an RTX 5080 because CUDA kernels are JIT-compiled on
first use. Subsequent calls for the same sentence length take ~1 second.

The daemon runs an explicit warmup synthesis as a background task during
lifespan startup. Any `/speak` request that arrives during warmup waits on
the provider's `_synth_lock` until warmup completes.

## CUDA runtime libraries from pip wheels

On Ubuntu 24.04 with a system-wide CUDA 12.8 install, `libcublasLt.so.12`
may not be in the default loader path. `onnxruntime-gpu` cannot find it
without help, and `InferenceSession` construction silently falls back to
CPU (with only a stderr warning).

The install pulls in NVIDIA CUDA runtime wheels
(`nvidia-cublas-cu12`, `nvidia-cudnn-cu12`, etc.) and the Kokoro provider
calls `onnxruntime.preload_dlls(cuda=True, cudnn=True)` at init time to
resolve them. If `preload_dlls` raises, the provider logs a warning and
falls back to CPU cleanly.

## ONNX Runtime CPU + GPU coexistence is broken

`pip install kokoro-onnx[gpu]` installs BOTH `onnxruntime` AND
`onnxruntime-gpu` into the same venv, and with both present the CPU
distribution silently shadows the GPU one. `assert_onnxruntime_environment`
in `src/readaloud/models.py` detects this at daemon startup and refuses to
start, with an error message pointing the user at the fix.

## Model weights are not shipped

`kokoro-v1.0.onnx` (~310 MB) and `voices-v1.0.bin` (~28 MB) live under
`~/.cache/readaloud/models/`. They are downloaded on demand by
`readaloud download-models` (called automatically by `readaloud setup`) and
verified against SHA256 pins in `src/readaloud/models.py`. If a download
URL changes or a hash drifts, the daemon refuses to start until the user
re-runs `readaloud download-models`.
