import json

from fastapi.testclient import TestClient

from app.core.events import unpack_audio
from app.main import create_app


def test_loopback_echoes_turn_audio_after_final_commit():
    client = TestClient(create_app())
    with client.websocket_connect("/ws/cascade") as ws:
        ws.send_text(json.dumps({"type": "session.start", "pipeline": "loopback"}))
        assert json.loads(ws.receive_text())["type"] == "session.ready"
        ws.send_text(json.dumps({"type": "turn.start", "turn_id": 7, "src": "en", "tgt": "es"}))
        assert json.loads(ws.receive_text())["type"] == "turn.started"
        pcm = bytes(range(256)) * 15  # 3840 bytes = 4 x 20 ms chunks
        ws.send_bytes(pcm[:1920])
        ws.send_bytes(pcm[1920:])
        ws.send_text(json.dumps({"type": "commit", "turn_id": 7, "final": False}))  # ignored
        ws.send_text(json.dumps({"type": "commit", "turn_id": 7, "final": True}))
        got, events = b"", []
        while True:
            m = ws.receive()
            if m.get("bytes") is not None:
                tid, chunk = unpack_audio(m["bytes"])
                assert tid == 7
                got += chunk
            else:
                ev = json.loads(m["text"])
                events.append(ev["type"])
                if ev["type"] == "turn.done":
                    break
        assert got == pcm
        assert "latency.mark" in events


def test_messages_before_session_start_are_rejected():
    client = TestClient(create_app())
    with client.websocket_connect("/ws/cascade") as ws:
        ws.send_text(json.dumps({"type": "commit", "turn_id": 1}))
        ev = json.loads(ws.receive_text())
        assert ev["type"] == "error" and ev["code"] == "no_session"
        ws.send_text("not json")
        assert json.loads(ws.receive_text())["code"] == "bad_message"
        ws.send_text(json.dumps({"type": "ping", "t": 1.0}))
        assert json.loads(ws.receive_text()) == {"type": "pong", "t": 1.0}
