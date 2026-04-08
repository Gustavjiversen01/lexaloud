"""Player lifecycle tests using FakeProvider + NullSink.

These exercise the job_id cancellation, bounded backpressure, chunk-boundary
pause, skip (current-sentence cut), stop (full reset), and back (rewind).
"""

from __future__ import annotations

import asyncio

import pytest

from lexaloud.audio import NullSink
from lexaloud.player import Player
from lexaloud.providers.fake import FakeProvider


def _sentences(n: int) -> list[str]:
    return [f"sentence {i}." for i in range(n)]


@pytest.mark.asyncio
async def test_speak_full_play_reaches_idle():
    provider = FakeProvider(synth_delay_ms=5)
    sink = NullSink()
    player = Player(provider, sink, ready_queue_depth=2)

    await player.speak(_sentences(5))
    # Wait for the consumer to drain.
    for _ in range(200):
        if player.state.state == "idle":
            break
        await asyncio.sleep(0.01)
    assert player.state.state == "idle"
    # Each FakeProvider sentence is 0.2s * 24000 Hz = 4800 samples.
    # Between sentences the consumer inserts an INTER_SENTENCE_PAD_SECONDS
    # silence chunk (default 0.18s * 24000 Hz = 4320 samples) to restore
    # the natural pause that Kokoro's trim=True default strips. Five
    # sentences means four pads. We care that all the audio reached the
    # sink, not how many write() calls happened.
    sentence_samples = int(provider.seconds_per_sentence * provider.sample_rate)
    pad_samples = int(Player.INTER_SENTENCE_PAD_SECONDS * provider.sample_rate)
    expected_samples = 5 * sentence_samples + 4 * pad_samples
    assert sink.samples_received == expected_samples
    assert len(provider.synthesize_calls) == 5


@pytest.mark.asyncio
async def test_speak_replace_cancels_previous_job():
    provider = FakeProvider(synth_delay_ms=20)
    sink = NullSink()
    player = Player(provider, sink, ready_queue_depth=2)

    await player.speak(_sentences(10))
    # Let a couple sentences happen.
    await asyncio.sleep(0.05)
    first_job_id = player.state  # just to snapshot
    prev_write = sink.write_count

    # Replace with a short new job.
    await player.speak(_sentences(1))
    # Wait for the new job to complete.
    for _ in range(200):
        if player.state.state == "idle":
            break
        await asyncio.sleep(0.01)

    assert player.state.state == "idle"
    # At least the one new sentence played (possibly plus some from the
    # old job that had already been written before the replace).
    assert sink.write_count >= prev_write + 1
    # Sink was stopped at least once by the replace.
    assert sink.stop_calls >= 1


@pytest.mark.asyncio
async def test_pause_bounds_memory_with_bounded_queue():
    """Pause must not grow the ready queue unboundedly.

    With ready_queue_depth=2 and a 10-sentence job, pausing immediately
    should leave at most 2 chunks in the queue (plus at most one in flight
    in the provider executor).
    """
    provider = FakeProvider(synth_delay_ms=5)
    sink = NullSink()
    player = Player(provider, sink, ready_queue_depth=2)

    await player.speak(_sentences(10))
    await player.pause()

    # Wait for the backpressure steady state to settle.
    await asyncio.sleep(0.2)

    assert player.state.state == "paused"
    # The queue is bounded; the producer is blocked on put once full.
    assert player._ready.qsize() <= 2  # type: ignore[attr-defined]

    # Provider should have synthesized at most (queue depth + in-flight) sentences.
    # With depth 2, producer synthesizes 2 and then blocks on a 3rd put.
    # Depending on scheduling, it may be 2 or 3 synthesize_calls.
    assert 1 <= len(provider.synthesize_calls) <= 4

    # Resume and let it finish.
    await player.resume()
    for _ in range(200):
        if player.state.state == "idle":
            break
        await asyncio.sleep(0.01)
    assert player.state.state == "idle"


@pytest.mark.asyncio
async def test_stop_bumps_job_id_and_clears_state():
    provider = FakeProvider(synth_delay_ms=20)
    sink = NullSink()
    player = Player(provider, sink, ready_queue_depth=2)

    await player.speak(_sentences(5))
    await asyncio.sleep(0.02)
    before_stop_writes = sink.write_count

    await player.stop()
    assert player.state.state == "idle"
    assert player.state.pending_count == 0
    assert player.state.ready_count == 0
    # Sink.stop was called.
    assert sink.stop_calls >= 1
    # After stop, the player accepts new speak.
    await player.speak(_sentences(1))
    for _ in range(200):
        if player.state.state == "idle":
            break
        await asyncio.sleep(0.01)
    assert player.state.state == "idle"
    assert sink.write_count >= before_stop_writes + 1


@pytest.mark.asyncio
async def test_append_mode_extends_pending():
    provider = FakeProvider(synth_delay_ms=50)
    sink = NullSink()
    player = Player(provider, sink, ready_queue_depth=2)

    await player.speak(_sentences(3))
    # Immediately append before the first job finishes.
    await player.speak(_sentences(2), mode="append")
    for _ in range(200):
        if player.state.state == "idle":
            break
        await asyncio.sleep(0.01)
    assert player.state.state == "idle"
    sentence_samples = int(provider.seconds_per_sentence * provider.sample_rate)
    pad_samples = int(Player.INTER_SENTENCE_PAD_SECONDS * provider.sample_rate)
    expected_samples = 5 * sentence_samples + 4 * pad_samples
    assert sink.samples_received == expected_samples


@pytest.mark.asyncio
async def test_skip_advances_past_current_sentence():
    provider = FakeProvider(synth_delay_ms=20)
    sink = NullSink()
    player = Player(provider, sink, ready_queue_depth=2)

    await player.speak(_sentences(3))
    await asyncio.sleep(0.01)  # small head start
    await player.skip()

    for _ in range(200):
        if player.state.state == "idle":
            break
        await asyncio.sleep(0.01)
    # After a skip on the first sentence, the remaining sentences should
    # play. Sink.stop was called to cut current audio.
    assert sink.stop_calls >= 1
    assert player.state.state == "idle"


@pytest.mark.asyncio
async def test_shutdown_clean():
    provider = FakeProvider(synth_delay_ms=5)
    sink = NullSink()
    player = Player(provider, sink, ready_queue_depth=2)

    await player.speak(_sentences(2))
    await asyncio.sleep(0.02)
    await player.shutdown()
    assert sink.close_calls == 1
    assert player.state.state == "idle"


@pytest.mark.asyncio
async def test_empty_speak_does_not_start_tasks():
    provider = FakeProvider()
    sink = NullSink()
    player = Player(provider, sink, ready_queue_depth=2)

    await player.speak([])
    await asyncio.sleep(0.01)
    assert player.state.state == "idle"
    assert sink.write_count == 0
