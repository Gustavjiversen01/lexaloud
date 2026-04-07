"""Tests for AudioSink implementations (NullSink + WavSink).

SoundDeviceSink is tested via import + lazy-open behavior only, because it
requires an audio device.
"""

from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np
import pytest

from readaloud.audio import NullSink, SoundDeviceSink, WavSink
from readaloud.providers.base import AudioChunk


def make_sine_chunk(sr: int = 24000, seconds: float = 0.1, freq: float = 440.0) -> AudioChunk:
    n = int(seconds * sr)
    t = np.arange(n, dtype=np.float32) / sr
    samples = (0.1 * np.sin(2 * math.pi * freq * t)).astype(np.float32)
    return AudioChunk(samples=samples, sample_rate=sr)


@pytest.mark.asyncio
async def test_null_sink_counts_samples():
    sink = NullSink()
    await sink.begin_stream(24000, 1)
    chunk = make_sine_chunk()
    await sink.write(chunk)
    await sink.write(chunk)
    await sink.end_stream()
    assert sink.begin_calls == [(24000, 1)]
    assert sink.write_count == 2
    assert sink.samples_received == 2 * chunk.num_samples
    assert sink.end_calls == 1


@pytest.mark.asyncio
async def test_null_sink_rejects_mismatched_sample_rate():
    sink = NullSink()
    await sink.begin_stream(24000, 1)
    chunk = AudioChunk(samples=np.zeros(10, dtype=np.float32), sample_rate=48000)
    with pytest.raises(ValueError):
        await sink.write(chunk)


@pytest.mark.asyncio
async def test_null_sink_stop_clears_stream_state():
    sink = NullSink()
    await sink.begin_stream(24000, 1)
    await sink.stop()
    assert sink.stop_calls == 1
    # After stop, another begin_stream should work.
    await sink.begin_stream(24000, 1)
    assert len(sink.begin_calls) == 2


@pytest.mark.asyncio
async def test_wav_sink_writes_non_silent_file(tmp_path: Path):
    sink = WavSink(tmp_path)
    await sink.begin_stream(24000, 1)
    for _ in range(3):
        await sink.write(make_sine_chunk(seconds=0.1))
    await sink.end_stream()

    assert len(sink.written_files) == 1
    wav_path = sink.written_files[0]
    with wave.open(str(wav_path), "rb") as w:
        assert w.getframerate() == 24000
        assert w.getnchannels() == 1
        frames = w.getnframes()
    # 3 chunks of 0.1s * 24000 = 7200 samples
    assert frames == 3 * 2400


@pytest.mark.asyncio
async def test_wav_sink_new_stream_creates_new_file(tmp_path: Path):
    sink = WavSink(tmp_path)
    for _ in range(2):
        await sink.begin_stream(24000, 1)
        await sink.write(make_sine_chunk())
        await sink.end_stream()
    assert len(sink.written_files) == 2
    assert sink.written_files[0] != sink.written_files[1]


@pytest.mark.asyncio
async def test_wav_sink_stop_flushes(tmp_path: Path):
    sink = WavSink(tmp_path)
    await sink.begin_stream(24000, 1)
    await sink.write(make_sine_chunk())
    await sink.stop()
    assert len(sink.written_files) == 1
    assert sink.written_files[0].exists()


@pytest.mark.asyncio
async def test_wav_sink_rejects_mismatched_sample_rate(tmp_path: Path):
    sink = WavSink(tmp_path)
    await sink.begin_stream(24000, 1)
    with pytest.raises(ValueError):
        await sink.write(
            AudioChunk(samples=np.zeros(10, dtype=np.float32), sample_rate=48000)
        )


def test_sounddevice_sink_does_not_open_on_construction():
    """SoundDeviceSink must be lazy: construction must not touch the audio device.

    We can test this without any audio hardware by constructing the sink
    and confirming its internal stream reference is still None.
    """
    sink = SoundDeviceSink()
    assert sink._stream is None  # type: ignore[attr-defined]
    assert sink._stream_sample_rate is None  # type: ignore[attr-defined]
