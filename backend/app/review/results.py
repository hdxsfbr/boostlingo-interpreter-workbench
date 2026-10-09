"""Results aggregation (DESIGN A12): per-variant mean / median / sd / range per
dimension, overall and by direction, next to M5 latency and chrF.

The statistics deliberately mirror `eval/blind_results.py` (statistics.mean
rounded to 2, sample stdev, composite = mean of the rounded dimension means),
so the preloaded set reproduces docs/benchmarks/blind/results.md exactly.
"""
from __future__ import annotations

import csv
import io
import json
import statistics
from pathlib import Path

from app.review.store import DIMS

KNOWN_ORDER = ("realtime", "realtime-mini", "cascade-openai", "cascade-openai-nomerge", "cascade-haiku",
               "cascade-elevenlabs", "cascade")


def stats(xs: list[int]) -> dict:
    if not xs:
        return {"n": 0, "mean": None, "median": None, "sd": None, "min": None, "max": None}
    return {"n": len(xs), "mean": round(statistics.mean(xs), 2), "median": statistics.median(xs),
            "sd": round(statistics.stdev(xs), 2) if len(xs) > 1 else 0.0, "min": min(xs), "max": max(xs)}


def m5_index(results_json: Path) -> dict[str, dict]:
    try:
        profiles = json.loads(results_json.read_text())["profiles"]
    except (OSError, ValueError, KeyError):
        return {}
    out = {}
    for p in profiles:
        q = p.get("quality", {})
        out[p["profile"]] = {
            "H_p50": p.get("H", {}).get("p50"), "H_p90": p.get("H", {}).get("p90"),
            "H_minus_gap_p50": p.get("H_minus_gap", {}).get("p50"),
            "chrF": {"all": q.get("all", {}).get("chrF"), "en->es": q.get("en->es", {}).get("chrF"),
                     "es->en": q.get("es->en", {}).get("chrF")},
            "usd_per_min": p.get("cost", {}).get("usd_per_min"),
        }
    return out


def aggregate(items: list, ratings: list[dict], m5: dict[str, dict] | None = None) -> list[dict]:
    """items: store Items (with variant); ratings: rows from the store (any raters)."""
    by_item = {it.item_id: it for it in items}
    variants = sorted({it.variant for it in items},
                      key=lambda v: (KNOWN_ORDER.index(v) if v in KNOWN_ORDER else 99, v))
    directions = sorted({it.direction for it in items})
    out = []
    for v in variants:
        rs = [r for r in ratings if r["item_id"] in by_item and by_item[r["item_id"]].variant == v]
        for scope in ("all", *directions):
            sr = [r for r in rs if scope == "all" or by_item[r["item_id"]].direction == scope]
            rec: dict = {"variant": v, "scope": scope, "n": len(sr)}
            for d in DIMS:
                rec[d] = stats([r[d] for r in sr if r[d] is not None])
            means = [rec[d]["mean"] for d in DIMS]
            rec["composite_mean"] = round(statistics.mean(means), 2) if all(m is not None for m in means) else None
            mm = (m5 or {}).get(v)
            if mm:
                rec["m5"] = {"H_p50": mm["H_p50"], "H_p90": mm["H_p90"], "H_minus_gap_p50": mm["H_minus_gap_p50"],
                             "chrF": mm["chrF"].get(scope), "usd_per_min": mm["usd_per_min"]}
            out.append(rec)
    return out


def to_csv(rows: list[dict]) -> str:
    head = ["variant", "scope", "n"] + [f"{d}_{k}" for d in DIMS for k in ("mean", "median", "sd", "min", "max")]
    head += ["composite_mean", "m5_H_p50_ms", "m5_H_p90_ms", "m5_chrF"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(head)
    for r in rows:
        m = r.get("m5") or {}
        w.writerow([r["variant"], r["scope"], r["n"]] + [r[d][k] for d in DIMS for k in ("mean", "median", "sd", "min", "max")]
                   + [r["composite_mean"], m.get("H_p50"), m.get("H_p90"), m.get("chrF")])
    return buf.getvalue()
