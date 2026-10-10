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
    retention_days: int = 0  # >0: a daily sweep deletes this app's traces older than this (public API)
    retry_backoff_s: float = 0.5  # one retry on 429/5xx/timeouts, then drop

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
    retried: int = 0
    deleted: int = 0  # scores/traces deleted (review deletes, retention)
    flushes: int = 0
    last_error: str = ""
    errors: list[str] = field(default_factory=list)


class Langfuse:
    def __init__(self, cfg: LangfuseConfig, transport: httpx.AsyncBaseTransport | None = None):
        self.cfg = cfg
        self.q: deque[dict] = deque()
        self.deletes: deque[str] = deque()  # API paths to DELETE (best effort)
        self._last_sweep = 0.0
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

    def delete(self, path: str) -> None:
        """Queue a best-effort DELETE (e.g. /api/public/scores/<id>); never blocks or raises."""
        if self.enabled and len(self.deletes) < self.cfg.max_queue:
            self.deletes.append(path)

    def status(self) -> dict:
        """For the protected /api/health (no secrets)."""
        s = self.stats
        return {"enabled": self.enabled, "configured": self.cfg.enabled, "host": self.cfg.host if self.cfg.enabled else None,
                "send_text": self.cfg.send_text, "retention_days": self.cfg.retention_days, "queued_now": len(self.q),
                "queued": s.queued, "sent": s.sent, "retried": s.retried, "rejected": s.rejected,
                "dropped": s.dropped_full + s.dropped_error, "deleted": s.deleted, "last_error": s.last_error or None}

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
            await self.run_deletes()
            if self.cfg.retention_days > 0 and time.time() - self._last_sweep > 24 * 3600:
                self._last_sweep = time.time()
                await self.sweep()

    async def flush(self) -> None:
        while self.q:
            batch = [self.q.popleft() for _ in range(min(self.cfg.max_batch, len(self.q)))]
            try:
                r = await self._call("POST", "/api/public/ingestion", json={"batch": batch})
                self.stats.flushes += 1
                errs = (r.json() or {}).get("errors") or [] if r.status_code == 207 else []
                self.stats.rejected += len(errs)
                self.stats.sent += len(batch) - len(errs)
                if errs:
                    self._warn(f"{len(errs)} events rejected: {str(errs[0])[:200]}")
            except Exception as e:  # noqa: BLE001 - fail-open: drop this batch, keep going
                self.stats.dropped_error += len(batch)
                self._warn(f"{type(e).__name__}: {str(e)[:120]}")
                return  # don't hammer a dead host; the rest waits for the next tick

    async def _call(self, method: str, path: str, **kw) -> httpx.Response:
        """One request with ONE retry on 429/5xx/transport errors (backoff, honours a short Retry-After)."""
        for attempt in (0, 1):
            try:
                # hard deadline on top of httpx's timeouts (a stalled host can't hold the flusher)
                r = await asyncio.wait_for(self._client.request(method, path, **kw), self.cfg.timeout_s + 0.5)
                if r.status_code == 429 or r.status_code >= 500:
                    raise httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
                if r.status_code >= 400:
                    raise _Fatal(f"HTTP {r.status_code}")
                return r
            except (TimeoutError, httpx.HTTPError) as e:
                if attempt:
                    raise
                self.stats.retried += 1
                ra = getattr(getattr(e, "response", None), "headers", {}).get("retry-after", "")
                await asyncio.sleep(min(float(ra), 2.0) if ra.replace(".", "", 1).isdigit() else self.cfg.retry_backoff_s)
        raise AssertionError("unreachable")

    async def run_deletes(self) -> None:
        while self.deletes:
            path = self.deletes.popleft()
            try:
                await self._call("DELETE", path)
                self.stats.deleted += 1
            except Exception as e:  # noqa: BLE001 - best effort
                self._warn(f"delete {path.rsplit('/', 1)[-1]}: {type(e).__name__}")

    async def sweep(self) -> None:
        """Retention: delete traces older than retention_days (project-wide; best effort, bounded)."""
        cutoff = iso(time.time() - self.cfg.retention_days * 86400)
        try:
            for _ in range(10):  # at most 10 x 100 traces per sweep
                r = await self._call("GET", "/api/public/traces", params={"toTimestamp": cutoff, "limit": 100})
                ids = [t["id"] for t in (r.json() or {}).get("data", [])]
                if not ids:
                    return
                await self._call("DELETE", "/api/public/traces", json={"traceIds": ids})
                self.stats.deleted += len(ids)
        except Exception as e:  # noqa: BLE001
            self._warn(f"retention sweep: {type(e).__name__}")

    def _warn(self, msg: str) -> None:
        self.stats.last_error = msg
        if time.monotonic() - self._last_log > 60:
            self._last_log = time.monotonic()
            log.warning("Langfuse: %s (dropped so far: %d)", msg, self.stats.dropped_error)


class _Fatal(Exception):
    """A 4xx other than 429: not retried."""


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
