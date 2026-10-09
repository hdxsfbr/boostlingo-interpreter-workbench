"""Retry only BEFORE a stage's first output (DESIGN §6): at most 2 retries,
exponential backoff from 200 ms with full jitter, honouring Retry-After.
Once output has started the turn fails instead, so audio is never repeated."""
from __future__ import annotations

import asyncio
import random
from collections.abc import AsyncIterator, Awaitable, Callable

from app.core.errors import ProviderError, RateLimited


def backoff_delay(attempt: int, base: float = 0.2, cap: float = 2.0, retry_after: float | None = None,
                  rng: Callable[[], float] = random.random) -> float:
    if retry_after is not None:
        return min(retry_after, cap * 2)
    return rng() * min(cap, base * (2 ** attempt))


async def stream_with_retry[T](make: Callable[[], AsyncIterator[T]], *, retries: int = 2,
                            on_retry: Callable[[ProviderError, int, float], Awaitable[None]] | None = None,
                            sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> AsyncIterator[T]:
    attempt = 0
    while True:
        started = False
        try:
            async for item in make():
                started = True
                yield item
            return
        except ProviderError as exc:
            if started or not exc.retryable or attempt >= retries:
                raise
            delay = backoff_delay(attempt, retry_after=exc.retry_after if isinstance(exc, RateLimited) else None)
            if on_retry:
                await on_retry(exc, attempt + 1, delay)
            await sleep(delay)
            attempt += 1
