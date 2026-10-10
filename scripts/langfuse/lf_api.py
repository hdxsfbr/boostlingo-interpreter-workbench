"""A20 helpers: read-only Langfuse public API (keys read from files; never printed)."""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CF = Path(os.environ.get("LANGFUSE_KEY_DIR", Path.home() / ".config/agentforge"))
HOST = os.environ.get("LANGFUSE_HOST", "https://us.cloud.langfuse.com")


def _auth() -> str:
    pk = (CF / "langfuse_public_key").read_text().strip()
    sk = (CF / "langfuse_secret_key").read_text().strip()
    return "Basic " + base64.b64encode(f"{pk}:{sk}".encode()).decode()


def get(path: str, **params) -> dict:
    q = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}, doseq=True)
    req = urllib.request.Request(f"{HOST}{path}{'?' + q if q else ''}", headers={"Authorization": _auth()})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 5:
                raise
            time.sleep(2 ** attempt)


def all_pages(path: str, **params) -> list[dict]:
    out, page = [], 1
    while True:
        d = get(path, page=page, limit=100, **params)
        out += d.get("data", [])
        if page >= (d.get("meta") or {}).get("totalPages", 1):
            return out
        page += 1


def project_id() -> str:
    return get("/api/public/projects")["data"][0]["id"]


def trace_url(trace_id: str) -> str:
    return f"{HOST}/project/{project_id()}/traces/{trace_id}"
