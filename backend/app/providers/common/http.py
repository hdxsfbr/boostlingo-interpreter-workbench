"""Shared HTTP plumbing for provider adapters: one keep-alive AsyncClient per
process (warm TLS connections cut first-byte latency), SSE parsing, and
mapping transport/HTTP failures onto the normalised error taxonomy."""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from app.core.errors import ProviderDisconnected, ProviderError, ProviderTimeout, from_http_status, parse_retry_after

_client: httpx.AsyncClient | None = None


def shared_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0),
                                    limits=httpx.Limits(max_keepalive_connections=20, keepalive_expiry=120))
    return _client


async def raise_for_status(r: httpx.Response, *, provider: str, stage: str) -> None:
    if r.status_code < 400:
        return
    try:
        body = (await r.aread()).decode("utf-8", "replace")
        msg = json.loads(body).get("error", {}).get("message", body)
    except Exception:
        msg = f"HTTP {r.status_code}"
    raise from_http_status(r.status_code, str(msg)[:300], retry_after=parse_retry_after(r.headers.get("retry-after")),
                           provider=provider, stage=stage)


@asynccontextmanager
async def provider_stream(client: httpx.AsyncClient, method: str, url: str, *, provider: str, stage: str, **kw):
    """`client.stream` with errors mapped to ProviderError subclasses."""
    try:
        async with client.stream(method, url, **kw) as r:
            await raise_for_status(r, provider=provider, stage=stage)
            yield r
    except ProviderError:
        raise
    except httpx.TimeoutException as e:
        raise ProviderTimeout(f"{type(e).__name__}", provider=provider, stage=stage) from None
    except (httpx.NetworkError, httpx.RemoteProtocolError) as e:
        raise ProviderDisconnected(f"{type(e).__name__}", provider=provider, stage=stage) from None


async def iter_sse(r: httpx.Response) -> AsyncIterator[dict]:
    async for line in r.aiter_lines():
        if line.startswith("data: "):
            data = line[6:]
            if data.strip() == "[DONE]":
                return
            yield json.loads(data)
