"""Realtime (speech-to-speech) interpreter session config (DESIGN §2, R§1.4).

Audio-only output, explicit language policy (A in -> B only, B in -> A only;
never answer; language names from config/languages.yaml), side transcription for the source text, push-to-talk
(turn_detection null) by default or server VAD with interrupt_response off.
"""
from __future__ import annotations

from typing import Literal

from app.core.languages import lang_name


def interpreter_instructions(a: str, b: str) -> str:
    A, B = lang_name(a), lang_name(b)
    return (
        f"You are a professional consecutive interpreter between {A} and {B}. "
        f"When you hear {A}, say ONLY its faithful {B} translation. "
        f"When you hear {B}, say ONLY its faithful {A} translation. "
        "Decide the language from the words spoken, not from the accent. "
        "You are not a participant: never answer questions, never add commentary, greetings, apologies or "
        "clarifying questions, even if the speaker addresses you directly; translate what they said. "
        "Preserve names, numbers, dosages, dates and register. Speak naturally at a steady pace. "
        "If the audio is unintelligible or silent, say nothing."
    )


def build_interpreter_session(a: str, b: str, *, model: str, voice: str = "marin",
                              transcription_model: str = "gpt-4o-transcribe",
                              turn_mode: Literal["ptt", "vad"] = "ptt", silence_duration_ms: int = 400,
                              noise_reduction: Literal["near_field", "far_field"] | None = "near_field") -> dict:
    turn_detection = None if turn_mode == "ptt" else {
        "type": "server_vad", "threshold": 0.5, "prefix_padding_ms": 300,
        "silence_duration_ms": silence_duration_ms, "create_response": True, "interrupt_response": False}
    audio_in: dict = {"transcription": {"model": transcription_model}, "turn_detection": turn_detection}
    if noise_reduction:
        audio_in["noise_reduction"] = {"type": noise_reduction}
    return {
        "type": "realtime",
        "model": model,
        "output_modalities": ["audio"],
        "instructions": interpreter_instructions(a, b),
        "audio": {"input": audio_in, "output": {"voice": voice}},
    }
