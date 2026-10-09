"""ElevenLabs stream-input adapter against a scripted fake socket. Never calls ElevenLabs."""
import asyncio
import base64
import json
from urllib.parse import parse_qs, urlparse

import pytest

from app.core.errors import AuthError, BudgetExceeded, ProviderDisconnected, RateLimited
from app.providers.tts.elevenlabs import ElevenLabsTTS, map_error

LOUD = (b"\x00\x40" * 240)  # 10 ms of non-silent PCM16


class FakeWS:
    """Replies with one audio frame per text chunk, then isFinal after the "" close."""

    def __init__(self, error=None, drop=False):
        self.sent, self.inbox, self.closed = [], asyncio.Queue(), False
        self.error, self.drop = error, drop

    async def send(self, data):
        m = json.loads(data)
        self.sent.append(m)
        if len(self.sent) == 1:
            return  # initial " " + voice settings
        if self.error:
            await self.inbox.put({"error": self.error, "message": self.error})
        elif self.drop:
            await self.inbox.put(None)
        elif m["text"] == "":
            await self.inbox.put({"audio": None, "isFinal": True})
        else:
            await self.inbox.put({"audio": base64.b64encode(LOUD).decode(), "isFinal": None})

    async def recv(self):
        m = await self.inbox.get()
        if m is None:
            raise ConnectionError("closed")
        return json.dumps(m)

    async def close(self):
        self.closed = True


async def chunks(*xs):
    for x in xs:
        yield x


def make(fake_factory, **kw):
    opened = []

    async def connect(url, key):
        assert key == "xi-test"
        ws = fake_factory()
        ws.url = url
        opened.append(ws)
        return ws
    return ElevenLabsTTS("xi-test", voices={"es": "voiceES"}, connect=connect, **kw), opened


async def test_streams_chunks_and_ends_on_isfinal():
    tts, opened = make(FakeWS, prewarm=False)
    out = [b async for b in tts.stream(chunks("Me duele ", "el pecho."), "es", "")]
    ws = opened[0]
    q = parse_qs(urlparse(ws.url).query)
    assert "/voiceES/stream-input" in ws.url
    assert q["model_id"] == ["eleven_flash_v2_5"] and q["output_format"] == ["pcm_24000"]
    assert q["language_code"] == ["es"] and q["auto_mode"] == ["true"]
    assert ws.sent[0]["text"] == " " and "voice_settings" in ws.sent[0]
    assert [m["text"] for m in ws.sent[1:]] == ["Me duele ", "el pecho. ", ""]
    assert b"".join(out) == LOUD * 2 and ws.closed


async def test_prewarmed_socket_is_used_and_refilled():
    tts, opened = make(FakeWS, prewarm=True)
    await tts.warm(["es"])
    assert len(opened) == 1
    _ = [b async for b in tts.stream(chunks("Hola."), "es", "voiceES")]
    assert len(opened[0].sent) == 3  # the pre-opened socket served the turn
    await asyncio.sleep(0)  # background refill
    await asyncio.sleep(0)
    assert len(opened) == 2 and ("voiceES", "es") in tts._ready
    await tts.aclose()
    assert opened[1].closed and not tts._ready


@pytest.mark.parametrize("err,exc", [("quota_exceeded", BudgetExceeded), ("rate_limit_reached", RateLimited),
                                     ("invalid_api_key auth failed", AuthError)])
async def test_server_errors_are_normalised(err, exc):
    tts, _ = make(lambda: FakeWS(error=err), prewarm=False)
    with pytest.raises(exc):
        _ = [b async for b in tts.stream(chunks("Hola."), "es", "voiceES")]


async def test_socket_drop_maps_to_disconnected():
    tts, _ = make(lambda: FakeWS(drop=True), prewarm=False)
    with pytest.raises(ProviderDisconnected):
        _ = [b async for b in tts.stream(chunks("Hola."), "es", "voiceES")]


def test_map_error_default():
    assert map_error({"message": "something odd"}).code == "provider_error"
