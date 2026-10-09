"""FastAPI entrypoint: serves the SPA, health, realtime secret minting,
turn-record sink and the cascade WebSocket gateway."""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.cascade_ws import router as cascade_router
from app.api.realtime_relay import router as relay_router
from app.api.realtime_session import router as realtime_router
from app.api.turns import router as turns_router
from app.core.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="AI Interpreter Workbench", version="0.1.0")

    @app.get("/healthz")
    async def healthz() -> dict:
        cfg = settings.app_config()
        return {
            "status": "ok",
            "providers": settings.provider_status(),
            "cascade": cfg["cascade"],
            "realtime_model": cfg["realtime"]["model"],
        }

    app.include_router(cascade_router)
    app.include_router(turns_router)
    app.include_router(realtime_router)
    app.include_router(relay_router)

    if settings.static_dir and settings.static_dir.is_dir():
        app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="spa")
    return app


app = create_app()
