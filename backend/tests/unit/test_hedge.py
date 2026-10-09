"""Hedged first-output requests (M5): backup request after hedge_after,
first arrival wins, loser cancelled, no duplicated output, error/timeout paths."""

import asyncio

import pytest

from app.cascade.hedge import hedged_first
from app.cascade.session import CascadeSession, ReplayableChunks, Timeouts
from app.core.errors import ProviderTimeout, RateLimited
from app.providers.fakes import FakeSTT, FakeTranslator, FakeTTS

from .test_cascade_session import Sink, finish, speak


class Scripted:
    """factory(): each call returns a stream with the next (delay, items, exc) script."""

    def __init__(self, *scripts):
        self.scripts = list(scripts)
        self.started = 0
        self.closed = []
        self.cancelled = []

    def __call__(self):
        delay, items, exc = self.scripts[self.started]
        idx = self.started
        self.started += 1

        async def gen():
            try:
                await asyncio.sleep(delay)
                if exc:
                    raise exc
                for x in items:
                    yield x
            except asyncio.CancelledError:
                self.cancelled.append(idx)
                raise
            finally:
                self.closed.append(idx)

        return gen()


async def collect(it):
    return [x async for x in it]


async def test_fast_primary_never_hedges():
    f = Scripted((0.01, ["a", "b"], None))
    events = []
    out = await collect(hedged_first(f, timeout=1, hedge_after=0.2, stage="mt", on_event=events.append))
    assert out == ["a", "b"] and f.started == 1 and events == []


async def test_slow_primary_fires_backup_and_backup_wins_loser_cancelled():
    f = Scripted((5.0, ["slow"], None), (0.01, ["x", "y"], None))
    events = []
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    out = await collect(hedged_first(f, timeout=2, hedge_after=0.1, stage="mt", on_event=events.append))
    assert out == ["x", "y"]  # only the winner's items, never both
    assert events == ["hedge_fired", "hedge_won"]
    assert 0 in f.cancelled and 0 in f.closed
    assert loop.time() - t0 < 1.0


async def test_primary_wins_after_hedge_fired_backup_cancelled():
    f = Scripted((0.15, ["p"], None), (5.0, ["b"], None))
    events = []
    out = await collect(hedged_first(f, timeout=2, hedge_after=0.1, stage="tts", on_event=events.append))
    assert out == ["p"] and events == ["hedge_fired"] and 1 in f.cancelled


async def test_both_slow_times_out_and_closes_both():
    f = Scripted((5.0, ["a"], None), (5.0, ["b"], None))
    with pytest.raises(ProviderTimeout) as ei:
        await collect(hedged_first(f, timeout=0.3, hedge_after=0.1, stage="mt", provider="p"))
    assert ei.value.stage == "mt"
    await asyncio.sleep(0)
    assert set(f.cancelled) == {0, 1}


async def test_backup_error_falls_back_to_pending_primary():
    f = Scripted((0.3, ["late"], None), (0.0, [], RateLimited("429")))
    out = await collect(hedged_first(f, timeout=2, hedge_after=0.1, stage="mt"))
    assert out == ["late"]


async def test_sole_error_propagates():
    f = Scripted((0.0, [], RateLimited("429")))
    with pytest.raises(RateLimited):
        await collect(hedged_first(f, timeout=1, hedge_after=0.5, stage="mt"))


async def test_hedge_disabled():
    f = Scripted((0.3, ["a"], None))
    assert await collect(hedged_first(f, timeout=1, hedge_after=None, stage="mt")) == ["a"]
    assert f.started == 1


async def test_replayable_chunks_multi_consumer_counts_once():
    q = asyncio.Queue()
    seen = []
    src = ReplayableChunks(q, seen.append)
    a, b = src(), src()
    for c in ("one", "two", None):
        q.put_nowait(c)
    assert await collect(a) == ["one", "two"]
    assert await collect(b) == ["one", "two"]
    assert seen == ["one", "two"]


# --- session level -------------------------------------------------------


class HangFirstMT(FakeTranslator):
    async def stream(self, text, src, tgt, ctx):
        first = not self.calls
        self.calls.append((text, src, tgt, ctx))
        if first:
            await asyncio.sleep(30)
        async for x in FakeTranslator(self.table).stream(text, src, tgt, ctx):
            yield x


class HangFirstTTS(FakeTTS):
    def __init__(self):
        super().__init__(first_byte=0.0)
        self.calls = 0

    async def stream(self, chunks, lang, voice):
        self.calls += 1
        if self.calls == 1:
            async for _ in chunks:
                await asyncio.sleep(30)
        async for x in super().stream(chunks, lang, voice):
            yield x


def make(mt=None, tts=None):
    sink = Sink()
    s = CascadeSession(
        FakeSTT(),
        mt or FakeTranslator(),
        tts or FakeTTS(),
        send_event=sink.event,
        send_audio=sink.send_audio,
        voices={"es": "marin"},
        timeouts=Timeouts(mt_first_token=1.0, tts_first_byte=1.0, hedge_s=0.1),
    )
    return s, sink


async def test_session_mt_hedge_rescues_stalled_request():
    mt = HangFirstMT({"Good morning, doctor.": "Buenos días, doctor."})
    s, sink = make(mt=mt)
    await speak(s)
    await finish(s, timeout=3)
    assert len(mt.calls) == 2
    assert sink.of("translation.final")[0]["text"] == "Buenos días, doctor."
    assert not sink.of("error")
    marks = sink.of("turn.done")[0]["marks"]
    assert "mt_hedge_fired" in marks and "mt_hedge_won" in marks


async def test_session_tts_hedge_rescues_stalled_request_without_duplicate_audio():
    tts = HangFirstTTS()
    s, sink = make(mt=FakeTranslator({"Good morning, doctor.": "Buenos días, doctor."}), tts=tts)
    await speak(s)
    await finish(s, timeout=3)
    assert tts.calls == 2 and tts.chunks == ["Buenos días, doctor."]
    assert len(sink.audio) == 2  # one chunk -> exactly two frames, from the winner only
    done = sink.of("turn.done")[0]
    assert done["usage"]["tts_chars"] == len("Buenos días, doctor.")  # chars counted once
    assert "tts_hedge_won" in done["marks"] and not sink.of("error")
