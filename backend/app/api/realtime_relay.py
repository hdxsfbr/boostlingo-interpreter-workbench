"""/ws/realtime: WebSocket relay fallback for Realtime mode (D1 fallback,
DESIGN R4). Used when WebRTC is unavailable (network, headless browser).

Browser -> relay:
  {"type": "relay.start", "a", "b", "turn_mode", "silence_duration_ms"}  (first message)
  binary PCM16 24 kHz mono                                -> input_audio_buffer.append
  {"type": "oai", "event": {...}}  whitelisted client events, forwarded as-is
Relay -> browser:
  {"type": "relay.ready", "model"} once the upstream session is configured
  JSON OpenAI server events, forwarded unchanged (normalised in the browser by
  the same OaiNormalizer as WebRTC), except response.output_audio.delta which
  becomes a binary frame: uint32 LE response index (1-based, order of
  response.created) + PCM16.
  {"type": "error", ...} contract errors for relay-level failures.

The standard API key stays server-side; the browser never sees a secret.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ValidationError

from app.core.config import get_settings
from app.core.errors import AuthError, ProviderDisconnected, ProviderError, RateLimited
from app.core.events import pack_audio
from app.realtime.session_config import build_interpreter_session

log = logging.getLogger(__name__)
router = APIRouter()
URL = "wss://api.openai.com/v1/realtime?model={model}"
CLIENT_EVENTS = {"input_audio_buffer.clear", "input_audio_buffer.commit", "response.create",
                 "response.cancel", "conversation.item.delete"}


class UpstreamWS(Protocol):
    async def send(self, data: str) -> None: ...
    async def recv(self) -> str: ...
    async def close(self) -> None: ...


async def default_connect(url: str, api_key: str) -> UpstreamWS:
    import websockets

    try:
        return await websockets.connect(url, additional_headers={"Authorization": f"Bearer {api_key}"},
                                        max_size=2**24, open_timeout=5, ping_interval=15)
    except websockets.InvalidStatus as e:
        code = e.response.status_code
        if code in (401, 403):
            raise AuthError(f"realtime socket rejected ({code})", provider="openai", stage="realtime") from None
        if code == 429:
            raise RateLimited("realtime socket rate-limited", provider="openai", stage="realtime") from None
        raise ProviderDisconnected(f"realtime socket HTTP {code}", provider="openai", stage="realtime") from None
    except (OSError, TimeoutError) as e:
        raise ProviderDisconnected(f"connect failed: {type(e).__name__}", provider="openai",
                                   stage="realtime") from None


Connect = Callable[[str, str], Awaitable[UpstreamWS]]
_connect: Connect = default_connect  # monkeypatched in tests


class RelayStart(BaseModel):
    type: str = "relay.start"
    a: str = "en"
    b: str = "es"
    turn_mode: str = "ptt"
    silence_duration_ms: int = 400


def relay_session(start: RelayStart) -> tuple[str, dict]:
    settings = get_settings()
    cfg = settings.app_config()["realtime"]
    model = cfg["model"]
    s = build_interpreter_session(start.a, start.b, model=model, voice=cfg.get("voice", "marin"),
                                  transcription_model=cfg.get("transcription_model", "gpt-4o-transcribe"),
                                  turn_mode="vad" if start.turn_mode == "vad" else "ptt",
                                  silence_duration_ms=start.silence_duration_ms)
    s.pop("model", None)  # not accepted in session.update
    s["audio"]["input"]["format"] = {"type": "audio/pcm", "rate": 24000}
    s["audio"]["output"]["format"] = {"type": "audio/pcm", "rate": 24000}
    return model, s


def _err(code: str, message: str, retryable: bool = False) -> str:
    return json.dumps({"type": "error", "code": code, "stage": "realtime", "retryable": retryable,
                       "message": message[:300]})


@router.websocket("/ws/realtime")
async def relay(ws: WebSocket) -> None:
    await ws.accept()
    settings = get_settings()
    try:
        first = await asyncio.wait_for(ws.receive_text(), timeout=10)
        start = RelayStart.model_validate_json(first)
    except (TimeoutError, ValidationError, WebSocketDisconnect, KeyError):
        with contextlib.suppress(Exception):
            await ws.send_text(_err("bad_message", "expected relay.start"))
            await ws.close()
        return
    if not settings.openai_api_key:
        await ws.send_text(_err("config_error", "OPENAI_API_KEY is not set"))
        await ws.close()
        return
    model, session = relay_session(start)
    try:
        up = await _connect(URL.format(model=model), settings.openai_api_key.get_secret_value())
    except ProviderError as e:
        await ws.send_text(_err(e.code, str(e), retryable=isinstance(e, (RateLimited, ProviderDisconnected))))
        await ws.close()
        return
    await up.send(json.dumps({"type": "session.update", "session": session}))
    responses = 0
    ready = asyncio.Event()

    async def downstream() -> None:
        nonlocal responses
        while True:
            ev = json.loads(await up.recv())
            t = ev.get("type")
            if t == "session.updated" and not ready.is_set():
                ready.set()
                await ws.send_text(json.dumps({"type": "relay.ready", "model": model}))
                continue
            if t == "error" and not ready.is_set():
                await ws.send_text(_err("realtime_session_error", ev.get("error", {}).get("message", "")))
                return
            if t == "response.created":
                responses += 1
            if t == "response.output_audio.delta":
                await ws.send_bytes(pack_audio(responses, base64.b64decode(ev.get("delta", ""))))
                # keep a light marker so the browser can stamp output_audio_first_delta
                ev = {"type": t, "response_id": ev.get("response_id"), "item_id": ev.get("item_id")}
            await ws.send_text(json.dumps(ev))

    async def upstream() -> None:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                return
            if (b := msg.get("bytes")) is not None:
                if ready.is_set():
                    await up.send(json.dumps({"type": "input_audio_buffer.append",
                                              "audio": base64.b64encode(b).decode()}))
                continue
            try:
                m = json.loads(msg.get("text") or "")
            except ValueError:
                await ws.send_text(_err("bad_message", "invalid JSON"))
                continue
            ev = m.get("event") if m.get("type") == "oai" else None
            if not isinstance(ev, dict) or ev.get("type") not in CLIENT_EVENTS:
                await ws.send_text(_err("bad_message", f"unsupported message {m.get('type')}"))
                continue
            await up.send(json.dumps(ev))

    tasks = [asyncio.create_task(downstream()), asyncio.create_task(upstream())]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in done:
            exc = t.exception()
            if exc and not isinstance(exc, WebSocketDisconnect):
                log.warning("realtime relay ended: %s", type(exc).__name__)
                with contextlib.suppress(Exception):
                    await ws.send_text(_err("provider_disconnected", "Realtime upstream closed", retryable=True))
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        with contextlib.suppress(Exception):
            await up.close()
        with contextlib.suppress(Exception):
            await ws.close()
