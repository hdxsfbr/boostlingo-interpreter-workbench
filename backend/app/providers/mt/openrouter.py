"""OpenRouter translator: OpenAI-compatible Chat Completions streaming with
another base_url (DESIGN §2), so any routed model (e.g. a Haiku or Llama
variant) can be the cascade MT. `provider.sort: "latency"` asks OpenRouter to
prefer the lowest-latency upstream (R§3.1). Same instructions/input as the
other translators. Optional: needs OPENROUTER_API_KEY.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

import httpx

from app.core.errors import ConfigError, ProviderError, RateLimited
from app.providers.base import TurnContext, Usage
from app.providers.common.http import iter_sse, provider_stream, shared_client
from app.providers.mt.openai import INSTRUCTIONS, build_input
from app.providers.registry import register


@register("mt", "openrouter")
class OpenRouterTranslator:
    name = "openrouter"
    BASE = "https://openrouter.ai/api/v1"

    def __init__(self, api_key: str, model: str, max_tokens: int = 400, sort: str | None = "latency",
                 client: httpx.AsyncClient | None = None, base_url: str | None = None) -> None:
        if not api_key:
            raise ConfigError("OPENROUTER_API_KEY is not set", provider="openrouter", stage="mt")
        self.api_key, self.model, self.max_tokens, self.sort, self.client = api_key, model, max_tokens, sort, client
        self.url = (base_url or self.BASE).rstrip("/") + "/chat/completions"
        self.last_usage = Usage()

    def body(self, text: str, src: str, tgt: str, ctx: TurnContext) -> dict:
        b: dict = {"model": self.model, "stream": True, "max_tokens": self.max_tokens,
                   "messages": [{"role": "system", "content": INSTRUCTIONS},
                                {"role": "user", "content": build_input(text, src, tgt, ctx)}],
                   "stream_options": {"include_usage": True}}
        if self.sort:
            b["provider"] = {"sort": self.sort}
        return b

    async def stream(self, text: str, src: str, tgt: str, ctx: TurnContext) -> AsyncIterator[str]:
        client = self.client or shared_client()
        self.last_usage = Usage()
        headers = {"Authorization": f"Bearer {self.api_key}", "X-Title": "AI Interpreter Workbench"}
        async with provider_stream(client, "POST", self.url, provider=self.name, stage="mt", headers=headers,
                                   json=self.body(text, src, tgt, ctx)) as r:
            async for ev in iter_sse(r):
                if err := ev.get("error"):
                    code = err.get("code")
                    if code == 429 or "rate" in str(err.get("message", "")).lower():
                        raise RateLimited(str(err.get("message"))[:300], provider=self.name, stage="mt")
                    raise ProviderError(f"{code}: {err.get('message', '')}"[:300], provider=self.name, stage="mt")
                for ch in ev.get("choices") or []:
                    if piece := (ch.get("delta") or {}).get("content"):
                        yield piece
                if u := ev.get("usage"):
                    self.last_usage = Usage(mt_input_tokens=u.get("prompt_tokens", 0),
                                            mt_output_tokens=u.get("completion_tokens", 0))
