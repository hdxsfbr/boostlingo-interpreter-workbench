"""Anthropic translator adapter against a Messages SSE stream (no network)."""
import json
from pathlib import Path

import httpx
import pytest

from app.core.errors import AuthError, BadRequest, ProviderError, RateLimited
from app.providers import registry
from app.providers.base import TurnContext
from app.providers.mt.anthropic import AnthropicTranslator

FIX = Path(__file__).resolve().parents[3] / "contract" / "fixtures" / "anthropic"


def sse(events):
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


def client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def collect(it):
    return [x async for x in it]


async def test_streams_text_deltas_usage_and_sends_workspace_header():
    events = json.loads((FIX / "messages_stream_translate.synthetic.json").read_text())["events"]
    seen = {}

    def handler(req: httpx.Request):
        seen["h"], seen["body"] = req.headers, json.loads(req.content)
        return httpx.Response(200, content=sse(events), headers={"content-type": "text/event-stream"})

    mt = AnthropicTranslator("sk-ant-test", "claude-haiku-5-5", workspace_id="wrkspc_test", client=client(handler))
    toks = await collect(mt.stream("I have had a headache for three days.", "en", "es", TurnContext()))
    assert "".join(toks) == "He tenido dolor de cabeza durante tres días." and len(toks) == 6
    assert (mt.last_usage.mt_input_tokens, mt.last_usage.mt_output_tokens) == (120, 14)
    h, b = seen["h"], seen["body"]
    assert h["x-api-key"] == "sk-ant-test" and h["anthropic-workspace-id"] == "wrkspc_test"
    assert h["anthropic-version"] == "2023-06-01"
    assert b["thinking"] == {"type": "disabled"} and b["output_config"] == {"effort": "low"}
    assert b["stream"] is True and b["model"] == "claude-haiku-5-5"
    for banned in ("temperature", "top_p", "top_k"):  # 400 on current Claude models (R§3.1)
        assert banned not in b
    assert b["messages"][-1]["role"] == "user"  # no assistant prefill (rejected by Haiku 5.5)
    assert b["messages"][0]["content"].endswith("Translate from English to Spanish:\nI have had a headache for three days.")


def test_workspace_header_omitted_when_not_configured():
    assert "anthropic-workspace-id" not in AnthropicTranslator("k", "m").headers()


@pytest.mark.parametrize("status,exc", [(429, RateLimited), (401, AuthError), (400, BadRequest)])
async def test_http_errors_are_normalised(status, exc):
    def handler(req):
        return httpx.Response(status, json={"type": "error", "error": {"type": "x", "message": "nope"}},
                              headers={"retry-after": "2"})

    mt = AnthropicTranslator("k", "m", workspace_id="w", client=client(handler))
    with pytest.raises(exc):
        await collect(mt.stream("x", "en", "es", TurnContext()))


async def test_mid_stream_overload_is_retryable_rate_limit():
    events = [{"type": "message_start", "message": {"usage": {"input_tokens": 3}}},
              {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}]
    mt = AnthropicTranslator("k", "m", client=client(lambda r: httpx.Response(200, content=sse(events))))
    with pytest.raises(RateLimited):
        await collect(mt.stream("x", "en", "es", TurnContext()))


async def test_mid_stream_other_error_raises_provider_error():
    events = [{"type": "error", "error": {"type": "api_error", "message": "boom"}}]
    mt = AnthropicTranslator("k", "m", client=client(lambda r: httpx.Response(200, content=sse(events))))
    with pytest.raises(ProviderError):
        await collect(mt.stream("x", "en", "es", TurnContext()))


def test_registered_and_missing_key_is_config_error():
    from app.core.errors import ConfigError
    with pytest.raises(ConfigError):
        registry.create("mt", "anthropic", api_key="", model="m")
