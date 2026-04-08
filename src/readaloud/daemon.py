"""FastAPI daemon exposing the ReadAloud HTTP API on loopback.

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

from .audio import AudioSink, SoundDeviceSink
from .config import Config, load_config
from .models import assert_onnxruntime_environment, ensure_artifacts
from .player import Player, PlayerState
from .preprocessor import PreprocessorConfig, preprocess
from .providers.base import SpeechProvider
from .providers.kokoro import KokoroProvider

log = logging.getLogger(__name__)


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
    player = Player(
        provider=provider, sink=sink, ready_queue_depth=cfg.daemon.ready_queue_depth
    )
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
            max_workers=2, thread_name_prefix="readaloud-worker"
        )
        loop = asyncio.get_running_loop()
        loop.set_default_executor(exec_pool)

        comps.player.set_warming(True)

        async def _warmup_bg() -> None:
            try:
                await comps.provider.warmup()
            except Exception as e:  # noqa: BLE001
                log.error("background warmup failed: %s", e)
            finally:
                comps.player.set_warming(False)

        warmup_task = asyncio.create_task(_warmup_bg(), name="readaloud-warmup")
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

    app = FastAPI(title="ReadAloud", version="0.0.1", lifespan=lifespan)
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
        if len(req.text.encode("utf-8")) > max_bytes:
            raise HTTPException(status_code=413, detail="text exceeds capture.max_bytes")
        sentences = preprocess(req.text, comps.preproc_config)
        if not sentences:
            raise HTTPException(status_code=400, detail="no synthesizable sentences")
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
    """Entry point for `readaloud daemon`."""
    import uvicorn

    cfg = load_config()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    app = create_app()
    uvicorn.run(app, host=cfg.daemon.host, port=cfg.daemon.port, log_config=None)


if __name__ == "__main__":
    run()
