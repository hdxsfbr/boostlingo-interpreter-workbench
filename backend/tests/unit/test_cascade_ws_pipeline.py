"""End-to-end through the WS gateway with fake providers (CASCADE_*=fake)."""
import json

import pytest
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
    monkeypatch.setenv("CASCADE_STT", "fake")
    monkeypatch.setenv("CASCADE_MT", "fake")
    monkeypatch.setenv("CASCADE_TTS", "nope")
    get_settings.cache_clear()
    with TestClient(create_app()).websocket_connect("/ws/cascade") as ws:
        ws.send_text(json.dumps({"type": "session.start", "pipeline": "cascade"}))
        ev = json.loads(ws.receive_text())
        assert ev["type"] == "error" and ev["code"] == "config_error" and "nope" in ev["message"]
    get_settings.cache_clear()


def test_missing_openai_key_is_a_config_error(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CASCADE_STT", raising=False)
    get_settings.cache_clear()
    with TestClient(create_app()).websocket_connect("/ws/cascade") as ws:
        ws.send_text(json.dumps({"type": "session.start", "pipeline": "cascade"}))
        ev = json.loads(ws.receive_text())
        assert ev["code"] == "config_error" and "OPENAI_API_KEY" in ev["message"]
    get_settings.cache_clear()


def test_haiku_profile_is_gated_until_enabled(monkeypatch):
    from app.cascade.ws_pipeline import build_providers
    from app.core.config import Settings
    from app.core.errors import ConfigError

    s = Settings(openai_api_key="sk-x", anthropic_api_key="sk-ant-x", anthropic_workspace_id="wrkspc_x",
                 anthropic_enabled=False)
    with pytest.raises(ConfigError, match="cascade-haiku is disabled"):
        build_providers(s, {"stt": "fake", "mt": "anthropic", "tts": "fake"})
    s.anthropic_enabled = True
    built, names, _, _ = build_providers(s, {"stt": "fake", "mt": "anthropic", "tts": "fake"})
    assert names["mt"] == "anthropic" and built["mt"].headers()["anthropic-workspace-id"] == "wrkspc_x"


def test_openrouter_profile_needs_its_key():
    from app.cascade.ws_pipeline import build_providers
    from app.core.config import Settings
    from app.core.errors import ConfigError

    with pytest.raises(ConfigError, match="OPENROUTER_API_KEY"):
        build_providers(Settings(openai_api_key="sk-x", openrouter_api_key=None),  # pin env (lesson from M1)
                        {"stt": "fake", "mt": "openrouter", "tts": "fake"})
    built, _names, _, _ = build_providers(Settings(openai_api_key="sk-x", openrouter_api_key="sk-or-x"),
                                         {"stt": "fake", "mt": "openrouter", "tts": "fake"})
    from app.providers.base import TurnContext
    assert built["mt"].body("x", "en", "es", TurnContext())["provider"] == {"sort": "latency"}


def test_speculation_is_off_with_elevenlabs_by_default():
    from app.cascade.ws_pipeline import speculative_enabled
    cfg = {"speculative_mt": True}
    assert speculative_enabled(cfg, "openai") is True
    assert speculative_enabled(cfg, "elevenlabs") is False  # A9: no credits on cancelled runs
    assert speculative_enabled({**cfg, "speculative_with_elevenlabs": True}, "elevenlabs") is True
    assert speculative_enabled({"speculative_mt": False, "speculative_with_elevenlabs": True}, "elevenlabs") is False


def test_pipeline_with_mocked_elevenlabs_builds_session_without_speculation(monkeypatch):
    import app.cascade.ws_pipeline as wp
    from app.providers.fakes import FakeSTT, FakeTranslator, FakeTTS

    fake_tts = FakeTTS()
    fake_tts.name = "elevenlabs"
    monkeypatch.setattr(wp, "build_providers", lambda settings, providers, langs=None: (
        {"stt": FakeSTT(), "mt": FakeTranslator(), "tts": fake_tts},
        {"stt": "fake", "mt": "fake", "tts": "elevenlabs"}, {}, wp.Timeouts()))
    from app.core.config import Settings
    from app.core.events import SessionStart

    async def noop(*a, **k):
        return None

    class IO:
        event = staticmethod(noop)
        audio = staticmethod(noop)

    start = SessionStart(type="session.start", src="en", tgt="es", providers={"tts": "elevenlabs"})
    s = Settings(openai_api_key="sk-x")
    assert s.app_config()["cascade"]["speculative_mt"] is True
    import asyncio

    async def build():
        pipe = wp.CascadePipeline.from_settings(start, IO(), s)
        pipe._opened.cancel()
        return pipe

    pipe = asyncio.run(build())
    assert pipe.session.speculative is False
