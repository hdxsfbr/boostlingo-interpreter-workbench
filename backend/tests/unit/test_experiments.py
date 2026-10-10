"""Experiments tab (DESIGN A13). The harness is replaced by a fake child
process that streams harness-shaped JSONL rows, so no browser, no provider
and no paid call is involved. Covers: config validation, cost estimate,
confirmation threshold, single-run lock, cancel (no orphaned processes),
persistence + summary, M5 baseline import == results.json, exports."""
import json
import sys
import textwrap
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.experiments as expmod
from app.core.config import REPO_ROOT, get_settings
from app.experiments.config import ExperimentConfig, estimate, m5_profile_stats
from app.main import create_app

BENCH = REPO_ROOT / "docs" / "benchmarks"
FAKE = textwrap.dedent('''
    import json, os, subprocess, sys, time
    out, n, delay, child = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]), sys.argv[4] == "1"
    if child:  # stands in for Chromium: a grandchild that must not outlive a cancel
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
        open(out + ".child", "w").write(str(p.pid))
    print("providers: " + json.dumps({"stt": "openai_live", "mt": "openai", "tts": "openai"}), flush=True)
    ids = sys.argv[5].split(",")
    with open(out, "a") as f:
        for i in range(n):
            time.sleep(delay)
            uid = ids[i % len(ids)]
            ok = i != 1
            f.write(json.dumps({"id": uid, "lang": uid[:2], "size": "short", "domain": "x", "speech_s": 1.5,
                "status": "done" if ok else "failed", "reason": None if ok else "mt: timeout", "turns": 1,
                "H_ms": 900.0 + 10 * i if ok else None, "H_minus_lag_ms": 450.0 + 10 * i if ok else None,
                "tail_est_ms": 800.0, "source": "Do you have any allergies?", "target": "Tiene alergias?",
                "reference": "Tiene alguna alergia?", "server_marks": {}, "browser_marks": {},
                "usage": [{"stt_audio_s": 2.0, "mt_input_tokens": 120, "mt_output_tokens": 20, "tts_chars": 20,
                           "tts_audio_s": 1.2}], "n": i + 1}) + "\\n")
            f.flush()
''')


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BENCH_DIR", str(BENCH))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    monkeypatch.setenv("GIT_COMMIT", "abc1234")
    get_settings.cache_clear()
    expmod._STATE.clear()
    script = tmp_path / "fake_harness.py"
    script.write_text(FAKE)
    opts = {"delay": 0.02, "child": False}

    def fake_cmd(setup, ids, cfg, out, url):
        return [sys.executable, str(script), str(out), str(len(ids) * cfg.passes), str(opts["delay"]),
                "1" if opts["child"] else "0", ",".join(ids)]
    with TestClient(create_app()) as c:
        _, runner = expmod.get_experiments()
        runner.command = fake_cmd
        runner.poll_s = 0.05
        yield c, opts, tmp_path
    expmod._STATE.clear()
    get_settings.cache_clear()


def wait(c, exp_id, statuses=("done", "failed", "cancelled"), timeout=20):
    t0 = time.time()
    while time.time() - t0 < timeout:
        e = c.get(f"/api/experiments/{exp_id}").json()
        if e["status"] in statuses:
            return e
        time.sleep(0.05)
    raise AssertionError(f"experiment stuck in {e['status']}")


BASE = {"name": "smoke", "setups": ["cascade-openai"], "utterances": "custom", "ids": ["en-s01", "es-s01", "en-s02"]}


# ----- config validation
@pytest.mark.parametrize("patch,msg", [
    ({"setups": ["nope"]}, "unknown setup"),
    ({"setups": []}, "at least 1"),
    ({"setups": ["cascade-openai", "cascade-openai"]}, "duplicate"),
    ({"setups": ["cascade-elevenlabs"]}, "allow_elevenlabs"),
    ({"ids": ["en-s99"]}, "known utterance ids"),
    ({"ids": ["../x"]}, "known utterance ids"),
    ({"utterances": "short", "ids": ["en-s01"]}, "only used with"),
    ({"ids": ["es-s01"], "directions": "en"}, "selection is empty"),
    ({"passes": 0}, "greater than or equal"),
    ({"passes": 6}, "less than or equal"),
    ({"name": "   "}, "name"),
])
def test_config_validation(env, patch, msg):
    c, _, _ = env
    r = c.post("/api/experiments/estimate", json={**BASE, **patch})
    assert r.status_code == 422 and msg in json.dumps(r.json()), r.json()


def test_selection_order_and_filters():
    assert len(ExperimentConfig(name="x", setups=["realtime-mini"], utterances="full").selected()) == 48
    short = ExperimentConfig(name="x", setups=["realtime-mini"], utterances="short").selected()
    assert len(short) == 16 and all("-s" in i for i in short)
    assert ExperimentConfig(name="x", setups=["realtime-mini"], utterances="short", directions="es").selected()[0] == "es-s01"


# ----- estimate
def test_estimate_uses_m5_per_utterance_cost_with_rate_fallback(env):
    from eval.metrics import PROFILES, row_cost
    c, _, _ = env
    st = m5_profile_stats(BENCH)
    cfg = ExperimentConfig(name="x", setups=["realtime-mini", "cascade-openai", "cascade-elevenlabs"],
                           utterances="short", passes=2, allow_elevenlabs=True)
    est = estimate(cfg, BENCH)
    ids = cfg.selected()
    speech = sum(st["speech_s"][i] for i in ids)
    rate = {p["profile"]: p["cost"]["usd_per_min"] for p in json.loads((BENCH / "results/m5/results.json").read_text())["profiles"]}
    for row in est["per_setup"]:
        raw = [json.loads(x) for x in (BENCH / f"results/m5/raw/{row['setup']}.jsonl").read_text().splitlines() if x.strip()]
        per: dict[str, list[float]] = {}
        for r in raw:
            per.setdefault(r["id"], []).append(row_cost(r, PROFILES[row["setup"]]))
        want = sum(sum(per[i]) / len(per[i]) if i in per else rate[row["setup"]] * st["speech_s"][i] / 60 for i in ids) * 2
        assert row["usd"] == pytest.approx(want, abs=1e-4)
        assert row["measured_utterances"] == sum(i in per for i in ids)
        assert row["utterances"] == 32 and row["duration_s"] > speech * 2
    assert est["per_setup"][0]["measured_utterances"] == 16 and est["per_setup"][2]["measured_utterances"] < 16
    assert est["per_setup"][2]["elevenlabs_chars"] > 0
    assert est["turns"] == 96 and est["usd"] == pytest.approx(sum(r["usd"] for r in est["per_setup"]), abs=1e-4)
    r = c.post("/api/experiments/estimate", json={"name": "x", "setups": ["realtime"], "utterances": "full", "passes": 3}).json()
    assert r["needs_confirmation"] is True and r["usd"] > r["confirm_above_usd"] == 1.0


def test_confirmation_required_above_threshold(env):
    c, _, _ = env
    body = {"name": "big", "setups": ["realtime"], "utterances": "full", "passes": 3}
    r = c.post("/api/experiments", json=body)
    assert r.status_code == 428 and r.json()["detail"]["code"] == "confirm_required"
    assert c.get("/api/experiments").json()[0]["id"] == "m5-baseline"  # nothing was created


def test_unavailable_setup_refused(env):
    c, _, _ = env
    r = c.post("/api/experiments", json={**BASE, "setups": ["cascade-elevenlabs"], "allow_elevenlabs": True})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "setup_unavailable"


# ----- run + persistence
def test_run_persists_rows_summary_and_provenance(env):
    c, _, _ = env
    exp = c.post("/api/experiments", json={**BASE, "passes": 2}).json()
    e = wait(c, exp["id"])
    assert e["status"] == "done" and e["git_commit"] == "abc1234" and not e["readonly"]
    turns = c.get(f"/api/experiments/{exp['id']}/turns").json()
    assert len(turns) == 6 and turns[0]["source"] and turns[1]["status"] == "failed"
    s = e["summary"][0]
    assert s["profile"] == "cascade-openai" and s["n"] == 6 and s["done"] == 5
    assert s["H"]["p50"] is not None and s["H_minus_gap"]["p90"] is not None
    assert s["quality"]["all"]["chrF"] > 0 and "src_WER_mean" in s["quality"]["en->es"]
    assert s["failures"]["count"] == 1 and s["cost"]["usd_per_min"] > 0
    assert e["cost_usd"] == pytest.approx(s["cost"]["usd_total"], abs=1e-4)
    assert e["models"]["cascade-openai"]["models"]["mt"] == "gpt-5.4-nano"
    assert e["models"]["cascade-openai"]["reported_providers"]["stt"] == "openai_live"
    assert e["progress"]["done"] == 6 and e["progress"]["failures"] == 1
    csv_ = c.get(f"/api/experiments/{exp['id']}/export.csv").text.splitlines()
    assert csv_[0].startswith("experiment,git_commit,setup,n,done,H_p50") and len(csv_) == 2
    assert len(c.get(f"/api/experiments/{exp['id']}/export.csv", params={"kind": "turns"}).text.splitlines()) == 7
    j = c.get(f"/api/experiments/{exp['id']}/export.json").json()
    assert len(j["turns"]) == 6 and j["summary_table"][0]["setup"] == "cascade-openai"
    ev = c.get(f"/api/experiments/{exp['id']}/events").text  # finished: snapshot only
    assert ev.startswith("data: ") and '"status": "done"' in ev


def test_single_run_lock(env):
    c, opts, _ = env
    opts["delay"] = 0.5
    first = c.post("/api/experiments", json=BASE).json()
    r = c.post("/api/experiments", json={**BASE, "name": "second"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "busy"
    assert c.get("/api/experiments/running").json()["id"] == first["id"]
    c.post(f"/api/experiments/{first['id']}/cancel")


def test_cancel_stops_cleanly_without_orphans(env):
    c, opts, tmp = env
    opts.update(delay=0.4, child=True)
    exp = c.post("/api/experiments", json={**BASE, "setups": ["cascade-openai", "realtime-mini"]}).json()
    out = tmp / "experiments" / exp["id"] / "cascade-openai.jsonl"
    t0 = time.time()
    while not (out.with_suffix(".jsonl.child").exists() and out.read_text().count("\n") >= 1) and time.time() - t0 < 10:
        time.sleep(0.05)
    child = int(out.with_suffix(".jsonl.child").read_text())
    r = c.post(f"/api/experiments/{exp['id']}/cancel").json()
    assert r["status"] == "cancelled"
    assert r["progress"]["done"] >= 1 and r["progress"]["done"] < 3   # partial rows kept
    assert not (tmp / "experiments" / exp["id"] / "realtime-mini.jsonl").exists()  # next setup never started
    time.sleep(0.2)
    stat = Path(f"/proc/{child}/stat")
    alive = stat.exists() and stat.read_text().split(")")[1].split()[0] != "Z"
    assert not alive, "the fake Chromium grandchild outlived the cancel"
    assert c.get("/api/experiments/running").json()["id"] is None
    assert c.post("/api/experiments", json=BASE).status_code == 200  # the lock is released


# ----- baseline + restart
def test_m5_baseline_matches_results_json(env):
    c, _, _ = env
    res = json.loads((BENCH / "results/m5/results.json").read_text())
    e = c.get("/api/experiments/m5-baseline").json()
    assert e["readonly"] and e["status"] == "done" and e["name"] == "M5 baseline"
    assert e["summary"] == res["profiles"]
    assert e["config"]["setups"] == [p["profile"] for p in res["profiles"]]
    assert e["cost_usd"] == pytest.approx(sum(p["cost"]["usd_total"] for p in res["profiles"]), abs=1e-4)
    n_raw = sum(1 for p in res["profiles"] for line in (BENCH / f"results/m5/raw/{p['profile']}.jsonl").read_text().splitlines() if line.strip())
    assert len(c.get("/api/experiments/m5-baseline/turns").json()) == n_raw
    table = {r["setup"]: r for r in expmod.summary_rows(e)}
    assert table["realtime"]["H_p50"] == 1002 and table["cascade-openai"]["chrF_en_es"] == 72.9
    # A21 headline = first audio of the last sentence; the literal first audible stays a secondary column
    assert table["cascade-openai"]["H_p50"] == 1744 and table["cascade-openai"]["H_p90"] == 2196
    assert table["cascade-openai"]["first_audible_p50"] == 545 and table["cascade-haiku"]["H_p50"] == 2060
    turns = c.get("/api/experiments/m5-baseline/turns").json()
    split = next(t for t in turns if t["setup"] == "cascade-openai" and t["utterance_id"] == "en-l01")
    assert split["h_ms"] >= 1000  # tail of the last segment, not the held first sentence (~0.5 s)
    assert c.post("/api/experiments/m5-baseline/cancel").status_code == 409  # read-only, not running


def test_stale_runs_marked_interrupted_on_restart(env):
    store, _ = expmod.get_experiments()
    store.create("exp-stale", "stale", {"setups": []}, {}, "x", status="running")
    expmod._STATE.clear()
    store2, _ = expmod.get_experiments()
    assert store2.get("exp-stale")["status"] == "interrupted"


def test_baseline_reimports_when_results_json_changes(tmp_path):
    from app.experiments import baseline
    from app.experiments.store import ExperimentStore
    st = ExperimentStore(tmp_path / "e.sqlite")
    assert baseline.import_m5(st, BENCH)
    assert not baseline.import_m5(st, BENCH)  # unchanged: no-op
    st.update("m5-baseline", summary=[{"profile": "stale"}])
    assert baseline.import_m5(st, BENCH)  # stale summary: re-imported from results.json
    res = json.loads((BENCH / "results/m5/results.json").read_text())
    assert st.get("m5-baseline")["summary"] == res["profiles"]


def test_h_fair_is_last_sentence_first_audio():
    from eval.metrics import fair
    assert fair({"H_ms": 510.0, "H_minus_lag_ms": 55.0, "tail_est_ms": 1707.0}) == (1707.0, 1252.0)  # split turn
    assert fair({"H_ms": 1700.0, "H_minus_lag_ms": 1245.0, "tail_est_ms": 1650.0}) == (1700.0, 1245.0)  # single segment
    assert fair({"H_ms": 1000.0, "H_minus_lag_ms": 545.0}) == (1000.0, 545.0)  # realtime: no tail
    assert fair({"H_ms": None}) == (None, None)
