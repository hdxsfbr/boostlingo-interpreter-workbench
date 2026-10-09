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
from app.core.events import Commit, ErrorEvent, SessionStart, TurnDone, TurnSkipped, TurnStart
from app.core.languages import languages_config
from app.core.recording import CascadeRecorder, RecordingError, RecordingStore, get_store
from app.providers import registry

log = logging.getLogger(__name__)


def _read_key_file(path) -> str:
    try:
        return Path(path).read_text().strip() if path else ""
    except OSError:
        return ""


def build_providers(settings: Settings, overrides: dict[str, str] | None = None, langs: list[str] | None = None):
    cfg = settings.app_config()
    names = {k: (overrides or {}).get(k) or cfg["cascade"][k] for k in ("stt", "mt", "tts")}
    p = cfg["providers"]
    key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else ""
    kwargs = {
        ("stt", "openai_live"): lambda: {"api_key": key, "model": p["openai_live"]["model"],
                                         "delay": p["openai_live"].get("delay"),
                                         "languages": langs},
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
            "model": el.get("model", "eleven_flash_v2_5"),
            "voices": {**{c: lg.voices["elevenlabs"] for c, lg in languages_config().languages.items()
                          if lg.voices.get("elevenlabs")}, **el.get("voices", {})},
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
    voices = dict(p.get("openai_tts", {}).get("voices", {})) if names["tts"] == "openai" else {}
    if names["tts"] == "openai":  # languages.yaml per-language voices fill the gaps (A14)
        for code, lang in languages_config().languages.items():
            if lang.voices.get("openai"):
                voices.setdefault(code, lang.voices["openai"])
    return built, names, voices, Timeouts.from_config(cfg.get("timeouts_s", {}))


def speculative_enabled(ccfg: dict, tts_name: str) -> bool:
    """Speculative MT/TTS is off by default with ElevenLabs (DESIGN A9): its
    cancelled runs still send chunks, which spend scarce free-tier credits.
    `cascade.speculative_with_elevenlabs: true` opts back in."""
    if not ccfg.get("speculative_mt", False):
        return False
    if tts_name == "elevenlabs":
        return bool(ccfg.get("speculative_with_elevenlabs", False))
    return True


def make_recorder(start: SessionStart, store: RecordingStore) -> tuple[CascadeRecorder | None, str | None]:
    """A11: record only if the session asked AND the server allows it; otherwise
    return a refusal message for the UI (nothing is captured)."""
    if not start.record:
        return None, None
    if not store.cfg.enabled:
        return None, "Recording is disabled on this server (recording.enabled=false); nothing is recorded."
    try:
        return CascadeRecorder(store, start.session_id or ""), None
    except RecordingError as e:
        return None, f"Recording refused: {e}"


def recording_io(io: SessionIO, rec: CascadeRecorder | None):
    """Wrap the session's outputs to capture TTS audio and save each turn's
    files when it ends (done, skipped or failed)."""
    if rec is None:
        return io.event, io.audio

    async def send_audio(turn_id: int, pcm: bytes) -> None:
        rec.add(turn_id, "target", pcm)
        await io.audio(turn_id, pcm)

    async def send_event(ev) -> None:
        terminal = isinstance(ev, TurnDone | TurnSkipped) or (
            isinstance(ev, ErrorEvent) and ev.turn_id is not None and not ev.retryable)
        if terminal:
            try:
                paths = await rec.finish(ev.turn_id)
            except (OSError, RecordingError, PermissionError):
                log.warning("turn %s: recording write failed", ev.turn_id, exc_info=True)
                paths = {}
            if paths and isinstance(ev, TurnDone):
                ev = ev.model_copy(update={"recording": paths})
        await io.event(ev)

    return send_event, send_audio


class CascadePipeline:
    name = "cascade"

    def __init__(self, session: CascadeSession, names: dict[str, str], warm: list) -> None:
        self.session = session
        self.names = names
        self._warm = warm
        self._opened: asyncio.Task | None = None
        self.recorder: CascadeRecorder | None = None
        self._rec_turn: int | None = None

    @classmethod
    def from_settings(cls, start: SessionStart, io: SessionIO, settings: Settings | None = None) -> CascadePipeline:
        settings = settings or get_settings()
        lc = languages_config()
        src, tgt = lc.resolve(start.src, start.tgt)  # ValueError -> config error shown in the UI
        (prov, names, voices, timeouts) = build_providers(settings, start.providers, [src, tgt])
        pair = lc.find(src, tgt)
        glossary = dict(pair.glossary) if pair else {}
        ccfg = settings.app_config()["cascade"]
        rec, refusal = make_recorder(start, get_store())
        send_event, send_audio = recording_io(io, rec)
        session = CascadeSession(prov["stt"], prov["mt"], prov["tts"], send_event=send_event, send_audio=send_audio,
                                 voices=voices, langs=[src, tgt], timeouts=timeouts, glossary=glossary,
                                 speculative=speculative_enabled(ccfg, names["tts"]),
                                 merge_fragments=bool(ccfg.get("merge_fragments", True)),
                                 chunker=ccfg.get("chunker") or {})
        pipe = cls(session, names, [prov["mt"], prov["tts"]])
        pipe.recorder = rec
        pipe._opened = asyncio.get_running_loop().create_task(pipe._open(io, refusal))
        return pipe

    async def _open(self, io: SessionIO, refusal: str | None = None) -> None:
        """Warm the STT socket and HTTP connections so turn 1 isn't slower."""
        if refusal:
            await io.event(ErrorEvent(code="recording_refused", stage="recording", retryable=False, message=refusal))
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
        self._rec_turn = msg.turn_id
        await self.session.turn_start(msg.turn_id, msg.src, msg.tgt)

    async def audio(self, pcm: bytes) -> None:
        if self.recorder is not None and self._rec_turn is not None:
            self.recorder.add(self._rec_turn, "source", pcm)
        self.session.audio(pcm)

    async def commit(self, msg: Commit) -> None:
        if msg.final and msg.turn_id == self._rec_turn:
            self._rec_turn = None  # the session ignores audio after the final commit; so does the recording
        await self.session.commit(msg.turn_id, msg.final)

    async def cancel(self, turn_id: int) -> None:
        await self.session.cancel(turn_id)

    async def pause_hint(self, turn_id: int) -> None:
        self.session.pause_hint(turn_id)

    async def close(self) -> None:
        if self._opened and not self._opened.done():
            self._opened.cancel()
        await self.session.close()
        for p in self._warm:  # e.g. pre-opened ElevenLabs sockets
            aclose = getattr(p, "aclose", None)
            if aclose:
                with contextlib.suppress(Exception):
                    await aclose()
