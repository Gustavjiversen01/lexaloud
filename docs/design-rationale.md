# Design rationale

This document distills the key decisions behind Lexaloud's
architecture, including the "why" behind choices that might look
overbuilt for a solo side project. If you want the "what", see
[`architecture.md`](architecture.md) and the code. If you want the
"how it might fail", see [`gotchas.md`](gotchas.md).

## The problem

Academic reading-along on Linux has no first-class tool. The industry
reference — macOS VoiceOver + an OS-level "Services" menu — relies on
hooks that Linux simply does not have at the toolkit layer. The
workable alternative is:

- Select text in any application
- Press a global hotkey
- Hear the selection read by a local neural voice

That sentence describes the happy path. Every other design choice is
downstream of making it robust.

## Why a FastAPI daemon, not a library or a script?

A CLI-only design would face three blocking problems:

1. **Model load cost**: Kokoro's first `create()` after
   `InferenceSession` construction takes ~30 seconds on an RTX 5080
   because CUDA kernels are JIT-compiled on first use. A hotkey
   workflow that pays this cost every time is unusable. A daemon
   amortizes it across the whole session.

2. **Cancellation**: pause, skip, and back need to interact with
   in-flight synthesis + in-flight audio playback + the producer that
   pre-fetches future sentences. You can't express that cleanly in a
   per-invocation subprocess — the subprocess has no durable state to
   cancel.

3. **GNOME hotkey ergonomics**: GNOME Custom Shortcuts fork a fresh
   subprocess per keystroke. That subprocess must exit cleanly, fast.
   Putting the audio loop inside the subprocess would hang the GNOME
   keygrab until audio finishes, which destroys the point.

So we have a daemon that owns all the expensive state, and a thin CLI
that speaks HTTP to it.

## Why HTTP at all? Why not a bespoke socket protocol?

- **FastAPI + httpx give us well-tested JSON, timeouts, and error
  handling** for free.
- **The daemon can be curl'd** during debugging — no custom client
  needed to poke `/state`.
- **`httpx.HTTPTransport(uds=)` on the CLI side** means we get all the
  HTTP niceness over a Unix domain socket, closing the attack surface
  without rewriting the protocol.

## Why Unix domain socket instead of TCP loopback?

The pre-rename daemon bound `127.0.0.1:5487`. Switching to UDS closes
two risks:

- **Local unprivileged attacker**: any process running as the same
  user can send `/speak` requests to a loopback port. Low severity
  (the most they can do is waste your CPU/GPU), but unnecessary.
- **Misconfigured `host`**: `DaemonConfig.host` was a user-editable
  field that could bind 0.0.0.0 if a user edited `config.toml`
  without reading the docs. UDS eliminates the footgun entirely.

The systemd user unit uses `RuntimeDirectory=lexaloud` +
`RuntimeDirectoryMode=0700`, so `$XDG_RUNTIME_DIR/lexaloud/` is
created with mode 0700 before the daemon starts and automatically
removed on service stop. Only the owner user can traverse into that
directory, which makes the socket file inside it unreachable to
anyone else regardless of the socket's own permissions.

## Why sentence-granularity streaming?

Three alternatives were considered:

1. **Whole-selection synthesis** — synthesize the entire pasted text,
   then play. Dead simple, but blocks audio output for 5-30 seconds
   on long passages and makes cancellation impossible until the whole
   job finishes.

2. **Sample-granularity streaming** — emit audio samples as they're
   produced. Kokoro doesn't work this way: `create()` returns the
   whole sentence as a numpy array, not a generator. We'd have to
   monkey-patch the model interface.

3. **Sentence-granularity streaming** (chosen) — split the text into
   sentences, synthesize each in the background, play them in order
   with a bounded pre-fetch queue. First audio arrives as soon as the
   first sentence is synthesized (~1 s), and pause/skip/back have
   clean semantic points to act on.

Inside the consumer, we additionally write the audio in
`SUB_CHUNK_SECONDS`-long blocks and check the pause event between
blocks. This gives mid-sentence pause with ~100 ms latency while
keeping the synthesis pipeline at sentence granularity.

## Why a bounded ready queue?

`asyncio.Queue(maxsize=3)` between the producer and the consumer is
what makes "pause for 15 minutes mid-article, then resume" work
without unbounded memory. When the consumer stops pulling, the
producer blocks on `put()` after 3 chunks have queued. Memory during a
long pause is bounded at 3 sentences of audio + 1 in-flight synthesis
result.

## Why onnxruntime-gpu with CUDA EP, not some other inference backend?

Spike 0 tried four install shapes on the target Ubuntu 24.04 + RTX
5080 machine:

1. `pip install kokoro-onnx` → CPU only.
2. `pip install kokoro-onnx[gpu]` → installs BOTH `onnxruntime` and
   `onnxruntime-gpu`, which silently shadow each other because they
   share the `onnxruntime/` package directory. Result: a session that
   reports `['CPUExecutionProvider']` even though `onnxruntime-gpu` is
   on disk.
3. `pip install onnxruntime-gpu && pip install --no-deps kokoro-onnx`
   → works IF and only if `onnxruntime.preload_dlls(cuda=True,
   cudnn=True)` is called before session construction. Otherwise
   session construction silently falls back to CPU, with only a
   stderr warning.
4. System-wide CUDA 12.8 install → too brittle for a side project.

The production install is (3), with two layers of defense:
- `scripts/install.sh` refuses to proceed if both `onnxruntime` and
  `onnxruntime-gpu` are already in the venv.
- `assert_onnxruntime_environment()` in `src/lexaloud/models.py`
  checks the same at daemon startup.

The exact failure modes and workarounds are documented in
`spikes/spike0_results.md` for posterity.

## Why pinned lockfiles?

`requirements-lock.cuda12.txt` and `requirements-lock.cpu.txt` pin
every transitive dependency to a specific version. Without this, pip
resolution on the user's machine can pull in a kokoro-onnx or
onnxruntime update that changes the silent-fallback behavior, and the
user has no way to debug it.

The morning-checklist for the release includes regenerating both
lockfiles with `--generate-hashes` for supply-chain integrity, but the
initial public release ships with unhashed pins because the audit
flagged hash regeneration of ~90 packages as potentially surfacing
transitive bugs that need human judgment.

## Why sentence segmentation with pysbd?

`pysbd` is a pure-Python sentence boundary detector tuned for academic
prose (including citations like `(Smith 2023)` and Latin
abbreviations like `i.e.`). It's MIT-licensed and has no C extensions.
We pair it with a small custom preprocessor that handles PDF-specific
issues (hyphenation across line breaks, repeated whitespace, etc.).

## Why GTK3 instead of GTK4 or Qt?

- **GTK3** has mature `AppIndicator3` / `AyatanaAppIndicator3`
  bindings for the GNOME tray, which we need.
- **GTK4** dropped AppIndicator support. Writing a GNOME Shell
  extension to replace the tray is a much larger scope.
- **Qt** would double the binary size and pull in another theming
  system for no clear benefit on GNOME (which doesn't match Qt's
  default look).

GTK3 is the most stable, smallest-blast-radius option for v0.1.0.

## Why no overlay / karaoke / browser extension?

All three are genuinely useful. They're deferred to v0.2+ because
each requires design work the maintainer wants to do right, not fast:

- **Floating overlay**: GTK mouse-through + layer-shell behavior is
  compositor-dependent (Wayland layer protocol + X11 override-redirect
  + Mutter quirks). Getting this right takes a dedicated spike.
- **Karaoke word-level**: Kokoro doesn't expose word timings. A forced
  aligner (e.g., `whisper-timestamped` or `mfa`) has its own model,
  licensing, and integration work.
- **Browser extension**: three store listings, cross-origin messaging,
  Manifest v3, clipboard vs. selection API differences. A separate
  project that happens to talk to the Lexaloud daemon.

See `ROADMAP.md` for the full deferred list.

## What would you change if you were starting over?

- **Don't use kokoro-onnx[gpu] extras at all** — the
  `pip install kokoro-onnx[gpu]` syntax looks natural but produces the
  broken coexistence state. The install shape should be explicit.
- **Settle on UDS from day one.** The TCP loopback design left
  cobwebs (the `DaemonConfig.host/port` fields) that took a dedicated
  migration commit to clean up.
- **Start with the distro-neutral installer.** Hardcoding apt made
  Tier 2 support (Fedora / Arch) a bigger rewrite than it should have
  been.

Most of this document is "here's what I'd tell v0-me". Lexaloud itself
is small enough that you can read all of it in an afternoon — the
design is not the moat, the taste in integration details is.
