"""Playback state machine.

Owns:
- `current_job_id` — monotonically increasing; each `/speak` bumps it.
- `pending_sentences` — deque of sentences not yet popped by the producer.
- `in_flight_sentences` — deque of sentences the producer has popped but the
  consumer hasn't yet played (pre-fetched in the ready queue OR currently
  being synthesized inside the executor). On cancel (skip/back/stop), these
  go back at the head of `pending_sentences` so a re-run doesn't lose them.
- `ready_queue` — bounded asyncio.Queue of completed AudioChunks (or `None`
  sentinel). Bounded queue = bounded memory during pause / slow consumer.
- `pause_event` — set while playing, cleared while paused.
- One producer task and one consumer task per job.

Lifecycle:

    POST /speak (replace, default)
      -> bump job_id (discards in-flight provider results)
      -> sink.stop() (flush any audio mid-play)
      -> drain ready_queue
      -> replace pending_sentences
      -> start a fresh pair of tasks (producer + consumer)

    POST /stop
      -> same as above minus the "start fresh"

    POST /pause
      -> clear pause_event
      -> consumer awaits pause_event.wait() on the next sentence boundary
      -> because ready_queue is bounded, producer blocks on Queue.put once
         full, which bounds memory usage during any-length pause

    POST /resume
      -> set pause_event

    POST /skip
      -> cancel tasks; sink.stop() (cut current sentence)
      -> put in-flight sentences (minus the current one) back at the head
         of pending so the new producer can re-process them
      -> restart tasks with the same job id

    POST /back
      -> prepend last-finished, current, and any in-flight sentences
      -> same flush as skip
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Literal

import numpy as np

from ._privacy import sentence_token
from .audio import AudioSink
from .providers.base import AudioChunk, SpeechProvider

log = logging.getLogger(__name__)


State = Literal["idle", "warming", "speaking", "paused"]


@dataclass
class PlayerState:
    state: State
    current_sentence: str | None
    pending_count: int
    ready_count: int
    provider_name: str
    session_providers: list[str]
    # Set by the producer when a whole job fails due to synthesis errors
    # (as opposed to cancellation). Exposed via /state so the CLI and
    # tray indicator can surface it to the user instead of silently
    # going back to "idle" with no audio played.
    last_error: str | None = None


class Player:
    # When writing a sentence to the sink, break it into sub-blocks of
    # approximately this many seconds. The consumer checks the pause event
    # between blocks, so pause takes effect within ~SUB_CHUNK_SECONDS of
    # the press plus the audio device's own buffer tail-out (~100-150ms).
    # Without sub-chunking, pause would only take effect at sentence
    # boundaries, which can be 5-10 seconds for dense academic prose.
    SUB_CHUNK_SECONDS: float = 0.1

    # Silence inserted between sentences. Kokoro.create(trim=True) strips
    # natural trailing silence, which makes concatenated sentences sound
    # rushed for dense academic prose. Inserting ~180ms of zeros restores
    # a natural pause and also eliminates any amplitude-discontinuity
    # click at the sentence boundary.
    INTER_SENTENCE_PAD_SECONDS: float = 0.18

    def __init__(
        self,
        provider: SpeechProvider,
        sink: AudioSink,
        ready_queue_depth: int = 3,
    ) -> None:
        self._provider = provider
        self._sink = sink
        self._ready_queue_depth = max(1, ready_queue_depth)

        self._current_job_id = 0
        self._pending: deque[str] = deque()
        # Sentences the producer popped but the consumer hasn't played yet
        # (either sitting in `_ready` or being synthesized in the executor).
        self._in_flight: deque[str] = deque()
        # None is the end-of-job sentinel from the producer.
        self._ready: asyncio.Queue[AudioChunk | None] = asyncio.Queue(
            maxsize=self._ready_queue_depth
        )
        self._pause = asyncio.Event()
        self._pause.set()  # unpaused by default

        self._producer_task: asyncio.Task | None = None
        self._consumer_task: asyncio.Task | None = None

        self._current_sentence_value: str | None = None
        self._last_finished_sentence: str | None = None
        self._state_value: State = "idle"
        self._last_error: str | None = None

        # Callback fired whenever _state or _current_sentence changes.
        # Used by the MPRIS2 adapter to emit PropertiesChanged signals.
        # Set via player._on_state_change = callback after construction.
        self._on_state_change: Callable[[PlayerState], None] | None = None

        # Protects transitions that mutate job state (stop/skip/back/speak).
        # Prevents two concurrent HTTP requests from entangling their
        # cancellation logic.
        self._control_lock = asyncio.Lock()

    # ---------- property-based state with auto-fire callback ----------

    @property
    def _state(self) -> State:
        return self._state_value

    @_state.setter
    def _state(self, new: State) -> None:
        self._state_value = new
        self._fire_state_change()

    @property
    def _current_sentence(self) -> str | None:
        return self._current_sentence_value

    @_current_sentence.setter
    def _current_sentence(self, new: str | None) -> None:
        self._current_sentence_value = new
        self._fire_state_change()

    def _fire_state_change(self) -> None:
        if self._on_state_change is not None:
            try:
                self._on_state_change(self.state)
            except Exception:  # noqa: BLE001
                pass  # never let a callback crash the player

    # ---------- state introspection ----------

    @property
    def state(self) -> PlayerState:
        return PlayerState(
            state=self._state,
            current_sentence=self._current_sentence,
            pending_count=len(self._pending) + len(self._in_flight),
            ready_count=self._ready.qsize(),
            provider_name=getattr(self._provider, "name", "unknown"),
            session_providers=list(getattr(self._provider, "session_providers", []) or []),
            last_error=self._last_error,
        )

    def set_warming(self, warming: bool) -> None:
        """Wire-up for the daemon to report warming state.

        Only flips state between 'idle' and 'warming' so we don't clobber
        an in-progress speak. The caller is expected to invoke this before
        starting the background warmup task and again after it completes.
        """
        if warming and self._state == "idle":
            self._state = "warming"
        elif not warming and self._state == "warming":
            self._state = "idle"

    def _is_current_job(self, job_id: int) -> bool:
        return job_id == self._current_job_id

    # ---------- internal task bodies ----------

    async def _producer(self, job_id: int) -> None:
        log.debug("producer job=%d starting", job_id)
        sentinel_sent = False
        attempts = 0
        successes = 0
        try:
            while True:
                if not self._is_current_job(job_id):
                    return
                try:
                    sentence = self._pending.popleft()
                except IndexError:
                    # No more sentences; signal end-of-job to the consumer.
                    await self._ready.put(None)
                    sentinel_sent = True
                    # If every synthesize() call in this job returned None,
                    # there was a systemic failure (bad voice, GPU OOM,
                    # model corruption). Surface it via `last_error` so the
                    # CLI and tray indicator can tell the user instead of
                    # silently going idle with zero audio.
                    if attempts > 0 and successes == 0:
                        self._last_error = (
                            "Synthesis produced no audio for any sentence in "
                            "this job. Check the daemon log "
                            "(`journalctl --user -u lexaloud -n 100`) for "
                            "details — likely causes: invalid voice name in "
                            "config, GPU out-of-memory, or corrupted model "
                            "files."
                        )
                        log.error("job=%d: %s", job_id, self._last_error)
                    return
                # Track this sentence as in-flight so skip/back can recover it.
                self._in_flight.append(sentence)
                try:
                    attempts += 1
                    chunk = await self._provider.synthesize(sentence, job_id, self._is_current_job)
                except asyncio.CancelledError:
                    # On cancel, return the in-flight sentence to pending
                    # so recovery can process it.
                    self._pending.appendleft(sentence)
                    with suppress(ValueError):
                        self._in_flight.remove(sentence)
                    raise
                if chunk is None:
                    # Either the job was superseded (cancellation) or the
                    # provider failed. Drop the in-flight record; if the
                    # job is still current, the None was a synthesis
                    # failure, not a cancellation — count it so we can
                    # surface the systemic error at end-of-job.
                    with suppress(ValueError):
                        self._in_flight.remove(sentence)
                    if not self._is_current_job(job_id):
                        return
                    # Synthesis failed but the job wasn't cancelled —
                    # continue trying subsequent sentences. If they all
                    # fail, the end-of-job path will set last_error.
                    log.debug(
                        "job=%d: synthesize returned None for sentence %s",
                        job_id,
                        sentence_token(sentence),
                    )
                    continue
                if not self._is_current_job(job_id):
                    with suppress(ValueError):
                        self._in_flight.remove(sentence)
                    return
                successes += 1
                # Attach the source sentence as metadata so the consumer
                # can report it in /state.
                chunk.metadata.setdefault("sentence", sentence)
                try:
                    await self._ready.put(chunk)  # backpressure applies here
                except asyncio.CancelledError:
                    # Cancelled while waiting to put; return sentence to pending.
                    self._pending.appendleft(sentence)
                    with suppress(ValueError):
                        self._in_flight.remove(sentence)
                    raise
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("producer job=%d failed: %s", job_id, e)
            self._last_error = f"producer task crashed: {e}"
        finally:
            # Ensure the consumer is never left waiting for a sentinel that
            # never arrives, even if an exception killed the producer.
            if not sentinel_sent:
                try:
                    self._ready.put_nowait(None)
                except asyncio.QueueFull:
                    # Consumer will be cancelled by the caller of cancel_tasks
                    # anyway; safe to drop.
                    pass

    async def _consumer(self, job_id: int) -> None:
        log.debug("consumer job=%d starting", job_id)
        stream_open = False
        stream_sr: int | None = None
        stream_ch: int | None = None
        sentences_written = 0
        try:
            while True:
                if not self._is_current_job(job_id):
                    return
                # Pause boundary: wait here between sentences while paused.
                await self._pause.wait()
                if not self._is_current_job(job_id):
                    return
                chunk = await self._ready.get()
                if chunk is None:
                    # End-of-job sentinel from producer.
                    if stream_open:
                        await self._sink.end_stream()
                        stream_open = False
                    if self._is_current_job(job_id):
                        self._state = "idle"
                        self._current_sentence = None
                    return
                if not self._is_current_job(job_id):
                    return

                # (Re)configure the sink if the sample rate or channel
                # count changed since the last chunk. Today Kokoro is
                # always 24 kHz mono; this guard catches any future
                # provider or voice that emits a different shape so we
                # don't silently feed mismatched samples into a stream
                # configured for the wrong rate.
                channels = 1 if chunk.samples.ndim == 1 else int(chunk.samples.shape[1])
                if not stream_open or chunk.sample_rate != stream_sr or channels != stream_ch:
                    if stream_open:
                        try:
                            await self._sink.end_stream()
                        except Exception as e:  # noqa: BLE001
                            log.warning("sink.end_stream failed during reopen: %s", e)
                    await self._sink.begin_stream(chunk.sample_rate, channels)
                    stream_sr = chunk.sample_rate
                    stream_ch = channels
                    stream_open = True

                # Insert an inter-sentence silence pad (except before
                # the first sentence of the stream). This restores the
                # natural pause that Kokoro's trim=True default strips.
                if sentences_written > 0:
                    try:
                        await self._write_silence_pad(stream_sr, stream_ch, job_id)
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:  # noqa: BLE001
                        log.warning("silence pad write failed: %s", e)

                self._current_sentence = chunk.metadata.get("sentence")
                try:
                    await self._write_in_blocks(chunk, job_id)
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001
                    log.error(
                        "sink.write failed mid-sentence; normalizing to idle: %s",
                        e,
                    )
                    # Normalize state so /state doesn't lie, /pause doesn't
                    # strand an event, and the next /speak recovers cleanly.
                    self._current_job_id += 1
                    self._state = "idle"
                    self._current_sentence = None
                    try:
                        await self._sink.stop()
                    except Exception as e2:  # noqa: BLE001
                        log.warning("sink.stop failed during error recovery: %s", e2)
                    return
                if not self._is_current_job(job_id):
                    return
                sentences_written += 1
                self._last_finished_sentence = self._current_sentence
                # The sentence just finished playing — remove it from the
                # in-flight deque (it will be the oldest entry).
                if self._current_sentence is not None:
                    with suppress(ValueError):
                        self._in_flight.remove(self._current_sentence)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("consumer job=%d failed: %s", job_id, e)
            # Normalize state on any other consumer-level exception so the
            # daemon isn't stuck reporting "speaking" forever.
            if self._is_current_job(job_id):
                self._current_job_id += 1
                self._state = "idle"
                self._current_sentence = None

    async def _write_silence_pad(self, sample_rate: int, channels: int, job_id: int) -> None:
        """Write a short silence chunk between sentences.

        Short enough (~180ms) that pause-event checking inside it is
        unnecessary; we only guard the job_id so a stop/skip/back can
        still interrupt the sequence cleanly.
        """
        pad_samples = int(self.INTER_SENTENCE_PAD_SECONDS * sample_rate)
        if pad_samples <= 0:
            return
        if not self._is_current_job(job_id):
            return
        shape: tuple[int, ...]
        if channels == 1:
            shape = (pad_samples,)
        else:
            shape = (pad_samples, channels)
        silence = np.zeros(shape, dtype=np.float32)
        pad_chunk = AudioChunk(
            samples=silence,
            sample_rate=sample_rate,
            metadata={"is_silence_pad": True},
        )
        await self._sink.write(pad_chunk)

    async def _write_in_blocks(self, chunk: AudioChunk, job_id: int) -> None:
        """Write an AudioChunk to the sink in SUB_CHUNK_SECONDS-long blocks.

        Between blocks we check:
          1. `_is_current_job(job_id)` so stop/skip/back-initiated job bumps
             take effect mid-sentence.
          2. `_pause.is_set()` so pause takes effect mid-sentence.

        Short chunks (smaller than one block) still go through the same
        loop with a single iteration — no special-case code path.

        Numpy slicing produces views, not copies, so the per-block
        overhead is a small AudioChunk dataclass allocation, not a
        memory copy of the audio.
        """
        block_samples = max(1, int(self.SUB_CHUNK_SECONDS * chunk.sample_rate))
        total = chunk.num_samples
        if total == 0:
            return

        offset = 0
        while offset < total:
            if not self._is_current_job(job_id):
                return
            if not self._pause.is_set():
                await self._pause.wait()
                if not self._is_current_job(job_id):
                    return
            end = min(offset + block_samples, total)
            sub_samples = chunk.samples[offset:end]
            sub_chunk = AudioChunk(
                samples=sub_samples,
                sample_rate=chunk.sample_rate,
                metadata=chunk.metadata,
            )
            await self._sink.write(sub_chunk)
            offset = end

    async def _start_tasks(self, job_id: int) -> None:
        # Ensure no stale tasks; caller is responsible for cancelling any
        # prior tasks before calling this.
        if self._producer_task is not None and not self._producer_task.done():
            raise RuntimeError("producer task not clean before _start_tasks")
        if self._consumer_task is not None and not self._consumer_task.done():
            raise RuntimeError("consumer task not clean before _start_tasks")
        self._producer_task = asyncio.create_task(self._producer(job_id), name=f"producer-{job_id}")
        self._consumer_task = asyncio.create_task(self._consumer(job_id), name=f"consumer-{job_id}")

    async def _cancel_tasks(self) -> None:
        tasks = [
            t for t in (self._producer_task, self._consumer_task) if t is not None and not t.done()
        ]
        for t in tasks:
            t.cancel()
        # Await concurrently so a slow producer doesn't gate the consumer.
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for t, r in zip(tasks, results, strict=True):
                if isinstance(r, asyncio.CancelledError):
                    pass
                elif isinstance(r, BaseException):
                    log.warning(
                        "task %s exited with error during cancel: %r",
                        t.get_name(),
                        r,
                    )
        self._producer_task = None
        self._consumer_task = None

    def _drain_ready_queue(self) -> None:
        while not self._ready.empty():
            try:
                self._ready.get_nowait()
            except asyncio.QueueEmpty:
                break

    def _recover_in_flight_to_pending(self) -> None:
        """Put any in-flight sentences back at the head of pending.

        Called after _cancel_tasks to recover work that was pre-fetched but
        never played, so skip/back/stop-restart don't silently lose sentences.
        The in-flight deque is consumed in reverse so the original order is
        preserved after the prepends.
        """
        while self._in_flight:
            s = self._in_flight.pop()
            self._pending.appendleft(s)

    async def _full_stop(self) -> None:
        # Bumps the job id first so any in-flight provider calls will return
        # None (or raise cancelled) after their executor result comes back.
        self._current_job_id += 1
        await self._cancel_tasks()
        # Only abort the audio stream if we were actually playing or paused.
        # When the player is idle (e.g., transitioning from idle → speaking
        # in a fresh /speak), the stream may be pre-warmed from the daemon
        # startup sink warmup. Aborting it here would kill the warm stream
        # and force a cold restart, reintroducing the first-use audio
        # clipping bug.
        if self._state in ("speaking", "paused"):
            try:
                await self._sink.stop()
            except Exception as e:  # noqa: BLE001
                log.warning("sink.stop failed: %s", e)
        self._drain_ready_queue()
        self._in_flight.clear()
        self._pending.clear()
        # Ensure pause does not block the next job.
        self._pause.set()
        self._state = "idle"
        self._current_sentence = None

    # ---------- public API ----------

    async def speak(self, sentences: list[str], mode: str = "replace") -> int:
        async with self._control_lock:
            # Append is only valid if a producer is still alive. If the
            # producer has already exited (e.g., last sentence completed
            # just before the append arrived), treat this as a fresh job
            # to avoid stranded sentences.
            producer_alive = self._producer_task is not None and not self._producer_task.done()
            if mode == "append" and self._state in ("speaking", "paused") and producer_alive:
                self._pending.extend(sentences)
                return self._current_job_id

            await self._full_stop()
            # Clear any prior error message so the fresh job starts with a
            # clean state; the producer will set last_error again if it
            # hits a systemic failure during THIS job.
            self._last_error = None
            new_job = self._current_job_id + 1
            self._current_job_id = new_job
            self._pending.extend(sentences)
            if sentences:
                self._state = "speaking"
                await self._start_tasks(new_job)
            return new_job

    async def pause(self) -> None:
        async with self._control_lock:
            # Pause only takes effect while actively speaking. Pausing
            # from "warming" would transition state to "paused" with no
            # running producer — resume would then flip to "speaking"
            # with no audio, leaving the player in a zombie state where
            # /state lies. The correct behavior is to ignore the pause
            # request entirely; warmup will finish on its own.
            if self._state == "speaking":
                self._pause.clear()
                self._state = "paused"

    async def resume(self) -> None:
        async with self._control_lock:
            if self._state == "paused":
                self._pause.set()
                self._state = "speaking"

    async def stop(self) -> None:
        async with self._control_lock:
            await self._full_stop()

    async def skip(self) -> None:
        """Skip the currently playing sentence.

        Cuts the current audio via sink.stop(), cancels producer/consumer,
        recovers pre-fetched but unplayed sentences (minus the one the
        consumer was playing) back to the head of pending, then restarts
        tasks on the same job id.
        """
        async with self._control_lock:
            if self._state not in ("speaking", "paused"):
                return
            current = self._current_sentence
            await self._cancel_tasks()
            try:
                await self._sink.stop()
            except Exception as e:  # noqa: BLE001
                log.warning("sink.stop failed on skip: %s", e)
            self._drain_ready_queue()
            # Drop the currently-playing sentence from in-flight; return
            # everything else to pending so we don't lose pre-fetched work.
            if current is not None:
                with suppress(ValueError):
                    self._in_flight.remove(current)
            self._recover_in_flight_to_pending()
            self._current_sentence = None
            self._pause.set()
            if self._pending:
                self._state = "speaking"
                await self._start_tasks(self._current_job_id)
            else:
                self._state = "idle"

    async def back(self) -> None:
        """Rewind one sentence.

        Recovers any pre-fetched in-flight sentences (including the current
        one) back to pending, then prepends the previously-finished sentence
        so the new run starts one sentence earlier. If there's no prior
        sentence, this restarts the current sentence.
        """
        async with self._control_lock:
            if self._state not in ("speaking", "paused"):
                return
            last_finished = self._last_finished_sentence
            await self._cancel_tasks()
            try:
                await self._sink.stop()
            except Exception as e:  # noqa: BLE001
                log.warning("sink.stop failed on back: %s", e)
            self._drain_ready_queue()
            # Return any in-flight (currently-playing + pre-fetched) to the
            # head of pending so nothing is lost.
            self._recover_in_flight_to_pending()
            # Now prepend the last-finished sentence so we rewind by one.
            if last_finished is not None:
                self._pending.appendleft(last_finished)
                # Forget it so a second back() does not rewind forever.
                self._last_finished_sentence = None
            self._current_sentence = None
            self._pause.set()
            if self._pending:
                self._state = "speaking"
                await self._start_tasks(self._current_job_id)
            else:
                self._state = "idle"

    async def shutdown(self) -> None:
        await self._full_stop()
        try:
            await self._sink.close()
        except Exception as e:  # noqa: BLE001
            log.warning("sink.close failed: %s", e)
