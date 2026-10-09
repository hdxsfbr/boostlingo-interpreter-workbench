"""One minimal live call per provider (PRD CQ-3.5). Opt-in, see conftest.py."""
import os

import pytest

from app.providers.base import Commit, TurnContext

from .conftest import fixture_pcm, need

pytestmark = pytest.mark.live


async def _chunks(*xs: str):
    for x in xs:
        yield x


async def test_openai_stt_live():
    need("OPENAI_API_KEY")
    from app.providers.stt.openai_live import OpenAILiveSTT
    pcm = fixture_pcm("en-s01")  # "Do you have any allergies?"
    stt = OpenAILiveSTT(os.environ["OPENAI_API_KEY"], languages=["en", "es"])

    async def audio():
        for i in range(0, len(pcm), 4800):
            yield pcm[i:i + 4800]
        yield Commit(final=True)
    finals = []
    try:
        async for ev in stt.stream(audio(), ["en", "es"]):
            if ev.final:
                finals.append(ev.text)
                break
    finally:
        await stt.aclose()
    assert "allerg" in " ".join(finals).lower()


async def test_openai_mt_live():
    need("OPENAI_API_KEY")
    from app.providers.mt.openai import OpenAITranslator
    mt = OpenAITranslator(os.environ["OPENAI_API_KEY"], model="gpt-5.4-nano")
    out = "".join([t async for t in mt.stream("Do you have any allergies?", "en", "es", TurnContext())])
    assert "alerg" in out.lower()


async def test_openai_tts_live():
    need("OPENAI_API_KEY")
    import httpx

    from app.providers.tts.openai import OpenAITTS
    async with httpx.AsyncClient(timeout=30) as client:  # own client: the shared one is bound to another test's loop
        tts = OpenAITTS(os.environ["OPENAI_API_KEY"], model="gpt-4o-mini-tts", client=client)
        pcm = b"".join([b async for b in tts.stream(_chunks("Hola."), "es", "marin")])
    assert len(pcm) > 24000  # > 0.5 s of 24 kHz PCM16


def test_realtime_session_mint_live(monkeypatch):
    need("OPENAI_API_KEY")
    from fastapi.testclient import TestClient

    from app.core.config import get_settings
    from app.main import create_app
    monkeypatch.setenv("DATA_DIR", "/tmp/live-tests-data")
    get_settings.cache_clear()
    r = TestClient(create_app()).post("/api/realtime/session", json={"model": "gpt-realtime-mini"})
    assert r.status_code == 200, r.text[:200]
    assert r.json()["value"].startswith("ek_") and r.json()["model"] == "gpt-realtime-mini"


async def test_openrouter_mt_live():
    need("OPENROUTER_API_KEY")
    from app.providers.mt.openrouter import OpenRouterTranslator
    mt = OpenRouterTranslator(os.environ["OPENROUTER_API_KEY"], model="anthropic/claude-haiku-5.5")
    out = "".join([t async for t in mt.stream("Do you have any allergies?", "en", "es", TurnContext())])
    assert "alerg" in out.lower()


async def test_elevenlabs_tts_live_through_credit_guard(tmp_path):
    need("ELEVENLABS_API_KEY_FILE")
    from pathlib import Path

    from app.core.budget import ElevenLabsBudget, Ledger
    from app.core.config import REPO_ROOT
    from app.providers.tts.elevenlabs import ElevenLabsTTS
    key = Path(os.environ["ELEVENLABS_API_KEY_FILE"]).read_text().strip()
    if not key:
        pytest.skip("ElevenLabs key file is empty")
    text = "Hola."  # 5 characters: the whole test spends 5 credits
    ledger = Ledger(REPO_ROOT / "data" / "elevenlabs_ledger.json")  # the real ledger, so the month cap holds
    tts = ElevenLabsBudget(ElevenLabsTTS(key, voices={"es": "JBFqnCBsd6RMkjVDRZzb"}, prewarm=False),
                           enabled=True, ledger=ledger, session_char_cap=50, month_char_cap=8000)
    before = ledger.used()
    try:
        pcm = b"".join([b async for b in tts.stream(_chunks(text), "es", "JBFqnCBsd6RMkjVDRZzb")])
    finally:
        await tts.aclose()
    assert len(pcm) > 0 and ledger.used() - before == len(text)
