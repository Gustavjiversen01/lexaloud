# Spike 0 — Kokoro standalone results

Target machine: Ubuntu 24.04.3 LTS, kernel 6.17.0-20-generic, glibc 2.39,
Python 3.12.3, RTX 5080 (driver 590.48.01, compute cap 12.0, 16303 MiB),
CUDA 12.8 installed system-wide at /usr/local/cuda-12.8.

Run date: 2026-04-07.

## TL;DR — install recipe for v1 core MVP

Produces a clean environment with CUDA EP working on the RTX 5080. This
recipe goes into `scripts/install.sh`.

```bash
python3 -m venv ~/.local/share/readaloud/venv
~/.local/share/readaloud/venv/bin/pip install --upgrade pip
~/.local/share/readaloud/venv/bin/pip install \
    --no-deps kokoro-onnx==0.5.0
~/.local/share/readaloud/venv/bin/pip install \
    -r requirements-lock.txt
```

At runtime, before constructing the `InferenceSession`:

```python
import onnxruntime as ort
ort.preload_dlls(cuda=True, cudnn=True, msvc=False)
session = ort.InferenceSession(
    model_path,
    providers=[("CUDAExecutionProvider", {}), "CPUExecutionProvider"],
)
from kokoro_onnx import Kokoro
kokoro = Kokoro.from_session(session, voices_path=str(voices_path))
```

## Install-shape comparison

The plan required trying `kokoro-onnx[gpu]` first before escalating to
`--no-deps`. The result: **`kokoro-onnx[gpu]` is not usable** because
`kokoro-onnx==0.5.0` depends on `onnxruntime>=1.20.1`, and the `[gpu]` extra
adds `onnxruntime-gpu`. pip installs both distributions into the same
environment.

Both packages install their Python modules into the shared `onnxruntime/`
directory. With both present, `import onnxruntime` silently resolves to the
CPU distribution's files — `ort.get_available_providers()` returns
`['AzureExecutionProvider', 'CPUExecutionProvider']` with no CUDA EP, and any
subsequent session construction is CPU-only.

Attempting to `pip uninstall onnxruntime` to remove the CPU variant while
keeping the GPU variant **breaks both packages**: they share directory
ownership, and pip's uninstall removes the shared `__init__.py` along with
the CPU-specific files. After `pip uninstall onnxruntime`, `import
onnxruntime` raises `AttributeError: module has no attribute '__version__'`.

The correct shape, which is what v1 uses:

1. Install `kokoro-onnx` with `--no-deps`.
2. Install `onnxruntime-gpu` separately.
3. Install kokoro-onnx's other transitive dependencies explicitly
   (`numpy`, `sounddevice`, `phonemizer-fork`, `espeakng-loader`, and the
   chain under `phonemizer-fork` — all captured in the lockfile).

## CUDA library load fix (required on this machine)

Even with `onnxruntime-gpu==1.24.4` installed alone and
`ort.get_available_providers()` listing `CUDAExecutionProvider`, constructing
an `InferenceSession` with `providers=[("CUDAExecutionProvider", {}), ...]`
**silently falls back to CPU** — no exception, only a stderr warning:

```
[E:onnxruntime:Default, provider_bridge_ort.cc:...] Failed to load library
libonnxruntime_providers_cuda.so with error: libcublasLt.so.12: cannot open
shared object file: No such file or directory
[W:onnxruntime:Default, onnxruntime_pybind_state.cc:...] Failed to create
CUDAExecutionProvider. Require cuDNN 9.* and CUDA 12.*.
```

Root cause: despite the system having `/usr/local/cuda-12.8` and a working
NVIDIA driver, the CUDA runtime libraries (`libcublasLt.so.12`,
`libcudnn.so.9`, etc.) are not in the default library search path.
`ldconfig -p | grep cublas` returns nothing. `find /usr/local/cuda-12.8 -name
'libcublasLt*'` also returns nothing — the system install does not include
cublas runtime libs.

The fix:

1. Install NVIDIA CUDA runtime wheels via pip (`nvidia-cublas-cu12`,
   `nvidia-cudnn-cu12`, `nvidia-cuda-runtime-cu12`, `nvidia-cuda-nvrtc-cu12`,
   `nvidia-cufft-cu12`, `nvidia-curand-cu12`, `nvidia-nvjitlink-cu12`).
2. Call `onnxruntime.preload_dlls(cuda=True, cudnn=True, msvc=False)` at
   daemon startup, **before** constructing the `InferenceSession`.

`preload_dlls` searches the NVIDIA pip wheels' install paths and loads the
CUDA/cuDNN libraries into the current process so the CUDA EP can find them.
Introduced in `onnxruntime>=1.22` per the ORT docs.

**The v1 daemon must call `preload_dlls` before any `InferenceSession`
construction.** Not doing so silently degrades performance by ~6× and
produces no visible error beyond a stderr warning that systemd would swallow.

### Warning messages (informational, not errors)

After CUDA EP is active, Kokoro loading produces two warnings:

```
[W:onnxruntime:] 39 Memcpy nodes are added to the graph main_graph for
CUDAExecutionProvider. It might have negative impact on performance
(including unable to run CUDA graph).
[W:onnxruntime:] ScatterND with reduction=='none' only guarantees to be
correct if indices are not duplicated.
```

Both are informational:
- The Memcpy warning means some Kokoro ops fall back to CPU and the CUDA
  graph can't be fully captured. This is a minor optimization loss, not a
  correctness issue. It's a property of the exported ONNX graph, not of our
  session setup.
- The ScatterND warning applies to ops where index duplication would be
  incorrect; Kokoro's ScatterND nodes do not have duplicated indices so this
  is safe for our use.

Silencing these is fine; leaving them visible at daemon startup is also fine.

## Performance measurements

Test passage: 125-word dense academic prose (from Hui & Godfroid 2026).
Output: 1,503,744 samples @ 24000 Hz = 62.66 s of audio.
Measured with `Kokoro.create(passage, voice="af_heart", lang="en-us")` via
`time.perf_counter()` around the call.

| Configuration | Wall time | Real-time factor |
|---|---|---|
| CPU EP only (`--cpu`) | 6.37 s | ~9.8× real-time |
| CUDA EP cold (first call after session build) | 31.00 s | ~2.0× real-time |
| CUDA EP warm (second call, same process) | 2.26 s | ~27.7× real-time |
| CUDA EP fully warm (third call) | 1.05 s | ~59.7× real-time |

### Interpretation

**Cold start is expensive.** The first synthesis after `InferenceSession`
construction triggers CUDA kernel JIT compilation and cuDNN algorithm
selection, which dominates the 31-second figure. This is a one-time cost per
process lifetime.

**Warm GPU is ~6× faster than CPU** (1.05s vs 6.37s once kernels are cached).
For short sentences (2-5 seconds of audio), latency to first audio on the
GPU is ~30-100 ms once warm.

**Design consequence for the daemon**: on startup, synthesize a short (1-2
word) warmup passage with the same voice the user will request. This absorbs
the cold-start cost before the first real user request. The warmup should be
invisible to the user — log it, but don't block the HTTP interface behind
it; the daemon can accept requests and the first one will naturally take
longer while warmup completes.

**CPU fallback is viable.** At 9.8× real-time on CPU alone, Kokoro keeps up
with natural reading speed on this machine with no GPU involvement at all.
If the CUDA path breaks in a future driver or ORT update, the core MVP
remains usable.

## Artifact provenance

Downloaded from
`https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/`.

| File | Size (bytes) | SHA256 |
|---|---|---|
| kokoro-v1.0.onnx | 325,532,387 | `7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5` |
| voices-v1.0.bin | 28,214,398 | `bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d` |

Pinned in `spikes/spike0_kokoro.py` under the `ARTIFACTS` constant, and should be
mirrored into `src/readaloud/models.py` when the core MVP builds that module.

## Kokoro.from_session signature (verified)

```python
Kokoro.from_session(
    session: onnxruntime.capi.onnxruntime_inference_collection.InferenceSession,
    voices_path: str,
    espeak_config: kokoro_onnx.config.EspeakConfig | None = None,
    vocab_config: dict | str | None = None,
)
```

Present in `kokoro-onnx==0.5.0`. `voices_path` is a string path (not
bytes/file-like). The default `espeak_config` and `vocab_config` are fine for
v1; leave them unset until a spike shows a need.

## Warnings and environment pollution

The target user has ROS 2 Jazzy sourced in their shell, which exports
`PYTHONPATH=/opt/ros/jazzy/lib/python3.12/site-packages`. This leaks into
`.venv-spike0` despite `pyvenv.cfg` having `include-system-site-packages =
false`, because `PYTHONPATH` is read *in addition to* the venv's site-packages.

Effects:

- `pip freeze` run without clearing `PYTHONPATH` produces a 186-line lockfile
  containing ROS packages that are not actually installed in the venv. The
  correct lockfile is 46 lines.
- Any `readaloud` daemon run from a shell that sourced the ROS setup script
  will inherit this pollution and may conflict with ROS Python packages.

**v1 action items from this finding:**

- `scripts/install.sh` runs `pip freeze` with `env -u PYTHONPATH` or with the
  cleaner alternative of `pip --isolated freeze`.
- `scripts/install.sh` should warn the user if `$PYTHONPATH` is non-empty at
  install time; print a note that the rendered systemd unit will unset it.
- The rendered systemd `.service` file sets `Environment=PYTHONPATH=` (empty)
  to scrub any inherited pollution.
- The README documents this for users who source ROS (or ComfyUI, or any
  other project that exports `PYTHONPATH`).

## What gets written from this spike

- `requirements-lock.txt` — 46-line clean dependency set, produced with
  `env -u PYTHONPATH .venv-spike0/bin/pip freeze`.
- `spikes/spike0_kokoro.py` — the spike script, with SHA256 constants pinned
  and `preload_dlls` called unconditionally in the CUDA path.
- `spikes/spike0_results.md` — this file.
- `spikes/spike0_results.json` — the most recent machine-readable run output
  (from `dataclasses.asdict`).
- `~/.cache/readaloud/models/kokoro-v1.0.onnx` and `voices-v1.0.bin` —
  artifacts downloaded once, will be reused by the core MVP.

## Decisions recorded

1. **Install shape**: `pip install --no-deps kokoro-onnx` + `pip install -r
   requirements-lock.txt`. Not `kokoro-onnx[gpu]`.
2. **Artifact source**: Option A (`thewh1teagle/kokoro-onnx` release tag
   `model-files-v1.0`). SHA256 pinned.
3. **`Kokoro.from_session(session, voices_path=...)`** signature is stable
   at `kokoro-onnx==0.5.0`; use it.
4. **Daemon startup must call `ort.preload_dlls(cuda=True, cudnn=True)`**
   before `InferenceSession` construction, unconditionally, on Linux with
   NVIDIA wheels.
5. **Daemon startup must warm up Kokoro** with a short synthesis after
   session construction, to absorb the ~30-second JIT/kernel-compile cost
   before the first user request.
6. **CPU EP remains a valid fallback** if CUDA fails at runtime; ~10×
   real-time is fine for reading-along.
7. **`PYTHONPATH` scrubbing** is required in the systemd unit and in
   `scripts/install.sh` because the target user sources ROS at login.
