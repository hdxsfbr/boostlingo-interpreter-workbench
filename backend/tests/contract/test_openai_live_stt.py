"""gpt-live-transcribe adapter against a scripted fake socket and a recorded
two-segment event stream (no network)."""
import asyncio
import json
from pathlib import Path

import pytest

from app.core.errors import ProviderDisconnected, RateLimited
from app.providers.base import Commit
from app.providers.stt.openai_live import OpenAILiveSTT

FIX = Path(__file__).resolve().parents[3] / "contract" / "fixtures" / "openai"
FRAME = b"\x01\x00" * 2400  # 100 ms


_IDS = iter(range(10**6))


class FakeWS:
    """Scripted server: a delta per append burst, committed+completed per commit."""

    def __init__(self, transcripts=None, replay=None, close_after_commit=False, error_on_commit=None):
        self.sent, self.inbox = [], asyncio.Queue()
        self.transcripts = list(transcripts or [])
        self.replay = replay
        self.n_item = next(_IDS) * 100
        self.close_after_commit = close_after_commit
        self.error_on_commit = error_on_commit
        self.closed = False

    def item(self):
        return f"item_{self.n_item}"

    async def send(self, data):
        m = json.loads(data)
        self.sent.append(m)
        t = m["type"]
        if t == "session.update":
            await self.inbox.put({"type": "session.updated"})
        elif t == "input_audio_buffer.append" and self.replay is None:
            await self.inbox.put({"type": "conversation.item.input_audio_transcription.delta",
                                  "item_id": self.item(), "delta": " word"})
        elif t == "input_audio_buffer.commit":
            if self.error_on_commit:
                await self.inbox.put({"type": "error", "error": self.error_on_commit})
                return
            if self.close_after_commit:
                await self.inbox.put(ConnectionError("gone"))
                return
            if self.replay is not None:
                if sum(1 for s in self.sent if s["type"] == "input_audio_buffer.commit") == 2:
                    for ev in self.replay:
                        await self.inbox.put(ev)
                return
            iid = self.item()
            self.n_item += 1
            await self.inbox.put({"type": "input_audio_buffer.committed", "item_id": iid})
            await self.inbox.put({"type": "conversation.item.input_audio_transcription.completed",
                                  "item_id": iid, "transcript": self.transcripts.pop(0),
                                  "usage": {"type": "duration", "seconds": 1}})

    async def recv(self):
        m = await self.inbox.get()
        if isinstance(m, Exception):
            raise m
        return json.dumps(m)

    async def close(self):
        self.closed = True


def stt_with(ws, **kw):
    async def connect(url, key):
        return ws
    return OpenAILiveSTT("sk-test", connect=connect, **kw)


async def audio(*items):
    for it in items:
        yield it


async def collect(stt, *items):
    return [e async for e in stt.stream(audio(*items), ["en", "es"])]


async def test_session_config_and_single_segment():
    ws = FakeWS(["Good morning."])
    stt = stt_with(ws, delay="low")
    await stt.open()
    evs = await collect(stt, FRAME, FRAME, Commit(final=True))
    upd = ws.sent[0]["session"]
    assert upd["type"] == "transcription"
    assert upd["audio"]["input"]["format"] == {"type": "audio/pcm", "rate": 24000}
    assert upd["audio"]["input"]["turn_detection"] is None
    assert upd["audio"]["input"]["transcription"] == {"model": "gpt-live-transcribe", "languages": ["en", "es"],
                                                      "delay": "low"}
    assert ws.sent[1]["type"] == "input_audio_buffer.clear"
    assert [e.final for e in evs][-1] is True and evs[-1].text == "Good morning." and evs[-1].seg == 0
    assert evs[-1].audio_s == 1.0
    assert any(not e.final for e in evs)


async def test_pause_commit_creates_second_segment():
    ws = FakeWS(["First part.", "Second part."])
    evs = await collect(stt_with(ws), FRAME, Commit(final=False), FRAME, Commit(final=True))
    finals = [(e.seg, e.text) for e in evs if e.final]
    assert finals == [(0, "First part."), (1, "Second part.")]


async def test_tiny_commit_is_not_sent_and_yields_empty_final():
    ws = FakeWS(["Hello there."])
    evs = await collect(stt_with(ws), FRAME, Commit(final=False), b"\x00\x00" * 10, Commit(final=True))
    assert sum(1 for s in ws.sent if s["type"] == "input_audio_buffer.commit") == 1
    # the empty final may overtake the real one; segments are keyed by seg number
    assert sorted((e.seg, e.text) for e in evs if e.final) == [(0, "Hello there."), (1, "")]


async def test_recorded_two_segment_stream_maps_items_to_segments():
    replay = [e for e in json.loads((FIX / "live_transcribe_two_segments.json").read_text())
              if e["type"] != "error"]
    ws = FakeWS(replay=replay)
    evs = await collect(stt_with(ws), FRAME, Commit(final=False), FRAME, Commit(final=True))
    finals = {e.seg: e.text for e in evs if e.final}
    assert finals == {0: "Could morning I have had a headache for three days.",
                      1: "And I took two tablets of ibuprofen"}
    partials = [e for e in evs if not e.final]
    assert partials[0].seg == 0 and partials[0].text == "Could"
    assert any(p.seg == 1 and p.text.startswith("And") for p in partials)


async def test_stale_items_from_a_cancelled_turn_are_ignored():
    ws = FakeWS(["Turn two."])
    stt = stt_with(ws)
    await stt.open()
    stt.seen_items.add("old_item")
    await ws.inbox.put({"type": "conversation.item.input_audio_transcription.completed", "item_id": "old_item",
                        "transcript": "LATE"})
    evs = await collect(stt, FRAME, Commit(final=True))
    assert [e.text for e in evs if e.final] == ["Turn two."]


async def test_rate_limit_error_event_maps_to_rate_limited():
    ws = FakeWS(error_on_commit={"type": "rate_limit_error", "code": "rate_limit_exceeded", "message": "slow"})
    with pytest.raises(RateLimited):
        await collect(stt_with(ws), FRAME, Commit(final=True))


async def test_socket_drop_raises_disconnected_and_reconnects_next_turn():
    ws1 = FakeWS(close_after_commit=True)
    ws2 = FakeWS(["Back again."])
    conns = [ws1, ws2]

    async def connect(url, key):
        return conns.pop(0)

    stt = OpenAILiveSTT("sk-test", connect=connect)
    with pytest.raises(ProviderDisconnected):
        await collect(stt, FRAME, Commit(final=True))
    evs = await collect(stt, FRAME, Commit(final=True))
    assert evs[-1].text == "Back again."
    await stt.aclose()
    assert ws2.closed


async def test_concurrent_open_connects_once():
    n = []
    ws = FakeWS(["One."])

    async def connect(url, key):
        n.append(1)
        await asyncio.sleep(0.01)
        return ws

    stt = OpenAILiveSTT("sk-test", connect=connect)
    await asyncio.gather(stt.open(), stt.open())
    assert len(n) == 1
    evs = await collect(stt, FRAME, Commit(final=True))
    assert evs[-1].text == "One."
