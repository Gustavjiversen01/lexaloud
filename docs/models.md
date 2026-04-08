# Model artifacts

Lexaloud uses the **Kokoro-82M** neural TTS model by [hexgrad on Hugging
Face](https://huggingface.co/hexgrad/Kokoro-82M), accessed via the
[`kokoro-onnx`](https://github.com/thewh1teagle/kokoro-onnx) ONNX
wrapper by thewh1teagle.

## Artifacts

| File | Size | SHA256 (pinned) | Source |
|------|------|-----------------|--------|
| `kokoro-v1.0.onnx` | ~310 MB | `7d5df8ec...` (full hash in source) | https://github.com/thewh1teagle/kokoro-onnx/releases |
| `voices-v1.0.bin` | ~28 MB | `bca610b8...` (full hash in source) | same release |

Full pins are in [`src/lexaloud/models.py`](../src/lexaloud/models.py).
Both files are verified SHA256 on every daemon startup; a mismatch
refuses to load the model.

## Download location

```
~/.cache/lexaloud/models/
├── kokoro-v1.0.onnx
└── voices-v1.0.bin
```

Override with `XDG_CACHE_HOME`:

```bash
XDG_CACHE_HOME=/mnt/big-drive/.cache lexaloud download-models
```

## Licensing

- **Kokoro-82M model weights**: Apache-2.0 per the Hugging Face model
  card. If this ever changes upstream, update this document and
  `THIRD_PARTY_LICENSES.md` accordingly.
- **`kokoro-onnx` wrapper package**: MIT per the wheel's LICENSE file.
- **Voices**: bundled with the `voices-v1.0.bin` file under the same
  Apache-2.0 license as the weights.

Lexaloud does not modify or repackage the weights. Users redistributing
a Lexaloud installation in bulk (e.g., AppImage, Docker) should ensure
their distribution respects the upstream Apache-2.0 and MIT terms.

## Voices

Kokoro v1.0 ships with ~50+ voices. Lexaloud's control window exposes
a curated subset:

| ID | Description |
|----|-------------|
| `af_heart` | American female, warm (default) |
| `af_bella` | American female, bright |
| `af_nova` | American female, energetic |
| `af_sarah` | American female, calm |
| `af_sky` | American female, light |
| `am_adam` | American male, deep |
| `am_michael` | American male, conversational |
| `am_onyx` | American male, serious |
| `bf_emma` | British female |
| `bf_isabella` | British female |
| `bm_george` | British male |
| `bm_lewis` | British male |

Any voice string the installed voices pack recognizes works in
`config.toml` — the curated list is just a convenience for the GUI
dropdown. See the Hugging Face model card for the full voice
catalog.

## Languages

Tested: `en-us`, `en-gb`.

Kokoro supports more languages upstream (Japanese, Chinese, etc.) but
the preprocessor and voice catalog in Lexaloud v0.1.0 are tuned for
English. Non-English use may work but is not supported.

## Why 310 MB?

Neural TTS tradeoffs. Kokoro is intentionally small as neural models
go — the closest comparable open-weights models (XTTS-v2, Mars-5) are
hundreds of MB to multiple GB. 310 MB is a one-time download that
lives in `~/.cache` and persists across Lexaloud reinstalls.

## Recovering from a corrupt download

```bash
rm -rf ~/.cache/lexaloud/models
lexaloud download-models
```

The installer checks SHA256 and refuses to start with a corrupt file,
so "it just feels slow lately" is never a corrupt model — the daemon
would hard-fail at startup instead.
