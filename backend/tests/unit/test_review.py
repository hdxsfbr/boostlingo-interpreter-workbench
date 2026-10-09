"""Review tab (DESIGN A12): blindness, save/resume, validation, aggregation,
recorded-session sets, and the preload of Andre's blind ratings matching
eval/blind_results.py output (docs/benchmarks/blind/results.csv)."""
import csv
import json
import statistics
import sys
import types
import wave

import pytest
from fastapi.testclient import TestClient

import app.api.review as reviewmod
from app.core.config import REPO_ROOT, get_settings
from app.main import create_app
from app.review.results import aggregate
from app.review.store import Item

BLIND = REPO_ROOT / "docs" / "benchmarks" / "blind"
VARIANTS = ("realtime", "cascade-openai", "cascade-haiku", "cascade-elevenlabs")
SET = "blind-m5"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BENCH_DIR", str(REPO_ROOT / "docs" / "benchmarks"))
    get_settings.cache_clear()
    monkeypatch.setattr(reviewmod, "_STORE", None)
    yield TestClient(create_app())
    get_settings.cache_clear()
    reviewmod._STORE = None


def rate(client, item, rater="bob", **kw):
    body = {"rater": rater, "adequacy": 4, "fluency": 4, "naturalness": 4, "notes": "", **kw}
    return client.put(f"/api/review/sets/{SET}/items/{item}/rating", json=body)


def leaks_variant(text: str) -> bool:
    return any(v in text for v in ("realtime", "cascade", "haiku", "elevenlabs", "openai"))


# ----- preload
def test_preload_marks_blind_set_complete_for_andre(client):
    sets = client.get("/api/review/sets", params={"rater": "andre"}).json()
    blind = next(s for s in sets if s["id"] == SET)
    assert blind["kind"] == "blind" and blind["items"] == 48
    assert blind["progress"] == {"done": 48, "total": 48, "complete": True}
    assert blind["revealed"] is True
    # idempotent: a second bootstrap does not duplicate or overwrite
    from app.review import sources
    assert sources.preload_ratings(reviewmod.get_review_store(), BLIND) == 0


def test_results_match_blind_results_output(client):
    rows = client.get(f"/api/review/sets/{SET}/results", params={"rater": "andre"}).json()["rows"]
    got = {(r["variant"], r["scope"]): r for r in rows}
    expected = list(csv.DictReader((BLIND / "results.csv").read_text().splitlines()))  # eval/blind_results.py output
    assert len(expected) == 12
    for e in expected:
        g = got[(e["profile"], e["scope"])]
        assert g["n"] == int(e["n"])
        for d in ("adequacy", "fluency", "naturalness"):
            for k in ("mean", "median", "sd", "min", "max"):
                assert g[d][k] == pytest.approx(float(e[f"{d}_{k}"])), (e["profile"], e["scope"], d, k)
        assert g["composite_mean"] == pytest.approx(float(e["composite_mean"]))
    # and against blind_results.py's own load()+stats() (sacrebleu is only needed for chrF)
    try:  # sacrebleu is only needed for chrF; stub it where it isn't installed
        import sacrebleu  # noqa: F401
    except ImportError:
        sys.modules["sacrebleu"] = types.ModuleType("sacrebleu")
    from eval import blind_results as br
    src = br.load()
    for v in VARIANTS:
        for d in br.DIMS:
            s = br.stats([r[d] for r in src if r["profile"] == v])
            assert got[(v, "all")][d]["mean"] == s["mean"] and got[(v, "all")][d]["sd"] == s["sd"]
    # M5 latency + chrF ride along
    assert got[("realtime", "all")]["m5"]["H_p50"] == 1002
    assert got[("cascade-openai", "en->es")]["m5"]["chrF"] == 72.9


# ----- blindness
def test_no_variant_in_api_before_reveal(client):
    r = client.get(f"/api/review/sets/{SET}", params={"rater": "bob"})
    body = r.json()
    assert r.status_code == 200 and body["revealed"] is False and len(body["items"]) == 48
    assert all("variant" not in it and "ref_id" not in it for it in body["items"])
    assert not leaks_variant(r.text)
    assert client.get(f"/api/review/sets/{SET}/results", params={"rater": "bob"}).status_code == 403
    assert client.get(f"/api/review/sets/{SET}/results.csv", params={"rater": "bob"}).status_code == 403
    exp = client.get(f"/api/review/sets/{SET}/ratings.csv", params={"rater": "bob"})
    assert exp.status_code == 200 and not leaks_variant(exp.text)
    sets = client.get("/api/review/sets", params={"rater": "bob"}).text
    assert not leaks_variant(sets.replace("blind-m5", ""))
    au = client.get(body["items"][0]["audio_url"])
    assert au.status_code == 200 and au.headers["content-type"].startswith("audio/")
    assert not leaks_variant(json.dumps(dict(au.headers)))


def test_reveal_shows_variants_and_flags_later_ratings(client):
    assert rate(client, "clip_001.ogg").status_code == 200
    assert client.post(f"/api/review/sets/{SET}/reveal", json={"rater": "bob"}).json() == {"revealed": True}
    body = client.get(f"/api/review/sets/{SET}", params={"rater": "bob"}).json()
    assert body["revealed"] and {it["variant"] for it in body["items"]} == set(VARIANTS)
    rate(client, "clip_002.ogg")
    flags = {r["item_id"]: r["after_reveal"] for r in reviewmod.get_review_store().ratings(SET, "bob")}
    assert flags == {"clip_001.ogg": 0, "clip_002.ogg": 1}
    assert client.get(f"/api/review/sets/{SET}/results", params={"rater": "bob"}).status_code == 200


def test_completing_the_set_reveals(client):
    items = [it["item_id"] for it in client.get(f"/api/review/sets/{SET}", params={"rater": "cy"}).json()["items"]]
    for it in items[:-1]:
        rate(client, it, rater="cy")
    assert client.get(f"/api/review/sets/{SET}", params={"rater": "cy"}).json()["revealed"] is False
    last = rate(client, items[-1], rater="cy").json()
    assert last["progress"]["complete"] is True
    assert client.get(f"/api/review/sets/{SET}", params={"rater": "cy"}).json()["revealed"] is True


# ----- save / resume / validation
def test_save_and_resume(client):
    assert rate(client, "clip_003.ogg", rater="Dana  Q", adequacy=5, fluency=None, naturalness=None, notes=" hm ").status_code == 200
    body = client.get(f"/api/review/sets/{SET}", params={"rater": "dana q"}).json()  # names are case/space-normalised
    assert body["ratings"]["clip_003.ogg"] == {"adequacy": 5, "fluency": None, "naturalness": None, "notes": "hm"}
    assert body["progress"]["done"] == 0  # partial ratings don't count as done
    rate(client, "clip_003.ogg", rater="dana q", adequacy=3, fluency=4, naturalness=5)
    body = client.get(f"/api/review/sets/{SET}", params={"rater": "dana q"}).json()
    assert body["ratings"]["clip_003.ogg"]["adequacy"] == 3 and body["progress"]["done"] == 1
    # Andre's preload is untouched by other raters
    assert client.get(f"/api/review/sets/{SET}", params={"rater": "andre"}).json()["progress"]["done"] == 48
    # delete scratch data
    assert client.delete(f"/api/review/sets/{SET}/ratings", params={"rater": "dana q"}).json() == {"deleted": 1}
    assert client.get(f"/api/review/sets/{SET}", params={"rater": "dana q"}).json()["ratings"] == {}


@pytest.mark.parametrize("kw,code", [
    ({"adequacy": 6}, 400), ({"adequacy": 0}, 400), ({"fluency": "x"}, 422), ({"notes": "n" * 2001}, 422),
    ({"rater": "../etc"}, 400), ({"rater": ""}, 400),
])
def test_rating_validation(client, kw, code):
    assert rate(client, "clip_001.ogg", **kw).status_code == code


def test_unknown_set_item_and_bad_ids(client):
    assert rate(client, "clip_999.ogg").status_code == 404
    assert client.get("/api/review/sets/nope", params={"rater": "bob"}).status_code == 404
    assert client.get(f"/api/review/sets/{SET}/items/..%2Fkey.csv/audio").status_code == 404
    assert client.post("/api/review/sessions/..bad").status_code == 400


# ----- aggregation
def test_aggregate_per_variant_and_direction():
    items = [Item("s", f"i{k}", k, "a", "en->es" if k % 2 else "es->en", variant="A" if k < 2 else "B") for k in range(4)]
    ratings = [{"item_id": "i0", "adequacy": 5, "fluency": 3, "naturalness": None},
               {"item_id": "i1", "adequacy": 3, "fluency": 3, "naturalness": 4},
               {"item_id": "i2", "adequacy": 4, "fluency": 4, "naturalness": 4}]
    rows = {(r["variant"], r["scope"]): r for r in aggregate(items, ratings)}
    a = rows[("A", "all")]
    assert a["n"] == 2 and a["adequacy"]["mean"] == 4 and a["adequacy"]["sd"] == round(statistics.stdev([5, 3]), 2)
    assert a["naturalness"]["n"] == 1 and a["composite_mean"] == round(statistics.mean([4, 3, 4]), 2)
    assert rows[("A", "en->es")]["adequacy"]["mean"] == 3
    assert rows[("B", "en->es")]["n"] == 0 and rows[("B", "en->es")]["composite_mean"] is None


# ----- recorded sessions
def _fake_session(data_dir, sid="2026-10-09T01-00-00-000Z-abcde"):
    d = data_dir / "recordings" / sid
    d.mkdir(parents=True)
    for n in (1, 2):
        with wave.open(str(d / f"turn-{n}-target.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            w.writeframes(b"\x10\x00" * 2400)
    (data_dir / "sessions").mkdir()
    recs = [{"record": {"turn_id": 1, "mode": "cascade", "src": "en", "tgt": "es", "source_text": "Hello",
                        "target_text": "Hola"}},
            {"record": {"turn_id": 2, "mode": "cascade", "src": "es", "tgt": "en", "source_text": "Gracias",
                        "target_text": "Thank you"}}]
    (data_dir / "sessions" / f"{sid}.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    return sid


def test_recorded_session_review(client, tmp_path):
    sid = _fake_session(tmp_path)
    lst = client.get("/api/review/sessions").json()
    assert lst == [{"session_id": sid, "turns": 2, "modes": ["cascade"], "set_id": None}]
    set_id = client.post(f"/api/review/sessions/{sid}").json()["set_id"]
    body = client.get(f"/api/review/sets/{set_id}", params={"rater": "bob"}).json()
    assert body["blind"] is False and body["revealed"] is True
    assert [(i["item_id"], i["direction"], i["source_text"], i["target_text"], i["variant"]) for i in body["items"]] == [
        ("turn-1", "en->es", "Hello", "Hola", "cascade"), ("turn-2", "es->en", "Gracias", "Thank you", "cascade")]
    assert client.get(body["items"][0]["audio_url"]).status_code == 200
    r = client.put(f"/api/review/sets/{set_id}/items/turn-1/rating",
                   json={"rater": "bob", "adequacy": 5, "fluency": 4, "naturalness": 3})
    assert r.status_code == 200
    res = client.get(f"/api/review/sets/{set_id}/results", params={"rater": "bob"}).json()["rows"]
    assert res[0]["variant"] == "cascade" and res[0]["adequacy"]["mean"] == 5
    # re-import keeps ratings
    client.post(f"/api/review/sessions/{sid}")
    assert client.get(f"/api/review/sets/{set_id}", params={"rater": "bob"}).json()["progress"]["done"] == 1
    assert client.get("/api/review/sessions").json()[0]["set_id"] == set_id
