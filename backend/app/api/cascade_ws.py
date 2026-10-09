"""WS /ws/cascade: the cascade gateway.

One WebSocket per browser session. Text frames carry the JSON contract
(app.core.events); binary uplink frames are raw PCM16 mono 24 kHz for the
current turn; binary downlink frames carry a turn_id header + PCM16.

The gateway is transport only. What happens to a turn's audio is decided by
a `TurnPipeline` (loopback for the M0 transport floor, the real cascade from
M1), so the transport and the pipeline evolve independently.
"""
from __future__ import annotations

import array
import asyncio
import logging
import math
import time
from typing import Protocol

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ValidationError

from app.core.events import (
    Commit,
    ErrorEvent,
    LatencyMark,
    Ping,
    Pong,
    SessionReady,
    SessionStart,
    TurnCancel,
    TurnDone,
    TurnStart,
    TurnStarted,
    client_message_adapter,
    pack_audio,
)

log = logging.getLogger(__name__)
router = APIRouter()


class SessionIO:
    """Serialises all sends on one socket (events and audio may come from
    several concurrent stage tasks)."""

    def __init__(self, ws: WebSocket) -> None:
        self._ws = ws
        self._lock = asyncio.Lock()
        self.closed = False

    async def event(self, ev: BaseModel) -> None:
        if self.closed:
            return
        async with self._lock:
            await self._ws.send_text(ev.model_dump_json())

    async def audio(self, turn_id: int, pcm: bytes) -> None:
        if self.closed or not pcm:
            return
        async with self._lock:
            await self._ws.send_bytes(pack_audio(turn_id, pcm))


class TurnPipeline(Protocol):
    name: str

    def providers(self) -> dict[str, str]: ...
    async def turn_start(self, msg: TurnStart) -> None: ...
    async def audio(self, pcm: bytes) -> None: ...
    async def commit(self, msg: Commit) -> None: ...
    async def cancel(self, turn_id: int) -> None: ...
    async def close(self) -> None: ...


class LoopbackPipeline:
    """M0: echoes each turn's audio back after the final commit. Measures the
    transport + playout floor (no providers involved)."""

    name = "loopback"
    CHUNK = 960  # 20 ms of PCM16 @ 24 kHz

    def __init__(self, io: SessionIO) -> None:
        self.io = io
        self.turn_id: int | None = None
        self.buf = bytearray()

    def providers(self) -> dict[str, str]:
        return {"stt": "none", "mt": "none", "tts": "loopback"}

    async def turn_start(self, msg: TurnStart) -> None:
        self.turn_id, self.buf = msg.turn_id, bytearray()
        await self.io.event(TurnStarted(turn_id=msg.turn_id, src=msg.src, tgt=msg.tgt))

    async def audio(self, pcm: bytes) -> None:
        if self.turn_id is not None:
            self.buf.extend(pcm)

    async def commit(self, msg: Commit) -> None:
        if not msg.final or msg.turn_id != self.turn_id:
            return
        t0 = time.monotonic()
        data, self.buf = trim_leading_silence(bytes(self.buf)), bytearray()
        for i in range(0, len(data), self.CHUNK):
            await self.io.audio(msg.turn_id, data[i:i + self.CHUNK])
            if i == 0:
                await self.io.event(LatencyMark(turn_id=msg.turn_id, mark="audio_first_sent",
                                                ms=(time.monotonic() - t0) * 1000))
        await self.io.event(TurnDone(turn_id=msg.turn_id, usage={"loopback_audio_s": len(data) / 48000}))

    async def cancel(self, turn_id: int) -> None:
        if turn_id == self.turn_id:
            self.buf = bytearray()

    async def close(self) -> None:
        self.buf = bytearray()


def frame_rms(pcm: bytes) -> float:
    a = array.array("h", pcm[: len(pcm) // 2 * 2])
    return math.sqrt(sum(x * x for x in a) / len(a)) / 32768 if a else 0.0


def trim_leading_silence(pcm: bytes, threshold: float = 0.01, chunk: int = 960) -> bytes:
    """Drop the pre-speech silence of a turn so the loopback measures the
    transport + playout floor, not how long the user waited before talking."""
    for i in range(0, len(pcm), chunk):
        if frame_rms(pcm[i:i + chunk]) >= threshold:
            return pcm[i:]
    return b""


def build_pipeline(start: SessionStart, io: SessionIO) -> TurnPipeline:
    if start.pipeline == "loopback":
        return LoopbackPipeline(io)
    from app.cascade.ws_pipeline import CascadePipeline  # M1

    return CascadePipeline.from_settings(start, io)


@router.websocket("/ws/cascade")
async def cascade_ws(ws: WebSocket) -> None:
    await ws.accept()
    io = SessionIO(ws)
    pipeline: TurnPipeline | None = None
    try:
        while True:
            frame = await ws.receive()
            if frame["type"] == "websocket.disconnect":
                break
            if (data := frame.get("bytes")) is not None:
                if pipeline is not None:
                    await pipeline.audio(data)
                continue
            try:
                msg = client_message_adapter.validate_json(frame.get("text") or "")
            except ValidationError as exc:
                await io.event(ErrorEvent(code="bad_message", stage="gateway", retryable=False,
                                          message=str(exc.errors()[:1])))
                continue
            if isinstance(msg, SessionStart):
                if pipeline is not None:
                    await pipeline.close()
                try:
                    pipeline = build_pipeline(msg, io)
                except Exception as exc:  # config/auth problems surface to the UI
                    log.warning("pipeline init failed: %s", type(exc).__name__)
                    await io.event(ErrorEvent(code="config_error", stage="gateway", retryable=False,
                                              message=str(exc)))
                    continue
                await io.event(SessionReady(pipeline=pipeline.name, providers=pipeline.providers()))
            elif isinstance(msg, Ping):
                await io.event(Pong(t=msg.t))
            elif pipeline is None:
                await io.event(ErrorEvent(code="no_session", stage="gateway", retryable=False,
                                          message="send session.start first"))
            elif isinstance(msg, TurnStart):
                await pipeline.turn_start(msg)
            elif isinstance(msg, Commit):
                await pipeline.commit(msg)
            elif isinstance(msg, TurnCancel):
                await pipeline.cancel(msg.turn_id)
    except WebSocketDisconnect:
        pass
    finally:
        io.closed = True
        if pipeline is not None:
            await pipeline.close()
