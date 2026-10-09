"""One-shot OpenRouter validity check through the cascade adapter (M4).

Sends ONE short translation request with the configured Haiku model via
OpenRouterTranslator's own URL/body/headers and prints only the HTTP status,
the model id requested and the model id OpenRouter reports serving. Never
prints headers or key material. Not for loops, tests or CI.

    set -a; source ../.env; set +a; python -m eval.openrouter_check
"""
from __future__ import annotations

import asyncio
import json
import os

import httpx

from app.core.config import get_settings
from app.providers.base import TurnContext
from app.providers.mt.openrouter import OpenRouterTranslator


async def main() -> None:
    cfg = get_settings().app_config()["providers"]["openrouter"]
    tr = OpenRouterTranslator(api_key=os.environ.get("OPENROUTER_API_KEY", ""), model=cfg["model"],
                              max_tokens=60, sort=cfg.get("sort"))
    body = tr.body("Good morning, doctor.", "en", "es", TurnContext(history=[], glossary={}))
    served, err = None, None
    headers = {"Authorization": f"Bearer {tr.api_key}", "X-Title": "AI Interpreter Workbench"}
    async with httpx.AsyncClient(timeout=30) as c, c.stream("POST", tr.url, json=body, headers=headers) as r:
        status = r.status_code
        if status == 200:
            async for line in r.aiter_lines():
                if line.startswith("data: ") and line[6:].strip() != "[DONE]":
                    ev = json.loads(line[6:])
                    served = served or ev.get("model")
                    if ev.get("error"):
                        err = ev["error"].get("message")
        else:
            try:
                err = json.loads(await r.aread()).get("error", {}).get("message")
            except ValueError:
                err = None
    print(f"status={status} model_requested={cfg['model']} model_served={served}" + (f" error={err}" if err else ""))


if __name__ == "__main__":
    asyncio.run(main())
