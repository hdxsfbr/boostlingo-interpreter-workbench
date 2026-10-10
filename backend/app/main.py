"""FastAPI entrypoint: serves the SPA, health, realtime secret minting,
turn-record sink and the cascade WebSocket gateway."""
from __future__ import annotations

import asyncio
import contextlib
import logging

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api.cascade_ws import router as cascade_router
from app.api.experiments import get_experiments
from app.api.experiments import router as experiments_router
from app.api.languages import router as languages_router
from app.api.realtime_relay import router as relay_router
from app.api.realtime_session import router as realtime_router
from app.api.recordings import router as recordings_router
from app.api.review import get_review_store
from app.api.review import router as review_router
from app.api.turns import router as turns_router
from app.core.auth import LOGGED_OUT_HTML, AuthGate, credentials_from_env
from app.core.config import get_settings
from app.core.recording import get_store
from app.observability.client import get_langfuse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app() -> FastAPI:
    settings = get_settings()
    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        store = get_store()  # A11 retention: sweep on startup, then periodically
        with contextlib.suppress(OSError):
            await asyncio.to_thread(store.sweep)
        task = asyncio.create_task(store.sweep_forever())
        with contextlib.suppress(OSError):  # A12: blind set import + preload (idempotent)
            await asyncio.to_thread(get_review_store)
        with contextlib.suppress(OSError):  # A13: mark stale runs, import the M5 baseline (idempotent)
            await asyncio.to_thread(get_experiments)
        lf = get_langfuse()  # A20: Langfuse flusher (no-op when off)
        await lf.start()
        yield
        task.cancel()
        await lf.stop()

    app = FastAPI(title="AI Interpreter Workbench", version="0.1.0", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz() -> dict:
        """Open (platform health check): status only, no model/provider/key details (A15)."""
        return {"status": "ok"}

    @app.get("/api/health")
    async def health() -> dict:
        """Details for the UI; behind the password gate like every other route."""
        cfg = settings.app_config()
        return {
            "status": "ok",
            "providers": settings.provider_status(),
            "cascade": cfg["cascade"],
            "realtime_model": cfg["realtime"]["model"],
            "swaps": settings.swap_options(),
            "recording": {"enabled": get_store().cfg.enabled, "retention_days": get_store().cfg.retention_days},
            "auth": {"enabled": credentials_from_env(warn=False) is not None},
            "tracing": {"langfuse": get_langfuse().status()},  # A20: on/off + sent/dropped counts, no secrets
        }

    @app.get("/auth/logged-out", include_in_schema=False)
    async def logged_out() -> HTMLResponse:
        return HTMLResponse(LOGGED_OUT_HTML, headers={"cache-control": "no-store"})

    app.include_router(cascade_router)
    app.include_router(turns_router)
    app.include_router(realtime_router)
    app.include_router(relay_router)
    app.include_router(recordings_router)
    app.include_router(review_router)
    app.include_router(experiments_router)
    app.include_router(languages_router)

    if settings.static_dir and settings.static_dir.is_dir():
        app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="spa")
    creds = credentials_from_env()
    if creds:  # A15: app-wide gate, outermost, so it covers SPA, /api, WS and SSE alike
        app.add_middleware(AuthGate, username=creds[0], password=creds[1],
                           revoked_path=settings.data_dir / "auth_revoked.json")
        logging.getLogger("app.auth").info("password gate on (user %s)", creds[0])
    return app


app = create_app()
