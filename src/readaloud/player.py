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

Lifecycle (see `../.claude/plans/peppy-sprouting-knuth.md`):

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
from dataclasses import dataclass
from typing import Literal

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


class Player:
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

        self._current_sentence: str | None = None
        self._last_finished_sentence: str | None = None
        self._state: State = "idle"

        # Protects transitions that mutate job state (stop/skip/back/speak).
        # Prevents two concurrent HTTP requests from entangling their
        # cancellation logic.
        self._control_lock = asyncio.Lock()

    # ---------- state introspection ----------

    @property
    def state(self) -> PlayerState:
        return PlayerState(
            state=self._state,
            current_sentence=self._current_sentence,
            pending_count=len(self._pending) + len(self._in_flight),
            ready_count=self._ready.qsize(),
            provider_name=getattr(self._provider, "name", "unknown"),
            session_providers=list(
                getattr(self._provider, "session_providers", []) or []
            ),
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
                    return
                # Track this sentence as in-flight so skip/back can recover it.
                self._in_flight.append(sentence)
                try:
                    chunk = await self._provider.synthesize(
                        sentence, job_id, self._is_current_job
                    )
                except asyncio.CancelledError:
                    # On cancel, return the in-flight sentence to pending
                    # so recovery can process it.
                    self._pending.appendleft(sentence)
                    try:
                        self._in_flight.remove(sentence)
                    except ValueError:
                        pass
                    raise
                if chunk is None or not self._is_current_job(job_id):
                    # Provider saw cancellation; drop the in-flight record.
                    try:
                        self._in_flight.remove(sentence)
                    except ValueError:
                        pass
                    return
                # Attach the source sentence as metadata so the consumer
                # can report it in /state.
                chunk.metadata.setdefault("sentence", sentence)
                try:
                    await self._ready.put(chunk)  # backpressure applies here
                except asyncio.CancelledError:
                    # Cancelled while waiting to put; return sentence to pending.
                    self._pending.appendleft(sentence)
                    try:
                        self._in_flight.remove(sentence)
                    except ValueError:
                        pass
                    raise
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("producer job=%d failed: %s", job_id, e)
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
        try:
            stream_open = False
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
                if not stream_open:
                    channels = (
                        1
                        if chunk.samples.ndim == 1
                        else int(chunk.samples.shape[1])
                    )
                    await self._sink.begin_stream(chunk.sample_rate, channels)
                    stream_open = True
                self._current_sentence = chunk.metadata.get("sentence")
                try:
                    await self._sink.write(chunk)
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001
                    log.error("sink.write failed: %s", e)
                    return
                self._last_finished_sentence = self._current_sentence
                # The sentence just finished playing — remove it from the
                # in-flight deque (it will be the oldest entry).
                try:
                    if self._current_sentence is not None:
                        self._in_flight.remove(self._current_sentence)
                except ValueError:
                    pass
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("consumer job=%d failed: %s", job_id, e)

    async def _start_tasks(self, job_id: int) -> None:
        # Ensure no stale tasks; caller is responsible for cancelling any
        # prior tasks before calling this.
        if self._producer_task is not None and not self._producer_task.done():
            raise RuntimeError("producer task not clean before _start_tasks")
        if self._consumer_task is not None and not self._consumer_task.done():
            raise RuntimeError("consumer task not clean before _start_tasks")
        self._producer_task = asyncio.create_task(
            self._producer(job_id), name=f"producer-{job_id}"
        )
        self._consumer_task = asyncio.create_task(
            self._consumer(job_id), name=f"consumer-{job_id}"
        )

    async def _cancel_tasks(self) -> None:
        tasks = [
            t
            for t in (self._producer_task, self._consumer_task)
            if t is not None and not t.done()
        ]
        for t in tasks:
            t.cancel()
        # Await concurrently so a slow producer doesn't gate the consumer.
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for t, r in zip(tasks, results):
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
            producer_alive = (
                self._producer_task is not None and not self._producer_task.done()
            )
            if (
                mode == "append"
                and self._state in ("speaking", "paused")
                and producer_alive
            ):
                self._pending.extend(sentences)
                return self._current_job_id

            await self._full_stop()
            new_job = self._current_job_id + 1
            self._current_job_id = new_job
            self._pending.extend(sentences)
            if sentences:
                self._state = "speaking"
                await self._start_tasks(new_job)
            return new_job

    async def pause(self) -> None:
        async with self._control_lock:
            if self._state in ("speaking", "warming"):
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
                try:
                    self._in_flight.remove(current)
                except ValueError:
                    pass
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
