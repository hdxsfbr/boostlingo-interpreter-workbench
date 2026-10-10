"""A20: build Langfuse events from data the app already has.

Live sessions: the browser's finished-turn record (POST /api/turns, the same record the
UI and the JSONL log use), so every number matches the Latency card exactly:
  trace  = one per interpreter session (id derived from the session id, upserted per turn)
  span   = one per turn (all raw browser + server marks in metadata)
  children = STT / MT / TTS generations + playback span (cascade), one realtime generation
Times are on the speech-end clock (DESIGN A18): child start/end = speech end + mark ms, so
an early (pre-speech-end) stage starts before the turn's speech end, flagged `early`.

Experiments: one trace per utterance per setup, sessionId = "exp-<id>", with WER/chrF/H as
scores. Review: one trace per rated clip, one score per dimension.
"""
from __future__ import annotations

import hashlib
import time
import uuid
from functools import lru_cache
from typing import Any

from app.core import pricing
from app.observability.client import Langfuse, iso

NS = uuid.UUID("6f1d2a8e-6b9e-4f7e-9a39-6c1b0f4a2b11")


def tid(*parts: str) -> str:
    return str(uuid.uuid5(NS, "/".join(parts)))


@lru_cache
def prompt_version() -> str:
    """Short hash of the MT instructions + the Realtime instruction template."""
    from app.providers.mt.openai import INSTRUCTIONS
    from app.realtime.session_config import interpreter_instructions
    h = hashlib.sha256((INSTRUCTIONS + "\n--\n" + interpreter_instructions("en", "es")).encode()).hexdigest()
    return h[:10]


def models_for(providers: dict[str, str]) -> dict[str, str]:
    """Provider names (session.ready) -> model ids from config/app.yaml."""
    from app.core.config import get_settings
    p = get_settings().app_config()["providers"]
    stt = {"openai_live": p["openai_live"]["model"]}
    mt = {"openai": p["openai"]["model"], "anthropic": p["anthropic"]["model"], "openrouter": p.get("openrouter", {}).get("model", "")}
    tts = {"openai": p["openai_tts"]["model"], "elevenlabs": p["elevenlabs"]["model"]}
    out = {}
    for k, table in (("stt", stt), ("mt", mt), ("tts", tts)):
        if providers.get(k):
            out[k] = table.get(providers[k], providers[k])
    if providers.get("realtime"):
        out["realtime"] = providers["realtime"]
    return out


def stage_costs(usage: dict, models: dict[str, str], speech_s: float | None = None) -> dict[str, float]:
    return pricing.stage_costs(usage, models, speech_s)


def _stage(rec: dict, mark: str) -> float | None:
    """Same formula as the UI's stageMs (A18): browser commit_sent + server duration."""
    c, v = (rec.get("browser_marks") or {}).get("commit_sent"), (rec.get("server_marks") or {}).get(mark)
    return None if c is None or v is None else c + v


def turn_events(lf: Langfuse, session_id: str, rec: dict, meta: dict | None, received_at: float | None = None) -> None:
    """Emit the trace upsert, the turn span and its stage children for one finished turn."""
    if not lf.enabled:
        return
    meta = meta or {}
    now = received_at or time.time()
    bm, sm = rec.get("browser_marks") or {}, rec.get("server_marks") or {}
    mode = rec.get("mode", "?")
    pair = "-".join(sorted(x for x in (rec.get("src"), rec.get("tgt")) if x))  # canonical; direction is per turn
    providers = meta.get("providers") or {}
    models = models_for(providers)
    trace = tid("session", session_id)
    commit = lf.cfg.release
    exp = meta.get("experiment")
    tags = ([f"mode:{mode}", f"pair:{pair}", f"commit:{commit}"] + (["source:harness"] if meta.get("harness") else [])
            + ([f"experiment:{exp}"] if exp else []))
    lf.emit("trace-create", {
        "id": trace, "name": "interpreter-session", "sessionId": session_id, "timestamp": iso(now), "release": commit,
        "tags": tags, "metadata": {"mode": mode, "pair": pair, "providers": providers, "models": models,
                                   "pipeline": meta.get("pipeline"), "prompt_version": prompt_version(),
                                   **({"experiment": exp} if exp else {})}})
    # anchor: the record arrives after playback; put speech end at (received - last mark)
    marks_ms = [v for v in bm.values() if isinstance(v, int | float)] + [s for m in sm if (s := _stage(rec, m)) is not None]
    t0 = now - max([0.0, *marks_ms]) / 1000 - 0.05
    at = lambda ms: iso(t0 + ms / 1000)
    span = str(uuid.uuid4())
    H = rec.get("latency_ms")  # literal first audible (browser)
    R = rec.get("response_ms", H)  # A21 headline: first audio of the last sentence
    usage = rec.get("usage") or {}
    speech_s = (rec.get("speech_ms") or 0) / 1000
    costs = stage_costs(usage, models, speech_s)
    stage_ms = {m: round(v, 1) for m in sm if (v := _stage(rec, m)) is not None}
    lf.emit("span-create", {
        "id": span, "traceId": trace, "name": f"turn {rec.get('turn_id')} · {mode} · {rec.get('src')}→{rec.get('tgt')}",
        "startTime": at(min([0.0, *stage_ms.values()])), "endTime": at(max(x for x in (H, R, 0.0) if x is not None) if H is not None else max([0.0, *marks_ms])),
        "input": lf.text(rec.get("source_text")), "output": lf.text(rec.get("target_text")),
        "level": "DEFAULT" if rec.get("status") == "done" else "WARNING",
        "statusMessage": rec.get("reason") or rec.get("status"),
        "metadata": {"turn_id": rec.get("turn_id"), "speaker": rec.get("speaker"), "status": rec.get("status"),
                     "latency_ms": H, "headline_ms": R, "speech_ms": rec.get("speech_ms"), "browser_marks": bm, "server_marks": sm,
                     "stage_ms_after_speech_end": stage_ms,
                     "early_stages": sorted(k for k, v in stage_ms.items() if v < 0),
                     "clock": "ms after speech end (browser); * server marks = commit_sent + server duration",
                     "cost_usd": round(sum(costs.values()), 6), "usage": usage}})
    for name, v in (("H_ms", R), ("first_audible_ms", H)):  # H_ms = the A21 headline, as in the UI
        if v is not None:
            lf.emit("score-create", {"id": str(uuid.uuid4()), "traceId": trace, "observationId": span, "name": name,
                                     "value": round(v, 1), "dataType": "NUMERIC"})

    def gen(name: str, start: float | None, first: float | None, end: float | None, **kw: Any) -> None:
        if start is None and end is None:
            return
        s = start if start is not None else end
        e = max(x for x in (end, first, s) if x is not None)
        body = {"id": str(uuid.uuid4()), "traceId": trace, "parentObservationId": span, "name": name,
                "startTime": at(s), "endTime": at(e), "metadata": {"early": s < 0, **kw.pop("metadata", {})}, **kw}
        if first is not None:
            body["completionStartTime"] = at(first)
        lf.emit("generation-create", body)

    if mode == "realtime":
        rt = usage.get("realtime") or {}
        gen("realtime", bm.get("commit_sent"), bm.get("output_audio_started"), bm.get("first_audible"),
            model=models.get("realtime"), input=lf.text(rec.get("source_text")), output=lf.text(rec.get("target_text")),
            usageDetails={k: v for k, v in {"input": rt.get("input_tokens"), "output": rt.get("output_tokens"),
                                            "total": rt.get("total_tokens")}.items() if v is not None},
            costDetails={"total": round(costs.get("realtime", 0.0), 6)},
            metadata={"marks": bm, "side_transcription_usd": round(costs.get("transcription", 0.0), 6), "transport": providers.get("transport"), "provider": "openai"})
        return
    s = lambda m: stage_ms.get(m)
    gen("stt", 0.0 if s("stt_final") is not None else None, None, s("stt_final"), model=models.get("stt"),
        output=lf.text(rec.get("source_text")),
        usageDetails={"input": usage.get("stt_audio_s", 0)}, costDetails={"total": round(costs.get("stt", 0.0), 6)},
        metadata={"provider": providers.get("stt"), "unit": "seconds of audio (audio itself is never sent)",
                  "span": "speech end → STT final"})
    mt_start = min((v for v in (s("spec_start"), s("stt_final"), s("mt_first_token")) if v is not None), default=None)
    if s("mt_first_token") is not None and mt_start is not None and mt_start > s("mt_first_token"):
        mt_start = s("mt_first_token")
    gen("mt", mt_start, s("mt_first_token"), s("mt_first_chunk"), model=models.get("mt"),
        input=lf.text(rec.get("source_text")), output=lf.text(rec.get("target_text")),
        usageDetails={"input": usage.get("mt_input_tokens", 0), "output": usage.get("mt_output_tokens", 0)},
        costDetails={"total": round(costs.get("mt", 0.0), 6)},
        metadata={"provider": providers.get("mt"), "prompt_version": prompt_version(), "speculative": "spec_hit" in sm,
                  "hedge_fired": "mt_hedge_fired" in sm})
    gen("tts", s("tts_request"), s("tts_first_byte"), s("tail_tts_first_byte") or s("tts_first_byte"), model=models.get("tts"),
        input=lf.text(rec.get("target_text")),
        usageDetails={"input": usage.get("tts_chars", 0)}, costDetails={"total": round(costs.get("tts", 0.0), 6)},
        metadata={"provider": providers.get("tts"), "unit": "characters", "tts_audio_s": usage.get("tts_audio_s")})
    if s("audio_first_sent") is not None and H is not None:
        lf.emit("span-create", {"id": str(uuid.uuid4()), "traceId": trace, "parentObservationId": span, "name": "playback",
                                "startTime": at(s("audio_first_sent")), "endTime": at(H),
                                "metadata": {"span": "audio sent → first audible (browser)"}})


def experiment_events(lf: Langfuse, exp_id: str, name: str, setup: str, rows: list[dict], prof: dict,
                      git_commit: str, config: dict) -> None:
    """One trace per utterance per setup, linked by sessionId exp-<id>; metrics as scores."""
    if not lf.enabled:
        return
    for i, r in enumerate(rows):
        trace = tid("exp", exp_id, setup, str(r.get("id")), str(i))
        lf.emit("trace-create", {
            "id": trace, "name": f"experiment · {setup} · {r.get('id')}", "sessionId": f"exp-{exp_id}", "release": git_commit,
            "tags": [f"experiment:{exp_id}", f"setup:{setup}", f"commit:{git_commit}", f"pair:{r.get('lang')}-{'es' if r.get('lang') == 'en' else 'en'}"],
            "input": lf.text(r.get("source")), "output": lf.text(r.get("target")),
            "metadata": {"experiment": exp_id, "experiment_name": name, "setup": setup, "models": prof,
                         "utterance": r.get("id"), "size": r.get("size"), "status": r.get("status"),
                         "prompt_version": prompt_version(), "config": config, "reference": lf.text(r.get("reference")),
                         "H_ms": r.get("H_fair_ms", r.get("H_ms")), "first_audible_ms": r.get("H_ms"), "H_minus_lag_ms": r.get("H_minus_lag_ms"), "cost_usd": r.get("cost_usd")}})
        for k, v in (("H_ms", r.get("H_fair_ms", r.get("H_ms"))), ("first_audible_ms", r.get("H_ms")),
                     ("H_minus_lag_ms", r.get("H_fair_minus_lag_ms", r.get("H_minus_lag_ms"))), ("src_wer", r.get("src_wer")),
                     ("chrF", r.get("chrf")), ("cost_usd", r.get("cost_usd")), ("judge", r.get("judge"))):
            if isinstance(v, int | float):
                lf.emit("score-create", {"id": str(uuid.uuid4()), "traceId": trace, "name": k, "value": round(float(v), 6),
                                         "dataType": "NUMERIC"})


def review_events(lf: Langfuse, set_id: str, item: dict, rater: str, scores: dict[str, int | None], notes: str) -> None:
    if not lf.enabled:
        return
    trace = tid("review", set_id, str(item.get("item_id")))
    lf.emit("trace-create", {"id": trace, "name": f"review · {set_id} · {item.get('item_id')}",
                             "sessionId": f"review-{set_id}", "tags": [f"review:{set_id}"],
                             "metadata": {k: v for k, v in item.items() if isinstance(v, str | int | float) and k != "audio"
                                          and (lf.cfg.send_text or k not in ("source_text", "reference", "target_text"))}})
    for dim, v in scores.items():
        if v is not None:
            lf.emit("score-create", {"id": tid("review-score", trace, rater, dim), "traceId": trace, "name": f"human_{dim}",
                                     "value": float(v), "dataType": "NUMERIC", "comment": f"rater {rater}" + (f": {notes}" if notes and lf.cfg.send_text else "")})


def review_score_ids(set_id: str, item_id: str, rater: str, dims: list[str]) -> list[str]:
    trace = tid("review", set_id, str(item_id))
    return [tid("review-score", trace, rater, d) for d in dims]
