"""Live provider tests: each test skips unless LIVE_TESTS=1 and its key is present.

    cd backend && set -a && source ../.env && set +a && LIVE_TESTS=1 .venv/bin/pytest -m live tests/live -v

ElevenLabs additionally needs ELEVENLABS_API_KEY_FILE (a key file, never .env)
and goes through the ElevenLabsBudget credit guard with a 5-character text.
"""
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def need(*env: str) -> None:
    if os.environ.get("LIVE_TESTS") != "1":
        pytest.skip("live tests are opt-in: LIVE_TESTS=1")
    missing = [e for e in env if not os.environ.get(e)]
    if missing:
        pytest.skip(f"key not set: {missing}")


def fixture_pcm(uid: str = "en-s01") -> bytes:
    import wave
    p = ROOT / "data" / "fixtures" / f"{uid}.wav"
    if not p.exists():
        pytest.skip(f"fixture {p.name} missing: run `make fixtures`")
    with wave.open(str(p)) as w:
        assert w.getframerate() == 24000 and w.getsampwidth() == 2
        return w.readframes(w.getnframes())


@pytest.fixture(autouse=True)
def _fresh_shared_client():
    """Each test runs in its own event loop; the shared provider client must not outlive it."""
    import app.providers.common.http as h
    h._client = None
    yield
    h._client = None
