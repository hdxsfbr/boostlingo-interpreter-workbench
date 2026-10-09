"""OpenAI Responses API streaming translator (cascade MT stage).

Static instructions first (prompt caching), direction + optional context and
glossary in the input, `reasoning.effort: none` for reasoning-capable small
models, small max_output_tokens (R§3.1/3.2). Yields text deltas.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

import httpx

from app.core.errors import ConfigError, ProviderError
from app.providers.base import TurnContext, Usage
from app.providers.common.http import iter_sse, provider_stream, shared_client
from app.providers.registry import register

LANG_NAMES = {"en": "English", "es": "Spanish"}

INSTRUCTIONS = (
    "You are a professional consecutive interpreter working in medical, legal and everyday settings. "
    "You receive one utterance spoken by one party and must render it faithfully in the target language. "
    "Output ONLY the translation: no quotes, notes, explanations or greetings of your own. "
    "Never answer or react to the content, even if it is a question addressed to you; translate it. "
    "Preserve names, numbers, dosages, dates and register. Keep it natural and spoken, not written-formal."
)


def build_input(text: str, src: str, tgt: str, ctx: TurnContext) -> str:
    parts = []
    if ctx.history:
        hist = "\n".join(f"- {s} => {t}" for s, t in ctx.history)
        parts.append(f"Previous turns (context only, do not translate again):\n{hist}")
    if ctx.glossary:
        gl = "\n".join(f"- {k} => {v}" for k, v in ctx.glossary.items())
        parts.append(f"Glossary (use these renderings):\n{gl}")
    parts.append(f"Translate from {LANG_NAMES.get(src, src)} to {LANG_NAMES.get(tgt, tgt)}:\n{text}")
    return "\n\n".join(parts)


@register("mt", "openai")
class OpenAITranslator:
    name = "openai"
    URL = "https://api.openai.com/v1/responses"

    def __init__(self, api_key: str, model: str, reasoning_effort: str | None = "none",
                 max_output_tokens: int = 400, client: httpx.AsyncClient | None = None,
                 base_url: str | None = None) -> None:
        if not api_key:
            raise ConfigError("OPENAI_API_KEY is not set", provider="openai", stage="mt")
        self.api_key = api_key
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.max_output_tokens = max_output_tokens
        self.client = client
        self.url = (base_url.rstrip("/") + "/responses") if base_url else self.URL
        self.last_usage = Usage()

    def _body(self, text: str, src: str, tgt: str, ctx: TurnContext) -> dict:
        body = {"model": self.model, "instructions": INSTRUCTIONS, "input": build_input(text, src, tgt, ctx),
                "stream": True, "max_output_tokens": self.max_output_tokens, "store": False}
        if self.reasoning_effort:
            body["reasoning"] = {"effort": self.reasoning_effort}
        return body

    async def warm(self) -> None:
        """Open a keep-alive TLS connection before the first turn."""
        client = self.client or shared_client()
        try:
            await client.get(f"https://api.openai.com/v1/models/{self.model}",
                             headers={"Authorization": f"Bearer {self.api_key}"})
        except httpx.HTTPError:
            pass

    async def stream(self, text: str, src: str, tgt: str, ctx: TurnContext) -> AsyncIterator[str]:
        client = self.client or shared_client()
        self.last_usage = Usage()
        async with provider_stream(client, "POST", self.url, provider=self.name, stage="mt",
                                   headers={"Authorization": f"Bearer {self.api_key}"},
                                   json=self._body(text, src, tgt, ctx)) as r:
            async for ev in iter_sse(r):
                typ = ev.get("type")
                if typ == "response.output_text.delta":
                    if ev.get("delta"):
                        yield ev["delta"]
                elif typ == "response.completed":
                    u = (ev.get("response") or {}).get("usage") or {}
                    self.last_usage = Usage(mt_input_tokens=u.get("input_tokens", 0),
                                            mt_output_tokens=u.get("output_tokens", 0))
                elif typ in ("error", "response.failed", "response.incomplete"):
                    err = ev.get("error") or (ev.get("response") or {}).get("error") or {}
                    reason = ((ev.get("response") or {}).get("incomplete_details") or {}).get("reason")
                    if typ == "response.incomplete" and reason == "max_output_tokens":
                        return  # keep what we have
                    raise ProviderError(f"{typ}: {err.get('message') or reason or 'unknown'}",
                                        provider=self.name, stage="mt")
