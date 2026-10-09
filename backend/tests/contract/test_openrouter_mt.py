"""OpenRouter translator against an OpenAI-compatible chat SSE stream (no network)."""
import json

import httpx
import pytest

from app.core.errors import AuthError, ProviderError, RateLimited
from app.providers import registry
from app.providers.base import TurnContext


def sse(events):
    return ("".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n").encode()


def mt_with(handler, **kw):
    return registry.create("mt", "openrouter", api_key="sk-or-test", model="anthropic/claude-haiku-5-5",
                           client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), **kw)


async def collect(it):
    return [x async for x in it]


async def test_streams_deltas_usage_and_latency_routing():
    events = [{"choices": [{"delta": {"role": "assistant", "content": ""}}]},
              {"choices": [{"delta": {"content": "My chest"}}]},
              {"choices": [{"delta": {"content": " hurts."}}]},
              {"choices": [{"delta": {}, "finish_reason": "stop"}]},
              {"choices": [], "usage": {"prompt_tokens": 90, "completion_tokens": 5}},
              ": OPENROUTER PROCESSING"]
    seen = {}

    def handler(req):
        seen["url"], seen["h"], seen["b"] = str(req.url), req.headers, json.loads(req.content)
        body = sse([e for e in events if isinstance(e, dict)])
        return httpx.Response(200, content=b": OPENROUTER PROCESSING\n\n" + body)

    mt = mt_with(handler)
    assert "".join(await collect(mt.stream("Me duele el pecho.", "es", "en", TurnContext()))) == "My chest hurts."
    assert (mt.last_usage.mt_input_tokens, mt.last_usage.mt_output_tokens) == (90, 5)
    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert seen["h"]["authorization"] == "Bearer sk-or-test"
    b = seen["b"]
    assert b["provider"] == {"sort": "latency"} and b["stream"] is True
    assert b["messages"][0]["role"] == "system" and b["messages"][1]["content"].endswith("Me duele el pecho.")


@pytest.mark.parametrize("status,exc", [(429, RateLimited), (401, AuthError)])
async def test_http_errors(status, exc):
    mt = mt_with(lambda r: httpx.Response(status, json={"error": {"message": "x"}}))
    with pytest.raises(exc):
        await collect(mt.stream("x", "en", "es", TurnContext()))


async def test_mid_stream_errors():
    mt = mt_with(lambda r: httpx.Response(200, content=sse([{"error": {"code": 429, "message": "Rate limit"}}])))
    with pytest.raises(RateLimited):
        await collect(mt.stream("x", "en", "es", TurnContext()))
    mt = mt_with(lambda r: httpx.Response(200, content=sse([{"error": {"code": 502, "message": "upstream"}}])))
    with pytest.raises(ProviderError):
        await collect(mt.stream("x", "en", "es", TurnContext()))
