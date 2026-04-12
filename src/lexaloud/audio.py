"""AudioSink protocol and three implementations.

The sink does not assume a single fixed sample rate for its lifetime; sample
rate is established per stream via `begin_stream(sr, channels)`.

`SoundDeviceSink` lazily opens the sounddevice output stream — daemon startup
must not require a working audio device.
"""

from __future__ import annotations

import asyncio
import logging
import wave
from pathlib import Path
from typing import Protocol

import numpy as np

from .providers.base import AudioChunk

log = logging.getLogger(__name__)


class AudioSink(Protocol):
    async def warmup(self, sample_rate: int, channels: int) -> None: ...
    async def begin_stream(self, sample_rate: int, channels: int) -> None: ...
    async def write(self, chunk: AudioChunk) -> None: ...
    async def end_stream(self) -> None: ...
    async def stop(self) -> None: ...
    async def close(self) -> None: ...


class NullSink:
    """Unit-test sink. Discards samples; records counters."""

    def __init__(self) -> None:
        self.begin_calls: list[tuple[int, int]] = []
        self.write_count = 0
        self.samples_received = 0
        self.end_calls = 0
        self.stop_calls = 0
        self.close_calls = 0
        self._stream_sample_rate: int | None = None

    async def warmup(self, sample_rate: int, channels: int) -> None:
        pass

    async def begin_stream(self, sample_rate: int, channels: int) -> None:
        self.begin_calls.append((sample_rate, channels))
        self._stream_sample_rate = sample_rate

    async def write(self, chunk: AudioChunk) -> None:
        if self._stream_sample_rate is not None and chunk.sample_rate != self._stream_sample_rate:
            raise ValueError(
                f"chunk sample_rate={chunk.sample_rate} does not match "
                f"stream sample_rate={self._stream_sample_rate}"
            )
        self.write_count += 1
        self.samples_received += chunk.num_samples

    async def end_stream(self) -> None:
        self.end_calls += 1
        self._stream_sample_rate = None

    async def stop(self) -> None:
        self.stop_calls += 1
        self._stream_sample_rate = None

    async def close(self) -> None:
        self.close_calls += 1


class WavSink:
    """Integration-test sink. Writes one WAV file per stream for assertions."""

    def __init__(self, out_dir: Path) -> None:
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._wave: wave.Wave_write | None = None
        self._path: Path | None = None
        self._sample_rate: int | None = None
        self._channels: int | None = None
        self._stream_index = 0
        # Exposed for tests.
        self.written_files: list[Path] = []

    async def begin_stream(self, sample_rate: int, channels: int) -> None:
        self._stream_index += 1
        self._path = self.out_dir / f"stream_{self._stream_index:04d}.wav"
        self._wave = wave.open(str(self._path), "wb")
        self._wave.setnchannels(channels)
        self._wave.setsampwidth(2)  # 16-bit PCM
        self._wave.setframerate(sample_rate)
        self._sample_rate = sample_rate
        self._channels = channels

    async def write(self, chunk: AudioChunk) -> None:
        if self._wave is None:
            raise RuntimeError("WavSink.write called before begin_stream")
        if chunk.sample_rate != self._sample_rate:
            raise ValueError(
                f"chunk sample_rate={chunk.sample_rate} != stream sample_rate={self._sample_rate}"
            )
        samples = chunk.samples
        if samples.ndim == 1 and (self._channels or 1) > 1:
            # Mono → duplicate across channels if somehow mismatched.
            samples = np.stack([samples] * (self._channels or 1), axis=1)
        # Clamp and convert to int16.
        clamped = np.clip(samples, -1.0, 1.0)
        pcm = (clamped * 32767.0).astype(np.int16)
        self._wave.writeframes(pcm.tobytes())

    async def end_stream(self) -> None:
        if self._wave is not None:
            self._wave.close()
            if self._path is not None:
                self.written_files.append(self._path)
            self._wave = None
            self._path = None
            self._sample_rate = None
            self._channels = None

    async def stop(self) -> None:
        # Same as end_stream for the WavSink — flush the current file and
        # close it. Subsequent begin_stream starts a new file.
        if self._wave is not None:
            self._wave.close()
            if self._path is not None:
                self.written_files.append(self._path)
            self._wave = None
            self._path = None
            self._sample_rate = None
            self._channels = None

    async def warmup(self, sample_rate: int, channels: int) -> None:
        pass

    async def close(self) -> None:
        await self.stop()


class SoundDeviceSink:
    """Runtime sink. Lazily opens a sounddevice.OutputStream on first
    begin_stream. Survives device reopens between streams.

    Stream lifecycle:
    - warmup() or begin_stream(): opens the stream (cold open via executor)
    - stop(): aborts buffered audio but keeps the stream object alive so
      the next begin_stream() can restart it cheaply (warm restart)
    - close(): actually closes the underlying PortAudio stream (only
      called during daemon shutdown via player.shutdown())

    The asyncio self._lock serializes all access. If the consumer is
    inside write() (blocked in the executor) and stop() calls abort(),
    the executor thread's stream.write() raises sd.PortAudioError, which
    the consumer handles via its existing except Exception path. This is
    safe because abort() and write() converge on PortAudio's internal
    mutex.
    """

    # Duration of silence written during cold open to absorb PipeWire's
    # resampler initialization (24000 Hz → 44100 Hz on most systems).
    COLD_PRIME_SECONDS: float = 2.0
    # Duration of silence written on warm restart (after abort + start).
    # Just absorbs the stream-start latency, not the resampler cost.
    WARM_PRIME_SECONDS: float = 0.02

    def __init__(self) -> None:
        self._stream = None  # sounddevice.OutputStream
        self._stream_sample_rate: int | None = None
        self._stream_channels: int | None = None
        # asyncio lock to protect the underlying blocking sounddevice API.
        self._lock = asyncio.Lock()

    def _open_stream(self, sample_rate: int, channels: int) -> None:
        import sounddevice as sd  # local import so the daemon can be imported without audio

        log.info("SoundDeviceSink: opening OutputStream sr=%d ch=%d", sample_rate, channels)
        # latency="low" maps to PortAudio's default_low_output_latency
        # (~20-50 ms on most devices) instead of "high" (~150+ ms), which
        # both tightens pause-response latency and reduces the
        # sample-rate-conversion warm-up that clips first words.
        # blocksize=1024 locks in a known callback block size instead of
        # letting PortAudio pick per-device; a fixed block produces
        # predictable write-blocking behavior and avoids occasional
        # 4096-frame blocks on PulseAudio.
        stream = sd.OutputStream(
            samplerate=sample_rate,
            channels=channels,
            dtype="float32",
            latency="low",
            blocksize=1024,
        )
        stream.start()
        log.info(
            "SoundDeviceSink: stream latency=%.1fms blocksize=%d",
            float(stream.latency) * 1000.0,
            int(stream.blocksize),
        )
        # Cold-prime: write enough silence to absorb PipeWire's
        # resampler initialization (24000→44100 Hz on most systems).
        # This is the critical fix for the "first word is cut off" bug:
        # PipeWire needs ~1-2s to spin up its SPA resampler on the first
        # stream at a non-native sample rate. The warmup() method also
        # writes this prime during daemon startup, so in practice the
        # cold prime here only fires if the audio device wasn't available
        # during warmup.
        self._write_prime(stream, sample_rate, channels, self.COLD_PRIME_SECONDS)
        self._stream = stream
        self._stream_sample_rate = sample_rate
        self._stream_channels = channels

    @staticmethod
    def _write_prime(stream, sample_rate: int, channels: int, seconds: float) -> None:
        """Write silence to prime the stream. Called from _open_stream
        (cold prime) and begin_stream restart (warm prime)."""
        try:
            prime_samples = int(seconds * sample_rate)
            if prime_samples <= 0:
                return
            silence = np.zeros((prime_samples, channels), dtype=np.float32)
            stream.write(silence)
        except Exception as e:  # noqa: BLE001
            log.warning("SoundDeviceSink: silence prime failed (continuing): %s", e)

    def _close_stream(self) -> None:
        if self._stream is not None:
            try:
                # abort() discards buffered output immediately; stop()
                # would drain the buffer before returning. For "stop
                # speaking right now" semantics (both user /stop and
                # daemon shutdown) abort is the correct choice and also
                # caps shutdown latency to a few ms instead of tens to
                # hundreds of ms.
                self._stream.abort()
                self._stream.close()
            except Exception as e:
                log.warning("SoundDeviceSink close failed: %s", e)
        self._stream = None
        self._stream_sample_rate = None
        self._stream_channels = None

    async def warmup(self, sample_rate: int, channels: int) -> None:
        """Pre-open the stream during daemon startup to warm PipeWire's
        resampler. Runs _open_stream in an executor so the blocking
        PortAudio calls + 2s silence write don't stall the event loop."""
        log.info(
            "sink warmup: opening stream (sr=%d, ch=%d, prime=%.1fs)",
            sample_rate,
            channels,
            self.COLD_PRIME_SECONDS,
        )
        async with self._lock:
            if self._stream is not None:
                log.info("sink warmup: stream already open, skipping")
                return  # already warm
            loop = asyncio.get_running_loop()
            try:
                await loop.run_in_executor(None, self._open_stream, sample_rate, channels)
                log.info(
                    "sink warmup: complete, stream active=%s latency=%.1fms",
                    self._stream.active if self._stream else "None",
                    float(self._stream.latency) * 1000 if self._stream else 0,
                )
            except Exception as e:
                log.error("sink warmup failed: %s", e)
                self._stream = None
                raise

    async def begin_stream(self, sample_rate: int, channels: int) -> None:
        async with self._lock:
            if self._stream is not None:
                if self._stream_sample_rate != sample_rate or self._stream_channels != channels:
                    # Rate/channels changed: full close and reopen.
                    self._close_stream()
                elif self._stream.stopped:
                    # Stream was aborted by stop() but kept alive for
                    # fast restart. Re-start it with a short warm prime
                    # (just the stream-start latency, not the full
                    # PipeWire resampler cost).
                    try:
                        self._stream.start()
                        self._write_prime(
                            self._stream,
                            sample_rate,
                            channels,
                            self.WARM_PRIME_SECONDS,
                        )
                    except Exception as e:
                        log.warning(
                            "stream restart failed, falling back to cold open: %s",
                            e,
                        )
                        self._close_stream()
                        # Fall through to the cold-open path below.
                    else:
                        return  # warm restart succeeded
                else:
                    return  # stream is active and matching: nothing to do

            # No stream (or just closed): cold open via executor so the
            # blocking PortAudio constructor + 2s silence prime don't
            # stall the event loop.
            loop = asyncio.get_running_loop()
            try:
                await loop.run_in_executor(None, self._open_stream, sample_rate, channels)
            except Exception as e:
                log.error("SoundDeviceSink failed to open audio device: %s", e)
                self._stream = None
                raise

    async def write(self, chunk: AudioChunk) -> None:
        async with self._lock:
            if self._stream is None:
                raise RuntimeError("SoundDeviceSink.write called before begin_stream")
            # Fail loudly instead of silently feeding mismatched audio
            # through a differently-configured stream. This is the guard
            # the audio-pipeline review flagged as the "future Kokoro
            # sample-rate change" tripwire.
            if chunk.sample_rate != self._stream_sample_rate:
                raise ValueError(
                    f"SoundDeviceSink.write: chunk sample_rate={chunk.sample_rate} "
                    f"does not match open stream sample_rate={self._stream_sample_rate}"
                )
            samples = chunk.samples
            if samples.dtype != np.float32:
                samples = samples.astype(np.float32)
            if samples.ndim == 1:
                samples = samples.reshape(-1, 1)
            # Ensure the buffer is C-contiguous before passing it to
            # PortAudio via sounddevice. Numpy slices of a contiguous
            # array are contiguous, but reshape of a non-contiguous
            # source (e.g., a transposed or strided view) is not, and
            # sounddevice.OutputStream.write would raise on it. This is
            # a no-op when the input is already contiguous.
            samples = np.ascontiguousarray(samples, dtype=np.float32)
            # `write` is blocking; drop the GIL via run_in_executor so
            # other coroutines can make progress.
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._stream.write, samples)

    async def end_stream(self) -> None:
        # Keep the stream open across end→begin to avoid device reopen cost.
        # Only close on stop() or close().
        return

    async def stop(self) -> None:
        """Abort buffered audio but keep the stream alive for fast
        restart on the next begin_stream(). Only close() actually tears
        down the underlying PortAudio stream."""
        async with self._lock:
            if self._stream is not None:
                try:
                    self._stream.abort()
                except Exception as e:  # noqa: BLE001
                    log.warning("SoundDeviceSink abort failed, closing stream: %s", e)
                    self._close_stream()

    async def close(self) -> None:
        async with self._lock:
            self._close_stream()
