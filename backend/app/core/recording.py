"""Opt-in session audio recording for auditability (DESIGN A11).

Off unless `recording.enabled` (config) / RECORDING_ENABLED=1 AND the session
asked for it (UI "Record session" toggle). Files live next to the session
JSONL: data/recordings/<session_id>/turn-<n>-{source,target}.<ext>.
- Cascade: the server keeps the inbound PCM and the outgoing TTS PCM per turn
  and writes WAV (PCM16 mono 24 kHz) when the turn ends.
- Realtime: the browser records (MediaRecorder) and uploads per turn.
Retention: directories older than `retention_days` are deleted on startup and
by a periodic sweep; DELETE /api/recordings/<session_id> removes one session.
Local only: production would need encryption at rest, access control and
access logging (README).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

SESSION_RE = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9_.-]{0,79}$")
SIDES = ("source", "target")
EXTS = {"audio/wav": "wav", "audio/x-wav": "wav", "audio/webm": "webm", "audio/ogg": "ogg"}
MAX_TURN = 100_000
MAX_TURN_BYTES = 48_000 * 600  # 10 min of PCM16 @ 24 kHz per side


class RecordingError(ValueError):
    pass


@dataclass
class RecordingConfig:
    enabled: bool = False
    retention_days: float = 30
    sweep_interval_h: float = 6
    max_upload_mb: float = 20

    @classmethod
    def from_settings(cls, settings) -> RecordingConfig:
        cfg = dict(settings.app_config().get("recording") or {})
        if getattr(settings, "recording_enabled", None) is not None:
            cfg["enabled"] = settings.recording_enabled
        return cls(**{k: v for k, v in cfg.items() if k in cls.__dataclass_fields__})


class RecordingStore:
    def __init__(self, data_dir: Path, cfg: RecordingConfig) -> None:
        self.root = (data_dir / "recordings").resolve()
        self.sessions = data_dir / "sessions"
        self.cfg = cfg

    # ---------------- paths (validated; no traversal) ----------------
    def session_dir(self, session_id: str) -> Path:
        if not isinstance(session_id, str) or not SESSION_RE.match(session_id) or ".." in session_id:
            raise RecordingError("invalid session_id")
        d = (self.root / session_id).resolve()
        if d.parent != self.root:
            raise RecordingError("invalid session_id")
        return d

    def turn_path(self, session_id: str, turn: int, side: str, ext: str) -> Path:
        if not isinstance(turn, int) or isinstance(turn, bool) or not 0 < turn <= MAX_TURN:
            raise RecordingError("invalid turn")
        if side not in SIDES:
            raise RecordingError("invalid side")
        if ext not in set(EXTS.values()):
            raise RecordingError("invalid extension")
        return self.session_dir(session_id) / f"turn-{turn}-{side}.{ext}"

    def rel(self, p: Path) -> str:
        return f"recordings/{p.parent.name}/{p.name}"

    # ---------------- writes ----------------
    def _check_enabled(self) -> None:
        if not self.cfg.enabled:
            raise PermissionError("recording is disabled on this server (recording.enabled=false)")

    def write_wav(self, session_id: str, turn: int, side: str, pcm: bytes, rate: int = 24000) -> Path:
        self._check_enabled()
        p = self.turn_path(session_id, turn, side, "wav")
        p.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(p), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(pcm)
        self._audit(session_id, turn, side, p, len(pcm))
        return p

    def save_upload(self, session_id: str, turn: int, side: str, content_type: str, data: bytes) -> Path:
        self._check_enabled()
        ctype = (content_type or "").split(";")[0].strip().lower()
        if ctype not in EXTS:
            raise RecordingError(f"unsupported content type {ctype!r}")
        if len(data) > self.cfg.max_upload_mb * 1024 * 1024:
            raise RecordingError("upload too large")
        if not data:
            raise RecordingError("empty upload")
        p = self.turn_path(session_id, turn, side, EXTS[ctype])
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(p)
        self._audit(session_id, turn, side, p, len(data))
        return p

    def _audit(self, session_id: str, turn: int, side: str, p: Path, nbytes: int) -> None:
        """One JSONL line per file next to the session's turn records."""
        self.sessions.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"ts": time.time(), "session_id": session_id,
                           "recording": {"turn": turn, "side": side, "path": self.rel(p), "bytes": nbytes}})
        with open(self.sessions / f"{session_id}.jsonl", "a", encoding="utf-8") as f:
            f.write(line + "\n")

    # ---------------- retention ----------------
    def delete_session(self, session_id: str) -> int:
        d = self.session_dir(session_id)
        if not d.is_dir():
            return 0
        n = sum(1 for _ in d.iterdir())
        shutil.rmtree(d)
        return n

    def sweep(self, now: float | None = None) -> int:
        """Delete recording files (and then empty session dirs) older than retention_days."""
        if not self.root.is_dir():
            return 0
        cutoff = (now or time.time()) - self.cfg.retention_days * 86400
        removed = 0
        for d in self.root.iterdir():
            if not d.is_dir() or d.is_symlink():
                continue
            for f in d.iterdir():
                if f.is_file() and f.stat().st_mtime < cutoff:
                    f.unlink()
                    removed += 1
            if not any(d.iterdir()):
                d.rmdir()
        if removed:
            log.info("recording retention: deleted %d files older than %s days", removed, self.cfg.retention_days)
        return removed

    async def sweep_forever(self) -> None:
        while True:
            await asyncio.sleep(max(60.0, self.cfg.sweep_interval_h * 3600))
            try:
                await asyncio.to_thread(self.sweep)
            except OSError:
                log.warning("recording sweep failed", exc_info=True)


@dataclass
class TurnAudio:
    source: bytearray = field(default_factory=bytearray)
    target: bytearray = field(default_factory=bytearray)


class CascadeRecorder:
    """Per-session server-side capture for the cascade (both sides, per turn)."""

    def __init__(self, store: RecordingStore, session_id: str) -> None:
        store.session_dir(session_id)  # validate early
        self.store, self.session_id = store, session_id
        self.turns: dict[int, TurnAudio] = {}

    def add(self, turn: int, side: str, pcm: bytes) -> None:
        buf = getattr(self.turns.setdefault(turn, TurnAudio()), side)
        if len(buf) + len(pcm) <= MAX_TURN_BYTES:
            buf.extend(pcm)

    async def finish(self, turn: int) -> dict[str, str]:
        ta = self.turns.pop(turn, None)
        if ta is None:
            return {}
        out = {}
        for side in SIDES:
            pcm = bytes(getattr(ta, side))
            if pcm:
                p = await asyncio.to_thread(self.store.write_wav, self.session_id, turn, side, pcm)
                out[side] = self.store.rel(p)
        return out


_STORE: RecordingStore | None = None


def get_store() -> RecordingStore:
    global _STORE
    if _STORE is None:
        from app.core.config import get_settings
        s = get_settings()
        _STORE = RecordingStore(s.data_dir, RecordingConfig.from_settings(s))
    return _STORE
