"""End-to-end through the WS gateway with fake providers (CASCADE_*=fake)."""
import json

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.events import unpack_audio
from app.main import create_app


def test_cascade_over_websocket_with_fake_providers(monkeypatch):
    for k in ("CASCADE_STT", "CASCADE_MT", "CASCADE_TTS"):
        monkeypatch.setenv(k, "fake")
    get_settings.cache_clear()
    client = TestClient(create_app())
    with client.websocket_connect("/ws/cascade") as ws:
        ws.send_text(json.dumps({"type": "session.start", "pipeline": "cascade", "src": "en", "tgt": "es"}))
        ready = json.loads(ws.receive_text())
        assert ready == {"type": "session.ready", "pipeline": "cascade",
                         "providers": {"stt": "fake", "mt": "fake", "tts": "fake"}}
        ws.send_text(json.dumps({"type": "turn.start", "turn_id": 1, "src": "en", "tgt": "es"}))
        for _ in range(10):
            ws.send_bytes(b"\x10\x00" * 480)
        ws.send_text(json.dumps({"type": "commit", "turn_id": 1, "final": True}))
        types, audio = [], 0
        while True:
            m = ws.receive()
            if m.get("bytes") is not None:
                tid, pcm = unpack_audio(m["bytes"])
                assert tid == 1
                audio += len(pcm)
                continue
            ev = json.loads(m["text"])
            types.append(ev["type"])
            if ev["type"] in ("turn.done", "error", "turn.skipped"):
                break
        assert types[-1] == "turn.done", types
        assert {"transcript.final", "translation.final", "latency.mark"} <= set(types)
        assert audio > 0
    get_settings.cache_clear()


def test_unknown_provider_reports_config_error(monkeypatch):
    monkeypatch.setenv("CASCADE_TTS", "nope")
    get_settings.cache_clear()
    with TestClient(create_app()).websocket_connect("/ws/cascade") as ws:
        ws.send_text(json.dumps({"type": "session.start", "pipeline": "cascade"}))
        ev = json.loads(ws.receive_text())
        assert ev["type"] == "error" and ev["code"] == "config_error" and "nope" in ev["message"]
    get_settings.cache_clear()
