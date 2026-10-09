"""Adapts CascadeSession to the WS gateway's TurnPipeline interface and builds
providers from config (registry + config/app.yaml + env overrides)."""
from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path

from app.api.cascade_ws import SessionIO
from app.cascade.session import CascadeSession, Timeouts
from app.core.budget import ElevenLabsBudget, Ledger
from app.core.config import Settings, get_settings
from app.core.errors import ConfigError, ProviderError
from app.core.events import Commit, ErrorEvent, SessionStart, TurnStart
from app.providers import registry

log = logging.getLogger(__name__)


def _read_key_file(path) -> str:
    try:
        return Path(path).read_text().strip() if path else ""
    except OSError:
        return ""


def build_providers(settings: Settings, overrides: dict[str, str] | None = None):
    cfg = settings.app_config()
    names = {k: (overrides or {}).get(k) or cfg["cascade"][k] for k in ("stt", "mt", "tts")}
    p = cfg["providers"]
    key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else ""
    kwargs = {
        ("stt", "openai_live"): lambda: {"api_key": key, "model": p["openai_live"]["model"],
                                         "delay": p["openai_live"].get("delay"),
                                         "languages": p["openai_live"].get("languages")},
        ("mt", "openai"): lambda: {"api_key": key, "model": p["openai"]["model"],
                                   "reasoning_effort": p["openai"].get("reasoning_effort"),
                                   "max_output_tokens": p["openai"].get("max_output_tokens", 400)},
        ("tts", "openai"): lambda: {"api_key": key, "model": p["openai_tts"]["model"]},
        ("mt", "anthropic"): lambda: {
            "api_key": settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else "",
            "workspace_id": (settings.anthropic_workspace_id.get_secret_value()
                             if settings.anthropic_workspace_id else None),
            "model": p["anthropic"]["model"], "max_tokens": p["anthropic"].get("max_tokens", 400),
            "effort": p["anthropic"].get("effort", "low")},
    }
    if names["mt"] == "openrouter":
        orc = p.get("openrouter", {})
        kwargs[("mt", "openrouter")] = lambda: {
            "api_key": settings.openrouter_api_key.get_secret_value() if settings.openrouter_api_key else "",
            "model": orc.get("model", "anthropic/claude-haiku-5-5"), "max_tokens": orc.get("max_tokens", 400),
            "sort": orc.get("sort", "latency")}
    if names["tts"] == "elevenlabs":
        if not settings.elevenlabs_enabled:
            raise ConfigError("ElevenLabs is disabled (ELEVENLABS_ENABLED=0; free-tier credits are reserved for "
                              "benchmark/demo runs). Switch TTS to OpenAI.", provider="elevenlabs", stage="tts")
        el = p["elevenlabs"]
        kwargs[("tts", "elevenlabs")] = lambda: {
            "api_key": _read_key_file(settings.elevenlabs_api_key_file),
            "model": el.get("model", "eleven_flash_v2_5"), "voices": el.get("voices", {}),
            "prewarm": el.get("prewarm", True)}
    if names["mt"] == "anthropic" and not settings.haiku_enabled():
        raise ConfigError("cascade-haiku is disabled (Anthropic validity check failed); "
                          "set providers.anthropic.enabled or ANTHROPIC_ENABLED=1 after a passing check",
                          provider="anthropic", stage="mt")
    built = {kind: registry.create(kind, names[kind], **kwargs.get((kind, names[kind]), dict)())
             for kind in ("stt", "mt", "tts")}
    if names["tts"] == "elevenlabs":  # always behind the credit guard
        el = p["elevenlabs"]
        built["tts"] = ElevenLabsBudget(built["tts"], enabled=settings.elevenlabs_enabled,
                                        ledger=Ledger(settings.data_dir / "elevenlabs_ledger.json"),
                                        session_char_cap=el.get("session_char_cap", 1500),
                                        month_char_cap=el.get("month_char_cap", 8000))
    voices = p.get("openai_tts", {}).get("voices", {}) if names["tts"] == "openai" else {}
    return built, names, voices, Timeouts.from_config(cfg.get("timeouts_s", {}))


class CascadePipeline:
    name = "cascade"

    def __init__(self, session: CascadeSession, names: dict[str, str], warm: list) -> None:
        self.session = session
        self.names = names
        self._warm = warm
        self._opened: asyncio.Task | None = None

    @classmethod
    def from_settings(cls, start: SessionStart, io: SessionIO, settings: Settings | None = None) -> CascadePipeline:
        settings = settings or get_settings()
        (prov, names, voices, timeouts) = build_providers(settings, start.providers)
        langs = settings.languages()
        glossary = next((pr.get("glossary") or {} for pr in langs.get("pairs", [])
                         if {pr.get("a"), pr.get("b")} == {start.src, start.tgt}), {})
        ccfg = settings.app_config()["cascade"]
        session = CascadeSession(prov["stt"], prov["mt"], prov["tts"], send_event=io.event, send_audio=io.audio,
                                 voices=voices, langs=[start.src, start.tgt], timeouts=timeouts, glossary=glossary,
                                 speculative=bool(ccfg.get("speculative_mt", False)),
                                 chunker=ccfg.get("chunker") or {})
        pipe = cls(session, names, [prov["mt"], prov["tts"]])
        pipe._opened = asyncio.get_running_loop().create_task(pipe._open(io))
        return pipe

    async def _open(self, io: SessionIO) -> None:
        """Warm the STT socket and HTTP connections so turn 1 isn't slower."""
        try:
            await self.session.open()
        except ProviderError as e:
            await io.event(ErrorEvent(code=e.code, stage="stt", retryable=True,
                                      message=f"STT connect failed ({e}); will retry on the next turn"))
        for p in self._warm:
            warm = getattr(p, "warm", None)
            if warm:
                await warm()

    def providers(self) -> dict[str, str]:
        return dict(self.names)

    async def turn_start(self, msg: TurnStart) -> None:
        await self.session.turn_start(msg.turn_id, msg.src, msg.tgt)

    async def audio(self, pcm: bytes) -> None:
        self.session.audio(pcm)

    async def commit(self, msg: Commit) -> None:
        await self.session.commit(msg.turn_id, msg.final)

    async def cancel(self, turn_id: int) -> None:
        await self.session.cancel(turn_id)

    async def close(self) -> None:
        if self._opened and not self._opened.done():
            self._opened.cancel()
        await self.session.close()
        for p in self._warm:  # e.g. pre-opened ElevenLabs sockets
            aclose = getattr(p, "aclose", None)
            if aclose:
                with contextlib.suppress(Exception):
                    await aclose()
