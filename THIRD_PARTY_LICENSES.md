# Third-party licenses

Lexaloud is distributed under the MIT license (see `LICENSE`). This file
discloses the licenses of the runtime dependencies that ship alongside a
working Lexaloud install.

## Disclosure: GPL-3.0 dynamic dependency chain

Lexaloud's own source code is MIT-licensed. The runtime text-to-speech
stack pulls in the following GPL-3.0 components via `kokoro-onnx`:

- `phonemizer-fork` — GPL-3.0-or-later (Python)
- `espeakng-loader` — package metadata declares no explicit license, but
  it bundles a prebuilt `espeak-ng` binary which is licensed under
  GPL-3.0-or-later (see https://github.com/espeak-ng/espeak-ng)

These are **dynamic-link dependencies**. Lexaloud's code does not statically
link against, embed, or copy any GPL-3 source. Under the widely-understood
reading of the GPL, dynamic use does not impose GPL-3 obligations on
Lexaloud's own source code. However, anyone **redistributing** the installed
runtime stack (for example, bundling a Lexaloud installation into an
AppImage or Docker image) should honor the GPL-3.0 terms of these components.

If you want a fully permissive stack, you would need to replace
`phonemizer-fork` / `espeak-ng` with an MIT/BSD/Apache-licensed phonemizer.
No such drop-in replacement existed at the time of this release.

## Key runtime dependencies

| Package            | Version   | License                  | Notes |
|--------------------|-----------|--------------------------|-------|
| `kokoro-onnx`      | 0.5.0     | MIT                      | Main TTS wrapper |
| `onnxruntime-gpu`  | 1.24.4    | MIT                      | ONNX Runtime with CUDA EP |
| `phonemizer-fork`  | 3.3.2     | GPL-3.0-or-later         | ⚠ GPL chain — see disclosure above |
| `espeakng-loader`  | 0.2.4     | GPL-3.0 (binary bundled) | ⚠ GPL chain — see disclosure above |
| `fastapi`          | 0.135.3   | MIT                      | HTTP daemon framework |
| `starlette`        | 1.0.0     | BSD-3-Clause             | FastAPI's ASGI core |
| `uvicorn`          | 0.44.0    | BSD-3-Clause             | ASGI server |
| `httpx`            | 0.28.1    | BSD-3-Clause             | CLI → daemon client |
| `pydantic`         | 2.12.5    | MIT                      | Request/response models |
| `pysbd`            | 0.3.4     | MIT                      | Sentence boundary detection |
| `sounddevice`      | 0.5.5     | MIT                      | Audio output via PortAudio |
| `numpy`            | 2.4.4     | BSD-3-Clause             | Audio sample arrays |

## Kokoro-82M model weights

The Kokoro-82M neural TTS model weights are developed by
[hexgrad/Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) and
distributed separately from this repository. The weights are licensed under
Apache-2.0 per the HuggingFace model card (verify at
https://huggingface.co/hexgrad/Kokoro-82M before redistributing).

Lexaloud downloads the ONNX-converted weights from the
[`kokoro-onnx`](https://github.com/thewh1teagle/kokoro-onnx) GitHub releases
on first run, SHA256-pinned in `src/lexaloud/models.py`.

## NVIDIA CUDA runtime wheels

The installation of `onnxruntime-gpu` via pip transitively installs NVIDIA's
CUDA runtime libraries as `pip` wheels:

- `nvidia-cublas-cu12`
- `nvidia-cuda-nvrtc-cu12`
- `nvidia-cuda-runtime-cu12`
- `nvidia-cudnn-cu12`
- `nvidia-cufft-cu12`
- `nvidia-curand-cu12`
- `nvidia-nvjitlink-cu12`

These are distributed by NVIDIA directly via `https://pypi.org/` under
NVIDIA's proprietary CUDA/cuDNN Software License Agreements. Lexaloud does
not redistribute these wheels; pip fetches them from NVIDIA's own PyPI
publishing channel on install. Users must accept NVIDIA's license terms
to use the CUDA backend. See:

- https://docs.nvidia.com/cuda/eula/index.html
- https://developer.nvidia.com/cudnn-license

## Transitive dependencies

A full list with versions can be regenerated at any time:

```bash
env -u PYTHONPATH .venv-spike0/bin/python -m piplicenses \
    --from=mixed --with-urls --format=markdown
```

All transitive packages present in `requirements-lock.cuda12.txt` and
`requirements-lock.cpu.txt` are MIT, BSD, Apache-2.0, MPL-2.0, or PSF-License
unless noted in the tables above.
