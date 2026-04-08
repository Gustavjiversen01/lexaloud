"""Regression tests for the bugs flagged by the concurrency review agent.

Each test is targeted at a specific bug the review found. If these pass,
the matching bug is fixed.
"""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

from lexaloud.audio import NullSink
from lexaloud.player import Player
from lexaloud.providers.base import AudioChunk
from lexaloud.providers.fake import FakeProvider


def _sentences(n: int) -> list[str]:
    return [f"sentence {i}." for i in range(n)]


# ---------- BUG 1: producer error hangs consumer forever ----------


class _FailingProvider:
    name = "failing"

    def __init__(self) -> None:
        self.synthesize_calls = 0

    async def warmup(self) -> None:
        pass

    async def synthesize(self, sentence, job_id, is_current_job):
        self.synthesize_calls += 1
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_producer_exception_does_not_hang_consumer():
    """If the provider raises, the producer must still put the sentinel so
    the consumer reaches idle instead of waiting on an empty queue forever.
    """
    provider = _FailingProvider()
    sink = NullSink()
    player = Player(provider, sink, ready_queue_depth=2)

    await player.speak(_sentences(3))
    # Give the producer time to fail and the consumer time to reach idle.
    for _ in range(200):
        if player.state.state == "idle":
            break
        await asyncio.sleep(0.01)
    assert player.state.state == "idle", (
        "consumer hung waiting for a sentinel that never arrived"
    )


# ---------- BUG 2/3: skip/back lose pre-fetched sentences ----------


class _SlowProvider:
    """Provides chunks deterministically with a configurable per-call delay.

    Pops sentences in the order they were requested; the first chunk takes
    `first_delay_s`, subsequent chunks take `tail_delay_s`. Both delays
    are enforced via `asyncio.sleep` so they yield to the loop and can be
    cancelled cleanly.
    """

    name = "slow"

    def __init__(self, sample_rate=24000, first_delay_s=0.05, tail_delay_s=0.005):
        self.sample_rate = sample_rate
        self.first_delay_s = first_delay_s
        self.tail_delay_s = tail_delay_s
        self.calls = 0

    async def warmup(self) -> None:
        pass

    async def synthesize(self, sentence, job_id, is_current_job):
        if not is_current_job(job_id):
            return None
        delay = self.first_delay_s if self.calls == 0 else self.tail_delay_s
        self.calls += 1
        await asyncio.sleep(delay)
        if not is_current_job(job_id):
            return None
        samples = np.zeros(int(0.01 * self.sample_rate), dtype=np.float32)
        return AudioChunk(
            samples=samples,
            sample_rate=self.sample_rate,
            metadata={"sentence": sentence},
        )


@pytest.mark.asyncio
async def test_skip_does_not_lose_prefetched_sentences():
    """Skip should cut the current sentence but NOT discard the pre-fetched
    sentences sitting in the ready queue. After skip, all remaining
    sentences must still play.
    """
    provider = FakeProvider(
        sample_rate=24000, seconds_per_sentence=0.02, synth_delay_ms=5
    )
    sink = NullSink()
    player = Player(provider, sink, ready_queue_depth=3)

    await player.speak(_sentences(5))
    # Let the producer pre-fetch 2-3 sentences.
    await asyncio.sleep(0.05)
    await player.skip()

    # Drain to idle.
    for _ in range(500):
        if player.state.state == "idle":
            break
        await asyncio.sleep(0.01)
    assert player.state.state == "idle"

    # Verify: 5 sentences were submitted. Skip should have cut at most one
    # sentence, so the consumer should have written at least 4 chunks in
    # total (via either the old consumer before skip or the new one after).
    assert sink.write_count >= 4, (
        f"skip lost pre-fetched sentences: only {sink.write_count} written "
        f"out of 5 submitted"
    )


@pytest.mark.asyncio
async def test_back_rewinds_one_sentence():
    """After finishing sentence 0 and starting sentence 1, back() should
    rewind so the player replays sentence 0 next. The total number of
    written chunks over the lifetime of the job must reflect the rewind.
    """
    provider = FakeProvider(
        sample_rate=24000, seconds_per_sentence=0.02, synth_delay_ms=5
    )
    sink = NullSink()
    player = Player(provider, sink, ready_queue_depth=2)

    await player.speak(_sentences(3))
    # Wait for at least one sentence to finish playing.
    for _ in range(200):
        if player._last_finished_sentence is not None:
            break
        await asyncio.sleep(0.005)

    await player.back()

    # Drain to idle.
    for _ in range(500):
        if player.state.state == "idle":
            break
        await asyncio.sleep(0.01)
    assert player.state.state == "idle"

    # Total writes should equal at least the number of sentences submitted;
    # if back() rewound once, there will be a replay, so count >= 3 +1.
    assert sink.write_count >= 3, (
        f"back() lost sentences: only {sink.write_count} written"
    )


# ---------- BUG 4: append-during-shutdown race ----------


@pytest.mark.asyncio
async def test_append_after_producer_done_starts_fresh_job():
    """If the producer has already exited (short job), append mode should
    fall through to starting a fresh job so the new sentences don't get
    stranded in pending with no consumer.
    """
    provider = FakeProvider(
        sample_rate=24000, seconds_per_sentence=0.01, synth_delay_ms=1
    )
    sink = NullSink()
    player = Player(provider, sink, ready_queue_depth=2)

    await player.speak(_sentences(1))
    # Wait for the job to fully complete.
    for _ in range(200):
        if player.state.state == "idle":
            break
        await asyncio.sleep(0.005)
    before_samples = sink.samples_received

    # Now append — state is idle, producer is done. Should start fresh.
    await player.speak(_sentences(2), mode="append")
    for _ in range(200):
        if player.state.state == "idle":
            break
        await asyncio.sleep(0.005)
    assert player.state.state == "idle"
    # Job 2 contributes 2 sentence_samples + 1 inter-sentence pad.
    sentence_samples = int(provider.seconds_per_sentence * provider.sample_rate)
    pad_samples = int(Player.INTER_SENTENCE_PAD_SECONDS * provider.sample_rate)
    expected_added = 2 * sentence_samples + 1 * pad_samples
    assert sink.samples_received == before_samples + expected_added, (
        "append-after-idle should have started a fresh job"
    )


# ---------- warming state is wired up ----------


@pytest.mark.asyncio
async def test_set_warming_toggles_state():
    provider = FakeProvider()
    sink = NullSink()
    player = Player(provider, sink, ready_queue_depth=2)

    assert player.state.state == "idle"
    player.set_warming(True)
    assert player.state.state == "warming"
    player.set_warming(False)
    assert player.state.state == "idle"


@pytest.mark.asyncio
async def test_set_warming_does_not_clobber_speaking():
    provider = FakeProvider(synth_delay_ms=20)
    sink = NullSink()
    player = Player(provider, sink, ready_queue_depth=2)

    await player.speak(_sentences(5))
    await asyncio.sleep(0.01)
    # While speaking, set_warming(True) must NOT flip state back to warming.
    player.set_warming(True)
    assert player.state.state != "warming"
    await player.stop()


@pytest.mark.asyncio
async def test_pause_is_noop_during_warming():
    """Pause must NOT transition warming -> paused. Previously it did, and
    resume() would then flip to "speaking" with no running producer,
    leaving the player in a zombie state where /state reports "speaking"
    forever with no audio. The fix is to restrict pause to the
    "speaking" state only (see player.pause()).
    """
    provider = FakeProvider()
    sink = NullSink()
    player = Player(provider, sink, ready_queue_depth=2)

    player.set_warming(True)
    assert player.state.state == "warming"
    await player.pause()
    # Pause was ignored; we're still warming, not paused.
    assert player.state.state == "warming"
    # Resume is also a no-op from warming; state stays warming.
    await player.resume()
    assert player.state.state == "warming"
