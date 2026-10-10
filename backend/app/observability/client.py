"""A20: minimal, fail-open Langfuse client (public ingestion API, no SDK).

Design rules (DESIGN A20):
- Off the audio path. Callers only `emit()`, which appends to an in-memory deque
  (thread-safe, O(1), never awaits, never raises). The audio pipeline never calls this.
- Batched and async: one background task flushes every `flush_interval_s` or when
  `max_batch` events are queued, with a short HTTP timeout.
- Fail-open: an unreachable/slow/erroring Langfuse only drops events (counted,
  logged at most once a minute). A full queue drops the new event.
- Never audio: payloads are text + numbers; `send_text: false` strips transcripts.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

log = logging.getLogger("langfuse")


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass
class LangfuseConfig:
    enabled: bool = False
    host: str = "https://us.cloud.langfuse.com"
    public_key: str = ""
    secret_key: str = ""
    send_text: bool = True
    flush_interval_s: float = 2.0
    max_batch: int = 50
    max_queue: int = 2000
    timeout_s: float = 3.0
    release: str = "unknown"  # git commit
    project_id: str = ""  # only for building UI links in logs/docs

    @property
    def ready(self) -> bool:
        return self.enabled and bool(self.public_key and self.secret_key and self.host)


@dataclass
class Stats:
    queued: int = 0
    sent: int = 0
    dropped_full: int = 0
    dropped_error: int = 0
    rejected: int = 0  # 207 per-event errors from Langfuse
    flushes: int = 0
    last_error: str = ""
    errors: list[str] = field(default_factory=list)


class Langfuse:
    def __init__(self, cfg: LangfuseConfig, transport: httpx.AsyncBaseTransport | None = None):
        self.cfg = cfg
        self.q: deque[dict] = deque()
        self.stats = Stats()
        self._transport = transport
        self._task: asyncio.Task | None = None
        self._wake: asyncio.Event | None = None
        self._last_log = 0.0

    @property
    def enabled(self) -> bool:
        return self.cfg.ready

    # ----- producer side (any thread, never blocks, never raises)
    def emit(self, type_: str, body: dict[str, Any]) -> None:
        if not self.enabled:
            return
        try:
            if len(self.q) >= self.cfg.max_queue:
                self.stats.dropped_full += 1
                return
            self.q.append({"id": str(uuid.uuid4()), "timestamp": iso(time.time()), "type": type_, "body": body})
            self.stats.queued += 1
            if self._wake is not None and len(self.q) >= self.cfg.max_batch:
                with contextlib.suppress(RuntimeError):
                    self._loop.call_soon_threadsafe(self._wake.set)
        except Exception:  # noqa: BLE001 - tracing must never break the caller
            self.stats.dropped_error += 1

    def text(self, s: str | None) -> str | None:
        return s if self.cfg.send_text else None

    # ----- consumer side
    async def start(self) -> None:
        if not self.enabled or self._task:
            return
        self._loop = asyncio.get_running_loop()
        self._wake = asyncio.Event()
        self._client = httpx.AsyncClient(
            base_url=self.cfg.host.rstrip("/"), timeout=self.cfg.timeout_s, transport=self._transport,
            headers={"Authorization": "Basic " + base64.b64encode(f"{self.cfg.public_key}:{self.cfg.secret_key}".encode()).decode()})
        self._task = asyncio.create_task(self._run(), name="langfuse-flusher")
        log.info("Langfuse tracing on (%s, send_text=%s)", self.cfg.host, self.cfg.send_text)

    async def stop(self, timeout: float = 3.0) -> None:
        if not self._task:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await self._task
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self.flush(), timeout)  # best effort, bounded
        with contextlib.suppress(Exception):
            await self._client.aclose()
        self._task = None

    async def _run(self) -> None:
        assert self._wake is not None
        while True:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._wake.wait(), self.cfg.flush_interval_s)
            self._wake.clear()
            await self.flush()

    async def flush(self) -> None:
        while self.q:
            batch = [self.q.popleft() for _ in range(min(self.cfg.max_batch, len(self.q)))]
            try:
                # hard deadline on top of httpx's timeouts (a stalled host can't hold the flusher)
                r = await asyncio.wait_for(self._client.post("/api/public/ingestion", json={"batch": batch}),
                                           self.cfg.timeout_s + 0.5)
                self.stats.flushes += 1
                if r.status_code >= 400:
                    raise httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
                errs = (r.json() or {}).get("errors") or [] if r.status_code == 207 else []
                self.stats.rejected += len(errs)
                self.stats.sent += len(batch) - len(errs)
                if errs:
                    self._warn(f"{len(errs)} events rejected: {str(errs[0])[:200]}")
            except Exception as e:  # noqa: BLE001 - fail-open: drop this batch, keep going
                self.stats.dropped_error += len(batch)
                self._warn(f"{type(e).__name__}: {str(e)[:120]}")
                return  # don't hammer a dead host; the rest waits for the next tick

    def _warn(self, msg: str) -> None:
        self.stats.last_error = msg
        if time.monotonic() - self._last_log > 60:
            self._last_log = time.monotonic()
            log.warning("Langfuse: %s (dropped so far: %d)", msg, self.stats.dropped_error)


_INSTANCE: Langfuse | None = None


def get_langfuse() -> Langfuse:
    global _INSTANCE
    if _INSTANCE is None:
        from app.core.config import get_settings
        _INSTANCE = Langfuse(get_settings().langfuse_config())
    return _INSTANCE


def set_langfuse(lf: Langfuse | None) -> None:  # tests
    global _INSTANCE
    _INSTANCE = lf
