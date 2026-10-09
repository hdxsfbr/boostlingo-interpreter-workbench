"""The InterpreterSession event contract (server side).

Mirrors `frontend/src/session/protocol.ts`. Both sides validate the shared
fixtures in `contract/fixtures/` so the contract cannot drift silently.

Server->client events are JSON text frames. Translated audio goes down as
binary frames: a 4-byte little-endian uint32 `turn_id` header followed by
PCM16 mono 24 kHz little-endian samples.
"""
from __future__ import annotations

import struct
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

Lang = str  # ISO 639-1 code from config/languages.yaml
SAMPLE_RATE = 24_000
AUDIO_HEADER = struct.Struct("<I")


class _Event(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------- server -> client ----------
class TurnStarted(_Event):
    type: Literal["turn.started"] = "turn.started"
    turn_id: int
    src: Lang
    tgt: Lang


class TranscriptEvent(_Event):
    type: Literal["transcript.partial", "transcript.final"]
    turn_id: int
    seg: int
    text: str


class TranslationEvent(_Event):
    type: Literal["translation.partial", "translation.final"]
    turn_id: int
    seg: int
    text: str


class LatencyMark(_Event):
    """Server stage mark. `ms` is a duration on the server's monotonic clock,
    measured from the turn's final commit being received (NFR-5: never
    compared directly with browser timestamps)."""

    type: Literal["latency.mark"] = "latency.mark"
    turn_id: int
    mark: str
    ms: float


class TurnDone(_Event):
    type: Literal["turn.done"] = "turn.done"
    turn_id: int
    marks: dict[str, float] = Field(default_factory=dict)
    usage: dict[str, Any] = Field(default_factory=dict)
    recording: dict[str, str] | None = None  # A11: relative paths of the saved source/target audio


class TurnSkipped(_Event):
    type: Literal["turn.skipped"] = "turn.skipped"
    turn_id: int
    reason: str


class ErrorEvent(_Event):
    type: Literal["error"] = "error"
    code: str
    stage: str
    retryable: bool
    message: str
    turn_id: int | None = None


class SessionReady(_Event):
    type: Literal["session.ready"] = "session.ready"
    pipeline: str
    providers: dict[str, str] = Field(default_factory=dict)


class Pong(_Event):
    type: Literal["pong"] = "pong"
    t: float | None = None


ServerEvent = Annotated[
    TurnStarted | TranscriptEvent | TranslationEvent | LatencyMark | TurnDone | TurnSkipped | ErrorEvent | SessionReady | Pong,
    Field(discriminator="type"),
]
server_event_adapter: TypeAdapter[ServerEvent] = TypeAdapter(ServerEvent)


# ---------- client -> server ----------
class SessionStart(_Event):
    type: Literal["session.start"] = "session.start"
    pipeline: Literal["loopback", "cascade"] = "cascade"
    src: Lang | None = None  # None = default pair from config/languages.yaml
    tgt: Lang | None = None
    turn_mode: Literal["ptt", "vad"] = "ptt"
    providers: dict[str, str] = Field(default_factory=dict)
    session_id: str | None = Field(default=None, max_length=80)
    record: bool = False  # A11: per-session opt-in; refused unless recording.enabled


class TurnStart(_Event):
    type: Literal["turn.start"] = "turn.start"
    turn_id: int
    src: Lang
    tgt: Lang


class Commit(_Event):
    """`final=True` at PTT release / VAD end of turn; `final=False` at an
    in-turn pause (yields an extra segment)."""

    type: Literal["commit"] = "commit"
    turn_id: int
    final: bool = True


class TurnCancel(_Event):
    type: Literal["turn.cancel"] = "turn.cancel"
    turn_id: int


class Ping(_Event):
    type: Literal["ping"] = "ping"
    t: float | None = None


class PauseHint(_Event):
    """Browser VAD saw a short in-turn silence (before the pause commit): the
    cascade may start speculative MT on the current partial (M4)."""

    type: Literal["pause.hint"] = "pause.hint"
    turn_id: int


ClientMessage = Annotated[
    SessionStart | TurnStart | Commit | TurnCancel | Ping | PauseHint, Field(discriminator="type")
]
client_message_adapter: TypeAdapter[ClientMessage] = TypeAdapter(ClientMessage)


def pack_audio(turn_id: int, pcm: bytes) -> bytes:
    return AUDIO_HEADER.pack(turn_id) + pcm


def unpack_audio(frame: bytes) -> tuple[int, bytes]:
    (turn_id,) = AUDIO_HEADER.unpack_from(frame)
    return turn_id, frame[AUDIO_HEADER.size:]
