"""Opt-in session recording (DESIGN A11): off by default, cascade capture when
on, server-side refusal when off, upload validation/traversal, retention."""
import json
import os
import time
import wave

import pytest
from fastapi.testclient import TestClient

import app.core.recording as recmod
from app.core.config import Settings, get_settings
from app.core.recording import RecordingConfig, RecordingError, RecordingStore
from app.main import create_app

FRAME = b"\x10\x00" * 480


@pytest.fixture
def env(tmp_path, monkeypatch):
    def setup(enabled: bool | None):
        for k in ("CASCADE_STT", "CASCADE_MT", "CASCADE_TTS"):
            monkeypatch.setenv(k, "fake")
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        if enabled is None:
            monkeypatch.delenv("RECORDING_ENABLED", raising=False)
        else:
            monkeypatch.setenv("RECORDING_ENABLED", "1" if enabled else "0")
        get_settings.cache_clear()
        monkeypatch.setattr(recmod, "_STORE", None)
        return TestClient(create_app())
    yield setup
    get_settings.cache_clear()
    recmod._STORE = None


def run_turn(client, record=True, session_id="s-1"):
    events, audio = [], 0
    with client.websocket_connect("/ws/cascade") as ws:
        ws.send_text(json.dumps({"type": "session.start", "pipeline": "cascade", "src": "en", "tgt": "es",
                                 "session_id": session_id, "record": record}))
        ws.send_text(json.dumps({"type": "turn.start", "turn_id": 1, "src": "en", "tgt": "es"}))
        for _ in range(10):
            ws.send_bytes(FRAME)
        ws.send_text(json.dumps({"type": "commit", "turn_id": 1, "final": True}))
        while True:
            m = ws.receive()
            if m.get("bytes") is not None:
                audio += 1
                continue
            ev = json.loads(m["text"])
            events.append(ev)
            if ev["type"] in ("turn.done", "turn.skipped") or (ev["type"] == "error" and ev.get("turn_id")):
                break
    return events, audio


def test_recording_is_off_by_default():
    assert RecordingConfig().enabled is False
    assert Settings().app_config()["recording"]["enabled"] is False


def test_cascade_writes_both_sides_when_enabled(env, tmp_path):
    client = env(True)
    events, _audio = run_turn(client)
    done = next(e for e in events if e["type"] == "turn.done")
    assert done["recording"] == {"source": "recordings/s-1/turn-1-source.wav",
                                 "target": "recordings/s-1/turn-1-target.wav"}
    with wave.open(str(tmp_path / "recordings/s-1/turn-1-source.wav")) as w:
        assert w.getframerate() == 24000 and w.getnframes() == 10 * 480  # every inbound frame
    with wave.open(str(tmp_path / "recordings/s-1/turn-1-target.wav")) as w:
        assert w.getnframes() > 0
    audit = [json.loads(x) for x in (tmp_path / "sessions/s-1.jsonl").read_text().splitlines()]
    assert {a["recording"]["side"] for a in audit} == {"source", "target"}


def test_nothing_recorded_without_the_session_toggle(env, tmp_path):
    client = env(True)
    events, _ = run_turn(client, record=False)
    assert not (tmp_path / "recordings").exists()
    assert all(e.get("recording") is None for e in events if e["type"] == "turn.done")


def test_server_refuses_recording_when_flag_off(env, tmp_path):
    client = env(None)  # config default: disabled
    events, _ = run_turn(client, record=True)
    assert any(e["type"] == "error" and e["code"] == "recording_refused" for e in events)
    assert [e for e in events if e["type"] == "turn.done"]  # the session itself still works
    assert not (tmp_path / "recordings").exists()


def test_upload_refused_when_flag_off(env, tmp_path):
    client = env(None)
    assert client.get("/api/recordings/config").json()["enabled"] is False
    r = client.post("/api/recordings/s-1/turns/1/source", content=b"x" * 10, headers={"content-type": "audio/webm"})
    assert r.status_code == 403
    assert not (tmp_path / "recordings").exists()


def test_upload_saved_and_validated(env, tmp_path):
    client = env(True)
    ok = client.post("/api/recordings/s-1/turns/2/target", content=b"webmdata",
                     headers={"content-type": "audio/webm;codecs=opus"})
    assert ok.status_code == 201 and ok.json()["path"] == "recordings/s-1/turn-2-target.webm"
    assert (tmp_path / "recordings/s-1/turn-2-target.webm").read_bytes() == b"webmdata"
    bad = {
        ("s-1", "1", "source", "text/plain"): 400,      # content type
        ("s-1", "0", "source", "audio/webm"): 400,      # turn out of range
        ("s-1", "1", "other", "audio/webm"): 400,       # side
        ("..", "1", "source", "audio/webm"): 400,       # traversal
        ("..%2F..%2Fetc", "1", "source", "audio/webm"): 400,
        (".hidden", "1", "source", "audio/webm"): 400,
    }
    for (sid, n, side, ctype), code in bad.items():
        r = client.post(f"/api/recordings/{sid}/turns/{n}/{side}", content=b"x", headers={"content-type": ctype})
        assert r.status_code in (code, 404, 422), (sid, n, side, ctype, r.status_code)
        assert r.status_code != 201
    big = client.post("/api/recordings/s-1/turns/3/source", content=b"x" * (21 * 1024 * 1024),
                      headers={"content-type": "audio/webm"})
    assert big.status_code == 413
    assert sorted(p.name for p in (tmp_path / "recordings").rglob("*") if p.is_file()) == ["turn-2-target.webm"]
    assert not list(tmp_path.parent.glob("etc*"))


def test_store_rejects_traversal_and_bad_names(tmp_path):
    st = RecordingStore(tmp_path, RecordingConfig(enabled=True))
    for sid in ("..", "../x", "a/b", "", "x" * 81, ".git", "a\\b"):
        with pytest.raises(RecordingError):
            st.turn_path(sid, 1, "source", "wav")
    with pytest.raises(RecordingError):
        st.turn_path("ok", 1, "source", "exe")
    with pytest.raises(PermissionError):
        RecordingStore(tmp_path, RecordingConfig(enabled=False)).write_wav("ok", 1, "source", FRAME)


def test_retention_sweep_and_manual_delete(env, tmp_path):
    st = RecordingStore(tmp_path, RecordingConfig(enabled=True, retention_days=30))
    old = st.write_wav("old", 1, "source", FRAME)
    new = st.write_wav("new", 1, "source", FRAME)
    t = time.time() - 31 * 86400
    os.utime(old, (t, t))
    assert st.sweep() == 1
    assert not old.exists() and not old.parent.exists() and new.exists()
    client = env(True)
    st2 = recmod.get_store()
    st2.write_wav("gone", 1, "target", FRAME)
    assert client.delete("/api/recordings/gone").json() == {"deleted_files": 1}
    assert not (tmp_path / "recordings/gone").exists()
    assert client.delete("/api/recordings/..").status_code in (400, 404)
