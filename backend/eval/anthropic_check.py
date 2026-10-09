"""ONE Anthropic validity check (secret-safe): a single streamed translation
with the production request shape (incl. anthropic-workspace-id). Prints only
the HTTP status code; on 200 saves the SSE events (no headers, no secrets) as
a contract fixture. Never run in loops or CI."""
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.providers.base import TurnContext  # noqa: E402
from app.providers.mt.anthropic import AnthropicTranslator  # noqa: E402

KEYS = Path.home() / ".config" / "agentforge"
FIX = Path(__file__).resolve().parents[2] / "contract" / "fixtures" / "anthropic" / "messages_stream_translate.json"

mt = AnthropicTranslator((KEYS / "anthropic_api_key").read_text().strip(), "claude-haiku-5-5",
                         workspace_id=(KEYS / "anthropic_workspace_id").read_text().strip())
body = mt.body("I have had a headache for three days.", "en", "es", TurnContext())
t0 = time.perf_counter()
events, first = [], None
with httpx.Client(timeout=20) as c, c.stream("POST", mt.url, headers=mt.headers(), json=body) as r:
    print("status", r.status_code)
    if r.status_code == 200:
        for line in r.iter_lines():
            if line.startswith("data: "):
                ev = json.loads(line[6:])
                if first is None and ev.get("type") == "content_block_delta":
                    first = (time.perf_counter() - t0) * 1000
                events.append(ev)
if events:
    FIX.parent.mkdir(parents=True, exist_ok=True)
    FIX.write_text(json.dumps(events, ensure_ascii=False, indent=1))
    print("events", len(events), "ttft_ms", round(first or -1))
