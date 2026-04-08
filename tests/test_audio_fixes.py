"""Regression tests for the two audio-pipeline bugs reported by the user:

1. First word cut off on every cold speak — fixed by priming the
   sounddevice OutputStream with 100ms of silence before the first
   real write.

2. Pause/unpause not instant, "quirky / doesn't work half the time" —
   fixed by splitting the consumer's per-sentence sink.write into
   ~100ms sub-blocks so the pause event can interrupt mid-sentence.
"""

from __future__ import annotations

import asyncio
import math
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from lexaloud.audio import NullSink, SoundDeviceSink
from lexaloud.player import Player
from lexaloud.providers.base import AudioChunk
from lexaloud.providers.fake import FakeProvider


# ---------------------------------------------------------------------
# Fix 1: SoundDeviceSink primes the stream with 100ms of silence
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sounddevice_sink_primes_stream_with_silence_on_open():
    """The first stream.write() that sounddevice sees MUST be a block of
    silence, not the real audio. This absorbs the PulseAudio/PipeWire
    stream setup latency that clips the first few tens of ms.
    """
    fake_stream = MagicMock()
    # Mock stream.latency / blocksize explicitly — otherwise MagicMock
    # returns other MagicMocks that float()/int() coerce to 1.0/1,
    # which would bloat the prime to 1.05 seconds of silence.
    fake_stream.latency = 0.05  # 50 ms — typical low-latency value
    fake_stream.blocksize = 1024

    class _FakeSd:
        OutputStream = MagicMock(return_value=fake_stream)

    sink = SoundDeviceSink()
    with patch.dict("sys.modules", {"sounddevice": _FakeSd()}):
        await sink.begin_stream(24000, 1)

    # sd.OutputStream was called with the expected kwargs including the
    # new latency and blocksize hints from the audio-pipeline review.
    _FakeSd.OutputStream.assert_called_once_with(
        samplerate=24000,
        channels=1,
        dtype="float32",
        latency="low",
        blocksize=1024,
    )
    # start() was called.
    assert fake_stream.start.called, "stream.start() was not called"
    # The FIRST write call must be the silence prime.
    first_write = fake_stream.write.call_args_list[0]
    samples_written = first_write.args[0]
    # prime_seconds = max(0.1, 0.05 + 0.05) = 0.1 → 2400 samples.
    expected_prime = int(0.1 * 24000)
    assert samples_written.shape == (expected_prime, 1), (
        f"prime shape should be ({expected_prime}, 1), got {samples_written.shape}"
    )
    assert np.all(samples_written == 0), "prime block must be silent"
    assert samples_written.dtype == np.float32


@pytest.mark.asyncio
async def test_sounddevice_sink_prime_scales_with_stream_latency():
    """If PortAudio reports a higher latency than our 100 ms floor, the
    prime grows to cover it (with a 50 ms safety margin). This matters
    for Bluetooth headsets where the default latency can be 150+ ms."""
    fake_stream = MagicMock()
    fake_stream.latency = 0.2  # 200 ms — e.g., a Bluetooth headset
    fake_stream.blocksize = 1024

    class _FakeSd:
        OutputStream = MagicMock(return_value=fake_stream)

    sink = SoundDeviceSink()
    with patch.dict("sys.modules", {"sounddevice": _FakeSd()}):
        await sink.begin_stream(24000, 1)

    first_write = fake_stream.write.call_args_list[0]
    samples_written = first_write.args[0]
    # max(0.1, 0.2 + 0.05) = 0.25 seconds → 6000 samples.
    expected_prime = int(0.25 * 24000)
    assert samples_written.shape == (expected_prime, 1)


@pytest.mark.asyncio
async def test_sounddevice_sink_continues_after_prime_failure():
    """If the silence prime raises (e.g., device went away mid-open), the
    sink should log and continue with the real stream — not crash."""
    fake_stream = MagicMock()
    fake_stream.latency = 0.05
    fake_stream.blocksize = 1024
    fake_stream.write.side_effect = [RuntimeError("buffer underflow"), None]

    class _FakeSd:
        OutputStream = MagicMock(return_value=fake_stream)

    sink = SoundDeviceSink()
    with patch.dict("sys.modules", {"sounddevice": _FakeSd()}):
        await sink.begin_stream(24000, 1)  # prime raises; should be caught

    # The stream was still set up successfully despite the prime failure.
    assert sink._stream is fake_stream  # type: ignore[attr-defined]
    assert sink._stream_sample_rate == 24000  # type: ignore[attr-defined]


# ---------------------------------------------------------------------
# Fix 2: Player sub-chunks the consumer write so pause is responsive
# ---------------------------------------------------------------------


class _LongChunkProvider:
    """Emits one ~1-second chunk per sentence so we can see sub-chunking."""

    name = "long-chunk"
    sample_rate = 24000
    seconds_per_sentence = 1.0

    def __init__(self) -> None:
        self.synthesize_calls = 0

    async def warmup(self) -> None:
        pass

    async def synthesize(self, sentence, job_id, is_current_job):
        if not is_current_job(job_id):
            return None
        self.synthesize_calls += 1
        # A 1-second block is long enough that sub-chunking produces
        # exactly 10 writes at SUB_CHUNK_SECONDS=0.1.
        n = int(self.seconds_per_sentence * self.sample_rate)
        samples = (0.01 * np.sin(np.linspace(0, 2 * math.pi * 220, n))).astype(np.float32)
        return AudioChunk(
            samples=samples,
            sample_rate=self.sample_rate,
            metadata={"sentence": sentence},
        )


@pytest.mark.asyncio
async def test_long_chunk_is_written_in_sub_blocks():
    """A 1-second sentence should reach the sink as approximately 10
    blocks of 100ms each (SUB_CHUNK_SECONDS=0.1). The exact count
    depends on integer rounding and the final partial block."""
    provider = _LongChunkProvider()
    sink = NullSink()
    player = Player(provider, sink, ready_queue_depth=2)

    await player.speak(["one full second of audio."])
    # Drain.
    for _ in range(500):
        if player.state.state == "idle":
            break
        await asyncio.sleep(0.01)
    assert player.state.state == "idle"

    # Expect roughly 10 sub-chunk writes for a 1.0s sentence.
    assert 8 <= sink.write_count <= 12, (
        f"expected ~10 sub-chunk writes for a 1-second sentence, "
        f"got {sink.write_count}"
    )
    # All samples made it through regardless.
    assert sink.samples_received == provider.sample_rate


@pytest.mark.asyncio
async def test_pause_interrupts_mid_sentence():
    """The critical regression test: with sub-chunking, pressing pause
    mid-sentence must halt the write loop within ~1 sub-chunk's worth of
    samples. Without sub-chunking, the test would fail because all 1.0s
    of audio would reach the sink before pause_event.wait could run.

    We use a custom NullSink variant that sleeps a few ms per write so
    the consumer actually yields to the event loop between sub-chunks
    — otherwise everything completes before the pause even fires.
    """
    provider = _LongChunkProvider()

    class _SlowNullSink(NullSink):
        async def write(self, chunk):
            await asyncio.sleep(0.01)  # 10 ms per sub-chunk
            await super().write(chunk)

    sink = _SlowNullSink()
    player = Player(provider, sink, ready_queue_depth=2)

    await player.speak(["one full second of audio."])
    # Let a few sub-chunks get through, then pause.
    await asyncio.sleep(0.03)
    await player.pause()

    # Freeze for a bit — more sub-chunks may still be in flight but the
    # sink-consumer loop should block on pause.wait within a few chunks.
    await asyncio.sleep(0.1)
    snapshot = sink.samples_received

    # Wait another 100ms to confirm no more writes are happening.
    await asyncio.sleep(0.1)
    after = sink.samples_received

    assert after == snapshot, (
        f"sink kept receiving samples while paused: {snapshot} -> {after}"
    )
    assert after < provider.sample_rate, (
        f"pause should have interrupted before the full sentence was written; "
        f"got {after} of {provider.sample_rate} samples"
    )
    assert player.state.state == "paused"

    # Resume and let the rest play.
    await player.resume()
    for _ in range(500):
        if player.state.state == "idle":
            break
        await asyncio.sleep(0.01)
    assert player.state.state == "idle"
    assert sink.samples_received == provider.sample_rate


@pytest.mark.asyncio
async def test_pause_resume_mid_sentence_preserves_all_audio():
    """Pausing mid-sentence and resuming must eventually deliver the full
    sentence's samples — no audio lost at the pause boundary."""
    provider = _LongChunkProvider()

    class _SlowNullSink(NullSink):
        async def write(self, chunk):
            await asyncio.sleep(0.005)
            await super().write(chunk)

    sink = _SlowNullSink()
    player = Player(provider, sink, ready_queue_depth=2)

    await player.speak(["one full second of audio."])
    # Pause, resume, pause again, resume — verify all samples eventually
    # arrive regardless of the pause-resume dance.
    await asyncio.sleep(0.02)
    await player.pause()
    await asyncio.sleep(0.05)
    await player.resume()
    await asyncio.sleep(0.02)
    await player.pause()
    await asyncio.sleep(0.05)
    await player.resume()

    for _ in range(500):
        if player.state.state == "idle":
            break
        await asyncio.sleep(0.01)
    assert player.state.state == "idle"
    assert sink.samples_received == provider.sample_rate


@pytest.mark.asyncio
async def test_sub_chunking_does_not_break_short_sentences():
    """A sentence shorter than one sub-chunk block (e.g., < 100ms) should
    still play through cleanly, as a single write."""

    class _ShortChunkProvider:
        name = "short"

        async def warmup(self) -> None:
            pass

        async def synthesize(self, sentence, job_id, is_current_job):
            if not is_current_job(job_id):
                return None
            # 0.05s — shorter than SUB_CHUNK_SECONDS=0.1
            n = 1200
            samples = np.zeros(n, dtype=np.float32)
            return AudioChunk(
                samples=samples,
                sample_rate=24000,
                metadata={"sentence": sentence},
            )

    provider = _ShortChunkProvider()
    sink = NullSink()
    player = Player(provider, sink, ready_queue_depth=2)

    await player.speak(["tiny."])
    for _ in range(200):
        if player.state.state == "idle":
            break
        await asyncio.sleep(0.01)
    assert player.state.state == "idle"
    assert sink.samples_received == 1200
    # Short chunks fit in a single sub-chunk block.
    assert sink.write_count == 1
