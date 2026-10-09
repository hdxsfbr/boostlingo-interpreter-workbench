"""OpenAI speech (TTS) adapter: POST /v1/audio/speech, gpt-4o-mini-tts,
response_format=pcm (raw 24 kHz s16le), stream_format=audio (R§4.1).

The endpoint takes whole text per request, so each chunk is one request with
ONE-CHUNK LOOKAHEAD: while chunk n streams, chunk n+1's request is already
in flight; audio is still yielded strictly in chunk order. Leading silence of
each request is trimmed (keeps 20 ms) so first audio is not padded.
"""
from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

import httpx

from app.core.audio import LeadingSilenceTrimmer
from app.core.errors import ConfigError
from app.providers.common.http import provider_stream, shared_client
from app.providers.registry import register

LANG_NAMES = {"en": "English", "es": "Spanish"}
_END = object()


@register("tts", "openai")
class OpenAITTS:
    name = "openai"
    URL = "https://api.openai.com/v1/audio/speech"

    def __init__(self, api_key: str, model: str = "gpt-4o-mini-tts", trim_leading_silence: bool = True,
                 speed: float | None = None, client: httpx.AsyncClient | None = None) -> None:
        if not api_key:
            raise ConfigError("OPENAI_API_KEY is not set", provider="openai", stage="tts")
        self.api_key = api_key
        self.model = model
        self.trim = trim_leading_silence
        self.speed = speed
        self.client = client

    def _body(self, text: str, lang: str, voice: str) -> dict:
        body = {"model": self.model, "voice": voice or "marin", "input": text, "response_format": "pcm",
                "stream_format": "audio",
                "instructions": f"Speak {LANG_NAMES.get(lang, lang)} clearly and naturally, like a professional "
                                f"interpreter: neutral tone, steady pace."}
        if self.speed:
            body["speed"] = self.speed
        return body

    async def _fetch(self, text: str, lang: str, voice: str, out: asyncio.Queue) -> None:
        client = self.client or shared_client()
        trimmer = LeadingSilenceTrimmer() if self.trim else None
        try:
            async with provider_stream(client, "POST", self.URL, provider=self.name, stage="tts",
                                       headers={"Authorization": f"Bearer {self.api_key}"},
                                       json=self._body(text, lang, voice)) as r:
                async for data in r.aiter_bytes():
                    if trimmer:
                        data = trimmer.feed(data)
                    if data:
                        await out.put(data)
            if trimmer and (rest := trimmer.flush()):
                await out.put(rest)
            await out.put(_END)
        except BaseException as e:  # hand the error to the consumer, in order
            await out.put(e)
            if isinstance(e, asyncio.CancelledError):
                raise

    async def stream(self, chunks: AsyncIterator[str], lang: str, voice: str) -> AsyncIterator[bytes]:
        pending: list[tuple[asyncio.Task, asyncio.Queue]] = []
        it = aiter(chunks)
        exhausted = False
        lookahead: asyncio.Task | None = None

        async def start_next() -> None:
            nonlocal exhausted
            if exhausted:
                return
            try:
                text = await anext(it)
            except StopAsyncIteration:
                exhausted = True
                return
            q: asyncio.Queue = asyncio.Queue()
            pending.append((asyncio.create_task(self._fetch(text, lang, voice, q)), q))

        try:
            await start_next()
            while pending:
                task, q = pending[0]
                lookahead = asyncio.create_task(start_next()) if len(pending) == 1 else None
                while (item := await q.get()) is not _END:
                    if isinstance(item, BaseException):
                        raise item
                    yield item
                pending.pop(0)
                if lookahead:
                    await lookahead
                if not pending:
                    await start_next()
        finally:
            if lookahead and not lookahead.done():
                lookahead.cancel()
                with contextlib.suppress(BaseException):
                    await lookahead
            for task, _ in pending:
                task.cancel()
            for task, _ in pending:
                with contextlib.suppress(BaseException):
                    await task
