"""POST /api/turns: append finished turn records (browser-measured latency,
server marks, usage, transcripts) to data/sessions/<session_id>.jsonl.
No audio is stored (PRD A2). The eval harness reads the same files."""
from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.observability.client import get_langfuse
from app.observability.traces import turn_events

router = APIRouter()
_SAFE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


class TurnPost(BaseModel):
    session_id: str
    record: dict[str, Any]
    user_agent: str | None = Field(default=None, max_length=400)
    meta: dict[str, Any] | None = None  # A20: providers, pair, pipeline (for tracing; not logged)


@router.post("/api/turns", status_code=204)
async def post_turn(body: TurnPost) -> None:
    if not _SAFE.match(body.session_id):
        raise HTTPException(400, "invalid session_id")
    d = get_settings().data_dir / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    now = time.time()
    line = json.dumps({"ts": now, **body.model_dump(exclude={"meta"})}, ensure_ascii=False)
    await asyncio.to_thread(_append, d / f"{body.session_id}.jsonl", line)
    lf = get_langfuse()
    if lf.enabled:  # A20: enqueue only (no I/O here); the browser posts after playback, off the audio path
        try:
            turn_events(lf, body.session_id, body.record, body.meta, now)
        except Exception:  # noqa: BLE001 - tracing is fail-open
            lf.stats.dropped_error += 1


def _append(path, line: str) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
