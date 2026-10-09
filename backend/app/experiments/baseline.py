"""Import the M5 results as the first, read-only experiment `m5-baseline` (DESIGN A13).

Summary = docs/benchmarks/results/m5/results.json profiles verbatim (same
shape eval.metrics.aggregate writes for new experiments); per-turn rows from
results/m5/raw/<profile>.jsonl for the latency chart.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from app.experiments.store import ExperimentStore

log = logging.getLogger(__name__)
BASELINE_ID = "m5-baseline"


def import_m5(store: ExperimentStore, bench_dir: Path, row_cost=None, profiles: dict | None = None) -> bool:
    if store.get(BASELINE_ID):
        return False
    res_p = bench_dir / "results" / "m5" / "results.json"
    if not res_p.is_file():
        return False
    res = json.loads(res_p.read_text())
    names = [p["profile"] for p in res["profiles"]]
    cfg = {"name": "M5 baseline", "setups": names, "utterances": "full", "directions": "both", "passes": 1,
           "source": "docs/benchmarks/results/m5/results.json", "note": "final M5 runs, one container per profile"}
    store.create(BASELINE_ID, "M5 baseline", cfg, {}, f"M5 results.json (generated {res.get('generated')})",
                 status="done", readonly=True, summary=res["profiles"],
                 models={p["profile"]: {"models": p.get("providers", {})} for p in res["profiles"]},
                 cost_usd=round(sum(p.get("cost", {}).get("usd_total") or 0 for p in res["profiles"]), 4))
    batch = []
    for name in names:
        raw = bench_dir / "results" / "m5" / "raw" / f"{name}.jsonl"
        if not raw.is_file():
            continue
        for line in raw.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            cost = 0.0
            if row_cost and profiles is not None:
                try:
                    cost = float(row_cost(r, profiles[name]))
                except (KeyError, TypeError, ValueError):
                    cost = 0.0
            batch.append((name, r, cost))
    store.add_turns(BASELINE_ID, batch)
    log.info("experiments: imported %s (%d profiles)", BASELINE_ID, len(names))
    return True
