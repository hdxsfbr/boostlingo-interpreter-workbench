"""Measure TTS time-to-first-audible-byte for cascade tuning (M4).
Warm keep-alive client, interleaved variants, ES and EN texts of different
lengths. First *audible* byte = after the adapter's leading-silence trim.
Keys from the environment (source ../.env); never printed.

    set -a; source ../.env; set +a
    python -m eval.tts_ttfb --rounds 3
"""
from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import time

from app.providers.common.http import shared_client
from app.providers.tts.openai import OpenAITTS

TEXTS = [
    ("es", "He tenido dolor de cabeza"),
    ("es", "He tenido dolor de cabeza durante tres días."),
    ("en", "My chest hurts"),
    ("en", "My chest hurts when I take a deep breath."),
]


class Variant(OpenAITTS):
    def __init__(self, label: str, model: str, instructions: bool, **kw) -> None:
        super().__init__(os.environ["OPENAI_API_KEY"], model=model, **kw)
        self.label, self.with_instructions = label, instructions

    def _body(self, text, lang, voice):
        b = super()._body(text, lang, voice)
        if not self.with_instructions:
            b.pop("instructions", None)
        if self.model.startswith("tts-1"):
            b.pop("instructions", None)
            b.pop("stream_format", None)
        return b


async def ttfb(v: Variant, lang: str, text: str, voice: str) -> float:
    async def one():
        yield text
    t0 = time.perf_counter()
    async for pcm in v.stream(one(), lang, voice):
        if pcm:
            return (time.perf_counter() - t0) * 1000
    return float("nan")


async def main(a) -> None:
    variants = [Variant("mini-tts+instr (current)", "gpt-4o-mini-tts", True),
                Variant("mini-tts no instr", "gpt-4o-mini-tts", False),
                Variant("tts-1", "tts-1", False)]
    await shared_client().get("https://api.openai.com/v1/models",
                              headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"})
    res: dict[tuple[str, str], list[float]] = {}
    for _ in range(a.rounds):
        for lang, text in TEXTS:
            for v in variants:
                voice = "alloy" if v.model.startswith("tts-1") else "marin"
                res.setdefault((v.label, f"{lang}:{len(text)}"), []).append(await ttfb(v, lang, text, voice))
    print("| variant | text | n | p50 ms | min | max |\n|---|---|---|---|---|---|")
    for (lab, t), xs in res.items():
        print(f"| {lab} | {t} | {len(xs)} | {statistics.median(xs):.0f} | {min(xs):.0f} | {max(xs):.0f} |")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=3)
    asyncio.run(main(ap.parse_args()))
