"""Recording endpoints (DESIGN A11).

GET    /api/recordings/config                         -> {enabled, retention_days, max_upload_mb}
POST   /api/recordings/{session_id}/turns/{n}/{side}  raw audio body (audio/webm|ogg|wav); realtime uploads
DELETE /api/recordings/{session_id}                   delete one session's recordings
Uploads are refused (403) unless recording is enabled in config.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request

from app.core.recording import RecordingError, get_store

router = APIRouter()


@router.get("/api/recordings/config")
async def recording_config() -> dict:
    c = get_store().cfg
    return {"enabled": c.enabled, "retention_days": c.retention_days, "max_upload_mb": c.max_upload_mb}


@router.post("/api/recordings/{session_id}/turns/{turn}/{side}", status_code=201)
async def upload_turn(session_id: str, turn: int, side: str, request: Request) -> dict:
    store = get_store()
    if not store.cfg.enabled:
        raise HTTPException(403, "recording is disabled on this server")
    limit = int(store.cfg.max_upload_mb * 1024 * 1024)
    if int(request.headers.get("content-length") or 0) > limit:
        raise HTTPException(413, "upload too large")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise HTTPException(413, "upload too large")
    try:
        p = await asyncio.to_thread(store.save_upload, session_id, turn, side,
                                    request.headers.get("content-type", ""), bytes(body))
    except PermissionError as e:
        raise HTTPException(403, str(e)) from None
    except RecordingError as e:
        raise HTTPException(413 if "too large" in str(e) else 400, str(e)) from None
    return {"path": store.rel(p)}


@router.delete("/api/recordings/{session_id}")
async def delete_session(session_id: str) -> dict:
    try:
        n = await asyncio.to_thread(get_store().delete_session, session_id)
    except RecordingError as e:
        raise HTTPException(400, str(e)) from None
    return {"deleted_files": n}
