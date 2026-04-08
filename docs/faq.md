# FAQ

## Is Lexaloud private? What does it send over the network?

Lexaloud performs zero telemetry. The only outbound network calls are
the one-time model artifact downloads from the `kokoro-onnx` GitHub
releases page, fetched over HTTPS with SHA256 integrity checks pinned
in source. After the first `lexaloud download-models`, Lexaloud never
contacts the network again.

The daemon listens on a Unix domain socket at
`$XDG_RUNTIME_DIR/lexaloud/lexaloud.sock` with mode 0700 on the parent
directory, enforced by systemd's `RuntimeDirectory=` directive. There
is no TCP listener, no open port.

Selection text is never written to disk. Log lines that mention a
sentence replace the content with a SHA-1 fingerprint + length, so
`journalctl --user -u lexaloud.service` never contains user text.

## Why kokoro-82M specifically?

- **Open weights**, Apache-2.0 licensed.
- **Small enough to run locally** on consumer hardware — 82M parameters
  vs. hundreds of MB for comparable neural voices.
- **Fast on CPU fallback** — ~10× real-time on a modern x86_64 CPU, fine
  for reading-along.
- **High quality** for its size, especially for English reading prose.

## Can I use a different TTS backend?

Not in v0.1.0. The `SpeechProvider` protocol (see
`src/lexaloud/providers/base.py`) is designed to support multiple
backends — additional providers (Piper, Chatterbox, etc.) are on the
v0.2+ roadmap.

## Why not pip install?

`pip install lexaloud` won't give you a working installation because
the TTS stack requires a specific `kokoro-onnx` + `onnxruntime-gpu`
install sequence that can't be expressed in a single `pip install`.
`scripts/install.sh` is the only supported path for v0.1.x. A PyPI
namespace placeholder exists to reserve the name; installing it will
print install instructions and exit.

## Why no mid-sentence pause?

Kokoro synthesizes one sentence at a time. Pause takes effect within
~100 ms of the keystroke thanks to sub-chunk polling during playback,
but the trailing ~100-150 ms of the current sub-chunk may still come
out of the OS audio buffer after you press pause.

## Why a FastAPI daemon instead of a library?

Three reasons:

1. **Warmup cost**: Kokoro's first call after model load is ~30 seconds
   on a cold CUDA context. A long-running daemon amortizes this across
   every subsequent invocation so the CLI feels instant.
2. **Job cancellation**: the daemon owns a monotonically-increasing
   job ID and can cooperatively cancel in-flight synthesis when you
   press stop/skip/back. A library-only design would make this
   orders-of-magnitude harder.
3. **Hotkey integration**: GNOME custom shortcuts run a fresh
   subprocess per keystroke. That subprocess exits almost immediately
   after sending the HTTP request — no audio state lives in the
   subprocess, only in the daemon.

## Will there be a floating overlay?

Yes — planned for v0.2. See `ROADMAP.md`.

## Will there be a browser extension?

Eventually — see `ROADMAP.md`. Browser extensions are a significant
ecosystem investment (three store listings, cross-origin messaging,
manifest v3) so they're deferred until the core desktop experience
is stable.

## Can I use Lexaloud on Windows or macOS?

No. Lexaloud is Linux-only by design. It depends on XDG
runtime directories, `systemd --user`, PortAudio via ALSA/PipeWire,
and GNOME-style custom shortcuts. Porting to Windows or macOS would
be a near-total rewrite.

## Can I use Lexaloud on a remote server?

The daemon binds a Unix domain socket, so it's local-only by design.
If you want to use Lexaloud for speech on a different machine than the
one where the text lives, the simplest approach is to copy the text
into the local clipboard over SSH (e.g., `ssh host cat file |
wl-copy`) and then use `lexaloud speak-clipboard`.

## What about accessibility?

Lexaloud is designed as a reading-along tool, not an accessibility
replacement for a screen reader. If you need a full screen reader,
Orca is the mature Linux option.

That said, several accessibility-oriented improvements are on the
v0.2+ roadmap (floating overlay with current-sentence highlighting,
optional karaoke word-level highlighting).

## Why does the daemon take ~30 seconds to warm up?

CUDA kernels are JIT-compiled on first use. The daemon runs a warmup
synthesis as a background task during lifespan startup. You can
observe this via `lexaloud status` during startup — the state will
show `warming` until the first synthesis completes. Subsequent
requests are ~1 second per sentence.

## How do I uninstall?

See [`uninstall.md`](uninstall.md).
