"""POST /api/realtime/session: mint a short-lived Realtime client secret
(FR-2.1). The browser uses it as a Bearer token for its WebRTC SDP exchange
with OpenAI; the real API key never leaves the server (NFR-4)."""
from __future__ import annotations

import logging
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.config import get_settings
from app.providers.common.http import shared_client
from app.realtime.session_config import build_interpreter_session

log = logging.getLogger(__name__)
router = APIRouter()
MINT_URL = "https://api.openai.com/v1/realtime/client_secrets"
ALLOWED_MODELS = {"gpt-realtime", "gpt-realtime-mini"}


class MintRequest(BaseModel):
    a: str = "en"
    b: str = "es"
    turn_mode: Literal["ptt", "vad"] = "ptt"
    silence_duration_ms: int = 400
    model: str | None = None  # defaults to config (gpt-realtime-mini in dev)


def _client() -> httpx.AsyncClient:
    return shared_client()


@router.post("/api/realtime/session")
async def mint(req: MintRequest):
    settings = get_settings()
    if not settings.openai_api_key:
        raise HTTPException(503, detail={"code": "config_error", "message": "OPENAI_API_KEY is not set"})
    cfg = settings.app_config()["realtime"]
    model = req.model or cfg["model"]
    if model not in ALLOWED_MODELS | {cfg["model"]}:
        raise HTTPException(400, detail={"code": "bad_request", "message": f"model {model} not allowed"})
    session = build_interpreter_session(req.a, req.b, model=model, voice=cfg.get("voice", "marin"),
                                        transcription_model=cfg.get("transcription_model", "gpt-4o-transcribe"),
                                        turn_mode=req.turn_mode, silence_duration_ms=req.silence_duration_ms)
    body = {"expires_after": {"anchor": "created_at", "seconds": int(cfg.get("secret_ttl_s", 600))},
            "session": session}
    try:
        r = await _client().post(MINT_URL, json=body, timeout=10.0, headers={
            "Authorization": f"Bearer {settings.openai_api_key.get_secret_value()}"})
    except httpx.HTTPError as e:
        raise HTTPException(502, detail={"code": "provider_disconnected", "message": type(e).__name__}) from None
    if r.status_code >= 400:
        try:
            msg = r.json().get("error", {}).get("message", "")
        except ValueError:
            msg = ""
        log.warning("client secret mint failed: HTTP %s", r.status_code)
        if r.status_code == 429:
            return JSONResponse(status_code=429, headers={"Retry-After": r.headers.get("retry-after", "1")},
                                content={"detail": {"code": "rate_limited", "message": msg[:300]}})
        code = "auth_error" if r.status_code in (401, 403) else "provider_error"
        raise HTTPException(502, detail={"code": code, "status": r.status_code, "message": msg[:300]})
    data = r.json()
    return {"value": data["value"], "expires_at": data.get("expires_at"), "model": model,
            "turn_mode": req.turn_mode}
