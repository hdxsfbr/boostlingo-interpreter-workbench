"""OpenAI realtime transcription adapter (cascade STT): gpt-live-transcribe
over a WebSocket transcription session (R§2.2).

- One socket per browser session, opened at session start (warm) and
  re-opened on the next turn if it drops.
- `session.type: transcription`, `audio/pcm` 24 kHz, `turn_detection: null`
  (the model has no VAD: we commit at PTT release and in-turn pauses),
  `languages`, `delay`.
- Partials: `...input_audio_transcription.delta` (accumulated per item);
  finals: `...completed`. Items are mapped to segments by commit order;
  cross-item ordering is not guaranteed, so we key on item_id.
- Commits with < 100 ms of new audio are not sent (the API rejects them);
  they yield an empty final for that segment instead.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, Protocol

from app.core.errors import (
    AuthError,
    BadRequest,
    ConfigError,
    ProviderDisconnected,
    ProviderError,
    RateLimited,
)
from app.providers.base import Commit, TranscriptEvent
from app.providers.registry import register

log = logging.getLogger(__name__)
URL = "wss://api.openai.com/v1/realtime?intent=transcription"
MIN_COMMIT_BYTES = 4800  # 100 ms of PCM16 @ 24 kHz


class WSConn(Protocol):
    async def send(self, data: str) -> None: ...
    async def recv(self) -> str: ...
    async def close(self) -> None: ...


async def default_connect(url: str, api_key: str) -> WSConn:
    import websockets

    try:
        return await websockets.connect(url, additional_headers={"Authorization": f"Bearer {api_key}"},
                                        max_size=2**22, open_timeout=5, ping_interval=15)
    except websockets.InvalidStatus as e:  # handshake rejected
        code = e.response.status_code
        if code in (401, 403):
            raise AuthError(f"transcription socket rejected ({code})", provider="openai", stage="stt") from None
        if code == 429:
            raise RateLimited("transcription socket rate-limited", provider="openai", stage="stt") from None
        raise ProviderDisconnected(f"transcription socket HTTP {code}", provider="openai", stage="stt") from None
    except (OSError, TimeoutError) as e:
        raise ProviderDisconnected(f"connect failed: {type(e).__name__}", provider="openai", stage="stt") from None


def _map_error(err: dict) -> ProviderError:
    code = err.get("code") or err.get("type") or "error"
    msg = f"{code}: {err.get('message', '')}"[:300]
    if "rate_limit" in code:
        return RateLimited(msg, provider="openai", stage="stt")
    if code in ("invalid_api_key", "authentication_error"):
        return AuthError(msg, provider="openai", stage="stt")
    return BadRequest(msg, provider="openai", stage="stt")


@register("stt", "openai_live")
class OpenAILiveSTT:
    name = "openai_live"

    def __init__(self, api_key: str, model: str = "gpt-live-transcribe", delay: str | None = "low",
                 languages: list[str] | None = None, prompt: str | None = None,
                 connect: Callable[[str, str], Awaitable[WSConn]] = default_connect, url: str = URL) -> None:
        if not api_key:
            raise ConfigError("OPENAI_API_KEY is not set", provider="openai", stage="stt")
        self.api_key, self.model, self.delay = api_key, model, delay
        self.languages = languages or ["en", "es"]
        self.prompt = prompt
        self._connect, self.url = connect, url
        self.ws: WSConn | None = None
        self.events: asyncio.Queue = asyncio.Queue()
        self.reader: asyncio.Task | None = None
        self.seen_items: set[str] = set()
        self._open_lock = asyncio.Lock()

    def _session_update(self, langs: list[str]) -> dict:
        tr: dict[str, Any] = {"model": self.model, "languages": langs}
        if self.delay:
            tr["delay"] = self.delay
        if self.prompt:
            tr["prompt"] = self.prompt
        return {"type": "session.update", "session": {"type": "transcription", "audio": {"input": {
            "format": {"type": "audio/pcm", "rate": 24000}, "transcription": tr, "turn_detection": None}}}}

    async def open(self) -> None:
        async with self._open_lock:  # warm-up and the first turn may race
            await self._open_locked()

    async def _open_locked(self) -> None:
        if self.ws is not None and self.reader is not None and not self.reader.done():
            return
        await self.aclose()
        self.seen_items.clear()  # new transcription session, new item ids
        self.ws = await self._connect(self.url, self.api_key)
        self.events = asyncio.Queue()
        self.reader = asyncio.create_task(self._read(self.ws, self.events))
        await self.ws.send(json.dumps(self._session_update(self.languages)))

    async def _read(self, ws: WSConn, q: asyncio.Queue) -> None:
        try:
            while True:
                await q.put(json.loads(await ws.recv()))
        except asyncio.CancelledError:
            raise
        except Exception as e:  # socket closed / protocol error
            await q.put({"type": "_closed", "reason": type(e).__name__})

    async def aclose(self) -> None:
        if self.reader:
            self.reader.cancel()
            with contextlib.suppress(BaseException):
                await self.reader
        if self.ws:
            with contextlib.suppress(Exception):
                await self.ws.close()
        self.ws, self.reader = None, None

    async def stream(self, audio: AsyncIterator[bytes | Commit], langs: list[str]) -> AsyncIterator[TranscriptEvent]:
        await self.open()  # re-open if the socket dropped since the last turn
        ws = self.ws
        assert ws is not None
        await ws.send(json.dumps({"type": "input_audio_buffer.clear"}))
        stale = set(self.seen_items)  # late events from a cancelled turn are ignored
        out: asyncio.Queue = asyncio.Queue()
        # bookkeeping shared by sender and receiver
        real_commit_segs: list[int] = []  # seg number for the k-th real commit
        item_order: list[str] = []  # distinct item ids of this turn, in order of appearance
        partial: dict[str, str] = {}
        state = {"next_seg": 0, "final_seg": None, "pending": 0, "sent_done": False, "audio_bytes": 0}

        def seg_for(item_id: str) -> int | None:
            if item_id not in item_order:
                item_order.append(item_id)
            k = item_order.index(item_id)
            return real_commit_segs[k] if k < len(real_commit_segs) else None

        async def sender() -> None:
            since_commit = 0
            async for item in audio:
                if isinstance(item, bytes):
                    since_commit += len(item)
                    state["audio_bytes"] += len(item)
                    await ws.send(json.dumps({"type": "input_audio_buffer.append",
                                              "audio": base64.b64encode(item).decode()}))
                    continue
                seg = state["next_seg"]
                state["next_seg"] += 1
                if item.final:
                    state["final_seg"] = seg
                if since_commit >= MIN_COMMIT_BYTES:
                    real_commit_segs.append(seg)
                    state["pending"] += 1
                    since_commit = 0
                    await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
                else:
                    await out.put(TranscriptEvent(seg=seg, text="", final=True))
                if item.final:
                    break
            state["sent_done"] = True
            await out.put(None)  # wake the merger

        async def receiver() -> None:
            while True:
                ev = await self.events.get()
                typ = ev.get("type", "")
                item_id = ev.get("item_id") or (ev.get("item") or {}).get("id")
                if item_id:
                    self.seen_items.add(item_id)
                    if item_id in stale:
                        continue
                if typ == "conversation.item.input_audio_transcription.delta":
                    partial[item_id] = partial.get(item_id, "") + ev.get("delta", "")
                    seg = seg_for(item_id)
                    await out.put(TranscriptEvent(seg=seg if seg is not None else state["next_seg"],
                                                  text=partial[item_id].strip(), final=False))
                elif typ == "conversation.item.input_audio_transcription.completed":
                    seg = seg_for(item_id)
                    secs = float((ev.get("usage") or {}).get("seconds", 0) or 0)
                    await out.put(("final", seg, (ev.get("transcript") or "").strip(), secs))
                elif typ == "conversation.item.input_audio_transcription.failed":
                    await out.put(("final", seg_for(item_id), "", 0.0))  # empty result, not fatal
                elif typ == "input_audio_buffer.committed":
                    seg_for(item_id)
                elif typ == "error":
                    err = ev.get("error") or {}
                    if err.get("code") == "input_audio_buffer_commit_empty":
                        continue  # guarded above; ignore races
                    await out.put(_map_error(err))
                    return
                elif typ == "_closed":
                    await out.put(ProviderDisconnected(f"transcription socket closed ({ev.get('reason')})",
                                                       provider="openai", stage="stt"))
                    return

        tasks = [asyncio.create_task(sender()), asyncio.create_task(receiver())]
        try:
            finals_done = 0
            while True:
                item = await out.get()
                if item is None:
                    pass
                elif isinstance(item, ProviderError):
                    if isinstance(item, ProviderDisconnected):
                        await self.aclose()
                    raise item
                elif isinstance(item, TranscriptEvent):
                    yield item
                    if item.final and item.seg == state["final_seg"] and state["pending"] == finals_done:
                        return
                else:
                    _, seg, text, secs = item
                    finals_done += 1
                    if seg is None:
                        seg = real_commit_segs[min(finals_done, len(real_commit_segs)) - 1]
                    yield TranscriptEvent(seg=seg, text=text, final=True, audio_s=secs)
                if state["sent_done"] and finals_done >= state["pending"]:
                    # every real commit is final; empty finals were already yielded
                    return
        finally:
            for t in tasks:
                t.cancel()
            for t in tasks:
                with contextlib.suppress(BaseException):
                    await t
