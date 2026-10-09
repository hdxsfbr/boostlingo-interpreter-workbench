"""Secret minting with a mocked OpenAI endpoint; session config shape."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

import app.api.realtime_session as rs
from app.core.config import get_settings
from app.main import create_app
from app.realtime.session_config import build_interpreter_session


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret")
    get_settings.cache_clear()
    calls = []

    def install(handler):
        def wrapped(req):
            calls.append(req)
            return handler(req)
        monkeypatch.setattr(rs, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(wrapped)))
        return calls

    yield TestClient(create_app()), install
    get_settings.cache_clear()


def test_mints_secret_without_leaking_key(client):
    c, install = client
    calls = install(lambda req: httpx.Response(200, json={"value": "ek_abc", "expires_at": 123, "session": {}}))
    r = c.post("/api/realtime/session", json={"a": "en", "b": "es"})
    assert r.status_code == 200
    assert r.json() == {"value": "ek_abc", "expires_at": 123, "model": "gpt-realtime-mini", "turn_mode": "ptt"}
    assert "sk-test-secret" not in r.text
    sent = json.loads(calls[0].content)
    assert calls[0].headers["authorization"] == "Bearer sk-test-secret"
    assert sent["expires_after"] == {"anchor": "created_at", "seconds": 600}
    s = sent["session"]
    assert s["type"] == "realtime" and s["model"] == "gpt-realtime-mini" and s["output_modalities"] == ["audio"]
    assert s["audio"]["input"]["turn_detection"] is None  # push-to-talk default


def test_rejects_unlisted_models(client):
    c, install = client
    install(lambda req: httpx.Response(200, json={"value": "ek"}))
    assert c.post("/api/realtime/session", json={"model": "gpt-4o"}).status_code == 400


@pytest.mark.parametrize("status,expect,code", [(401, 502, "auth_error"), (429, 429, "rate_limited"),
                                                (500, 502, "provider_error")])
def test_upstream_errors_are_mapped(client, status, expect, code):
    c, install = client
    install(lambda req: httpx.Response(status, json={"error": {"message": "x"}}, headers={"retry-after": "2"}))
    r = c.post("/api/realtime/session", json={})
    assert r.status_code == expect and r.json()["detail"]["code"] == code


def test_vad_config_has_matched_silence_and_no_interrupt():
    s = build_interpreter_session("en", "es", model="gpt-realtime-mini", turn_mode="vad", silence_duration_ms=300)
    td = s["audio"]["input"]["turn_detection"]
    assert td == {"type": "server_vad", "threshold": 0.5, "prefix_padding_ms": 300, "silence_duration_ms": 300,
                  "create_response": True, "interrupt_response": False}
    assert "never answer" in s["instructions"]
    assert s["audio"]["input"]["transcription"] == {"model": "gpt-4o-transcribe"}
