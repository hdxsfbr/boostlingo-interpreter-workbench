"""M5 benchmark metrics (DESIGN §9): latency, quality, cost, failures.

    python -m eval.metrics --run realtime=../data/m5/realtime.jsonl --run cascade-openai=... \
        --judge --roundtrip --out-dir ../docs/benchmarks/results/m5

Per profile:
- latency: H (last voiced frame -> first audible sample), H minus the fixed
  450 ms PTT release gap (DESIGN A2), and the cascade tail estimate; p50/p90/p95.
- source WER: the mode's own transcript (Realtime side transcription or the
  cascade STT) vs the scripted fixture text; jiwer with Whisper normalizers
  (EN: EnglishTextNormalizer; ES: BasicTextNormalizer keeping diacritics).
- translation quality: corpus chrF (primary) and BLEU (sacrebleu) vs the
  reference translations, per direction. COMET is not computed.
- answered-instead-of-translated: optional LLM judge (--judge, gpt-5.4-mini).
- TTS round trip (--roundtrip): the recorded output audio is transcribed with
  gpt-4o-transcribe and compared with the text the pipeline meant to speak
  (WER), plus duration / loudness sanity from ffmpeg.
- cost per minute of source speech from turn usage x config/pricing.yaml.
- failures: non-"done" rows by reason, split turns, hedges fired/won.

Writes <out-dir>/<date>-<profile>.csv (per utterance), results.json and summary.md.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import statistics
import subprocess
import time
from pathlib import Path

import httpx
import jiwer
import sacrebleu
import yaml
from whisper_normalizer.basic import BasicTextNormalizer
from whisper_normalizer.english import EnglishTextNormalizer

ROOT = Path(__file__).resolve().parents[2]
PRICING = yaml.safe_load((ROOT / "config" / "pricing.yaml").read_text())
UTT = yaml.safe_load((ROOT / "docs" / "benchmarks" / "utterances.yaml").read_text())
TEXT = {u["id"]: u["text"] for lang in ("en", "es") for u in UTT[lang]}
_NORM = {"en": EnglishTextNormalizer(), "es": BasicTextNormalizer(remove_diacritics=False)}
OTHER = {"en": "es", "es": "en"}

# provider makeup per profile name (for cost); unknown names fall back by mode
PROFILES = {
    "realtime": {"realtime": "gpt-realtime"},
    "realtime-mini": {"realtime": "gpt-realtime-mini"},
    "cascade-openai": {"stt": "gpt-live-transcribe", "mt": "gpt-5.4-nano", "tts": "gpt-4o-mini-tts"},
    "cascade-haiku": {"stt": "gpt-live-transcribe", "mt": "anthropic/claude-haiku-5.5", "tts": "gpt-4o-mini-tts"},
    "cascade-elevenlabs": {"stt": "gpt-live-transcribe", "mt": "gpt-5.4-nano", "tts": "elevenlabs-flash"},
}


def norm(text: str, lang: str) -> str:
    return re.sub(r"\s+", " ", _NORM[lang](text or "")).strip()


def wer(ref: str, hyp: str, lang: str) -> float | None:
    r, h = norm(ref, lang), norm(hyp, lang)
    if not r:
        return None
    return jiwer.wer(r, h) if h else 1.0


def pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, round(q * (len(xs) - 1)))]


def clean(text: str) -> str:
    return " ".join((text or "").replace(" / ", " ").split())


# ---------------------------------------------------------------- cost

def row_cost(r: dict, prof: dict) -> float:
    c = 0.0
    p1m = PRICING["per_1m_tokens"]
    for u in r.get("usage") or []:
        if not u:
            continue
        if "realtime" in u and prof.get("realtime"):
            rt, p = u["realtime"] or {}, p1m[prof["realtime"]]
            i, o = rt.get("input_token_details") or {}, rt.get("output_token_details") or {}
            cached = i.get("cached_tokens_details") or {}
            ca, ct = cached.get("audio_tokens", 0), cached.get("text_tokens", 0)
            c += ((i.get("audio_tokens", 0) - ca) * p["audio_in"] + ca * p["audio_cached_in"]
                  + (i.get("text_tokens", 0) - ct) * p["text_in"] + ct * p["text_cached_in"]
                  + o.get("audio_tokens", 0) * p["audio_out"] + o.get("text_tokens", 0) * p["text_out"]) / 1e6
        else:
            c += u.get("stt_audio_s", 0) / 60 * PRICING["per_minute"][prof["stt"]]
            pm = p1m[prof["mt"]]
            c += (u.get("mt_input_tokens", 0) * pm["text_in"] + u.get("mt_output_tokens", 0) * pm["text_out"]) / 1e6
            if prof["tts"] == "elevenlabs-flash":
                c += u.get("tts_chars", 0) / 1000 * PRICING["per_1k_chars"]["elevenlabs-flash"]
            else:
                a, pt = PRICING["assumptions"], p1m[prof["tts"]]
                c += (u.get("tts_chars", 0) / a["chars_per_token"] * pt["text_in"]
                      + u.get("tts_audio_s", 0) * a["tts_audio_tokens_per_s"] * pt["audio_out"]) / 1e6
    if prof.get("realtime"):  # side transcription of the input (not in response usage)
        c += r.get("speech_s", 0) / 60 * PRICING["per_minute"]["gpt-4o-transcribe"]
    return c


# ---------------------------------------------------------------- OpenAI helpers (benchmark only)

def _client() -> httpx.Client:
    return httpx.Client(base_url="https://api.openai.com/v1", timeout=120,
                        headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"})


JUDGE_PROMPT = (
    "You audit a medical/legal speech interpreter between English and Spanish. For each item you get the "
    "speaker's words (source) and the interpreter's output. Label each item:\n"
    '- "translation": the output renders the source in the other language (quality does not matter)\n'
    '- "answered": the output responds to / answers / comments on the source instead of translating it\n'
    '- "other": empty, wrong language, or unrelated\n'
    'Return JSON {"labels": [{"i": <index>, "label": "..."}]} covering every item.')


def judge(rows: list[dict], cache: dict) -> None:
    todo = [r for r in rows if r.get("target") and (r["source"], r["target"]) and
            json.dumps([r["source"], r["target"]]) not in cache]
    for k in range(0, len(todo), 25):
        batch = todo[k:k + 25]
        items = [{"i": i, "source": clean(r["source"]), "output": clean(r["target"])} for i, r in enumerate(batch)]
        with _client() as cl:
            res = cl.post("/responses", json={
                "model": "gpt-5.4-mini", "reasoning": {"effort": "none"},
                "instructions": JUDGE_PROMPT, "input": json.dumps(items, ensure_ascii=False),
                "text": {"format": {"type": "json_object"}}})
            res.raise_for_status()
        out = "".join(c.get("text", "") for o in res.json().get("output", []) for c in o.get("content", []) or [])
        labels = {x["i"]: x["label"] for x in json.loads(out)["labels"]}
        for i, r in enumerate(batch):
            cache[json.dumps([r["source"], r["target"]])] = labels.get(i, "other")
    for r in rows:
        r["judge"] = cache.get(json.dumps([r.get("source"), r.get("target")])) if r.get("target") else "other"


def audio_stats(path: str) -> dict:
    out = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-af", "silencedetect=n=-45dB:d=0.3,volumedetect",
                         "-f", "null", "-"], capture_output=True, text=True, check=False).stderr
    dur = re.search(r"time=(\d+):(\d+):([\d.]+)", out.split("size=")[-1] if "size=" in out else out)
    total = int(dur[1]) * 3600 + int(dur[2]) * 60 + float(dur[3]) if dur else None
    sil = sum(float(x) for x in re.findall(r"silence_duration: ([\d.]+)", out))
    mx = re.search(r"max_volume: ([-\d.]+) dB", out)
    return {"audio_total_s": round(total, 2) if total else None,
            "audio_voiced_s": round(total - sil, 2) if total else None,
            "audio_max_db": float(mx[1]) if mx else None}


def roundtrip(rows: list[dict], cache: dict) -> None:
    for r in rows:
        f = r.get("audio_file")
        if not f or not Path(f).exists():
            continue
        r.update(audio_stats(f))
        tgt = OTHER[r["lang"]]
        if f not in cache:
            with _client() as cl, open(f, "rb") as fh:
                res = cl.post("/audio/transcriptions", data={"model": "gpt-4o-transcribe", "language": tgt},
                              files={"file": (Path(f).name, fh, "audio/webm")})
                res.raise_for_status()
                cache[f] = res.json().get("text", "")
        r["rt_text"] = cache[f]
        r["rt_wer"] = wer(clean(r.get("target", "")), cache[f], tgt)


# ---------------------------------------------------------------- aggregation

def load(path: str) -> list[dict]:
    return [json.loads(line) for line in open(path) if line.strip()]


def per_row(rows: list[dict], prof: dict) -> None:
    for r in rows:
        tgt = OTHER[r["lang"]]
        r["src_wer"] = wer(TEXT[r["id"]], clean(r.get("source", "")), r["lang"]) if r.get("status") == "done" else None
        hyp = clean(r.get("target", ""))
        r["chrf"] = sacrebleu.sentence_chrf(hyp, [r.get("reference", "")]).score if r.get("status") == "done" else None
        r["cost_usd"] = row_cost(r, prof)
        marks = [m or {} for m in (r.get("server_marks_all") or [r.get("server_marks") or {}])]
        r["hedges_fired"] = sum(1 for m in marks for k in m if k.endswith("hedge_fired"))
        r["hedges_won"] = sum(1 for m in marks for k in m if k.endswith("hedge_won"))
        r["norm_tgt"] = norm(hyp, tgt)


def stats(xs: list[float]) -> dict:
    return {"n": len(xs), "p50": round(statistics.median(xs)) if xs else None,
            "p90": round(pct(xs, .9)) if xs else None, "p95": round(pct(xs, .95)) if xs else None}


def aggregate(name: str, rows: list[dict], prof: dict) -> dict:
    done = [r for r in rows if r.get("status") == "done"]

    def lat(key, subset=done):
        return stats([r[key] for r in subset if r.get(key) is not None])

    out: dict = {"profile": name, "providers": prof, "n": len(rows), "done": len(done),
                 "H": lat("H_ms"), "H_minus_gap": lat("H_minus_lag_ms"), "tail": lat("tail_est_ms"),
                 "by_size": {s: {"H": lat("H_ms", [r for r in done if r["size"] == s]),
                                 "H_minus_gap": lat("H_minus_lag_ms", [r for r in done if r["size"] == s])}
                             for s in ("short", "medium", "long")},
                 "quality": {}, "failures": {}}
    for lang in ("en", "es"):
        d = [r for r in done if r["lang"] == lang]
        if not d:
            continue
        hyps = [clean(r.get("target", "")) for r in d]
        refs = [r.get("reference", "") for r in d]
        w = [r["src_wer"] for r in d if r.get("src_wer") is not None]
        src_r = [norm(TEXT[r["id"]], lang) for r in d]
        src_h = [norm(clean(r.get("source", "")), lang) for r in d]
        out["quality"][f"{lang}->{OTHER[lang]}"] = {
            "n": len(d), "chrF": round(sacrebleu.corpus_chrf(hyps, [refs]).score, 1),
            "BLEU": round(sacrebleu.corpus_bleu(hyps, [refs]).score, 1),
            "src_WER_corpus": round(jiwer.wer(src_r, src_h), 3) if all(src_r) else None,
            "src_WER_mean": round(statistics.mean(w), 3) if w else None}
    allh = [clean(r.get("target", "")) for r in done]
    out["quality"]["all"] = {"chrF": round(sacrebleu.corpus_chrf(allh, [[r.get("reference", "") for r in done]]).score, 1)
                             if done else None}
    judged = [r for r in rows if r.get("judge")]
    if judged:
        out["quality"]["answered_rate"] = round(sum(r["judge"] == "answered" for r in judged) / len(judged), 3)
        out["quality"]["judge_other"] = sum(r["judge"] == "other" for r in judged)
    rt = [r for r in rows if r.get("rt_wer") is not None]
    if rt:
        out["roundtrip"] = {"n": len(rt), "wer_mean": round(statistics.mean(r["rt_wer"] for r in rt), 3),
                            "wer_max": round(max(r["rt_wer"] for r in rt), 3),
                            "voiced_s_total": round(sum(r.get("audio_voiced_s") or 0 for r in rt), 1),
                            "max_db": max(r.get("audio_max_db") or -99 for r in rt)}
    reasons: dict[str, int] = {}
    for r in rows:
        if r.get("status") != "done":
            k = f"{r.get('status')}:{r.get('reason') or r.get('error', '')[:40]}"
            reasons[k] = reasons.get(k, 0) + 1
    out["failures"] = {"count": len(rows) - len(done), "rate": round((len(rows) - len(done)) / max(1, len(rows)), 3),
                       "reasons": reasons, "split_turns": sum(1 for r in rows if (r.get("turns") or 1) > 1),
                       "hedges_fired": sum(r["hedges_fired"] for r in rows),
                       "hedges_won": sum(r["hedges_won"] for r in rows)}
    mins = sum(r.get("speech_s", 0) for r in rows) / 60
    cost = sum(r["cost_usd"] for r in rows)
    out["cost"] = {"usd_total": round(cost, 4), "source_min": round(mins, 2),
                   "usd_per_min": round(cost / mins, 4) if mins else None, "pricing_as_of": str(PRICING["as_of"])}
    # Realtime: cost/min over the first ~1 min of speech vs the whole run (history growth)
    acc, c1 = 0.0, 0.0
    for r in rows:
        if acc >= 60:
            break
        acc += r.get("speech_s", 0)
        c1 += r["cost_usd"]
    out["cost"]["usd_per_min_first_1min"] = round(c1 / (acc / 60), 4) if acc else None
    return out


CSV_COLS = ["profile", "id", "lang", "size", "domain", "status", "reason", "turns", "speech_s", "H_ms",
            "H_minus_lag_ms", "tail_est_ms", "src_wer", "chrf", "judge", "rt_wer", "audio_voiced_s", "cost_usd",
            "hedges_fired", "hedges_won", "source", "target", "reference", "rt_text"]


def fmt(v, nd=0):
    return "–" if v is None else (f"{v:.{nd}f}" if isinstance(v, float | int) else str(v))


def summary_md(results: list[dict]) -> str:
    L = ["# M5 benchmark summary (machine-generated by backend/eval/metrics.py)", "",
         ("H = last voiced input frame -> first audible output sample (browser clock). The harness releases PTT "
          "450 ms after the last voiced frame (DESIGN A2), so **H−gap** removes that fixed release gap. "
          "Tail = cascade server estimate for the final segment's first audio (excludes network/playout). "
          "Latencies in ms."), "",
         ("| Profile | n done/total | H p50 | H p90 | H−gap p50 | H−gap p90 | tail p50 | tail p90 | chrF EN→ES | "
          "chrF ES→EN | BLEU EN→ES | BLEU ES→EN | src WER EN | src WER ES | answered | TTS round-trip WER | "
          "$/min | failures |"), "|" + "---|" * 18]
    for r in results:
        q = r["quality"]
        e, s = q.get("en->es", {}), q.get("es->en", {})
        L.append("| " + " | ".join([
            r["profile"], f"{r['done']}/{r['n']}", fmt(r["H"]["p50"]), fmt(r["H"]["p90"]),
            fmt(r["H_minus_gap"]["p50"]), fmt(r["H_minus_gap"]["p90"]), fmt(r["tail"]["p50"]), fmt(r["tail"]["p90"]),
            fmt(e.get("chrF"), 1), fmt(s.get("chrF"), 1), fmt(e.get("BLEU"), 1), fmt(s.get("BLEU"), 1),
            fmt(e.get("src_WER_corpus"), 3), fmt(s.get("src_WER_corpus"), 3),
            fmt(q.get("answered_rate"), 3), fmt((r.get("roundtrip") or {}).get("wer_mean"), 3),
            fmt(r["cost"]["usd_per_min"], 4), f"{r['failures']['count']}"]) + " |")
    L += ["", "## Latency by utterance size (H p50 / H−gap p50)", "",
          "| Profile | short | medium | long |", "|---|---|---|---|"]
    for r in results:
        b = r["by_size"]
        L.append(f"| {r['profile']} | " + " | ".join(
            f"{fmt(b[s]['H']['p50'])} / {fmt(b[s]['H_minus_gap']['p50'])} (n={b[s]['H']['n']})"
            for s in ("short", "medium", "long")) + " |")
    L += ["", "## Failures, splits, hedges, cost detail", "",
          ("| Profile | failures (reason: count) | split turns | hedges fired/won | $ total | source min | "
           "$/min first 1 min |"), "|---|---|---|---|---|---|---|"]
    for r in results:
        f = r["failures"]
        reasons = ", ".join(f"{k}: {v}" for k, v in f["reasons"].items()) or "none"
        L.append(f"| {r['profile']} | {reasons} | {f['split_turns']} | {f['hedges_fired']}/{f['hedges_won']} | "
                 f"{r['cost']['usd_total']:.4f} | {r['cost']['source_min']} | {fmt(r['cost']['usd_per_min_first_1min'], 4)} |")
    L += ["", (f"Pricing: config/pricing.yaml (as of {PRICING['as_of']}). Cost per minute of *source speech* "
               "(voiced span of the fixtures). gpt-4o-mini-tts audio is estimated at 20 audio tokens/s; ElevenLabs is "
               "shown at list price although the free tier bills credits. Realtime includes the side transcription "
               "(gpt-4o-transcribe, estimate)."), ""]
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="append", required=True, help="profile=path.jsonl (repeatable)")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--judge", action="store_true", help="LLM judge for answered-instead-of-translated (OpenAI)")
    ap.add_argument("--roundtrip", action="store_true", help="transcribe recorded output audio (OpenAI)")
    ap.add_argument("--cache", default=str(ROOT / "data" / "m5" / "metrics_cache.json"))
    a = ap.parse_args()
    cache_p = Path(a.cache)
    cache = json.loads(cache_p.read_text()) if cache_p.exists() else {"judge": {}, "rt": {}}
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    date = time.strftime("%Y-%m-%d")
    results = []
    for spec in a.run:
        name, path = spec.split("=", 1)
        rows = load(path)
        prof = PROFILES.get(name) or PROFILES["realtime-mini" if "realtime" in name else "cascade-openai"]
        per_row(rows, prof)
        if a.judge:
            judge(rows, cache["judge"])
        if a.roundtrip:
            roundtrip(rows, cache["rt"])
        cache_p.parent.mkdir(parents=True, exist_ok=True)
        cache_p.write_text(json.dumps(cache, ensure_ascii=False, indent=1))
        with open(out / f"{date}-{name}.csv", "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=CSV_COLS, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow({**r, "profile": name})
        results.append(aggregate(name, rows, prof))
        print(json.dumps({k: results[-1][k] for k in ("profile", "H", "H_minus_gap", "quality", "cost", "failures")},
                         ensure_ascii=False))
    (out / "results.json").write_text(json.dumps({"generated": date, "profiles": results}, ensure_ascii=False, indent=1))
    (out / "summary.md").write_text(summary_md(results))
    print("wrote", out / "results.json", out / "summary.md")


if __name__ == "__main__":
    main()
