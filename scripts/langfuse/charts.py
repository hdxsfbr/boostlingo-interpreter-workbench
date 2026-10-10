"""A20: charts from the Langfuse public API (read-only; keys from files, never printed).

    python3 scripts/langfuse/charts.py --since 2026-10-10T20:00:00Z [--out docs/images/langfuse/charts]

Live sessions: the per-turn spans ("turn ...") of interpreter-session traces carry the same
numbers as the Latency card (headline_ms = A21 headline, stage_ms_after_speech_end, cost_usd,
speech_ms). Experiments: per-utterance traces (sessionId exp-<id>) with H_ms / chrF / src_wer scores.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import statistics
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from lf_api import all_pages  # noqa: E402

# Relay tokens (frontend/public/brand/tokens.css)
C = {"primary": "#1462F0", "accent": "#DD3900", "text": "#252224", "muted": "#585C66", "bg": "#F4F7FD", "teal": "#82C5BF"}
PAL = [C["primary"], C["teal"], C["accent"], C["muted"], "#7FA6F5", "#2E8C84"]
plt.rcParams.update({"font.family": ["DejaVu Sans"], "axes.edgecolor": C["muted"], "axes.labelcolor": C["text"],
                     "xtick.color": C["text"], "ytick.color": C["text"], "text.color": C["text"], "figure.facecolor": "white",
                     "axes.facecolor": C["bg"], "axes.grid": True, "grid.color": "white", "axes.spines.top": False,
                     "axes.spines.right": False})


def setup_of(meta: dict) -> str:
    m = meta.get("models") or {}
    if m.get("realtime"):
        return m["realtime"].replace("gpt-realtime-mini", "realtime-mini").replace("gpt-realtime", "gpt-realtime")
    mt = m.get("mt", "")
    return "cascade-haiku" if "haiku" in mt else "cascade-openai" if mt.startswith("gpt") else f"cascade-{mt or '?'}"


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, round(q / 100 * (len(xs) - 1))))] if xs else float("nan")


def foot(fig, n, src="Langfuse public API"):
    fig.text(0.01, 0.01, f"Source: {src} · n = {n} · generated {dt.date.today().isoformat()} · Relay workbench (A20)",
             fontsize=8, color=C["muted"])


def save(fig, out: Path, name: str) -> Path:
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    p = out / name
    fig.savefig(p, dpi=150)
    plt.close(fig)
    print("wrote", p)
    return p


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", required=True, help="UTC ISO; only data from this time on")
    ap.add_argument("--out", default="docs/images/langfuse/charts")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    traces = all_pages("/api/public/traces", fromTimestamp=a.since)
    sess = {t["id"]: t for t in traces if t["name"] == "interpreter-session"}
    exps = {t["id"]: t for t in traces if t["name"].startswith("experiment")}
    spans = [o for o in all_pages("/api/public/observations", fromStartTime=a.since, type="SPAN")
             if o["name"].startswith("turn ") and o["traceId"] in sess]
    turns = []
    for o in spans:
        md, tm = o.get("metadata") or {}, sess[o["traceId"]]["metadata"] or {}
        if md.get("status") != "done" or md.get("headline_ms") is None:
            continue
        turns.append({"setup": setup_of(tm), "pair": tm.get("pair"), "session": o["traceId"], "t": o["startTime"],
                      "H": md["headline_ms"], "first": md.get("latency_ms"), "stages": md.get("stage_ms_after_speech_end") or {},
                      "cost": md.get("cost_usd") or 0.0, "speech_s": (md.get("speech_ms") or 0) / 1000})
    by = collections.defaultdict(list)
    for t in turns:
        by[t["setup"]].append(t)
    order = sorted(by, key=lambda s: statistics.median(x["H"] for x in by[s]))
    print(f"turns: {len(turns)} in {len(sess)} sessions; experiment traces: {len(exps)}")

    # 1. headline latency p50/p90 per setup
    fig, ax = plt.subplots(figsize=(8, 4.2))
    xs = range(len(order))
    p50 = [pct([x["H"] for x in by[s]], 50) for s in order]
    p90 = [pct([x["H"] for x in by[s]], 90) for s in order]
    ax.bar([i - 0.2 for i in xs], p50, 0.4, color=C["primary"], label="p50")
    ax.bar([i + 0.2 for i in xs], p90, 0.4, color=C["teal"], label="p90")
    for i, (a5, a9) in enumerate(zip(p50, p90, strict=True)):
        ax.text(i - 0.2, a5, f"{a5:.0f}", ha="center", va="bottom", fontsize=8)
        ax.text(i + 0.2, a9, f"{a9:.0f}", ha="center", va="bottom", fontsize=8)
    ax.set_xticks(list(xs), [f"{s}\n(n={len(by[s])})" for s in order])
    ax.set_ylabel("ms")
    ax.set_title("Headline latency: speech end → first audio of the last sentence (A21)")
    ax.legend()
    foot(fig, len(turns))
    save(fig, out, "latency-p50-p90-by-setup.png")

    # 2. cascade per-stage breakdown (median ms after speech end, non-early turns only)
    stages = [("stt_final", "STT final"), ("mt_first_token", "MT 1st token"), ("tts_first_byte", "TTS 1st byte"),
              ("audio_first_sent", "audio sent")]
    cas = [s for s in order if s.startswith("cascade")]
    fig, ax = plt.subplots(figsize=(8, 4.2))
    w = 0.8 / max(1, len(cas))
    for j, s in enumerate(cas):
        vals = []
        for k, _ in stages:
            v = [x["stages"][k] for x in by[s] if x["stages"].get(k, -1) >= 0]
            vals.append(statistics.median(v) if v else 0)
        ax.bar([i + (j - (len(cas) - 1) / 2) * w for i in range(len(stages))], vals, w, color=PAL[j], label=f"{s} (n={len(by[s])})")
    hl = [statistics.median(x["H"] for x in by[s]) for s in cas]
    ax.set_xticks(range(len(stages)), [lbl for _, lbl in stages])
    ax.set_ylabel("median ms after speech end")
    ax.set_title("Cascade stages (median; early/speculative stages excluded)\n"
                 + " · ".join(f"{s} headline p50 {h:.0f} ms" for s, h in zip(cas, hl, strict=True)), fontsize=10)
    ax.legend(fontsize=8)
    foot(fig, sum(len(by[s]) for s in cas))
    save(fig, out, "cascade-stage-breakdown.png")

    # 3. cost per turn and per minute of speech
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9, 4))
    cpt = [statistics.mean(x["cost"] for x in by[s]) * 1000 for s in order]
    cpm = [(sum(x["cost"] for x in by[s]) / (sum(x["speech_s"] for x in by[s]) / 60)) if sum(x["speech_s"] for x in by[s]) else 0
           for s in order]
    a1.bar(order, cpt, color=PAL[: len(order)])
    a1.set_title("Cost per turn (mean, $ × 1000)")
    a2.bar(order, cpm, color=PAL[: len(order)])
    a2.set_title("Cost per minute of speech ($)")
    for axx, vals, f in ((a1, cpt, "{:.2f}"), (a2, cpm, "${:.3f}")):
        axx.tick_params(axis="x", rotation=20)
        for i, v in enumerate(vals):
            axx.text(i, v, f.format(v), ha="center", va="bottom", fontsize=8)
    total = sum(x["cost"] for x in turns)
    fig.suptitle(f"Estimated API cost (config/pricing.yaml; realtime incl. side transcription) · total ${total:.3f}", fontsize=10)
    foot(fig, len(turns))
    save(fig, out, "cost-by-setup.png")

    # 4. experiment quality vs latency
    scores = [s for s in all_pages("/api/public/scores", fromTimestamp=a.since) if s["traceId"] in exps]
    sc = collections.defaultdict(dict)
    for s in scores:
        sc[s["traceId"]][s["name"]] = s["value"]
    pts = collections.defaultdict(list)
    for tid_, v in sc.items():
        setup = (exps[tid_]["metadata"] or {}).get("setup", "?")
        if "H_ms" in v and "chrF" in v:
            pts[setup].append((v["H_ms"], v["chrF"], v.get("src_wer")))
    if pts:
        fig, (a1, a2) = plt.subplots(1, 2, figsize=(10, 4.2))
        for j, (s, p) in enumerate(sorted(pts.items())):
            a1.scatter([x[0] for x in p], [x[1] for x in p], color=PAL[j], label=f"{s} (n={len(p)})", alpha=0.85)
            w_ = [x for x in p if x[2] is not None]
            a2.scatter([x[0] for x in w_], [x[2] * 100 for x in w_], color=PAL[j], label=s, alpha=0.85)
        a1.set(xlabel="headline H (ms)", ylabel="chrF", title="Translation quality vs latency")
        a2.set(xlabel="headline H (ms)", ylabel="source WER (%)", title="Source ASR WER vs latency")
        a1.legend(fontsize=8)
        foot(fig, sum(len(p) for p in pts.values()), "Langfuse scores (experiment traces)")
        save(fig, out, "quality-vs-latency.png")

    # 5. drift: latency over time within the longest session(s)
    per = collections.defaultdict(list)
    for t in turns:
        per[t["session"]].append(t)
    longest = sorted(per.values(), key=len, reverse=True)[:3]
    fig, ax = plt.subplots(figsize=(8, 4))
    for j, ts in enumerate(longest):
        ts.sort(key=lambda x: x["t"])
        ax.plot(range(1, len(ts) + 1), [x["H"] for x in ts], marker="o", ms=3, color=PAL[j],
                label=f"{ts[0]['setup']} {ts[0]['pair']} ({len(ts)} turns)")
    ax.set(xlabel="turn # in session", ylabel="headline H (ms)", title="Latency over a session (drift check)")
    ax.legend(fontsize=8)
    foot(fig, sum(len(x) for x in longest))
    save(fig, out, "latency-drift-in-session.png")

    # 6. distribution by setup and pair
    keys = sorted({(t["setup"], t["pair"]) for t in turns}, key=lambda k: (order.index(k[0]), k[1]))
    fig, ax = plt.subplots(figsize=(9, 4.2))
    data = [[t["H"] for t in turns if (t["setup"], t["pair"]) == k] for k in keys]
    bp = ax.boxplot(data, patch_artist=True, showfliers=True)
    for j, b in enumerate(bp["boxes"]):
        b.set_facecolor(PAL[order.index(keys[j][0]) % len(PAL)])
    for m in bp["medians"]:
        m.set_color(C["text"])
    ax.set_xticks(range(1, len(keys) + 1), [f"{s}\n{p} (n={len(d)})" for (s, p), d in zip(keys, data, strict=True)], fontsize=8)
    ax.set(ylabel="headline H (ms)", title="Headline latency distribution by setup and language pair")
    foot(fig, len(turns))
    save(fig, out, "latency-by-setup-and-pair.png")


if __name__ == "__main__":
    main()
