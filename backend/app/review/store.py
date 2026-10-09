"""SQLite persistence for review sets, items and ratings (DESIGN A12).

One file, `data/review.sqlite3`. Every write is a single transaction (atomic);
WAL mode keeps readers from blocking the writer. Ratings are keyed by
(set, item, rater); the rater is a plain name (no auth, local tool).

Blindness lives here too: an item's `variant` is stored but only returned by
`items(..., reveal=True)`, which the API calls only after the rater pressed
Reveal or rated every item.
"""
from __future__ import annotations

import contextlib
import re
import sqlite3
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

DIMS = ("adequacy", "fluency", "naturalness")
RATER_RE = re.compile(r"^[a-z0-9][a-z0-9 _.-]{0,39}$")
SET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$")
ITEM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
MAX_NOTES = 2000

SCHEMA = """
CREATE TABLE IF NOT EXISTS review_sets (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK (kind IN ('blind','session')),
  title TEXT NOT NULL, blind INTEGER NOT NULL, created REAL NOT NULL, source TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS review_items (
  set_id TEXT NOT NULL REFERENCES review_sets(id) ON DELETE CASCADE, item_id TEXT NOT NULL,
  idx INTEGER NOT NULL, audio TEXT NOT NULL, direction TEXT NOT NULL, source_text TEXT NOT NULL DEFAULT '',
  reference TEXT NOT NULL DEFAULT '', target_text TEXT NOT NULL DEFAULT '', variant TEXT NOT NULL,
  ref_id TEXT NOT NULL DEFAULT '', PRIMARY KEY (set_id, item_id));
CREATE TABLE IF NOT EXISTS ratings (
  set_id TEXT NOT NULL, item_id TEXT NOT NULL, rater TEXT NOT NULL,
  adequacy INTEGER CHECK (adequacy BETWEEN 1 AND 5), fluency INTEGER CHECK (fluency BETWEEN 1 AND 5),
  naturalness INTEGER CHECK (naturalness BETWEEN 1 AND 5), notes TEXT NOT NULL DEFAULT '',
  updated REAL NOT NULL, after_reveal INTEGER NOT NULL DEFAULT 0, origin TEXT NOT NULL DEFAULT 'ui',
  PRIMARY KEY (set_id, item_id, rater),
  FOREIGN KEY (set_id, item_id) REFERENCES review_items(set_id, item_id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS reveals (
  set_id TEXT NOT NULL REFERENCES review_sets(id) ON DELETE CASCADE, rater TEXT NOT NULL,
  at REAL NOT NULL, PRIMARY KEY (set_id, rater));
"""


class ReviewError(ValueError):
    """Bad input (400) or unknown set/item (404 when `missing`)."""

    def __init__(self, msg: str, missing: bool = False):
        super().__init__(msg)
        self.missing = missing


def norm_rater(name: str) -> str:
    r = " ".join((name or "").split()).lower()
    if not RATER_RE.match(r):
        raise ReviewError("rater name: 1-40 chars, letters/digits/space/_ . - (case-insensitive)")
    return r


@dataclass
class Item:
    set_id: str
    item_id: str
    idx: int
    audio: str
    direction: str
    source_text: str = ""
    reference: str = ""
    target_text: str = ""
    variant: str = ""
    ref_id: str = ""


class ReviewStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript(SCHEMA)

    @contextlib.contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        try:
            with db:  # one transaction: commit on success, roll back on error
                yield db
        finally:
            db.close()

    # ----- sets / items
    def create_set(self, set_id: str, kind: str, title: str, blind: bool, items: list[Item], source: str = "",
                   replace_items: bool = False) -> None:
        if not SET_RE.match(set_id):
            raise ReviewError("invalid set id")
        for it in items:
            if not ITEM_RE.match(it.item_id):
                raise ReviewError(f"invalid item id {it.item_id!r}")
        with self._db() as db:
            db.execute("INSERT OR IGNORE INTO review_sets (id, kind, title, blind, created, source) VALUES (?,?,?,?,?,?)",
                       (set_id, kind, title, int(blind), time.time(), source))
            if replace_items:  # session sets: refresh texts/paths, keep ratings of items that still exist
                keep = {it.item_id for it in items}
                for (old,) in db.execute("SELECT item_id FROM review_items WHERE set_id=?", (set_id,)).fetchall():
                    if old not in keep:
                        db.execute("DELETE FROM review_items WHERE set_id=? AND item_id=?", (set_id, old))
            for it in items:
                db.execute(
                    "INSERT INTO review_items (set_id,item_id,idx,audio,direction,source_text,reference,target_text,variant,ref_id)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(set_id,item_id) DO UPDATE SET idx=excluded.idx,"
                    " audio=excluded.audio, direction=excluded.direction, source_text=excluded.source_text,"
                    " reference=excluded.reference, target_text=excluded.target_text, variant=excluded.variant,"
                    " ref_id=excluded.ref_id",
                    (set_id, it.item_id, it.idx, it.audio, it.direction, it.source_text, it.reference,
                     it.target_text, it.variant, it.ref_id))

    def get_set(self, set_id: str) -> dict:
        with self._db() as db:
            r = db.execute("SELECT * FROM review_sets WHERE id=?", (set_id,)).fetchone()
            if not r:
                raise ReviewError("unknown review set", missing=True)
            n = db.execute("SELECT COUNT(*) FROM review_items WHERE set_id=?", (set_id,)).fetchone()[0]
        return {"id": r["id"], "kind": r["kind"], "title": r["title"], "blind": bool(r["blind"]), "items": n}

    def list_sets(self) -> list[dict]:
        with self._db() as db:
            rows = db.execute("SELECT s.id, s.kind, s.title, s.blind, COUNT(i.item_id) AS n FROM review_sets s"
                              " LEFT JOIN review_items i ON i.set_id=s.id GROUP BY s.id ORDER BY s.kind, s.created").fetchall()
        return [{"id": r["id"], "kind": r["kind"], "title": r["title"], "blind": bool(r["blind"]), "items": r["n"]} for r in rows]

    def items(self, set_id: str) -> list[Item]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM review_items WHERE set_id=? ORDER BY idx", (set_id,)).fetchall()
        return [Item(**{k: r[k] for k in r.keys()}) for r in rows]  # noqa: SIM118

    def item(self, set_id: str, item_id: str) -> Item:
        with self._db() as db:
            r = db.execute("SELECT * FROM review_items WHERE set_id=? AND item_id=?", (set_id, item_id)).fetchone()
        if not r:
            raise ReviewError("unknown item", missing=True)
        return Item(**{k: r[k] for k in r.keys()})  # noqa: SIM118

    # ----- ratings
    def save_rating(self, set_id: str, item_id: str, rater: str, scores: dict[str, int | None], notes: str = "",
                    origin: str = "ui") -> dict:
        rater = norm_rater(rater)
        vals = {}
        for d in DIMS:
            v = scores.get(d)
            if v is not None and (isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 5):
                raise ReviewError(f"{d} must be an integer 1-5 or empty")
            vals[d] = v
        if len(notes or "") > MAX_NOTES:
            raise ReviewError(f"notes longer than {MAX_NOTES} characters")
        self.item(set_id, item_id)  # 404 on unknown set/item
        revealed = self.revealed(set_id, rater)
        with self._db() as db:
            db.execute(
                "INSERT INTO ratings (set_id,item_id,rater,adequacy,fluency,naturalness,notes,updated,after_reveal,origin)"
                " VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(set_id,item_id,rater) DO UPDATE SET adequacy=excluded.adequacy,"
                " fluency=excluded.fluency, naturalness=excluded.naturalness, notes=excluded.notes,"
                " updated=excluded.updated, after_reveal=excluded.after_reveal, origin=excluded.origin",
                (set_id, item_id, rater, vals["adequacy"], vals["fluency"], vals["naturalness"], (notes or "").strip(),
                 time.time(), int(revealed), origin))
        return {"item_id": item_id, **vals, "notes": (notes or "").strip()}

    def ratings(self, set_id: str, rater: str | None = None) -> list[dict]:
        q, args = "SELECT * FROM ratings WHERE set_id=?", [set_id]
        if rater is not None:
            q += " AND rater=?"
            args.append(norm_rater(rater))
        with self._db() as db:
            return [dict(r) for r in db.execute(q, args).fetchall()]

    def delete_ratings(self, set_id: str, rater: str) -> int:
        rater = norm_rater(rater)
        with self._db() as db:
            n = db.execute("DELETE FROM ratings WHERE set_id=? AND rater=?", (set_id, rater)).rowcount
            db.execute("DELETE FROM reveals WHERE set_id=? AND rater=?", (set_id, rater))
        return n

    # ----- progress / reveal
    def progress(self, set_id: str, rater: str) -> dict:
        total = self.get_set(set_id)["items"]
        done = sum(1 for r in self.ratings(set_id, rater) if all(r[d] is not None for d in DIMS))
        return {"done": done, "total": total, "complete": total > 0 and done == total}

    def reveal(self, set_id: str, rater: str) -> None:
        rater = norm_rater(rater)
        self.get_set(set_id)
        with self._db() as db:
            db.execute("INSERT OR IGNORE INTO reveals (set_id, rater, at) VALUES (?,?,?)", (set_id, rater, time.time()))

    def revealed(self, set_id: str, rater: str) -> bool:
        """Variants are visible to this rater: not a blind set, Reveal pressed, or every item rated."""
        s = self.get_set(set_id)
        if not s["blind"]:
            return True
        rater = norm_rater(rater)
        with self._db() as db:
            if db.execute("SELECT 1 FROM reveals WHERE set_id=? AND rater=?", (set_id, rater)).fetchone():
                return True
        return self.progress(set_id, rater)["complete"]
