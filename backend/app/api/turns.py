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

router = APIRouter()
_SAFE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


class TurnPost(BaseModel):
    session_id: str
    record: dict[str, Any]
    user_agent: str | None = Field(default=None, max_length=400)


@router.post("/api/turns", status_code=204)
async def post_turn(body: TurnPost) -> None:
    if not _SAFE.match(body.session_id):
        raise HTTPException(400, "invalid session_id")
    d = get_settings().data_dir / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"ts": time.time(), **body.model_dump()}, ensure_ascii=False)
    await asyncio.to_thread(_append, d / f"{body.session_id}.jsonl", line)


def _append(path, line: str) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
