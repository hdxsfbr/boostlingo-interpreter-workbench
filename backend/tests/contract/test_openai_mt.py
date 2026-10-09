"""OpenAI translator adapter against a recorded Responses SSE stream (no network)."""
import json
from pathlib import Path

import httpx
import pytest

from app.core.errors import AuthError, ConfigError, ProviderDisconnected, RateLimited
from app.providers.base import TurnContext
from app.providers.mt.openai import OpenAITranslator, build_input

FIX = Path(__file__).resolve().parents[3] / "contract" / "fixtures" / "openai"


def sse_body(events):
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


def client_with(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def collect(it):
    return [x async for x in it]


async def test_maps_deltas_and_usage_from_recorded_stream():
    events = json.loads((FIX / "responses_stream_translate.json").read_text())
    seen = {}

    def handler(req: httpx.Request):
        seen["auth"] = req.headers["authorization"]
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, content=sse_body(events), headers={"content-type": "text/event-stream"})

    mt = OpenAITranslator("sk-test", "gpt-5.4-nano", client=client_with(handler))
    toks = await collect(mt.stream("Good morning.", "en", "es", TurnContext()))
    expected = "".join(e["delta"] for e in events if e["type"] == "response.output_text.delta")
    assert "".join(toks) == expected and len(toks) > 1
    assert mt.last_usage.mt_input_tokens == 33 and mt.last_usage.mt_output_tokens == 17
    b = seen["body"]
    assert b["stream"] is True and b["reasoning"] == {"effort": "none"} and b["store"] is False
    assert b["instructions"].startswith("You are a professional consecutive interpreter")
    assert b["input"].endswith("Translate from English to Spanish:\nGood morning.")
    assert seen["auth"] == "Bearer sk-test"


def test_input_includes_history_and_glossary_but_instructions_stay_static():
    ctx = TurnContext(history=[("Hi", "Hola")], glossary={"ibuprofen": "ibuprofeno"})
    s = build_input("Take ibuprofen.", "en", "es", ctx)
    assert "- Hi => Hola" in s and "- ibuprofen => ibuprofeno" in s
    assert OpenAITranslator("k", "m")._body("x", "en", "es", ctx)["instructions"] == \
        OpenAITranslator("k", "m")._body("y", "es", "en", TurnContext())["instructions"]


def test_reasoning_omitted_for_non_reasoning_models():
    assert "reasoning" not in OpenAITranslator("k", "gpt-4.1-nano", reasoning_effort=None)._body(
        "x", "en", "es", TurnContext())


@pytest.mark.parametrize("status,exc", [(429, RateLimited), (401, AuthError)])
async def test_http_errors_are_normalised(status, exc):
    def handler(req):
        return httpx.Response(status, json={"error": {"message": "nope"}}, headers={"retry-after": "1.5"})

    mt = OpenAITranslator("sk-test", "m", client=client_with(handler))
    with pytest.raises(exc) as ei:
        await collect(mt.stream("x", "en", "es", TurnContext()))
    assert ei.value.stage == "mt"
    if status == 429:
        assert ei.value.retry_after == 1.5


async def test_network_error_maps_to_disconnected():
    def handler(req):
        raise httpx.ConnectError("boom")

    mt = OpenAITranslator("sk-test", "m", client=client_with(handler))
    with pytest.raises(ProviderDisconnected):
        await collect(mt.stream("x", "en", "es", TurnContext()))


async def test_failed_event_raises_and_missing_key_is_config_error():
    def handler(req):
        return httpx.Response(200, content=sse_body([{"type": "response.failed",
                                                      "response": {"error": {"message": "server"}}}]))

    mt = OpenAITranslator("sk-test", "m", client=client_with(handler))
    with pytest.raises(Exception, match="response.failed"):
        await collect(mt.stream("x", "en", "es", TurnContext()))
    with pytest.raises(ConfigError):
        OpenAITranslator("", "m")
