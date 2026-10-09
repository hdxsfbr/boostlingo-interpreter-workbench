"""Blind-rating materials (PRD D3 / DESIGN §9): anonymised output clips per
utterance x profile, a rating sheet and a separate key.

    python -m eval.blind --run realtime=../data/m5/realtime.jsonl ... --ids en-s01,... \
        --out ../docs/benchmarks/blind

Clips are the recorded output audio (what the listener heard), trimmed of
leading/trailing silence and re-encoded to Opus. Clip numbers are shuffled
with a fixed seed so raters cannot infer the profile from order.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
UTT = yaml.safe_load((ROOT / "docs" / "benchmarks" / "utterances.yaml").read_text())
BY_ID = {u["id"]: {**u, "lang": lang} for lang in ("en", "es") for u in UTT[lang]}

README = """# Blind rating kit (M5)

{n} clips: {n_utt} utterances x {n_prof} interpreter profiles, shuffled. Each clip is the
interpreter's spoken output for one source utterance, exactly as the listener heard it
(leading/trailing silence trimmed).

How to rate (per clip, 1 = very poor, 5 = excellent):
- **Adequacy**: does the audio convey the full meaning of the source text (numbers, names, negations)?
- **Fluency**: is it grammatical, natural target-language speech?
- **Naturalness**: does the voice sound natural (prosody, pronunciation, no glitches)?

Use `rating_sheet.csv` (source text and direction are given; the reference translation is
one acceptable rendering, not the only one). Do **not** open `key.csv` until all ratings
are in. Report the number of raters honestly (DESIGN D3); one rater is a smoke test, not a
statistically meaningful result.
"""


def trim(src: str, dst: Path) -> None:
    flt = ("silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,"
           "areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.15,areverse")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-af", flt, "-ac", "1", "-c:a", "libopus",
                    "-b:a", "32k", str(dst)], check=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="append", required=True, help="profile=path.jsonl")
    ap.add_argument("--ids", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=20261011)
    a = ap.parse_args()
    ids = a.ids.split(",")
    clips = []
    for spec in a.run:
        name, path = spec.split("=", 1)
        rows = {}
        for line in open(path):  # noqa: SIM115
            r = json.loads(line)
            if r.get("audio_file") and r["id"] in ids and r["id"] not in rows and r.get("status") == "done":
                rows[r["id"]] = r
        for uid in ids:
            if uid in rows:
                clips.append((name, uid, rows[uid]["audio_file"]))
            else:
                print(f"missing clip: {name} {uid}")
    random.Random(a.seed).shuffle(clips)
    out = Path(a.out)
    (out / "clips").mkdir(parents=True, exist_ok=True)
    sheet, key = [], []
    for i, (name, uid, f) in enumerate(clips, 1):
        clip = f"clip_{i:03d}.ogg"
        trim(f, out / "clips" / clip)
        u = BY_ID[uid]
        sheet.append({"clip": clip, "direction": f"{u['lang']}->{'es' if u['lang'] == 'en' else 'en'}",
                      "source_text": u["text"], "reference_translation": u["reference_translation"],
                      "adequacy_1_5": "", "fluency_1_5": "", "naturalness_1_5": "", "notes": ""})
        key.append({"clip": clip, "profile": name, "utterance_id": uid})
    for fn, rows in (("rating_sheet.csv", sheet), ("key.csv", key)):
        with open(out / fn, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    profs = {c[0] for c in clips}
    (out / "README.md").write_text(README.format(n=len(clips), n_utt=len(ids), n_prof=len(profs)))
    print(f"wrote {len(clips)} clips to {out}")


if __name__ == "__main__":
    main()
