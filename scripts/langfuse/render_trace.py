"""Render ONE Langfuse trace tree from the public API as a PNG (a rendering, not the
Langfuse UI: the UI needs a user login). Spans/generations as a timeline, scores listed.

    python3 render_trace.py <trace_id> out.png [--turns 2]
"""
import argparse
from datetime import datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from lf_api import get, trace_url  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("trace_id")
ap.add_argument("out")
ap.add_argument("--turns", type=int, default=2)
a = ap.parse_args()
t = get(f"/api/public/traces/{a.trace_id}")
obs = t.get("observations") or []
ts = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() if s else None  # noqa: E731
roots = sorted([o for o in obs if not o.get("parentObservationId")], key=lambda o: ts(o["startTime"]))[-a.turns:]
rows = []
for r in roots:
    rows.append((r, 0))
    kids = sorted([o for o in obs if o.get("parentObservationId") == r["id"]], key=lambda o: ts(o["startTime"]))
    rows += [(k, 1) for k in kids]
COL = {"SPAN": "#8A93A6", "GENERATION": "#1462F0"}
fig_h = 2.4 + 0.42 * len(rows) + 0.25 * len(roots)
fig, ax = plt.subplots(figsize=(16, fig_h), dpi=110)
y = 0
labels = []
for o, depth in rows:
    md = o.get("metadata") or {}
    if depth == 0:
        se = None
        # speech end = turn start + (-min stage) ... use stage_ms to find speech end
        st = md.get("stage_ms_after_speech_end") or {}
        t0 = ts(o["startTime"]) - min([0.0, *st.values()]) / 1000
    s, e = ts(o["startTime"]) - t0, ts(o["endTime"] or o["startTime"]) - t0
    ax.barh(y, max(e - s, 0.01), left=s, color=COL.get(o["type"], "#82C5BF"), alpha=0.35 if depth == 0 else 0.9, height=0.6)
    if o.get("completionStartTime"):
        c = ts(o["completionStartTime"]) - t0
        ax.plot([c, c], [y - 0.3, y + 0.3], color="#DD3900", lw=2)
    extra = ""
    if o["type"] == "GENERATION":
        cost = (o.get("costDetails") or {}).get("total") or o.get("calculatedTotalCost") or 0
        extra = f"  {o.get('model') or ''}  usage {o.get('usageDetails') or ''}  ${cost:.5f}"
        if md.get("early"):
            extra += "  [early]"
    if depth == 0:
        extra = f"  H={md.get('latency_ms', 0):.0f} ms  cost ${md.get('cost_usd', 0):.5f}"
    labels.append(("    " * depth) + o["name"] + f"  [{s * 1000:.0f} → {e * 1000:.0f} ms]" + extra)
    y += 1
ax.set_yticks(range(len(rows)))
ax.set_yticklabels(labels, fontsize=8, family="monospace")
ax.invert_yaxis()
ax.axvline(0, color="#252224", lw=1, ls="--")
ax.text(0, -0.9, " speech end", fontsize=8)
ax.set_xlabel("seconds after speech end (turn clock; blue = generation, grey = span, orange tick = first output)")
sc = [s for s in get("/api/public/scores", traceId=a.trace_id, limit=100).get("data", []) if s.get("traceId") == a.trace_id]
sc_txt = ", ".join(f"{s['name']}={s['value']:.0f}" for s in sc[:8])
fig.text(0.01, 0.995, f"RENDERING of Langfuse trace (from the public API, not a UI screenshot)\n{t['name']}  ·  tags {', '.join(t.get('tags') or [])}\n"
             f"scores: {sc_txt}\n{trace_url(a.trace_id)}", fontsize=9, va="top", ha="left")
plt.tight_layout(rect=(0, 0, 1, 1 - 0.75 / fig_h))
plt.savefig(a.out)
print("wrote", a.out)
