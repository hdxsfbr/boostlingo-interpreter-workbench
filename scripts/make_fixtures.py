"""Synthesize benchmark fixtures from docs/benchmarks/utterances.yaml (DESIGN §9).

Writes data/fixtures/<id>.wav (24 kHz mono PCM16, gitignored) with OpenAI TTS
voices that differ from the pipeline voice (marin), alternating two voices per
language so the set is not one speaker. Existing files are skipped, so re-runs
cost nothing. Needs OPENAI_API_KEY in the environment (`set -a; source .env`).
Never prints the key.

    python scripts/make_fixtures.py [--only en-s01,es-m02] [--force]
"""

from __future__ import annotations

import argparse
import os
import sys
import wave
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
VOICES = {"en": ["ash", "sage"], "es": ["coral", "verse"]}
STYLE = {
    "en": "Speak naturally at a normal conversational pace, like a clinician or court clerk talking to a client.",
    "es": "Habla en español latinoamericano, con naturalidad y a un ritmo de conversación normal, como un paciente o un cliente.",
}
LEAD_SILENCE_MS = 150
RATE = 24000


def synth(client: httpx.Client, text: str, voice: str, lang: str) -> bytes:
    r = client.post(
        "https://api.openai.com/v1/audio/speech",
        json={"model": "gpt-4o-mini-tts", "voice": voice, "input": text, "instructions": STYLE[lang], "response_format": "pcm"},
    )
    if r.status_code != 200:
        raise SystemExit(f"TTS failed for {text[:30]!r}: HTTP {r.status_code}")
    return r.content


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "data" / "fixtures"))
    args = ap.parse_args()
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        print("OPENAI_API_KEY is not set (run: set -a; source .env; set +a)", file=sys.stderr)
        return 2
    only = {s for s in args.only.split(",") if s}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    data = yaml.safe_load((ROOT / "docs" / "benchmarks" / "utterances.yaml").read_text())
    made = 0
    with httpx.Client(headers={"Authorization": f"Bearer {key}"}, timeout=60) as client:
        for lang, items in data.items():
            for i, u in enumerate(items):
                if only and u["id"] not in only:
                    continue
                path = out / f"{u['id']}.wav"
                if path.exists() and not args.force:
                    continue
                pcm = synth(client, u["text"], VOICES[lang][i % 2], lang)
                lead = b"\x00\x00" * (RATE * LEAD_SILENCE_MS // 1000)
                with wave.open(str(path), "wb") as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(RATE)
                    w.writeframes(lead + pcm)
                made += 1
                print(f"{u['id']}: {len(pcm) / 2 / RATE:.2f}s ({VOICES[lang][i % 2]})")
    print(f"made {made} fixture(s) in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
