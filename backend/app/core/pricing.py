"""One pricing module (A20): config/pricing.yaml -> USD, shared by the M5/Experiments
metrics (eval/metrics.py row_cost) and per-stage Langfuse cost (app/observability)."""
from __future__ import annotations

from pathlib import Path

import yaml

PRICING: dict = yaml.safe_load((Path(__file__).resolve().parents[3] / "config" / "pricing.yaml").read_text())
PRICE_KEY = {"eleven_flash_v2_5": "elevenlabs-flash"}  # app.yaml model id -> pricing.yaml key
SIDE_TRANSCRIBER = "gpt-4o-transcribe"


def realtime_cost(rt: dict, model: str) -> float:
    p = PRICING["per_1m_tokens"][model]
    i, o = rt.get("input_token_details") or {}, rt.get("output_token_details") or {}
    cd = i.get("cached_tokens_details") or {}
    ca, ct = cd.get("audio_tokens", 0), cd.get("text_tokens", 0)
    return ((i.get("audio_tokens", 0) - ca) * p["audio_in"] + ca * p["audio_cached_in"]
            + (i.get("text_tokens", 0) - ct) * p["text_in"] + ct * p["text_cached_in"]
            + o.get("audio_tokens", 0) * p["audio_out"] + o.get("text_tokens", 0) * p["text_out"]) / 1e6


def side_transcription_cost(speech_s: float) -> float:
    """Realtime's input transcription (not in response usage), billed on the streamed audio."""
    return speech_s / 60 * PRICING["per_minute"][SIDE_TRANSCRIBER]


def stt_cost(u: dict, model: str) -> float:
    return u.get("stt_audio_s", 0) / 60 * PRICING["per_minute"][model]


def mt_cost(u: dict, model: str) -> float:
    pm = PRICING["per_1m_tokens"][model]
    return (u.get("mt_input_tokens", 0) * pm["text_in"] + u.get("mt_output_tokens", 0) * pm["text_out"]) / 1e6


def tts_cost(u: dict, model: str) -> float:
    model = PRICE_KEY.get(model, model)
    if model == "elevenlabs-flash":
        return u.get("tts_chars", 0) / 1000 * PRICING["per_1k_chars"]["elevenlabs-flash"]
    a, pt = PRICING["assumptions"], PRICING["per_1m_tokens"][model]
    return (u.get("tts_chars", 0) / a["chars_per_token"] * pt["text_in"]
            + u.get("tts_audio_s", 0) * a["tts_audio_tokens_per_s"] * pt["audio_out"]) / 1e6


def row_cost(r: dict, prof: dict) -> float:
    """A harness row (usage list per turn) priced for a setup profile (M5 / Experiments)."""
    c = 0.0
    for u in r.get("usage") or []:
        if not u:
            continue
        if "realtime" in u and prof.get("realtime"):
            c += realtime_cost(u["realtime"] or {}, prof["realtime"])
        else:
            c += stt_cost(u, prof["stt"]) + mt_cost(u, prof["mt"]) + tts_cost(u, prof["tts"])
    if prof.get("realtime"):
        c += side_transcription_cost(r.get("speech_s", 0))
    return c


def stage_costs(usage: dict, models: dict[str, str], speech_s: float | None = None) -> dict[str, float]:
    """One live turn, per stage: {"realtime", "transcription"} or {"stt", "mt", "tts"}. Unknown models are skipped."""
    p1m, pm = PRICING["per_1m_tokens"], PRICING["per_minute"]
    usage, out = usage or {}, {}
    if "realtime" in usage:
        if models.get("realtime") in p1m:
            out["realtime"] = realtime_cost(usage["realtime"] or {}, models["realtime"])
        if speech_s:
            out["transcription"] = side_transcription_cost(speech_s)
        return out
    if models.get("stt") in pm:
        out["stt"] = stt_cost(usage, models["stt"])
    if models.get("mt") in p1m:
        out["mt"] = mt_cost(usage, models["mt"])
    if PRICE_KEY.get(models.get("tts", ""), models.get("tts", "")) in ({"elevenlabs-flash"} | set(p1m)):
        out["tts"] = tts_cost(usage, models["tts"])
    return out
