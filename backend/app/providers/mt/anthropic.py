"""Anthropic Messages API streaming translator (`cascade-haiku` profile).

`claude-haiku-5-5` with thinking disabled and effort `low` (latency; disabled
thinking is allowed at effort <= high), no temperature/top_p/top_k (R§3.1).
The account's key is not workspace-scoped, so every request carries the
`anthropic-workspace-id` header (Anthropic returns 400 without it).
Same static instructions and input builder as the OpenAI translator, so the
two profiles differ only in the model.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

import httpx

from app.core.errors import ConfigError, ProviderError, RateLimited
from app.providers.base import TurnContext, Usage
from app.providers.common.http import iter_sse, provider_stream, shared_client
from app.providers.mt.openai import INSTRUCTIONS, build_input
from app.providers.registry import register

API_VERSION = "2023-06-01"


@register("mt", "anthropic")
class AnthropicTranslator:
    name = "anthropic"
    URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, api_key: str, model: str, workspace_id: str | None = None, max_tokens: int = 400,
                 effort: str | None = "low", client: httpx.AsyncClient | None = None,
                 base_url: str | None = None) -> None:
        if not api_key:
            raise ConfigError("ANTHROPIC_API_KEY is not set", provider="anthropic", stage="mt")
        self.api_key, self.model, self.workspace_id = api_key, model, workspace_id
        self.max_tokens, self.effort, self.client = max_tokens, effort, client
        self.url = (base_url.rstrip("/") + "/v1/messages") if base_url else self.URL
        self.last_usage = Usage()

    def headers(self) -> dict[str, str]:
        h = {"x-api-key": self.api_key, "anthropic-version": API_VERSION, "content-type": "application/json"}
        if self.workspace_id:
            h["anthropic-workspace-id"] = self.workspace_id
        return h

    def body(self, text: str, src: str, tgt: str, ctx: TurnContext) -> dict:
        b: dict = {"model": self.model, "max_tokens": self.max_tokens, "stream": True,
                   "system": [{"type": "text", "text": INSTRUCTIONS}],
                   "thinking": {"type": "disabled"},
                   "messages": [{"role": "user", "content": build_input(text, src, tgt, ctx)}]}
        if self.effort:
            b["output_config"] = {"effort": self.effort}
        return b

    async def warm(self) -> None:
        """Open a keep-alive TLS connection (no billable call)."""
        client = self.client or shared_client()
        try:
            await client.get("https://api.anthropic.com/", timeout=3.0)
        except httpx.HTTPError:
            pass

    async def stream(self, text: str, src: str, tgt: str, ctx: TurnContext) -> AsyncIterator[str]:
        client = self.client or shared_client()
        self.last_usage = Usage()
        inp = out = 0
        async with provider_stream(client, "POST", self.url, provider=self.name, stage="mt",
                                   headers=self.headers(), json=self.body(text, src, tgt, ctx)) as r:
            async for ev in iter_sse(r):
                typ = ev.get("type")
                if typ == "content_block_delta":
                    d = ev.get("delta") or {}
                    if d.get("type") == "text_delta" and d.get("text"):
                        yield d["text"]
                elif typ == "message_start":
                    u = (ev.get("message") or {}).get("usage") or {}
                    inp = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
                elif typ == "message_delta":
                    out = (ev.get("usage") or {}).get("output_tokens", out)
                elif typ == "message_stop":
                    break
                elif typ == "error":
                    err = ev.get("error") or {}
                    if err.get("type") in ("overloaded_error", "rate_limit_error"):
                        raise RateLimited(err.get("message", err["type"]), provider=self.name, stage="mt")
                    raise ProviderError(f"{err.get('type')}: {err.get('message', '')}"[:300],
                                        provider=self.name, stage="mt")
        self.last_usage = Usage(mt_input_tokens=inp, mt_output_tokens=out)
