"""ElevenLabs Flash v2.5 over the stream-input WebSocket (R§4.2).

`wss://api.elevenlabs.io/v1/text-to-speech/{voice}/stream-input` with
`model_id=eleven_flash_v2_5`, `output_format=pcm_24000` (no resampling),
`language_code`, `auto_mode=true` (no chunk-length buffering). Text chunks are
sent as they arrive from the chunker; the turn ends with `{"text": ""}` and
audio is read until `isFinal`.

One socket per turn keeps end-of-turn unambiguous; to hide the connect cost a
socket per target language is **pre-opened** (handshake + initial message)
and handed to the next turn, with `inactivity_timeout` raised so it survives
between turns. Always wrapped in `ElevenLabsBudget`; never called in tests.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Protocol
from urllib.parse import urlencode

from app.core.audio import LeadingSilenceTrimmer
from app.core.errors import (
    AuthError,
    BudgetExceeded,
    ConfigError,
    ProviderDisconnected,
    ProviderError,
    RateLimited,
)
from app.providers.registry import register

BASE = "wss://api.elevenlabs.io/v1/text-to-speech/{voice}/stream-input"


class WSConn(Protocol):
    async def send(self, data: str) -> None: ...
    async def recv(self) -> str: ...
    async def close(self) -> None: ...


async def default_connect(url: str, api_key: str) -> WSConn:
    import websockets

    try:
        return await websockets.connect(url, additional_headers={"xi-api-key": api_key}, max_size=2**23,
                                        open_timeout=5, ping_interval=15)
    except websockets.InvalidStatus as e:
        code = e.response.status_code
        if code in (401, 403):
            raise AuthError(f"ElevenLabs socket rejected ({code})", provider="elevenlabs", stage="tts") from None
        if code == 429:
            raise RateLimited("ElevenLabs socket rate-limited", provider="elevenlabs", stage="tts") from None
        raise ProviderDisconnected(f"ElevenLabs socket HTTP {code}", provider="elevenlabs", stage="tts") from None
    except (OSError, TimeoutError) as e:
        raise ProviderDisconnected(f"connect failed: {type(e).__name__}", provider="elevenlabs",
                                   stage="tts") from None


def map_error(msg: dict) -> ProviderError:
    text = f"{msg.get('error') or ''} {msg.get('message') or ''}".strip()[:300]
    low = text.lower()
    if "quota" in low or "credits" in low:
        return BudgetExceeded(f"ElevenLabs quota: {text}", provider="elevenlabs", stage="tts")
    if "rate" in low or "concurren" in low or "too many" in low:
        return RateLimited(text, provider="elevenlabs", stage="tts")
    if "auth" in low or "api key" in low or "unauthor" in low:
        return AuthError(text, provider="elevenlabs", stage="tts")
    return ProviderError(text or "ElevenLabs error", provider="elevenlabs", stage="tts")


@register("tts", "elevenlabs")
class ElevenLabsTTS:
    name = "elevenlabs"

    def __init__(self, api_key: str, model: str = "eleven_flash_v2_5", voices: dict[str, str] | None = None,
                 prewarm: bool = True, inactivity_timeout: int = 120,
                 connect: Callable[[str, str], Awaitable[WSConn]] = default_connect) -> None:
        if not api_key:
            raise ConfigError("ElevenLabs key file is missing or empty", provider="elevenlabs", stage="tts")
        self.api_key, self.model, self.voices = api_key, model, voices or {}
        self.prewarm, self.inactivity_timeout, self._connect = prewarm, inactivity_timeout, connect
        self._ready: dict[tuple[str, str], WSConn] = {}
        self._refills: set[asyncio.Task] = set()

    def url(self, voice: str, lang: str) -> str:
        q = {"model_id": self.model, "output_format": "pcm_24000", "language_code": lang, "auto_mode": "true",
             "inactivity_timeout": str(self.inactivity_timeout)}
        return BASE.format(voice=voice) + "?" + urlencode(q)

    async def _open(self, voice: str, lang: str) -> WSConn:
        ws = await self._connect(self.url(voice, lang), self.api_key)
        # initial message: a single space + voice settings (protocol requirement)
        await ws.send(json.dumps({"text": " ", "voice_settings": {"stability": 0.5, "similarity_boost": 0.8,
                                                                  "speed": 1.0}}))
        return ws

    async def _take(self, voice: str, lang: str) -> WSConn:
        ws = self._ready.pop((voice, lang), None)
        return ws if ws is not None else await self._open(voice, lang)

    async def warm(self, langs: list[str] | None = None) -> None:
        if not self.prewarm:
            return
        for lang in langs or list(self.voices):
            voice = self.voices.get(lang)
            if voice and (voice, lang) not in self._ready:
                with contextlib.suppress(ProviderError):
                    self._ready[(voice, lang)] = await self._open(voice, lang)

    async def stream(self, chunks: AsyncIterator[str], lang: str, voice: str) -> AsyncIterator[bytes]:
        voice = voice or self.voices.get(lang, "")
        if not voice:
            raise ConfigError(f"no ElevenLabs voice configured for '{lang}'", provider="elevenlabs", stage="tts")
        ws = await self._take(voice, lang)
        async def sender() -> None:
            async for c in chunks:
                if c.strip():
                    await ws.send(json.dumps({"text": c.rstrip() + " "}))
            await ws.send(json.dumps({"text": ""}))  # end of input: generate the rest, then isFinal

        send_task = asyncio.create_task(sender())
        trimmer = LeadingSilenceTrimmer()  # same first-audio treatment as the OpenAI adapter
        try:
            while True:
                if send_task.done() and send_task.exception():
                    raise send_task.exception()
                try:
                    raw = await ws.recv()
                except Exception as e:  # socket closed
                    if send_task.done() and send_task.exception():
                        raise send_task.exception() from None
                    raise ProviderDisconnected(f"ElevenLabs socket closed: {type(e).__name__}",
                                               provider="elevenlabs", stage="tts") from None
                msg = json.loads(raw)
                if msg.get("error") or (msg.get("message") and not msg.get("audio")):
                    raise map_error(msg)
                if msg.get("audio") and (pcm := trimmer.feed(base64.b64decode(msg["audio"]))):
                    yield pcm
                if msg.get("isFinal"):
                    if rest := trimmer.flush():
                        yield rest
                    break
            await send_task
        finally:
            if not send_task.done():
                send_task.cancel()
            with contextlib.suppress(BaseException):
                await send_task
            with contextlib.suppress(Exception):
                await ws.close()
            if self.prewarm:  # hand a fresh socket to the next turn, off the critical path
                t = asyncio.create_task(self._refill(voice, lang))
                self._refills.add(t)
                t.add_done_callback(self._refills.discard)

    async def _refill(self, voice: str, lang: str) -> None:
        with contextlib.suppress(Exception):
            if (voice, lang) not in self._ready:
                self._ready[(voice, lang)] = await self._open(voice, lang)

    async def aclose(self) -> None:
        for t in list(self._refills):
            t.cancel()
        for ws in self._ready.values():
            with contextlib.suppress(Exception):
                await ws.close()
        self._ready.clear()
