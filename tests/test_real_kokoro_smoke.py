"""Optional local smoke test that uses the REAL Kokoro provider.

Skipped unless LEXALOUD_REAL_TTS=1 is set in the environment. Produces a
WAV that a human can listen to.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from lexaloud.audio import WavSink
from lexaloud.models import ensure_artifacts
from lexaloud.player import Player
from lexaloud.providers.kokoro import KokoroProvider


pytestmark = pytest.mark.skipif(
    os.environ.get("LEXALOUD_REAL_TTS") != "1",
    reason="set LEXALOUD_REAL_TTS=1 to run the real-Kokoro smoke test",
)


@pytest.mark.asyncio
async def test_real_kokoro_produces_audible_wav(tmp_path: Path):
    artifacts = ensure_artifacts(download_if_missing=False)
    provider = KokoroProvider(
        model_path=artifacts["kokoro-v1.0.onnx"],
        voices_path=artifacts["voices-v1.0.bin"],
    )
    sink = WavSink(tmp_path)
    player = Player(provider=provider, sink=sink, ready_queue_depth=2)

    await provider.warmup()
    await player.speak(
        [
            "This is a real Kokoro synthesis test.",
            "The player renders sentences in order.",
            "You should hear a calm narrator.",
        ]
    )
    # Wait for completion.
    for _ in range(2000):
        if player.state.state == "idle":
            break
        await asyncio.sleep(0.05)

    assert player.state.state == "idle"
    assert len(sink.written_files) >= 1
    wav = sink.written_files[0]
    assert wav.exists()
    print(f"\nReal Kokoro WAV written to: {wav}")
    assert wav.stat().st_size > 44_000  # at least ~1 second of audio
