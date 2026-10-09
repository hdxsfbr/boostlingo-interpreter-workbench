"""ElevenLabs credit guard (DESIGN §2: free tier, 10,000 credits/month).

`ElevenLabsBudget` wraps any TTSProvider and refuses *before* the API call:
- unless ELEVENLABS_ENABLED=1 (`enabled=True`);
- when a session would exceed `session_char_cap` (default 1,500);
- when the month would exceed `month_char_cap` (default 8,000) according to
  a persistent ledger (`data/elevenlabs_ledger.json`, keyed by YYYY-MM).
Characters are counted conservatively at 1 credit/char, and are charged when a
chunk is *sent*, not when audio comes back. There is no silent fallback to
another TTS: BudgetExceeded surfaces as "switch TTS to OpenAI".
"""
from __future__ import annotations

import json
import os
import threading
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from pathlib import Path

from app.core.errors import BudgetExceeded

_LOCK = threading.Lock()


class Ledger:
    def __init__(self, path: Path, now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.path, self.now = path, now

    def _month(self) -> str:
        return self.now().strftime("%Y-%m")

    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text())
        except (FileNotFoundError, ValueError):
            return {}

    def used(self) -> int:
        return int(self._read().get(self._month(), 0))

    def charge(self, chars: int, cap: int) -> int:
        """Atomically add `chars` unless that would exceed `cap`; returns the new total."""
        with _LOCK:
            data = self._read()
            m = self._month()
            total = int(data.get(m, 0)) + chars
            if total > cap:
                raise BudgetExceeded(f"ElevenLabs monthly cap reached ({data.get(m, 0)}/{cap} chars); "
                                     "switch TTS to OpenAI", provider="elevenlabs", stage="tts")
            data[m] = total
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=1))
            os.replace(tmp, self.path)
            return total


class ElevenLabsBudget:
    """TTSProvider wrapper; one instance per cascade session."""

    def __init__(self, inner, *, enabled: bool, ledger: Ledger, session_char_cap: int = 1500,
                 month_char_cap: int = 8000) -> None:
        self.inner, self.enabled, self.ledger = inner, enabled, ledger
        self.session_cap, self.month_cap = session_char_cap, month_char_cap
        self.session_used = 0
        self.name = getattr(inner, "name", "elevenlabs")

    def check_enabled(self) -> None:
        if not self.enabled:
            raise BudgetExceeded("ElevenLabs is disabled (set ELEVENLABS_ENABLED=1 for benchmark/demo runs); "
                                 "switch TTS to OpenAI", provider="elevenlabs", stage="tts")

    def _charge(self, text: str) -> None:
        n = len(text)
        if self.session_used + n > self.session_cap:
            raise BudgetExceeded(f"ElevenLabs session cap reached ({self.session_used}/{self.session_cap} chars); "
                                 "switch TTS to OpenAI", provider="elevenlabs", stage="tts")
        self.ledger.charge(n, self.month_cap)
        self.session_used += n

    async def warm(self) -> None:
        if self.enabled and hasattr(self.inner, "warm"):
            await self.inner.warm()

    async def aclose(self) -> None:
        if hasattr(self.inner, "aclose"):
            await self.inner.aclose()

    async def stream(self, chunks: AsyncIterator[str], lang: str, voice: str) -> AsyncIterator[bytes]:
        self.check_enabled()

        async def guarded() -> AsyncIterator[str]:
            async for c in chunks:
                self._charge(c)  # raises before the chunk reaches the provider
                yield c

        async for pcm in self.inner.stream(guarded(), lang, voice):
            yield pcm
