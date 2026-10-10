"""SQLite persistence for experiments (DESIGN A13): `data/experiments.sqlite3`,
next to the Review DB. One transaction per write; per-turn rows keep the full
harness row as JSON plus the columns the UI sorts and charts on."""
from __future__ import annotations

import contextlib
import json
import sqlite3
import time
from collections.abc import Iterator
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, status TEXT NOT NULL
    CHECK (status IN ('queued','running','done','failed','cancelled','interrupted')),
  readonly INTEGER NOT NULL DEFAULT 0, config TEXT NOT NULL, estimate TEXT NOT NULL DEFAULT '{}',
  created REAL NOT NULL, started REAL, finished REAL, git_commit TEXT NOT NULL DEFAULT 'unknown',
  models TEXT NOT NULL DEFAULT '{}', summary TEXT NOT NULL DEFAULT '[]', cost_usd REAL NOT NULL DEFAULT 0,
  error TEXT NOT NULL DEFAULT '', progress TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS experiment_turns (
  exp_id TEXT NOT NULL REFERENCES experiments(id) ON DELETE CASCADE, setup TEXT NOT NULL, n INTEGER NOT NULL,
  utterance_id TEXT NOT NULL, lang TEXT NOT NULL, size TEXT NOT NULL, status TEXT NOT NULL,
  h_ms REAL, h_minus_gap_ms REAL, tail_ms REAL, cost_usd REAL NOT NULL DEFAULT 0, row TEXT NOT NULL,
  PRIMARY KEY (exp_id, setup, n));
"""
JSON_COLS = ("config", "estimate", "models", "summary", "progress")
UPDATABLE = {"status", "started", "finished", "git_commit", "cost_usd", "error", *JSON_COLS}


class ExperimentStore:
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
            with db:
                yield db
        finally:
            db.close()

    def create(self, exp_id: str, name: str, config: dict, estimate: dict, git_commit: str, status: str = "queued",
               readonly: bool = False, **extra) -> None:
        with self._db() as db:
            db.execute("INSERT INTO experiments (id,name,status,readonly,config,estimate,created,git_commit) VALUES (?,?,?,?,?,?,?,?)",
                       (exp_id, name, status, int(readonly), json.dumps(config), json.dumps(estimate), time.time(), git_commit))
        if extra:
            self.update(exp_id, **extra)

    def update(self, exp_id: str, **fields) -> None:
        if not fields:
            return
        cols, vals = [], []
        bad = set(fields) - UPDATABLE
        if bad:
            raise ValueError(f"not updatable: {sorted(bad)}")
        for k, v in fields.items():
            cols.append(f"{k}=?")
            vals.append(json.dumps(v) if k in JSON_COLS else v)
        with self._db() as db:
            db.execute(f"UPDATE experiments SET {', '.join(cols)} WHERE id=?", (*vals, exp_id))

    def _row(self, r: sqlite3.Row) -> dict:
        d = dict(r)
        for k in JSON_COLS:
            d[k] = json.loads(d[k])
        d["readonly"] = bool(d["readonly"])
        return d

    def get(self, exp_id: str) -> dict | None:
        with self._db() as db:
            r = db.execute("SELECT * FROM experiments WHERE id=?", (exp_id,)).fetchone()
        return self._row(r) if r else None

    def list(self) -> list[dict]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM experiments ORDER BY readonly DESC, created DESC").fetchall()
        return [self._row(r) for r in rows]

    def add_turn(self, exp_id: str, setup: str, row: dict, cost: float) -> None:
        self.add_turns(exp_id, [(setup, row, cost)])

    def add_turns(self, exp_id: str, items: list[tuple[str, dict, float]]) -> None:
        """Several rows in one transaction (baseline import)."""
        with self._db() as db:
            for setup, row, cost in items:
                self._insert(db, exp_id, setup, row, cost)

    def delete(self, exp_id: str) -> None:
        with self._db() as db:
            db.execute("DELETE FROM experiment_turns WHERE exp_id=?", (exp_id,))
            db.execute("DELETE FROM experiments WHERE id=?", (exp_id,))

    @staticmethod
    def _insert(db: sqlite3.Connection, exp_id: str, setup: str, row: dict, cost: float) -> None:
        # A21: h_ms is the headline (first audio of the last sentence); the literal first audible stays in row
        h, t, g = row.get("H_ms"), row.get("tail_est_ms"), row.get("H_minus_lag_ms")
        hf = max(h, t) if (h is not None and t is not None) else h
        gf = (g + hf - h) if (g is not None and hf is not None) else g
        db.execute(
            "INSERT OR REPLACE INTO experiment_turns (exp_id,setup,n,utterance_id,lang,size,status,h_ms,h_minus_gap_ms,"
            "tail_ms,cost_usd,row) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (exp_id, setup, int(row.get("n") or 0), row.get("id", "?"), row.get("lang", "?"), row.get("size", "?"),
             row.get("status", "?"), hf, gf, t, cost,
             json.dumps(row, ensure_ascii=False)))

    def turns(self, exp_id: str, full: bool = False) -> list[dict]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM experiment_turns WHERE exp_id=? ORDER BY setup, n", (exp_id,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            row = json.loads(d.pop("row"))
            if full:
                d["row"] = row
            else:
                d["source"], d["target"] = row.get("source", ""), row.get("target", "")
            out.append(d)
        return out

    def mark_interrupted(self) -> int:
        """Startup: anything still queued/running belonged to a previous process."""
        with self._db() as db:
            return db.execute("UPDATE experiments SET status='interrupted', finished=?, error='server restarted during the run'"
                              " WHERE status IN ('queued','running')", (time.time(),)).rowcount
