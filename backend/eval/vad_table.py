# ruff: noqa: SIM115, E701, E702 - small offline analysis script
"""VAD silence-window sweep table: python -m eval.vad_table <realtime prefix> <cascade prefix> (files <prefix>_<ms>.jsonl)."""
import json
import statistics
import sys


def pct(xs,q): xs=sorted(xs); return xs[min(len(xs)-1, round(q*(len(xs)-1)))]
print("| Mode | window | utterances | 1 turn | split | no turn / stuck | H p50 / p90 (short+medium, 1 turn) | H p50 (all done) |")
print("|---|---|---|---|---|---|---|---|")
for mode, pre in [("Realtime (server_vad, WebRTC)", sys.argv[1]), ("Cascade (browser VAD)", sys.argv[2])]:
    for v in (300, 400, 500):
        rs=[json.loads(l) for l in open(f"{pre}_{v}.jsonl")]
        one=[r for r in rs if r["status"]=="done" and r.get("turns")==1]
        split=[r for r in rs if r.get("turns",0)>1]
        bad=[r for r in rs if r["status"] in ("no_turn","harness_error")]
        sm=[r["H_ms"] for r in one if r["size"]!="long" and r.get("H_ms")]
        al=[r["H_ms"] for r in rs if r["status"]=="done" and r.get("H_ms")]
        print(f"| {mode} | {v} ms | {len(rs)} | {len(one)} | {len(split)} | {len(bad)} | {statistics.median(sm):.0f} / {pct(sm,.9):.0f} (n={len(sm)}) | {statistics.median(al):.0f} |")
