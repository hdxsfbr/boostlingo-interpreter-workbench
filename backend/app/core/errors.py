"""Normalised provider errors. Adapters map HTTP/WS failures onto these so the
orchestrator and UI handle every provider the same way (DESIGN §2, §6)."""
from __future__ import annotations


class ProviderError(Exception):
    code = "provider_error"
    retryable = False

    def __init__(self, message: str = "", *, provider: str = "", stage: str = "") -> None:
        super().__init__(message or self.code)
        self.provider = provider
        self.stage = stage


class RateLimited(ProviderError):
    code = "rate_limited"
    retryable = True

    def __init__(self, message: str = "", *, retry_after: float | None = None, **kw) -> None:
        super().__init__(message, **kw)
        self.retry_after = retry_after


class ProviderTimeout(ProviderError):
    code = "timeout"
    retryable = True


class ProviderDisconnected(ProviderError):
    code = "provider_disconnected"
    retryable = True


class ProviderUnavailable(ProviderError):
    """5xx from the provider."""

    code = "provider_unavailable"
    retryable = True


class AuthError(ProviderError):
    code = "auth_error"


class ConfigError(ProviderError):
    code = "config_error"


class BadRequest(ProviderError):
    code = "bad_request"


class EmptyResult(ProviderError):
    code = "empty_result"


class BudgetExceeded(ProviderError):
    code = "budget_exceeded"


def from_http_status(status: int, message: str, *, retry_after: float | None = None, provider: str = "",
                     stage: str = "") -> ProviderError:
    kw = {"provider": provider, "stage": stage}
    if status == 429:
        return RateLimited(message, retry_after=retry_after, **kw)
    if status in (401, 403):
        return AuthError(message, **kw)
    if status == 408:
        return ProviderTimeout(message, **kw)
    if status >= 500:
        return ProviderUnavailable(message, **kw)
    return BadRequest(message, **kw)


def parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None
