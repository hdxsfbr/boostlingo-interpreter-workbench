"""Provider interfaces (CQ-2). The cascade orchestrator imports ONLY these.

Audio everywhere is PCM16 mono 24 kHz little-endian bytes.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Commit:
    """End of a segment: PTT release (final=True) or in-turn pause (final=False)."""

    final: bool = True


@dataclass
class TranscriptEvent:
    seg: int
    text: str
    final: bool
    audio_s: float = 0.0  # billed audio seconds, on finals when the provider reports it


@dataclass
class TurnContext:
    """Recent turns for pronoun/gender consistency plus the pair glossary."""

    history: list[tuple[str, str]] = field(default_factory=list)  # (source, translation)
    glossary: dict[str, str] = field(default_factory=dict)


@dataclass
class Usage:
    stt_audio_s: float = 0.0
    mt_input_tokens: int = 0
    mt_output_tokens: int = 0
    tts_chars: int = 0

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


@runtime_checkable
class STTProvider(Protocol):
    name: str

    async def open(self) -> None:
        """Warm up (e.g. connect the realtime transcription socket)."""

    def stream(self, audio: AsyncIterator[bytes | Commit], langs: list[str]) -> AsyncIterator[TranscriptEvent]:
        """Consume audio + commits for ONE turn; yield partials and one final per committed segment.
        Ends after the final for the Commit(final=True) segment."""

    async def aclose(self) -> None: ...


@runtime_checkable
class Translator(Protocol):
    name: str
    last_usage: Usage

    def stream(self, text: str, src: str, tgt: str, ctx: TurnContext) -> AsyncIterator[str]:
        """Yield translated text tokens/deltas as they are generated."""


@runtime_checkable
class TTSProvider(Protocol):
    name: str

    def stream(self, chunks: AsyncIterator[str], lang: str, voice: str) -> AsyncIterator[bytes]:
        """Sentence chunks in, PCM16 24 kHz out, strictly in chunk order."""
