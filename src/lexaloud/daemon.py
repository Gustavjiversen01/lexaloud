"""FastAPI daemon exposing the Lexaloud HTTP API on loopback.

Routes:
    POST /speak  {text, mode?}
    POST /pause
    POST /resume
    POST /stop
    POST /skip
    POST /back
    GET  /state
    GET  /healthz

Design notes:
- Uses a dedicated ThreadPoolExecutor for provider work so that interpreter
  shutdown (triggered by systemd SIGTERM) can bail out without waiting on
  the default executor's non-daemon worker threads.
- The provider's warmup runs as a background task during lifespan; while
  warmup runs, the player's state is reported as "warming" via
  `player.set_warming(True)`.
- The /speak middleware enforces a Content-Length cap using JSONResponse
  directly — HTTPException raised from middleware does NOT pass through
  FastAPI's exception handlers, so returning the response here is essential.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import __version__
from .audio import AudioSink, SoundDeviceSink
from .config import Config, load_config, runtime_dir, socket_path
from .models import assert_onnxruntime_environment, ensure_artifacts
from .player import Player, PlayerState
from .preprocessor import PreprocessorConfig, preprocess
from .providers.base import SpeechProvider
from .providers.kokoro import KokoroProvider

log = logging.getLogger(__name__)


# Hard cap on the length of a single sentence after preprocessing. Dense
# academic prose can legitimately hit 500-1500 characters; 4096 is a
# generous ceiling that still rules out pathological input (e.g., an
# uninterrupted 200 KB paragraph with no sentence boundaries, which
# would either OOM the GPU or silently produce garbage audio).
MAX_SENTENCE_CHARS = 4096


# ---------- request/response models ----------


class SpeakRequest(BaseModel):
    text: str = Field(..., min_length=1)
    mode: Literal["replace", "append"] = "replace"


class StateResponse(BaseModel):
    state: str
    current_sentence: str | None
    pending_count: int
    ready_count: int
    provider_name: str
    session_providers: list[str]


# ---------- daemon wiring ----------


@dataclass
class DaemonComponents:
    cfg: Config
    provider: SpeechProvider
    sink: AudioSink
    player: Player
    preproc_config: PreprocessorConfig


def build_components(cfg: Config | None = None) -> DaemonComponents:
    cfg = cfg or load_config()

    # Runtime guard: refuse to start if the ONNX Runtime environment is broken.
    assert_onnxruntime_environment()

    artifacts = ensure_artifacts(download_if_missing=False)
    provider = KokoroProvider(
        model_path=artifacts["kokoro-v1.0.onnx"],
        voices_path=artifacts["voices-v1.0.bin"],
        voice=cfg.provider.voice,
        lang=cfg.provider.lang,
        speed=cfg.provider.speed,
    )
    sink: AudioSink = SoundDeviceSink()
    player = Player(provider=provider, sink=sink, ready_queue_depth=cfg.daemon.ready_queue_depth)
    preproc_config = PreprocessorConfig(
        strip_numeric_bracket_citations=cfg.preprocessor.strip_numeric_bracket_citations,
        strip_parenthetical_citations=cfg.preprocessor.strip_parenthetical_citations,
        expand_latin_abbreviations=cfg.preprocessor.expand_latin_abbreviations,
        pdf_cleanup=cfg.preprocessor.pdf_cleanup,
    )
    return DaemonComponents(
        cfg=cfg,
        provider=provider,
        sink=sink,
        player=player,
        preproc_config=preproc_config,
    )


def create_app(components: DaemonComponents | None = None) -> FastAPI:
    comps = components or build_components()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Use a dedicated ThreadPoolExecutor so shutdown can bail out without
        # waiting on the default executor's non-daemon worker threads. This
        # makes systemd SIGTERM responsive even if a Kokoro.create() is in
        # flight in the executor at the moment of shutdown.
        exec_pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="lexaloud-worker"
        )
        loop = asyncio.get_running_loop()
        loop.set_default_executor(exec_pool)

        comps.player.set_warming(True)

        async def _warmup_bg() -> None:
            try:
                await comps.provider.warmup()
            except Exception as e:  # noqa: BLE001
                log.error("background warmup failed: %s", e)
            # Sink warmup: pre-open the audio stream so PipeWire's
            # 24000→44100 Hz resampler is initialized before the user's
            # first hotkey press. Best-effort — the daemon works without
            # it (begin_stream cold-opens lazily), but the first sentence
            # would clip without the warm stream.
            try:
                await comps.sink.warmup(24000, 1)
            except Exception as e:  # noqa: BLE001
                log.warning("sink warmup failed (audio device may be unavailable): %s", e)
            finally:
                comps.player.set_warming(False)

        warmup_task = asyncio.create_task(_warmup_bg(), name="lexaloud-warmup")
        try:
            yield
        finally:
            warmup_task.cancel()
            try:
                await warmup_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            await comps.player.shutdown()
            exec_pool.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(title="Lexaloud", version=__version__, lifespan=lifespan)
    app.state.components = comps

    max_bytes = comps.cfg.capture.max_bytes
    # Allow a small overhead for JSON envelope (keys + quotes + escapes).
    HARD_HEADER_CAP = max_bytes + 4096

    @app.middleware("http")
    async def _payload_guard(request: Request, call_next):
        # HTTPException raised from middleware does NOT pass through
        # FastAPI's exception handler machinery — it surfaces as a 500.
        # We must return a JSONResponse directly.
        if request.url.path == "/speak":
            content_length = request.headers.get("content-length")
            if content_length is not None:
                try:
                    if int(content_length) > HARD_HEADER_CAP:
                        return JSONResponse(
                            status_code=413,
                            content={"detail": "payload too large"},
                        )
                except ValueError:
                    pass
        return await call_next(request)

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/state", response_model=StateResponse)
    async def get_state() -> StateResponse:
        s: PlayerState = comps.player.state
        return StateResponse(**asdict(s))

    @app.post("/speak", response_model=StateResponse)
    async def speak(req: SpeakRequest) -> StateResponse:
        if "\x00" in req.text:
            raise HTTPException(status_code=400, detail="text contains null bytes")
        if len(req.text.encode("utf-8")) > max_bytes:
            raise HTTPException(status_code=413, detail="text exceeds capture.max_bytes")
        sentences = preprocess(req.text, comps.preproc_config)
        if not sentences:
            raise HTTPException(status_code=400, detail="no synthesizable sentences")
        too_long = [(i, len(s)) for i, s in enumerate(sentences) if len(s) > MAX_SENTENCE_CHARS]
        if too_long:
            idx, length = too_long[0]
            raise HTTPException(
                status_code=400,
                detail=(
                    f"sentence {idx} exceeds MAX_SENTENCE_CHARS "
                    f"({length} > {MAX_SENTENCE_CHARS}); preprocessing failed "
                    f"to segment this input"
                ),
            )
        await comps.player.speak(sentences, mode=req.mode)
        return StateResponse(**asdict(comps.player.state))

    @app.post("/pause", response_model=StateResponse)
    async def pause() -> StateResponse:
        await comps.player.pause()
        return StateResponse(**asdict(comps.player.state))

    @app.post("/resume", response_model=StateResponse)
    async def resume() -> StateResponse:
        await comps.player.resume()
        return StateResponse(**asdict(comps.player.state))

    @app.post("/stop", response_model=StateResponse)
    async def stop() -> StateResponse:
        await comps.player.stop()
        return StateResponse(**asdict(comps.player.state))

    @app.post("/toggle", response_model=StateResponse)
    async def toggle() -> StateResponse:
        """Flip between speaking and paused. No-op in idle/warming."""
        current = comps.player.state.state
        if current == "speaking":
            await comps.player.pause()
        elif current == "paused":
            await comps.player.resume()
        return StateResponse(**asdict(comps.player.state))

    @app.post("/skip", response_model=StateResponse)
    async def skip() -> StateResponse:
        await comps.player.skip()
        return StateResponse(**asdict(comps.player.state))

    @app.post("/back", response_model=StateResponse)
    async def back() -> StateResponse:
        await comps.player.back()
        return StateResponse(**asdict(comps.player.state))

    return app


def run() -> None:
    """Entry point for `lexaloud daemon`.

    Binds a Unix domain socket at $XDG_RUNTIME_DIR/lexaloud/lexaloud.sock.
    The parent dir is created and owned by systemd via `RuntimeDirectory=`
    in the unit file; as a belt-and-suspenders fallback for non-systemd
    invocations (e.g., running `lexaloud daemon` from a shell for
    debugging), we create it here too with mode 0700.

    The previous TCP loopback bind (cfg.daemon.host/port) is deprecated in
    v0.1.0 and kept only in the Config dataclass for forward compat.
    """
    import uvicorn

    _ = load_config()  # load_config still parses config.toml for side effects
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    sock = socket_path()
    parent = sock.parent
    rt = runtime_dir()

    # Defense-in-depth: refuse to bind outside the user's XDG_RUNTIME_DIR.
    # This guards against environment-variable shenanigans (e.g., a caller
    # who sets XDG_RUNTIME_DIR to /tmp before invoking the daemon).
    try:
        resolved_sock = sock.resolve()
        resolved_rt = rt.resolve()
    except OSError as e:
        log.error("cannot resolve socket path: %s", e)
        raise
    if not str(resolved_sock).startswith(str(resolved_rt) + "/"):
        raise RuntimeError(
            f"refusing to bind UDS outside XDG_RUNTIME_DIR: "
            f"socket={resolved_sock}, runtime_dir={resolved_rt}"
        )

    parent.mkdir(parents=True, exist_ok=True)
    # Enforce 0700 on the parent dir (matches RuntimeDirectoryMode=0700
    # in the systemd unit).
    parent.chmod(0o700)
    # Remove any stale socket from a previous run. Safe because UDS
    # files are not inodes the OS reclaims automatically on daemon crash.
    if sock.exists() or sock.is_symlink():
        sock.unlink()

    app = create_app()
    uvicorn.run(app, uds=str(sock), log_config=None)


if __name__ == "__main__":
    run()
