"""Markdown latency table from harness JSONL runs (restricted to common ids).

    python -m eval.summarize before.jsonl:Before after.jsonl:After [--ids-from after.jsonl]

Columns (ms, p50 / p90 over turns with status done):
- H: headline, last voiced frame -> first audible sample (includes the 450 ms release, A2)
- H-gap: H minus the per-turn release gap
- tail: when the LAST segment's audio would start (cascade estimate, see harness)
- tail-gap: tail minus the release gap
- short H / short H-gap: short utterances only (usually one segment, so no pipelining head start)
"""
from __future__ import annotations

import argparse
import json
import statistics


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, round(q * (len(xs) - 1)))]


def cell(xs):
    return f"{statistics.median(xs):.0f} / {pct(xs, .9):.0f}" if xs else "–"


def load(path):
    return [json.loads(line) for line in open(path)]  # noqa: SIM115


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+", help="file.jsonl:Label")
    ap.add_argument("--ids-from", help="restrict every run to the ids present in this run")
    ap.add_argument("--lang", choices=["en", "es"])
    a = ap.parse_args()
    ids = {r["id"] for r in load(a.ids_from)} if a.ids_from else None
    print("| Variant | n | H p50/p90 | H−gap p50/p90 | tail p50/p90 | tail−gap p50/p90 | short H | short H−gap |")
    print("|---|---|---|---|---|---|---|---|")
    for spec in a.runs:
        path, label = spec.split(":", 1)
        rs = [r for r in load(path) if r.get("status") == "done" and (ids is None or r["id"] in ids)
              and (a.lang is None or r["lang"] == a.lang)]
        h = [r["H_ms"] for r in rs if r.get("H_ms") is not None]
        hg = [r["H_minus_lag_ms"] for r in rs if r.get("H_minus_lag_ms") is not None]
        tl = [r["tail_est_ms"] for r in rs if r.get("tail_est_ms") is not None]
        tg = [r["tail_est_ms"] - r["release_lag_ms"] for r in rs
              if r.get("tail_est_ms") is not None and r.get("release_lag_ms") is not None]
        sh = [r["H_ms"] for r in rs if r["size"] == "short" and r.get("H_ms") is not None]
        sg = [r["H_minus_lag_ms"] for r in rs if r["size"] == "short" and r.get("H_minus_lag_ms") is not None]
        print(f"| {label} | {len(rs)} | {cell(h)} | {cell(hg)} | {cell(tl)} | {cell(tg)} | {cell(sh)} | {cell(sg)} |")


if __name__ == "__main__":
    main()
