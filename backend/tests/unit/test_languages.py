"""Language pairs are config (FR-5, DESIGN A14): loading, validation, defaults,
and both directions of both pairs reaching prompts/instructions/STT hints."""
import shutil

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import REPO_ROOT, get_settings
from app.core.languages import LanguagesConfig, languages_config, load_languages

TWO_PAIRS = {
    "languages": {"en": {"name": "English"}, "es": {"name": "Spanish"}, "fr": {"name": "French", "voices": {"openai": "cedar"}}},
    "default_pair": "en-es",
    "pairs": [{"id": "en-es", "a": "en", "b": "es", "benchmarked": True, "glossary": {"ER": "urgencias"}},
              {"id": "en-fr", "a": "en", "b": "fr"}],
}


@pytest.fixture
def two_pairs(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    shutil.copytree(REPO_ROOT / "config", cfg)
    (cfg / "languages.yaml").write_text(yaml.safe_dump(TWO_PAIRS))
    monkeypatch.setenv("CONFIG_DIR", str(cfg))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    get_settings.cache_clear()
    yield languages_config()
    get_settings.cache_clear()


def test_repo_config_loads_with_en_es_default():
    lc = load_languages(REPO_ROOT / "config" / "languages.yaml")
    assert lc.default.id == "en-es" and lc.default.langs == ["en", "es"] and lc.default.benchmarked
    assert lc.name("es") == "Spanish" and lc.name("xx") == "xx"
    assert lc.benchmarked().id == "en-es"


@pytest.mark.parametrize("patch,msg", [
    ({"pairs": [{"id": "x", "a": "en", "b": "de"}]}, "not defined"),
    ({"pairs": [{"id": "x", "a": "en", "b": "en"}]}, "must differ"),
    ({"pairs": [{"id": "x", "a": "en", "b": "es"}, {"id": "x", "a": "es", "b": "en"}]}, "duplicate pair ids"),
    ({"languages": {"EN": {"name": "English"}}}, "ISO 639"),
    ({"default_pair": "en-de"}, "default_pair"),
    ({"pairs": []}, "at least 1"),
])
def test_validation(patch, msg):
    with pytest.raises(ValidationError, match=msg):
        LanguagesConfig.model_validate({**TWO_PAIRS, **patch})


def test_resolve_defaults_order_and_refusal(two_pairs):
    assert two_pairs.resolve(None, None) == ("en", "es")
    assert two_pairs.resolve("fr", "en") == ("fr", "en")  # either order of a configured pair
    with pytest.raises(ValueError, match="not configured"):
        two_pairs.resolve("es", "fr")
    pub = two_pairs.public()
    assert [p["label"] for p in pub["pairs"]] == ["English ↔ Spanish", "English ↔ French"]
    assert pub["default_pair"] == "en-es"


@pytest.mark.parametrize("src,tgt,S,T", [("en", "es", "English", "Spanish"), ("es", "en", "Spanish", "English"),
                                         ("en", "fr", "English", "French"), ("fr", "en", "French", "English")])
def test_both_directions_of_both_pairs_reach_prompts(two_pairs, src, tgt, S, T):
    from app.providers.base import TurnContext
    from app.providers.mt.openai import build_input
    from app.providers.tts.openai import OpenAITTS
    from app.realtime.session_config import build_interpreter_session
    assert f"Translate from {S} to {T}:" in build_input("hi", src, tgt, TurnContext())
    assert f"Speak {T} clearly" in OpenAITTS("sk-test")._body("x", tgt, "")["instructions"]
    s = build_interpreter_session(src, tgt, model="gpt-realtime")
    assert f"between {S} and {T}" in s["instructions"]


def test_api_languages_and_mint_refuses_unconfigured_pair(two_pairs, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    get_settings.cache_clear()
    from app.main import create_app
    c = TestClient(create_app())
    j = c.get("/api/languages").json()
    assert [p["id"] for p in j["pairs"]] == ["en-es", "en-fr"] and j["languages"]["fr"]["name"] == "French"
    r = c.post("/api/realtime/session", json={"a": "es", "b": "fr"})
    assert r.status_code == 400 and "not configured" in r.json()["detail"]["message"]


def test_stt_hint_follows_the_session_pair():
    from app.providers.stt.openai_live import OpenAILiveSTT
    stt = OpenAILiveSTT("sk-test")
    assert "languages" not in stt._session_update([])["session"]["audio"]["input"]["transcription"]
    assert stt._session_update(["en", "fr"])["session"]["audio"]["input"]["transcription"]["languages"] == ["en", "fr"]


async def test_cascade_pipeline_resolves_pair_glossary_voice_and_refuses_unknown(two_pairs, monkeypatch):
    import app.cascade.ws_pipeline as wp
    from app.core.events import SessionStart
    seen = {}
    real_build = wp.build_providers

    def fake_build(settings, providers, langs=None):
        seen["langs"] = langs
        raise RuntimeError("stop after resolve")
    monkeypatch.setattr(wp, "build_providers", fake_build)
    with pytest.raises(RuntimeError):
        wp.CascadePipeline.from_settings(SessionStart(src="fr", tgt="en"), io=None, settings=get_settings())
    assert seen["langs"] == ["fr", "en"]
    with pytest.raises(RuntimeError):
        wp.CascadePipeline.from_settings(SessionStart(), io=None, settings=get_settings())
    assert seen["langs"] == ["en", "es"]  # default pair
    with pytest.raises(ValueError, match="not configured"):
        wp.CascadePipeline.from_settings(SessionStart(src="es", tgt="fr"), io=None, settings=get_settings())
    monkeypatch.setattr(wp, "build_providers", real_build)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    get_settings.cache_clear()
    _, _names, voices, _ = wp.build_providers(get_settings(), {"stt": "openai_live", "mt": "openai", "tts": "openai"}, ["en", "fr"])
    assert voices["fr"] == "cedar" and voices["en"] == "marin"  # languages.yaml fills, app.yaml wins
