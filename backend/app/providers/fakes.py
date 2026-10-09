"""Scripted fake providers for orchestrator tests and offline demos.
Delays and failures are injectable; outputs are deterministic."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable

from app.core.errors import ProviderError
from app.providers.base import Commit, TranscriptEvent, TurnContext, Usage
from app.providers.registry import register


@register("stt", "fake")
class FakeSTT:
    """Each Commit yields a partial then a final for the next scripted segment
    text (cycled). Audio bytes are counted to report audio_s."""

    name = "fake"

    def __init__(self, segments: list[str] | None = None, final_delay: float = 0.01,
                 fail: ProviderError | None = None, hang_after_commit: bool = False) -> None:
        self.segments = segments or ["Good morning, doctor."]
        self.final_delay = final_delay
        self.fail = fail
        self.hang_after_commit = hang_after_commit
        self.opened = self.closed = False
        self._i = 0

    async def open(self) -> None:
        self.opened = True

    async def stream(self, audio: AsyncIterator[bytes | Commit], langs: list[str]) -> AsyncIterator[TranscriptEvent]:
        seg, nbytes = 0, 0
        async for item in audio:
            if isinstance(item, bytes):
                nbytes += len(item)
                continue
            if self.fail:
                raise self.fail
            text = self.segments[self._i % len(self.segments)]
            self._i += 1
            yield TranscriptEvent(seg=seg, text=text.split(" ")[0], final=False)
            if self.hang_after_commit:
                await asyncio.sleep(3600)
            await asyncio.sleep(self.final_delay)
            yield TranscriptEvent(seg=seg, text=text, final=True, audio_s=nbytes / 48000)
            nbytes = 0
            seg += 1
            if item.final:
                return

    async def aclose(self) -> None:
        self.closed = True


@register("mt", "fake")
class FakeTranslator:
    """Translates via a dict (or upper-cases), streaming word tokens."""

    name = "fake"

    def __init__(self, table: dict[str, str] | None = None, ttft: float = 0.01, token_delay: float = 0.001,
                 failures: list[ProviderError] | None = None, fail_mid_stream: ProviderError | None = None,
                 fn: Callable[[str], str] | None = None) -> None:
        self.table = table or {}
        self.ttft = ttft
        self.token_delay = token_delay
        self.failures = list(failures or [])
        self.fail_mid_stream = fail_mid_stream
        self.fn = fn
        self.calls: list[tuple[str, str, str, TurnContext]] = []
        self.last_usage = Usage()

    async def stream(self, text: str, src: str, tgt: str, ctx: TurnContext) -> AsyncIterator[str]:
        self.calls.append((text, src, tgt, ctx))
        if self.failures:
            raise self.failures.pop(0)
        out = self.table.get(text) if text in self.table else (self.fn(text) if self.fn else text.upper())
        self.last_usage = Usage(mt_input_tokens=len(text.split()) + 20, mt_output_tokens=len(out.split()))
        await asyncio.sleep(self.ttft)
        words = out.split(" ") if out else []
        for i, w in enumerate(words):
            if self.fail_mid_stream and i == 1:
                raise self.fail_mid_stream
            yield w if i == 0 else " " + w
            await asyncio.sleep(self.token_delay)


@register("tts", "fake")
class FakeTTS:
    """Per chunk, yields two PCM frames whose bytes encode the chunk index, so
    tests can assert in-order audio. Never touches the network."""

    name = "fake"

    def __init__(self, first_byte: float = 0.01, frame_bytes: int = 960, fail: ProviderError | None = None) -> None:
        self.first_byte = first_byte
        self.frame_bytes = frame_bytes
        self.fail = fail
        self.chunks: list[str] = []

    async def stream(self, chunks: AsyncIterator[str], lang: str, voice: str) -> AsyncIterator[bytes]:
        async for chunk in chunks:
            if self.fail:
                raise self.fail
            idx = len(self.chunks)
            self.chunks.append(chunk)
            await asyncio.sleep(self.first_byte)
            for _ in range(2):
                yield bytes([idx % 256]) * self.frame_bytes
