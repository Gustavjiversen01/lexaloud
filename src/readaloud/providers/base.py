"""SpeechProvider protocol and the AudioChunk data shape.

A provider takes a single sentence of text and returns one `AudioChunk`
holding the whole synthesized waveform for that sentence. Streaming is done
at sentence granularity rather than sample granularity — this is the plan's
key design choice to make cancellation and backpressure controllable.

See docs: `.claude/plans/peppy-sprouting-knuth.md` (Provider interface).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import numpy as np


@dataclass
class AudioChunk:
    """One complete synthesized sentence (or test waveform)."""

    samples: np.ndarray  # float32, shape (n,) mono OR (n, channels)
    sample_rate: int
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> float:
        n = int(self.samples.shape[0]) if self.samples.ndim > 0 else 0
        return n / float(self.sample_rate) if self.sample_rate else 0.0

    @property
    def num_samples(self) -> int:
        return int(self.samples.shape[0]) if self.samples.ndim > 0 else 0


@runtime_checkable
class SpeechProvider(Protocol):
    """Synthesize one sentence at a time with cooperative cancellation.

    Implementations MUST:
      * Check `is_current_job(job_id)` before starting expensive work; return
        `None` if the id has been superseded.
      * After the synthesis call returns, re-check and return `None` if the
        id has been superseded, so late results never reach the sink.
      * Never raise for cancellation — return `None` instead.
    """

    name: str

    async def synthesize(self, sentence: str, job_id: int, is_current_job) -> AudioChunk | None:
        ...

    async def warmup(self) -> None:
        """Run any one-time expensive initialization (CUDA JIT, etc.)."""
        ...
