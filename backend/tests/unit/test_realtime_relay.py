import asyncio
import base64
import json

import pytest
from fastapi.testclient import TestClient

from app.api import realtime_relay
from app.core.errors import RateLimited
from app.core.events import unpack_audio


class FakeUpstream:
    def __init__(self):
        self.sent, self.inbox, self.closed = [], asyncio.Queue(), False

    async def send(self, data):
        m = json.loads(data)
        self.sent.append(m)
        if m["type"] == "session.update":
            await self.inbox.put({"type": "session.updated"})
        elif m["type"] == "response.create":
            for ev in ({"type": "response.created", "response": {"id": "r1"}},
                       {"type": "response.output_audio.delta", "response_id": "r1", "item_id": "i",
                        "delta": base64.b64encode(b"\x01\x00\x02\x00").decode()},
                       {"type": "response.done", "response": {"id": "r1", "status": "completed"}}):
                await self.inbox.put(ev)

    async def recv(self):
        return json.dumps(await self.inbox.get())

    async def close(self):
        self.closed = True


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    from app.core.config import get_settings
    get_settings.cache_clear()
    from app.main import create_app
    up = FakeUpstream()

    async def connect(url, key):
        assert "model=gpt-realtime" in url and url.endswith("gpt-realtime")
        return up
    monkeypatch.setattr(realtime_relay, "_connect", connect)
    yield TestClient(create_app()), up
    get_settings.cache_clear()


def test_relay_session_config_and_audio_roundtrip(client):
    c, up = client
    with c.websocket_connect("/ws/realtime") as ws:
        ws.send_text(json.dumps({"type": "relay.start", "a": "en", "b": "es", "turn_mode": "ptt"}))
        assert json.loads(ws.receive_text()) == {"type": "relay.ready", "model": "gpt-realtime"}
        upd = up.sent[0]["session"]
        assert "model" not in upd and upd["audio"]["input"]["format"]["rate"] == 24000
        assert upd["audio"]["input"]["turn_detection"] is None
        ws.send_bytes(b"\x00\x00" * 480)
        ws.send_text(json.dumps({"type": "oai", "event": {"type": "input_audio_buffer.commit"}}))
        ws.send_text(json.dumps({"type": "oai", "event": {"type": "response.create"}}))
        assert json.loads(ws.receive_text())["type"] == "response.created"
        resp_idx, pcm = unpack_audio(ws.receive_bytes())
        assert (resp_idx, pcm) == (1, b"\x01\x00\x02\x00")
        marker = json.loads(ws.receive_text())
        assert marker == {"type": "response.output_audio.delta", "response_id": "r1", "item_id": "i"}
        assert json.loads(ws.receive_text())["type"] == "response.done"
    types = [m["type"] for m in up.sent]
    assert types[:4] == ["session.update", "input_audio_buffer.append", "input_audio_buffer.commit", "response.create"]
    assert base64.b64decode(up.sent[1]["audio"]) == b"\x00\x00" * 480


def test_relay_rejects_non_whitelisted_events(client):
    c, up = client
    with c.websocket_connect("/ws/realtime") as ws:
        ws.send_text(json.dumps({"type": "relay.start", "turn_mode": "vad"}))
        ws.receive_text()
        assert up.sent[0]["session"]["audio"]["input"]["turn_detection"]["type"] == "server_vad"
        ws.send_text(json.dumps({"type": "oai", "event": {"type": "session.update", "session": {}}}))
        err = json.loads(ws.receive_text())
        assert err["type"] == "error" and err["code"] == "bad_message"
    assert all(m["type"] != "session.update" or "audio" in m["session"] for m in up.sent)


def test_relay_requires_start_message(client):
    c, _ = client
    with c.websocket_connect("/ws/realtime") as ws:
        ws.send_text(json.dumps({"type": "nope", "a": 3}))
        err = json.loads(ws.receive_text())
        assert err["code"] == "bad_message"


def test_relay_reports_upstream_rate_limit(client, monkeypatch):
    c, _ = client

    async def limited(url, key):
        raise RateLimited("realtime socket rate-limited", provider="openai", stage="realtime")
    monkeypatch.setattr(realtime_relay, "_connect", limited)
    with c.websocket_connect("/ws/realtime") as ws:
        ws.send_text(json.dumps({"type": "relay.start"}))
        err = json.loads(ws.receive_text())
        assert err["code"] == "rate_limited" and err["retryable"] is True
