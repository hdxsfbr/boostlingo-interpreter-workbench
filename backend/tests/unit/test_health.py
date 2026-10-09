from fastapi.testclient import TestClient

from app.main import create_app


def test_healthz_is_minimal_and_details_move_to_api_health(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    from app.core.config import get_settings

    get_settings.cache_clear()
    c = TestClient(create_app())
    assert c.get("/healthz").json() == {"status": "ok"}  # A15: nothing about models, providers or keys
    body = c.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["providers"]["openai"] is True
    assert "sk-test-not-real" not in str(body)
    mt = {o["name"]: o for o in body["swaps"]["mt"]}
    assert mt["openai"]["ready"] is True and set(mt) == {"openai", "anthropic", "openrouter"}
    tts = {o["name"]: o for o in body["swaps"]["tts"]}
    assert tts["elevenlabs"]["ready"] is False and "credits" in tts["elevenlabs"]["reason"]
    get_settings.cache_clear()
