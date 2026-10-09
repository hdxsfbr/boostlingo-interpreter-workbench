"""ElevenLabs credit guard: disabled flag, session cap, month ledger, abort before the call."""
import json
from datetime import UTC, datetime

import pytest

from app.core.budget import ElevenLabsBudget, Ledger
from app.core.errors import BudgetExceeded


class SpyTTS:
    name = "elevenlabs"

    def __init__(self):
        self.received: list[str] = []
        self.calls = 0

    async def stream(self, chunks, lang, voice):
        self.calls += 1
        async for c in chunks:
            self.received.append(c)
            yield b"\x01\x00" * len(c)


async def chunks(*xs):
    for x in xs:
        yield x


async def drain(it):
    return [b async for b in it]


def guard(tmp_path, *, enabled=True, session=1500, month=8000, now=None):
    led = Ledger(tmp_path / "ledger.json", now=now or (lambda: datetime(2026, 10, 8, tzinfo=UTC)))
    spy = SpyTTS()
    return ElevenLabsBudget(spy, enabled=enabled, ledger=led, session_char_cap=session, month_char_cap=month), spy, led


async def test_disabled_refuses_before_any_call(tmp_path):
    g, spy, led = guard(tmp_path, enabled=False)
    with pytest.raises(BudgetExceeded, match="disabled"):
        await drain(g.stream(chunks("Hola."), "es", "v"))
    assert spy.calls == 0 and led.used() == 0


async def test_session_cap_stops_before_the_chunk_is_sent(tmp_path):
    g, spy, led = guard(tmp_path, session=10)
    with pytest.raises(BudgetExceeded, match="session cap"):
        await drain(g.stream(chunks("Hola amigo", "más texto"), "es", "v"))
    assert spy.received == ["Hola amigo"]  # second chunk never reached the provider
    assert g.session_used == 10 and led.used() == 10


async def test_month_ledger_persists_across_sessions_and_months(tmp_path):
    g1, _, led = guard(tmp_path, month=12)
    await drain(g1.stream(chunks("12345678"), "es", "v"))
    g2, spy2, _ = guard(tmp_path, month=12)  # new session, same ledger file
    with pytest.raises(BudgetExceeded, match="monthly cap"):
        await drain(g2.stream(chunks("12345"), "es", "v"))
    assert spy2.received == []
    assert json.loads((tmp_path / "ledger.json").read_text()) == {"2026-10": 8}
    g3, spy3, _ = guard(tmp_path, month=12, now=lambda: datetime(2026, 11, 1, tzinfo=UTC))
    await drain(g3.stream(chunks("12345"), "es", "v"))  # new month, fresh allowance
    assert spy3.received == ["12345"]


def test_build_providers_refuses_elevenlabs_unless_enabled(tmp_path):
    from app.cascade.ws_pipeline import build_providers
    from app.core.config import Settings
    from app.core.errors import ConfigError

    s = Settings(openai_api_key="sk-x", elevenlabs_enabled=False, data_dir=tmp_path)
    with pytest.raises(ConfigError, match="ElevenLabs is disabled"):
        build_providers(s, {"stt": "fake", "mt": "fake", "tts": "elevenlabs"})
    key = tmp_path / "el_key"
    key.write_text("xi-test\n")
    s = Settings(openai_api_key="sk-x", elevenlabs_enabled=True, elevenlabs_api_key_file=key, data_dir=tmp_path)
    built, names, _, _ = build_providers(s, {"stt": "fake", "mt": "fake", "tts": "elevenlabs"})
    assert isinstance(built["tts"], ElevenLabsBudget) and built["tts"].inner.api_key == "xi-test"
