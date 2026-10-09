"""GET /api/languages: configured languages and pairs (FR-5, DESIGN A14)."""
from __future__ import annotations

from fastapi import APIRouter

from app.core.languages import languages_config

router = APIRouter()


@router.get("/api/languages")
def languages() -> dict:
    return languages_config().public()
