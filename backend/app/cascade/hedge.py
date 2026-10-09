"""Hedged first output (M5): if a provider stream has produced nothing after
`hedge_after` seconds, start ONE backup request with the same input; whichever
stream yields its first item first wins and the other is cancelled. The
overall first-output deadline (`timeout`) still applies, so a turn fails with
ProviderTimeout only if neither request produced output in time.

Only the first item is raced: once a stream has produced output it is the
turn's stream (audio/text is never duplicated, consistent with DESIGN §6's
"no retry after first byte" rule).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any

from app.core.errors import ProviderTimeout

log = logging.getLogger(__name__)
_END = object()


async def _first(it: AsyncIterator) -> Any:
    try:
        return await anext(it)
    except StopAsyncIteration:
        return _END


async def _close(it: AsyncIterator, task: asyncio.Task | None) -> None:
    if task is not None and not task.done():
        task.cancel()
        with contextlib.suppress(BaseException):
            await task
    aclose = getattr(it, "aclose", None)
    if aclose:
        with contextlib.suppress(BaseException):
            await aclose()


async def hedged_first(
    factory: Callable[[], AsyncIterator],
    *,
    timeout: float,
    hedge_after: float | None,
    stage: str,
    provider: str = "",
    on_event: Callable[[str], None] | None = None,
) -> AsyncIterator:
    """Yield the winner's items. `on_event` gets "hedge_fired" / "hedge_won"."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout

    def start() -> tuple[AsyncIterator, asyncio.Task]:
        it = aiter(factory())
        return it, asyncio.create_task(_first(it))

    def timed_out() -> ProviderTimeout:
        return ProviderTimeout(f"{stage}: no output within {timeout:.1f}s", stage=stage, provider=provider)

    racers = [start()]
    backup: tuple[AsyncIterator, asyncio.Task] | None = None
    hedge_at = loop.time() + hedge_after if hedge_after is not None and 0 < hedge_after < timeout else None
    winner = None
    last_exc: BaseException | None = None
    try:
        while winner is None:
            for r in [r for r in racers if r[1].done()]:
                if r[1].cancelled() or r[1].exception() is not None:
                    last_exc = r[1].exception() if not r[1].cancelled() else timed_out()
                    racers.remove(r)
                    await _close(*r)
                elif winner is None:
                    winner = r
            if winner is not None:
                break
            if not racers:
                assert last_exc is not None
                raise last_exc
            now = loop.time()
            if now >= deadline:
                raise timed_out()
            wake = deadline
            if hedge_at is not None and backup is None:
                if now >= hedge_at:
                    if on_event:
                        on_event("hedge_fired")
                    backup = start()
                    racers.append(backup)
                    continue
                wake = min(wake, hedge_at)
            await asyncio.wait(
                {t for _, t in racers}, timeout=wake - now, return_when=asyncio.FIRST_COMPLETED
            )
        for r in list(racers):
            if r is not winner:
                racers.remove(r)
                await _close(*r)
        if on_event and backup is not None and winner is backup:
            on_event("hedge_won")
        it, task = winner
        first = task.result()
        if first is _END:
            return
        yield first
        async for x in it:
            yield x
    finally:
        for it, task in racers:
            await _close(it, task)
