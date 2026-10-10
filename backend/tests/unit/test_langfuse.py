"""A20 Langfuse tracing: mocked HTTP only; fail-open, off the request path, never audio."""
import asyncio
import base64
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app
from app.observability import traces
from app.observability.client import Langfuse, LangfuseConfig, set_langfuse

CASCADE = {"turn_id": 3, "mode": "cascade", "speaker": "A", "src": "en", "tgt": "es", "status": "done", "latency_ms": 709.2,
           "browser_marks": {"commit_sent": 460.7, "first_audible": 709.2},
           "server_marks": {"spec_start": 193.9, "spec_hit": 618.7, "mt_first_token": -7793.9, "mt_first_chunk": -7781.6,
                            "tts_request": -7781.4, "tts_first_byte": -6916, "tail_tts_first_byte": 1325.4,
                            "audio_first_sent": 1.2, "stt_final": 650.2},
           "source_text": "Your blood pressure is a little high today.", "target_text": "Tu presión arterial está un poco alta hoy.",
           "usage": {"stt_audio_s": 14, "mt_input_tokens": 732, "mt_output_tokens": 55, "tts_chars": 170, "tts_audio_s": 15.04}}
REALTIME = {"turn_id": 2, "mode": "realtime", "speaker": "B", "src": "es", "tgt": "en", "status": "done", "latency_ms": 1261.1,
            "browser_marks": {"commit_sent": 465.3, "response_created": 528.6, "output_audio_started": 1138.8, "first_audible": 1261.1},
            "server_marks": {}, "source_text": "Me duele la cabeza.", "target_text": "My head hurts.",
            "usage": {"realtime": {"total_tokens": 297, "input_tokens": 229, "output_tokens": 68,
                                   "input_token_details": {"text_tokens": 133, "audio_tokens": 96},
                                   "output_token_details": {"text_tokens": 18, "audio_tokens": 50}}}}
META = {"providers": {"stt": "openai_live", "mt": "openai", "tts": "openai"}, "pipeline": "cascade", "pair": "en-es"}


def lf(send_text=True, **kw) -> Langfuse:
    return Langfuse(LangfuseConfig(enabled=True, public_key="pk-lf-test", secret_key="sk-lf-test", send_text=send_text,
                                   release="abc1234", **kw))


def by_type(l: Langfuse, t: str) -> list[dict]:
    return [e["body"] for e in l.q if e["type"] == t]


def test_off_by_default():
    get_settings.cache_clear()
    c = get_settings().langfuse_config()
    assert c.enabled is False and not Langfuse(c).enabled
    off = Langfuse(LangfuseConfig(enabled=False, public_key="pk", secret_key="sk"))
    off.emit("trace-create", {"id": "x"})
    assert not off.q
    traces.turn_events(off, "s", CASCADE, META)
    assert not off.q


def test_enabled_without_keys_stays_off():
    assert not Langfuse(LangfuseConfig(enabled=True)).enabled


def test_cascade_turn_tree_matches_ui_numbers():
    l = lf()
    traces.turn_events(l, "2026-10-10T01-26-17-474Z-7xb90", CASCADE, META, received_at=1_800_000_000.0)
    (tr,) = by_type(l, "trace-create")
    assert tr["sessionId"] == "2026-10-10T01-26-17-474Z-7xb90" and tr["name"] == "interpreter-session"
    assert {"mode:cascade", "pair:en-es", "commit:abc1234"} <= set(tr["tags"])
    assert tr["metadata"]["models"] == {"stt": "gpt-live-transcribe", "mt": "gpt-5.4-nano", "tts": "gpt-4o-mini-tts"}
    turn = next(s for s in by_type(l, "span-create") if "parentObservationId" not in s)
    md = turn["metadata"]
    assert md["latency_ms"] == 709.2 and md["browser_marks"] == CASCADE["browser_marks"] and md["server_marks"] == CASCADE["server_marks"]
    # the UI's stageMs: commit_sent + server duration
    assert md["stage_ms_after_speech_end"]["mt_first_token"] == round(460.7 - 7793.9, 1)
    assert md["stage_ms_after_speech_end"]["stt_final"] == round(460.7 + 650.2, 1)
    assert "mt_first_token" in md["early_stages"] and md["cost_usd"] > 0
    gens = {g["name"]: g for g in by_type(l, "generation-create")}
    assert set(gens) == {"stt", "mt", "tts"}
    assert gens["mt"]["model"] == "gpt-5.4-nano" and gens["mt"]["usageDetails"] == {"input": 732, "output": 55}
    assert gens["mt"]["metadata"]["early"] is True and gens["mt"]["metadata"]["speculative"] is True
    assert gens["tts"]["usageDetails"] == {"input": 170} and gens["stt"]["usageDetails"] == {"input": 14}
    assert all(g["costDetails"]["total"] > 0 for g in gens.values())
    assert all(g["parentObservationId"] == turn["id"] and g["traceId"] == tr["id"] for g in gens.values())
    assert any(s["name"] == "playback" for s in by_type(l, "span-create"))
    (h,) = by_type(l, "score-create")
    assert h["name"] == "H_ms" and h["value"] == 709.2
    # deterministic session trace id: later turns upsert the same trace
    l2 = lf()
    traces.turn_events(l2, "2026-10-10T01-26-17-474Z-7xb90", {**CASCADE, "turn_id": 4}, META)
    assert by_type(l2, "trace-create")[0]["id"] == tr["id"]


def test_realtime_turn_generation():
    l = lf()
    traces.turn_events(l, "s-rt", REALTIME, {"providers": {"realtime": "gpt-realtime-mini", "transport": "webrtc"}})
    (g,) = by_type(l, "generation-create")
    assert g["name"] == "realtime" and g["model"] == "gpt-realtime-mini"
    assert g["usageDetails"] == {"input": 229, "output": 68, "total": 297} and g["costDetails"]["total"] > 0
    assert g["metadata"]["marks"] == REALTIME["browser_marks"]


def test_never_audio_and_send_text_off_strips_transcripts():
    l = lf(send_text=False)
    rec = {**CASCADE, "audio": "UklGRg==", "recording": {"src": "/data/x.webm"}}
    traces.turn_events(l, "s", rec, META)
    blob = json.dumps(list(l.q))
    for s in (CASCADE["source_text"], CASCADE["target_text"], "UklGRg==", "x.webm"):
        assert s not in blob
    assert '"latency_ms": 709.2' in blob  # numbers still go


async def _flush_with(handler, **kw) -> Langfuse:
    l = lf(**kw)
    l._transport = httpx.MockTransport(handler)
    await l.start()
    traces.turn_events(l, "s", CASCADE, META)
    await l.flush()
    await l.stop()
    return l


def test_flush_posts_batches_with_basic_auth():
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        n = len(json.loads(req.content)["batch"])
        return httpx.Response(207, json={"successes": [{}] * (n - 1), "errors": [{"id": "x", "status": 400, "message": "bad"}]})
    l = asyncio.run(_flush_with(handler, max_batch=4))
    assert seen and all(r.url.path == "/api/public/ingestion" for r in seen)
    assert seen[0].headers["authorization"] == "Basic " + base64.b64encode(b"pk-lf-test:sk-lf-test").decode()
    assert all(len(json.loads(r.content)["batch"]) <= 4 for r in seen)
    assert l.stats.rejected == len(seen) and l.stats.sent > 0 and not l.q


def test_unreachable_host_fails_open():
    def handler(req):
        raise httpx.ConnectError("unreachable")
    l = asyncio.run(_flush_with(handler))
    assert l.stats.dropped_error > 0 and l.stats.sent == 0


def test_queue_full_drops_newest_without_raising():
    l = lf(max_queue=3)
    for i in range(10):
        l.emit("trace-create", {"id": str(i)})
    assert len(l.q) == 3 and l.stats.dropped_full == 7


@pytest.fixture
def app_with(monkeypatch, tmp_path):
    def make(transport):
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        get_settings.cache_clear()
        inst = lf(flush_interval_s=0.05, timeout_s=0.1, host="http://10.255.255.1:9")
        inst._transport = transport
        set_langfuse(inst)
        return inst
    yield make
    set_langfuse(None)
    get_settings.cache_clear()


def test_api_turns_stays_fast_when_langfuse_is_unreachable_or_slow(app_with):
    async def slow(req):
        await asyncio.sleep(5)  # longer than the 0.2 s timeout
        return httpx.Response(200)
    inst = app_with(httpx.MockTransport(slow))
    with TestClient(create_app()) as c:
        t0 = time.perf_counter()
        for i in range(20):
            assert c.post("/api/turns", json={"session_id": "s-1", "record": {**CASCADE, "turn_id": i}, "meta": META}).status_code == 204
        per_call = (time.perf_counter() - t0) / 20
        assert per_call < 0.05, per_call  # enqueue only: never waits on Langfuse
        time.sleep(1.0)  # let the flusher hit its deadline (0.1 + 0.5 s)
    assert inst.stats.queued >= 20 * 5 and inst.stats.dropped_error > 0 and inst.stats.sent == 0
    # and the JSONL log is unaffected (no meta written)
    assert "meta" not in (get_settings().data_dir / "sessions" / "s-1.jsonl").read_text()


def test_unreachable_real_host_does_not_break_requests(app_with):
    inst = app_with(None)  # real transport to a blackholed address, 0.2 s timeout
    with TestClient(create_app()) as c:
        assert c.post("/api/turns", json={"session_id": "s-2", "record": CASCADE, "meta": META}).status_code == 204
        time.sleep(0.5)
        assert c.get("/api/health").status_code == 200
    assert inst.stats.sent == 0


def test_experiment_rows_become_traces_with_scores():
    l = lf()
    rows = [{"id": "en-s01", "lang": "en", "size": "short", "status": "done", "H_ms": 1200.5, "H_minus_lag_ms": 750.5,
             "src_wer": 0.0, "chrf": 71.2, "cost_usd": 0.0008, "source": "Do you have any allergies?", "target": "¿Tiene alergias?"}]
    traces.experiment_events(l, "e1", "smoke", "cascade-openai", rows, {"mt": "gpt-5.4-nano"}, "abc1234", {"passes": 1})
    (tr,) = by_type(l, "trace-create")
    assert tr["sessionId"] == "exp-e1" and "experiment:e1" in tr["tags"] and "setup:cascade-openai" in tr["tags"]
    assert tr["metadata"]["prompt_version"] and tr["metadata"]["config"] == {"passes": 1}
    assert {s["name"]: s["value"] for s in by_type(l, "score-create")} == {
        "H_ms": 1200.5, "H_minus_lag_ms": 750.5, "src_wer": 0.0, "chrF": 71.2, "cost_usd": 0.0008}


def test_review_rating_becomes_human_scores():
    l = lf()
    item = {"set_id": "m5", "item_id": "c01", "idx": 1, "audio": "/x.ogg", "direction": "en-es", "variant": "cascade-openai",
            "source_text": "hi"}
    traces.review_events(l, "m5", item, "andre", {"accuracy": 5, "naturalness": 4, "overall": None}, "good")
    assert {s["name"]: s["value"] for s in by_type(l, "score-create")} == {"human_accuracy": 5.0, "human_naturalness": 4.0}
    assert "/x.ogg" not in json.dumps(list(l.q))
