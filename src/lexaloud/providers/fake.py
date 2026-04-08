"""Deterministic fake provider for tests.

Produces a short sine-wave buffer for each sentence, at a configurable
sample rate, so player/lifecycle/daemon tests can run without touching real
Kokoro, CUDA, or any audio device.
"""

from __future__ import annotations

import asyncio
import math

import numpy as np

from .base import AudioChunk


class FakeProvider:
    """Sine-wave synthesizer used by tests."""

    name = "fake"

    def __init__(
        self,
        sample_rate: int = 24000,
        seconds_per_sentence: float = 0.2,
        frequency_hz: float = 440.0,
        synth_delay_ms: float = 10.0,
    ) -> None:
        self.sample_rate = sample_rate
        self.seconds_per_sentence = seconds_per_sentence
        self.frequency_hz = frequency_hz
        self.synth_delay_ms = synth_delay_ms
        # Exposed for test assertions.
        self.synthesize_calls: list[tuple[int, str]] = []
        self.cancelled_calls = 0

    async def warmup(self) -> None:
        # FakeProvider has no real cold start; still simulate a short delay so
        # warmup-vs-request ordering tests can observe a serialized state.
        await asyncio.sleep(self.synth_delay_ms / 1000.0)

    async def synthesize(self, sentence: str, job_id: int, is_current_job) -> AudioChunk | None:
        if not is_current_job(job_id):
            self.cancelled_calls += 1
            return None
        self.synthesize_calls.append((job_id, sentence))
        # Simulate synthesis time
        await asyncio.sleep(self.synth_delay_ms / 1000.0)
        if not is_current_job(job_id):
            self.cancelled_calls += 1
            return None
        n = int(self.seconds_per_sentence * self.sample_rate)
        t = np.arange(n, dtype=np.float32) / self.sample_rate
        samples = 0.1 * np.sin(2.0 * math.pi * self.frequency_hz * t).astype(np.float32)
        return AudioChunk(samples=samples, sample_rate=self.sample_rate)
