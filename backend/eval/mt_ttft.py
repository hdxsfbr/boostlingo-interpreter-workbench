"""Measure translator time-to-first-token (TTFT) to pick the cascade MT
default (DESIGN D4 / M1 exit). Warm keep-alive client, interleaved models,
both directions. Prints a markdown table; keys come from the environment.

    set -a; source ../.env; set +a
    python -m eval.mt_ttft --models gpt-6-luna gpt-5.4-nano gpt-4.1-nano --rounds 2
"""
from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import time

from app.providers.base import TurnContext
from app.providers.common.http import shared_client
from app.providers.mt.openai import OpenAITranslator

UTTERANCES = [
    ("en", "es", "Good morning, doctor."),
    ("en", "es", "I have had a headache for three days and I took two tablets of ibuprofen."),
    ("en", "es", "Please sign here and bring your insurance card next time."),
    ("en", "es", "Is the pain sharp or dull, and does it get worse at night?"),
    ("en", "es", "Your next hearing is on March fifteenth at nine thirty in the morning."),
    ("es", "en", "Buenos días, ¿cómo se siente hoy?"),
    ("es", "en", "Me duele el pecho cuando respiro profundo."),
    ("es", "en", "Tomo metformina de quinientos miligramos dos veces al día."),
    ("es", "en", "No entiendo la pregunta, ¿me la puede repetir más despacio?"),
    ("es", "en", "Mi hijo tiene fiebre desde anoche y no quiere comer."),
]
NON_REASONING = {"gpt-4.1-nano", "gpt-4.1-mini"}


async def one(mt: OpenAITranslator, src: str, tgt: str, text: str) -> tuple[float, float, str]:
    t0 = time.perf_counter()
    first, out = None, ""
    async for tok in mt.stream(text, src, tgt, TurnContext()):
        if first is None:
            first = time.perf_counter() - t0
        out += tok
    return (first or 0) * 1000, (time.perf_counter() - t0) * 1000, out


async def main(models: list[str], rounds: int) -> None:
    key = os.environ["OPENAI_API_KEY"]
    mts = {m: OpenAITranslator(key, m, reasoning_effort=None if m in NON_REASONING else "none") for m in models}
    for mt in mts.values():
        await mt.warm()
    res: dict[str, list[tuple[float, float]]] = {m: [] for m in models}
    samples: dict[str, list[str]] = {m: [] for m in models}
    for _ in range(rounds):
        for src, tgt, text in UTTERANCES:
            for m, mt in mts.items():
                ttft, total, out = await one(mt, src, tgt, text)
                res[m].append((ttft, total))
                if len(samples[m]) < 3:
                    samples[m].append(f"{text} -> {out}")
    q = lambda xs, p: statistics.quantiles(xs, n=10)[8] if p == 90 else statistics.median(xs)
    print("| model | n | TTFT p50 ms | TTFT p90 ms | total p50 ms |\n|---|---|---|---|---|")
    for m in models:
        tt = [r[0] for r in res[m]]
        tot = [r[1] for r in res[m]]
        print(f"| `{m}` | {len(tt)} | {q(tt, 50):.0f} | {q(tt, 90):.0f} | {q(tot, 50):.0f} |")
    print()
    for m in models:
        for s in samples[m]:
            print(f"- `{m}`: {s}")
    await shared_client().aclose()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=["gpt-6-luna", "gpt-5.4-nano"])
    ap.add_argument("--rounds", type=int, default=2)
    a = ap.parse_args()
    asyncio.run(main(a.models, a.rounds))
