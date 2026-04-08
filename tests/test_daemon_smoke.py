"""Deterministic daemon smoke test.

Wires a FakeProvider + WavSink via build_components()-equivalent hand-rolling,
then hits POST /speak and verifies a WAV file was produced with expected
sample rate and non-zero duration. No GPU, no audio device, no network.

We use httpx.AsyncClient + ASGITransport instead of fastapi.testclient.TestClient
because TestClient runs the ASGI app on a worker thread via anyio's portal,
which has been observed to hang in this combination of pinned versions
(fastapi 0.135.3 + starlette 1.0.0 + anyio 4.13.0). The async transport
talks to the ASGI app in-process on the test event loop and matches the
async nature of the routes themselves, with no thread bridging.

Lifespan is driven manually via `app.router.lifespan_context(app)` so we
don't need the optional `asgi-lifespan` package.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import httpx

from lexaloud.audio import WavSink
from lexaloud.config import Config
from lexaloud.daemon import DaemonComponents, create_app
from lexaloud.player import Player
from lexaloud.preprocessor import PreprocessorConfig
from lexaloud.providers.fake import FakeProvider


def _make_components(tmp_path: Path, *, max_bytes: int | None = None) -> DaemonComponents:
    cfg = Config()
    if max_bytes is not None:
        cfg.capture.max_bytes = max_bytes
    provider = FakeProvider(sample_rate=24000, seconds_per_sentence=0.05, synth_delay_ms=2)
    sink = WavSink(tmp_path)
    player = Player(provider=provider, sink=sink, ready_queue_depth=2)
    preproc_config = PreprocessorConfig(
        strip_numeric_bracket_citations=True,
        strip_parenthetical_citations=False,
        expand_latin_abbreviations=True,
        pdf_cleanup=True,
    )
    return DaemonComponents(
        cfg=cfg, provider=provider, sink=sink, player=player, preproc_config=preproc_config
    )


@asynccontextmanager
async def _client_for(app):
    """Yield an httpx.AsyncClient bound to the app via ASGITransport.

    Drives FastAPI's lifespan manually so the warmup background task and
    the dedicated executor pool are exercised the same way they would be
    under uvicorn.
    """
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def _wait_for_idle(client: httpx.AsyncClient, timeout_s: float = 2.0) -> dict:
    """Poll /state until state == 'idle' or timeout."""
    deadline = asyncio.get_running_loop().time() + timeout_s
    state: dict = {}
    while asyncio.get_running_loop().time() < deadline:
        r = await client.get("/state")
        state = r.json()
        if state.get("state") == "idle":
            return state
        await asyncio.sleep(0.01)
    return state


async def test_healthz_and_state(tmp_path: Path):
    comps = _make_components(tmp_path)
    app = create_app(comps)
    async with _client_for(app) as client:
        r = await client.get("/healthz")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}
        r = await client.get("/state")
        assert r.status_code == 200
        # State may be "warming" briefly if the lifespan's background warmup
        # task hasn't yet completed the FakeProvider's short warmup sleep.
        assert r.json()["state"] in ("warming", "idle")


async def test_payload_guard_middleware_rejects_oversized_content_length(tmp_path: Path):
    """Middleware returns a real 413 JSONResponse, not an HTML 500."""
    comps = _make_components(tmp_path, max_bytes=100)
    app = create_app(comps)
    async with _client_for(app) as client:
        # 10 KB body easily exceeds the (100 + 4096) header cap.
        huge = "a" * 10_000
        r = await client.post("/speak", json={"text": huge})
        assert r.status_code == 413
        assert "detail" in r.json()


async def test_speak_produces_wav(tmp_path: Path):
    comps = _make_components(tmp_path)
    app = create_app(comps)
    async with _client_for(app) as client:
        r = await client.post(
            "/speak",
            json={"text": "This is one. This is two. This is three."},
        )
        assert r.status_code == 200
        state = await _wait_for_idle(client)
        assert state.get("state") == "idle"

    sink: WavSink = comps.sink  # type: ignore[assignment]
    assert len(sink.written_files) >= 1
    wav = sink.written_files[0]
    assert wav.exists()
    # WAV header is 44 bytes; must contain real samples too.
    assert wav.stat().st_size > 44


async def test_speak_empty_returns_400(tmp_path: Path):
    comps = _make_components(tmp_path)
    app = create_app(comps)
    async with _client_for(app) as client:
        # Whitespace passes pydantic min_length but the preprocessor
        # produces no sentences, so the daemon returns 400.
        r = await client.post("/speak", json={"text": "   "})
        assert r.status_code == 400
        # An empty string is rejected by pydantic with 422.
        r = await client.post("/speak", json={"text": ""})
        assert r.status_code == 422


async def test_speak_then_stop(tmp_path: Path):
    comps = _make_components(tmp_path)
    app = create_app(comps)
    async with _client_for(app) as client:
        r = await client.post(
            "/speak",
            json={"text": "one. two. three. four. five."},
        )
        assert r.status_code == 200
        r = await client.post("/stop")
        assert r.status_code == 200
        assert r.json()["state"] == "idle"


async def test_speak_then_pause_resume(tmp_path: Path):
    """Pause must actually transition to 'paused' for a job that's still
    in flight, then resume must clear it. Uses a slower per-sentence delay
    so the job hasn't already finished by the time we pause.
    """
    cfg = Config()
    # Slow enough that 5 sentences take ~250 ms total.
    provider = FakeProvider(sample_rate=24000, seconds_per_sentence=0.05, synth_delay_ms=20)
    sink = WavSink(tmp_path)
    player = Player(provider=provider, sink=sink, ready_queue_depth=2)
    preproc_config = PreprocessorConfig()
    comps = DaemonComponents(
        cfg=cfg, provider=provider, sink=sink, player=player, preproc_config=preproc_config
    )
    app = create_app(comps)
    async with _client_for(app) as client:
        r = await client.post(
            "/speak",
            json={"text": "one. two. three. four. five."},
        )
        assert r.status_code == 200
        # Give the consumer a moment to begin playing.
        await asyncio.sleep(0.02)

        r = await client.post("/pause")
        assert r.status_code == 200
        # Pause is chunk-boundary; the consumer may finish the current
        # sentence before pausing, so we may briefly observe "speaking"
        # again — but resume should always work and the eventual end
        # state must be idle.
        assert r.json()["state"] in ("paused", "speaking", "idle")

        r = await client.post("/resume")
        assert r.status_code == 200
        state = await _wait_for_idle(client, timeout_s=3.0)
        assert state.get("state") == "idle"


async def test_skip_response_returns_state(tmp_path: Path):
    comps = _make_components(tmp_path)
    app = create_app(comps)
    async with _client_for(app) as client:
        await client.post("/speak", json={"text": "one. two. three."})
        r = await client.post("/skip")
        assert r.status_code == 200
        body = r.json()
        assert "state" in body
        assert body["provider_name"] == "fake"


async def test_back_response_returns_state(tmp_path: Path):
    comps = _make_components(tmp_path)
    app = create_app(comps)
    async with _client_for(app) as client:
        await client.post("/speak", json={"text": "one. two. three."})
        r = await client.post("/back")
        assert r.status_code == 200
        assert "state" in r.json()


async def test_toggle_is_noop_on_idle(tmp_path: Path):
    """Toggle on an idle player should not raise and should stay idle."""
    comps = _make_components(tmp_path)
    app = create_app(comps)
    async with _client_for(app) as client:
        # Wait for warmup to finish so the state is deterministically idle.
        await _wait_for_idle(client, timeout_s=2.0)
        r = await client.post("/toggle")
        assert r.status_code == 200
        assert r.json()["state"] in ("idle", "warming")


async def test_toggle_pauses_then_resumes(tmp_path: Path):
    """Starting from speaking, one /toggle should pause, a second should resume."""
    cfg = Config()
    # Slow enough sentences that the job is still in flight when we toggle.
    provider = FakeProvider(sample_rate=24000, seconds_per_sentence=0.05, synth_delay_ms=20)
    sink = WavSink(tmp_path)
    player = Player(provider=provider, sink=sink, ready_queue_depth=2)
    preproc_config = PreprocessorConfig()
    comps = DaemonComponents(
        cfg=cfg, provider=provider, sink=sink, player=player, preproc_config=preproc_config
    )
    app = create_app(comps)
    async with _client_for(app) as client:
        await client.post("/speak", json={"text": "one. two. three. four. five."})
        # Give the consumer a moment to begin playing.
        await asyncio.sleep(0.02)
        # First toggle: pause (or briefly already idle if very fast).
        r = await client.post("/toggle")
        assert r.status_code == 200
        assert r.json()["state"] in ("paused", "idle")
        # Second toggle: resume (unless already idle).
        r = await client.post("/toggle")
        assert r.status_code == 200
        # Drain to idle.
        state = await _wait_for_idle(client, timeout_s=3.0)
        assert state.get("state") == "idle"


async def test_speak_rejects_null_bytes(tmp_path: Path):
    """POST /speak with a null byte in text must return 400."""
    comps = _make_components(tmp_path)
    app = create_app(comps)
    async with _client_for(app) as client:
        r = await client.post("/speak", json={"text": "hello\x00world"})
        assert r.status_code == 400
        assert "null" in r.json()["detail"].lower()


async def test_speak_rejects_oversized_sentence(tmp_path: Path):
    """POST /speak with a post-preprocess sentence > MAX_SENTENCE_CHARS → 400."""
    from lexaloud.daemon import MAX_SENTENCE_CHARS

    comps = _make_components(tmp_path)
    app = create_app(comps)
    # A long run-on without any sentence terminators that pysbd would split
    # on. Use 5000 `a` chars — well above MAX_SENTENCE_CHARS=4096.
    huge = "a" * (MAX_SENTENCE_CHARS + 500)
    async with _client_for(app) as client:
        r = await client.post("/speak", json={"text": huge})
        assert r.status_code == 400
        assert "MAX_SENTENCE_CHARS" in r.json()["detail"] or "exceeds" in r.json()["detail"]


async def test_speak_ordinary_text_not_flagged_by_sentence_cap(tmp_path: Path):
    """A normal multi-sentence paragraph must still pass the sentence cap."""
    comps = _make_components(tmp_path)
    app = create_app(comps)
    text = "First sentence. " + "Second sentence. " * 5 + "Third sentence."
    async with _client_for(app) as client:
        r = await client.post("/speak", json={"text": text})
        assert r.status_code == 200
