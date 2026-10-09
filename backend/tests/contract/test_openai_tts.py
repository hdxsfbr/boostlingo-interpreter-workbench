"""OpenAI TTS adapter with a mocked /v1/audio/speech (no network)."""
import asyncio
import json

import httpx
import pytest

from app.core.audio import LeadingSilenceTrimmer
from app.core.errors import ProviderUnavailable, RateLimited
from app.providers.tts.openai import OpenAITTS

LOUD = (8000).to_bytes(2, "little", signed=True)
SILENT = b"\x00\x00"


async def agen(items, delay=0.0):
    for x in items:
        await asyncio.sleep(delay)
        yield x


def pcm_for(text: str) -> bytes:
    # 100 ms leading silence (like the real API) + one loud sample per char
    return SILENT * 2400 + LOUD * len(text)


async def test_requests_pcm_streaming_and_yields_in_chunk_order_with_lookahead():
    starts, bodies = [], []

    async def handler(req: httpx.Request):
        body = json.loads(req.content)
        bodies.append(body)
        starts.append(body["input"])
        if body["input"] == "uno.":  # first chunk is slow; lookahead must not reorder audio
            await asyncio.sleep(0.05)
        return httpx.Response(200, content=pcm_for(body["input"]))

    tts = OpenAITTS("sk-test", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    out = [c async for c in tts.stream(agen(["uno.", "dos dos.", "tres tres tres."]), "es", "marin")]
    audio = b"".join(out)
    # leading silence trimmed to 20 ms pad (480 samples) per request
    expected = b"".join(SILENT * 480 + LOUD * len(t) for t in ["uno.", "dos dos.", "tres tres tres."])
    assert audio == expected
    assert starts[:2] == ["uno.", "dos dos."]  # chunk 2 requested while chunk 1 streamed
    b = bodies[0]
    assert (b["model"], b["response_format"], b["stream_format"], b["voice"]) == ("gpt-4o-mini-tts", "pcm", "audio", "marin")
    assert "Spanish" in b["instructions"]


@pytest.mark.parametrize("status,exc", [(429, RateLimited), (503, ProviderUnavailable)])
async def test_errors_surface_in_order_and_normalised(status, exc):
    def handler(req):
        return httpx.Response(status, json={"error": {"message": "x"}})

    tts = OpenAITTS("sk-test", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(exc) as ei:
        _ = [c async for c in tts.stream(agen(["hola."]), "es", "marin")]
    assert ei.value.stage == "tts"


async def test_closing_consumer_cancels_inflight_requests():
    async def handler(req):
        await asyncio.sleep(0.01)
        return httpx.Response(200, content=pcm_for("x" * 50))

    tts = OpenAITTS("sk-test", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    before = len(asyncio.all_tasks())
    gen = tts.stream(agen(["a.", "b.", "c."]), "es", "marin")
    await anext(gen)
    await gen.aclose()
    await asyncio.sleep(0.02)
    assert len(asyncio.all_tasks()) == before


def test_trimmer_handles_odd_splits_and_all_silence():
    t = LeadingSilenceTrimmer(pad_ms=0)
    data = SILENT * 100 + LOUD * 3
    out = t.feed(data[:51]) + t.feed(data[51:])  # odd byte split
    assert out == LOUD * 3
    t2 = LeadingSilenceTrimmer(max_trim_ms=10)
    assert t2.feed(SILENT * 100) == b""
    assert len(t2.feed(SILENT * 200)) > 0  # gives up trimming after max_trim
