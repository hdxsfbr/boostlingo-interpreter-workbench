"""Where review items come from (DESIGN A12).

(a) Blind benchmark set: `docs/benchmarks/blind/` (rating_sheet.csv + key.csv +
    clips/). Imported once as set `blind-m5`; the key's profile becomes the
    item's hidden `variant`. Andre's completed sheet is preloaded as rater
    `andre` so the set opens complete and Results matches results.md.
(b) Recorded sessions: `data/recordings/<sid>/turn-<n>-target.*` joined with the
    turn records in `data/sessions/<sid>.jsonl` (source/target text, mode).
"""
from __future__ import annotations

import csv
import json
import logging
import re
from pathlib import Path

from app.core.recording import SESSION_RE
from app.review.store import DIMS, Item, ReviewError, ReviewStore

log = logging.getLogger(__name__)
BLIND_SET = "blind-m5"
PRELOAD_RATER = "andre"
_TURN_FILE = re.compile(r"^turn-(\d{1,6})-target\.(wav|webm|ogg)$")


def import_blind(store: ReviewStore, blind_dir: Path) -> bool:
    """Create the blind set from the sheet + key (idempotent). Returns True if the set exists."""
    sheet, key = blind_dir / "rating_sheet.csv", blind_dir / "key.csv"
    if not (sheet.is_file() and key.is_file()):
        return False
    with open(key, newline="", encoding="utf-8") as f:
        keyed = {r["clip"]: r for r in csv.DictReader(f)}
    with open(sheet, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    items = [Item(set_id=BLIND_SET, item_id=r["clip"], idx=i, audio=f"clips/{r['clip']}", direction=r["direction"],
                  source_text=r["source_text"], reference=r.get("reference_translation", ""),
                  variant=keyed[r["clip"]]["profile"], ref_id=keyed[r["clip"]]["utterance_id"])
             for i, r in enumerate(rows)]
    store.create_set(BLIND_SET, "blind", "M5 blind benchmark (48 clips, 4 variants)", True, items,
                     source="docs/benchmarks/blind")
    return True


def preload_ratings(store: ReviewStore, blind_dir: Path, rater: str = PRELOAD_RATER) -> int:
    """Import the completed rating sheet as `rater`, only if that rater has no ratings yet."""
    if store.ratings(BLIND_SET, rater):
        return 0
    n = 0
    with open(blind_dir / "rating_sheet.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            scores = {d: int(r[f"{d}_1_5"]) if r.get(f"{d}_1_5", "").strip() else None for d in DIMS}
            if all(v is None for v in scores.values()):
                continue
            store.save_rating(BLIND_SET, r["clip"], rater, scores, r.get("notes", ""), origin="preload:rating_sheet.csv")
            n += 1
    return n


def bootstrap(store: ReviewStore, blind_dir: Path) -> None:
    try:
        if import_blind(store, blind_dir):
            n = preload_ratings(store, blind_dir)
            if n:
                log.info("review: preloaded %d ratings for %s", n, PRELOAD_RATER)
    except (OSError, KeyError, ValueError) as e:  # never block startup on the review tab
        log.warning("review: blind import skipped: %s", e)


# ----- recorded sessions
def _turn_records(data_dir: Path, sid: str) -> dict[int, dict]:
    p = data_dir / "sessions" / f"{sid}.jsonl"
    out: dict[int, dict] = {}
    if not p.is_file():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line).get("record")
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict) and isinstance(rec.get("turn_id"), int):
            out[rec["turn_id"]] = rec
    return out


def _targets(data_dir: Path, sid: str) -> dict[int, str]:
    d = data_dir / "recordings" / sid
    out = {}
    if d.is_dir() and not d.is_symlink():
        for f in d.iterdir():
            m = _TURN_FILE.match(f.name)
            if m and f.is_file() and not f.is_symlink():
                out[int(m.group(1))] = f"recordings/{sid}/{f.name}"
    return out


def list_sessions(data_dir: Path) -> list[dict]:
    root = data_dir / "recordings"
    out = []
    if not root.is_dir():
        return out
    for d in sorted(root.iterdir(), reverse=True):
        if not (d.is_dir() and SESSION_RE.match(d.name)):
            continue
        targets = _targets(data_dir, d.name)
        if not targets:
            continue
        recs = _turn_records(data_dir, d.name)
        modes = sorted({recs[t].get("mode", "?") for t in targets if t in recs})
        out.append({"session_id": d.name, "turns": len(targets), "modes": modes})
    return out


def session_set_id(sid: str) -> str:
    return f"session-{sid}"


def import_session(store: ReviewStore, data_dir: Path, sid: str) -> str:
    """Create or refresh the review set for one recorded session (rates each turn's target audio)."""
    if not SESSION_RE.match(sid):
        raise ReviewError("invalid session id")
    targets = _targets(data_dir, sid)
    if not targets:
        raise ReviewError("no recorded target audio for this session", missing=True)
    recs = _turn_records(data_dir, sid)
    items = []
    for i, turn in enumerate(sorted(targets)):
        r = recs.get(turn, {})
        items.append(Item(set_id=session_set_id(sid), item_id=f"turn-{turn}", idx=i, audio=targets[turn],
                          direction=f"{r.get('src', '?')}->{r.get('tgt', '?')}", source_text=r.get("source_text", ""),
                          target_text=r.get("target_text", ""), variant=r.get("mode", "unknown"), ref_id=str(turn)))
    store.create_set(session_set_id(sid), "session", f"Session {sid}", False, items, source=f"recordings/{sid}",
                     replace_items=True)
    return session_set_id(sid)
