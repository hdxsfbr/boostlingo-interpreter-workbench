"""Review tab API (DESIGN A12). Rater = plain name, no auth (local tool).

Blindness: for blind sets, item payloads, results and CSV exports carry no
variant (nor the utterance id) until this rater pressed Reveal or rated every
item; results are refused (403) until then.
"""
from __future__ import annotations

import mimetypes

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.observability.client import get_langfuse
from app.observability.traces import review_events, review_score_ids
from app.review import results as res
from app.review import sources
from app.review.store import DIMS, MAX_NOTES, ReviewError, ReviewStore, norm_rater

# explicit: slim images may lack /etc/mime.types, and the browser needs audio/* to play a clip
AUDIO_TYPES = {".ogg": "audio/ogg", ".wav": "audio/wav", ".webm": "audio/webm", ".m4a": "audio/mp4", ".mp3": "audio/mpeg"}
router = APIRouter(prefix="/api/review")
_STORE: ReviewStore | None = None


def get_review_store() -> ReviewStore:
    global _STORE
    if _STORE is None:
        s = get_settings()
        _STORE = ReviewStore(s.data_dir / "review.sqlite3")
        sources.bootstrap(_STORE, s.bench_dir / "blind")
    return _STORE


def _err(e: ReviewError) -> HTTPException:
    return HTTPException(404 if e.missing else 400, str(e))


def _rater(rater: str) -> str:
    try:
        return norm_rater(rater)
    except ReviewError as e:
        raise _err(e) from e


class RatingIn(BaseModel):
    rater: str = Field(max_length=60)
    adequacy: int | None = None
    fluency: int | None = None
    naturalness: int | None = None
    notes: str = Field(default="", max_length=MAX_NOTES)


class RaterIn(BaseModel):
    rater: str = Field(max_length=60)


def _item_view(it, revealed: bool) -> dict:
    d = {"item_id": it.item_id, "idx": it.idx, "direction": it.direction, "source_text": it.source_text,
         "reference": it.reference, "target_text": it.target_text,
         "audio_url": f"/api/review/sets/{it.set_id}/items/{it.item_id}/audio"}
    if revealed:
        d["variant"] = it.variant
    return d


@router.get("/sets")
def list_sets(rater: str | None = None) -> list[dict]:
    st = get_review_store()
    out = st.list_sets()
    if rater:
        r = _rater(rater)
        for s in out:
            s["progress"] = st.progress(s["id"], r)
            s["revealed"] = st.revealed(s["id"], r)
    return out


@router.get("/sets/{set_id}")
def get_set(set_id: str, rater: str) -> dict:
    st = get_review_store()
    r = _rater(rater)
    try:
        info = st.get_set(set_id)
        revealed = st.revealed(set_id, r)
        ratings = {x["item_id"]: {**{d: x[d] for d in DIMS}, "notes": x["notes"]} for x in st.ratings(set_id, r)}
        return {**info, "rater": r, "revealed": revealed, "progress": st.progress(set_id, r),
                "items": [_item_view(it, revealed) for it in st.items(set_id)], "ratings": ratings}
    except ReviewError as e:
        raise _err(e) from e


@router.put("/sets/{set_id}/items/{item_id}/rating")
def save_rating(set_id: str, item_id: str, body: RatingIn) -> dict:
    st = get_review_store()
    try:
        saved = st.save_rating(set_id, item_id, body.rater, {d: getattr(body, d) for d in DIMS}, body.notes)
        _trace_rating(st, set_id, item_id, body)
        return {"saved": saved, "progress": st.progress(set_id, norm_rater(body.rater))}
    except ReviewError as e:
        raise _err(e) from e


@router.get("/sets/{set_id}/items/{item_id}/audio")
def audio(set_id: str, item_id: str) -> FileResponse:
    st = get_review_store()
    s = get_settings()
    try:
        info, it = st.get_set(set_id), st.item(set_id, item_id)
    except ReviewError as e:
        raise _err(e) from e
    if info["kind"] == "blind":
        root = (s.bench_dir / "blind" / "clips").resolve()
        p = (s.bench_dir / "blind" / it.audio).resolve()
    else:
        root = (s.data_dir / "recordings").resolve()
        p = (s.data_dir / it.audio).resolve()
    if root not in p.parents or not p.is_file():
        raise HTTPException(404, "audio not found (deleted by retention?)")
    # no filename / path in the response headers: the clip name is all the client knows
    return FileResponse(p, media_type=AUDIO_TYPES.get(p.suffix.lower()) or mimetypes.guess_type(p.name)[0]
                        or "application/octet-stream")


@router.post("/sets/{set_id}/reveal")
def reveal(set_id: str, body: RaterIn) -> dict:
    st = get_review_store()
    try:
        st.reveal(set_id, _rater(body.rater))
    except ReviewError as e:
        raise _err(e) from e
    return {"revealed": True}


def _results(set_id: str, rater: str, raters: str) -> list[dict]:
    st = get_review_store()
    r = _rater(rater)
    try:
        if not st.revealed(set_id, r):
            raise HTTPException(403, "blind set: finish rating every item or press Reveal to see results")
        ratings = st.ratings(set_id, None if raters == "all" else r)
        return res.aggregate(st.items(set_id), ratings, res.m5_index(get_settings().bench_dir / "results" / "m5" / "results.json"))
    except ReviewError as e:
        raise _err(e) from e


@router.get("/sets/{set_id}/results")
def results(set_id: str, rater: str, raters: str = Query("me", pattern="^(me|all)$")) -> dict:
    rows = _results(set_id, rater, raters)
    st = get_review_store()
    raters_n = len({x["rater"] for x in st.ratings(set_id)}) if raters == "all" else 1
    return {"set_id": set_id, "raters": raters, "rater_count": raters_n, "rows": rows}


@router.get("/sets/{set_id}/results.csv")
def results_csv(set_id: str, rater: str, raters: str = Query("me", pattern="^(me|all)$")) -> PlainTextResponse:
    rows = _results(set_id, rater, raters)
    return PlainTextResponse(res.to_csv(rows), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{set_id}-results.csv"'})


@router.get("/sets/{set_id}/ratings.csv")
def ratings_csv(set_id: str, rater: str) -> PlainTextResponse:
    """This rater's raw ratings; the variant column is filled only once revealed."""
    import csv
    import io
    st = get_review_store()
    r = _rater(rater)
    try:
        revealed = st.revealed(set_id, r)
        items = {it.item_id: it for it in st.items(set_id)}
        mine = {x["item_id"]: x for x in st.ratings(set_id, r)}
    except ReviewError as e:
        raise _err(e) from e
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["item_id", "direction", "variant", *DIMS, "notes"])
    for iid, it in items.items():
        x = mine.get(iid, {})
        w.writerow([iid, it.direction, it.variant if revealed else "", *(x.get(d) for d in DIMS), x.get("notes", "")])
    return PlainTextResponse(buf.getvalue(), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{set_id}-{r}-ratings.csv"'})


@router.delete("/sets/{set_id}/ratings")
def delete_ratings(set_id: str, rater: str) -> dict:
    st = get_review_store()
    try:
        st.get_set(set_id)
        mine = [x["item_id"] for x in st.ratings(set_id, _rater(rater))]
        n = st.delete_ratings(set_id, _rater(rater))
        _untrace_ratings(set_id, mine, _rater(rater))
        return {"deleted": n}
    except ReviewError as e:
        raise _err(e) from e


@router.get("/sessions")
def sessions() -> list[dict]:
    st = get_review_store()
    have = {s["id"] for s in st.list_sets()}
    out = sources.list_sessions(get_settings().data_dir)
    for s in out:
        sid = sources.session_set_id(s["session_id"])
        s["set_id"] = sid if sid in have else None
    return out


@router.post("/sessions/{session_id}")
def import_session(session_id: str) -> dict:
    try:
        return {"set_id": sources.import_session(get_review_store(), get_settings().data_dir, session_id)}
    except ReviewError as e:
        raise _err(e) from e


__all__ = ["get_review_store", "router"]


def _trace_rating(st, set_id: str, item_id: str, body: RatingIn) -> None:
    """A20: human ratings as Langfuse scores (no-op unless tracing is on; never fails the save)."""
    lf = get_langfuse()
    if not lf.enabled:
        return
    try:
        import dataclasses
        review_events(lf, set_id, dataclasses.asdict(st.item(set_id, item_id)), norm_rater(body.rater),
                      {d: getattr(body, d) for d in DIMS}, body.notes)
    except Exception:  # noqa: BLE001 - tracing is fail-open
        lf.stats.dropped_error += 1


def _untrace_ratings(set_id: str, item_ids: list[str], rater: str) -> None:
    """A20: delete the matching Langfuse human_* scores (queued, best effort, fail-open)."""
    lf = get_langfuse()
    if not lf.enabled:
        return
    for item in item_ids:
        for sid in review_score_ids(set_id, item, rater, list(DIMS)):
            lf.delete(f"/api/public/scores/{sid}")
