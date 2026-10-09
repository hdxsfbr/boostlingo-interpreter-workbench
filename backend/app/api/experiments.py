"""Experiments tab API (DESIGN A13): setups, estimate, run (one at a time),
live progress (SSE), cancel, history, detail, per-turn rows, CSV/JSON export."""
from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import secrets
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import ValidationError

from app.core.config import get_settings
from app.experiments import baseline
from app.experiments.config import SETUPS, ExperimentConfig, direction_options, estimate, utterances
from app.experiments.runner import Busy, ExperimentRunner
from app.experiments.store import ExperimentStore

router = APIRouter(prefix="/api/experiments")
_STATE: dict = {}


def exp_cfg() -> dict:
    return {"confirm_above_usd": 1.0, "self_url": "http://127.0.0.1:8740",
            **(get_settings().app_config().get("experiments") or {})}


def get_experiments() -> tuple[ExperimentStore, ExperimentRunner]:
    if "store" not in _STATE:
        s = get_settings()
        store = ExperimentStore(s.data_dir / "experiments.sqlite3")
        store.mark_interrupted()
        _STATE["store"] = store
        _STATE["runner"] = ExperimentRunner(store, s.data_dir, exp_cfg()["self_url"], os.environ.get("GIT_COMMIT", "unknown"))
        try:
            m = _STATE["runner"].metrics
            baseline.import_m5(store, s.bench_dir, m.row_cost, m.PROFILES)
        except ImportError:  # metrics deps missing: import without per-turn cost
            baseline.import_m5(store, s.bench_dir)
    return _STATE["store"], _STATE["runner"]


def _availability() -> dict[str, str]:
    """setup -> '' if runnable, else why not (provider not configured)."""
    sw = get_settings().swap_options()
    ready = {f"{k}:{o['name']}": (o["ready"], o["reason"]) for k, opts in sw.items() for o in opts}
    out = {}
    for name, s in SETUPS.items():
        if s.needs == "openrouter":
            ok, why = ready.get("mt:openrouter", (False, "OpenRouter not configured"))
        elif s.needs == "elevenlabs":
            ok, why = ready.get("tts:elevenlabs", (False, "ElevenLabs disabled"))
        else:
            ok, why = ready.get("mt:openai", (False, "OPENAI_API_KEY missing"))
        out[name] = "" if ok else why
    return out


def _parse(body: dict) -> ExperimentConfig:
    try:
        return ExperimentConfig.model_validate(body)
    except ValidationError as e:
        raise HTTPException(422, detail=[{"loc": x["loc"], "msg": x["msg"]} for x in e.errors()]) from None


@router.get("/setups")
def setups() -> dict:
    av = _availability()
    utt = utterances()
    return {"setups": [{"name": s.name, "label": s.label, "mode": s.mode, "models": s.models, "warning": s.warning,
                        "unavailable": av[s.name], "needs_confirmation_checkbox": s.name == "cascade-elevenlabs"}
                       for s in SETUPS.values()],
            "default_setups": ["realtime-mini", "cascade-openai"],
            "directions": direction_options(),
            "confirm_above_usd": float(exp_cfg()["confirm_above_usd"]),
            "utterances": [{"id": k, "lang": u["lang"], "size": u["size"], "text": u["text"]} for k, u in utt.items()]}


@router.post("/estimate")
def post_estimate(body: dict) -> dict:
    cfg = _parse(body)
    est = estimate(cfg, get_settings().bench_dir)
    thr = float(exp_cfg()["confirm_above_usd"])
    return {**est, "confirm_above_usd": thr, "needs_confirmation": est["usd"] > thr, "utterance_ids": cfg.selected()}


@router.post("")
async def create(body: dict):
    store, runner = get_experiments()
    confirm = bool(body.pop("confirm", False))
    cfg = _parse(body)
    av = _availability()
    blocked = {s: av[s] for s in cfg.setups if av[s]}
    if blocked:
        raise HTTPException(400, detail={"code": "setup_unavailable", "message": f"not runnable here: {blocked}"})
    est = estimate(cfg, get_settings().bench_dir)
    thr = float(exp_cfg()["confirm_above_usd"])
    if est["usd"] > thr and not confirm:
        return JSONResponse(status_code=428, content={"detail": {
            "code": "confirm_required", "message": f"estimated ${est['usd']:.2f} is above ${thr:.2f}; confirm to run",
            "estimate": est}})
    if runner.busy():
        raise HTTPException(409, detail={"code": "busy", "message": f"experiment {runner.busy()} is running; "
                                                                    "only one runs at a time (cancel it or wait)"})
    exp_id = time.strftime("exp-%Y%m%d-%H%M%S-") + secrets.token_hex(2)
    store.create(exp_id, cfg.name, cfg.model_dump(), est, runner.git_commit)
    try:
        await runner.start(exp_id, cfg)
    except Busy as e:
        store.update(exp_id, status="cancelled", error=str(e))
        raise HTTPException(409, detail={"code": "busy", "message": str(e)}) from None
    return store.get(exp_id)


@router.get("")
def list_experiments() -> list[dict]:
    store, _ = get_experiments()
    keep = ("id", "name", "status", "readonly", "created", "started", "finished", "cost_usd", "git_commit", "error")
    out = []
    for e in store.list():
        d = {k: e[k] for k in keep}
        d["setups"] = e["config"].get("setups", [])
        d["estimate_usd"] = e["estimate"].get("usd")
        d["progress"] = {k: e["progress"].get(k) for k in ("done", "total")} if e["progress"] else None
        out.append(d)
    return out


@router.get("/running")
def running() -> dict:
    store, runner = get_experiments()
    rid = runner.busy()
    return {"id": rid, "experiment": store.get(rid) if rid else None}


def _get(exp_id: str) -> dict:
    store, _ = get_experiments()
    e = store.get(exp_id)
    if not e:
        raise HTTPException(404, "unknown experiment")
    return e


@router.get("/{exp_id}")
def detail(exp_id: str) -> dict:
    return _get(exp_id)


@router.get("/{exp_id}/turns")
def turns(exp_id: str) -> list[dict]:
    _get(exp_id)
    return get_experiments()[0].turns(exp_id)


@router.post("/{exp_id}/cancel")
async def cancel(exp_id: str) -> dict:
    e = _get(exp_id)
    if e["status"] not in ("queued", "running"):
        raise HTTPException(409, detail={"code": "not_running", "message": f"experiment is {e['status']}"})
    _, runner = get_experiments()
    await runner.cancel(exp_id)
    return get_experiments()[0].get(exp_id)


@router.get("/{exp_id}/events")
async def events(exp_id: str, request: Request) -> StreamingResponse:
    e = _get(exp_id)
    _, runner = get_experiments()

    async def gen():
        yield f"data: {json.dumps({'type': 'snapshot', 'id': exp_id, 'status': e['status'], **(e['progress'] or {})})}\n\n"
        if e["status"] not in ("queued", "running"):
            return
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        runner.subscribers.add(q)
        try:
            while not await request.is_disconnected():
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if ev.get("id") != exp_id:
                    continue
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                if ev["type"] == "status" and ev["status"] not in ("running", "queued"):
                    return
        finally:
            runner.subscribers.discard(q)
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


SUMMARY_COLS = ["setup", "n", "done", "H_p50", "H_p90", "H_gap_p50", "H_gap_p90", "tail_p50", "chrF_all", "chrF_en_es",
                "chrF_es_en", "WER_en", "WER_es", "usd_total", "usd_per_min", "failures"]


def summary_rows(e: dict) -> list[dict]:
    out = []
    for p in e["summary"]:
        q = p.get("quality", {})
        out.append({"setup": p["profile"], "n": p["n"], "done": p["done"], "H_p50": p["H"]["p50"], "H_p90": p["H"]["p90"],
                    "H_gap_p50": p["H_minus_gap"]["p50"], "H_gap_p90": p["H_minus_gap"]["p90"],
                    "tail_p50": p.get("tail", {}).get("p50"), "chrF_all": q.get("all", {}).get("chrF"),
                    "chrF_en_es": q.get("en->es", {}).get("chrF"), "chrF_es_en": q.get("es->en", {}).get("chrF"),
                    "WER_en": q.get("en->es", {}).get("src_WER_mean"), "WER_es": q.get("es->en", {}).get("src_WER_mean"),
                    "usd_total": p.get("cost", {}).get("usd_total"), "usd_per_min": p.get("cost", {}).get("usd_per_min"),
                    "failures": p.get("failures", {}).get("count")})
    return out


@router.get("/{exp_id}/export.json")
def export_json(exp_id: str) -> JSONResponse:
    e = _get(exp_id)
    body = {**e, "summary_table": summary_rows(e), "turns": get_experiments()[0].turns(exp_id, full=True)}
    return JSONResponse(body, headers={"Content-Disposition": f'attachment; filename="{exp_id}.json"'})


@router.get("/{exp_id}/export.csv")
def export_csv(exp_id: str, kind: str = "summary") -> PlainTextResponse:
    e = _get(exp_id)
    buf = io.StringIO()
    if kind == "turns":
        cols = ["setup", "n", "utterance_id", "lang", "size", "status", "h_ms", "h_minus_gap_ms", "tail_ms", "cost_usd",
                "source", "target"]
        w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(get_experiments()[0].turns(exp_id))
    else:
        w = csv.DictWriter(buf, fieldnames=["experiment", "git_commit", *SUMMARY_COLS])
        w.writeheader()
        for r in summary_rows(e):
            w.writerow({"experiment": exp_id, "git_commit": e["git_commit"], **r})
    return PlainTextResponse(buf.getvalue(), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{exp_id}-{kind}.csv"'})
