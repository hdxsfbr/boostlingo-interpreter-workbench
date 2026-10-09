import pytest

from app.core.errors import (
    AuthError,
    BadRequest,
    ProviderTimeout,
    ProviderUnavailable,
    RateLimited,
    from_http_status,
    parse_retry_after,
)
from app.core.retry import backoff_delay, stream_with_retry


def test_http_status_mapping():
    assert isinstance(from_http_status(429, "x", retry_after=1.5), RateLimited)
    assert from_http_status(429, "x", retry_after=1.5).retry_after == 1.5
    assert isinstance(from_http_status(401, "x"), AuthError)
    assert isinstance(from_http_status(503, "x"), ProviderUnavailable)
    assert isinstance(from_http_status(408, "x"), ProviderTimeout)
    assert isinstance(from_http_status(400, "x"), BadRequest)
    assert parse_retry_after("2") == 2.0 and parse_retry_after("soon") is None and parse_retry_after(None) is None


def test_backoff_full_jitter_and_retry_after():
    assert backoff_delay(0, rng=lambda: 1.0) == pytest.approx(0.2)
    assert backoff_delay(3, rng=lambda: 1.0) == pytest.approx(1.6)
    assert backoff_delay(10, rng=lambda: 1.0) == pytest.approx(2.0)  # capped
    assert backoff_delay(0, retry_after=1.25) == 1.25


async def _collect(it):
    return [x async for x in it]


async def test_retries_before_first_output_then_succeeds():
    calls, sleeps, notices = [], [], []

    def make():
        calls.append(1)

        async def gen():
            if len(calls) < 3:
                raise RateLimited("slow down", retry_after=0.5)
            yield "a"
            yield "b"

        return gen()

    async def sleep(d):
        sleeps.append(d)

    async def on_retry(exc, attempt, delay):
        notices.append((exc.code, attempt))

    assert await _collect(stream_with_retry(make, sleep=sleep, on_retry=on_retry)) == ["a", "b"]
    assert len(calls) == 3 and sleeps == [0.5, 0.5] and notices == [("rate_limited", 1), ("rate_limited", 2)]


async def test_gives_up_after_two_retries():
    async def sleep(_):
        pass

    def make():
        async def gen():
            raise ProviderUnavailable("down")
            yield  # pragma: no cover

        return gen()

    with pytest.raises(ProviderUnavailable):
        await _collect(stream_with_retry(make, sleep=sleep))


async def test_never_retries_after_output_started_or_non_retryable():
    async def sleep(_):
        pass

    n = []

    def make():
        n.append(1)

        async def gen():
            yield "partial"
            raise ProviderTimeout("mid-stream")

        return gen()

    with pytest.raises(ProviderTimeout):
        await _collect(stream_with_retry(make, sleep=sleep))
    assert len(n) == 1

    def make_auth():
        n.append(1)

        async def gen():
            raise AuthError("bad key")
            yield  # pragma: no cover

        return gen()

    n.clear()
    with pytest.raises(AuthError):
        await _collect(stream_with_retry(make_auth, sleep=sleep))
    assert len(n) == 1
