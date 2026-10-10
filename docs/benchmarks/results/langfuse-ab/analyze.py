"""Langfuse off vs on (A20): same analysis as recording-ab, plus realtime-mini rows."""
import csv, glob, json, statistics as st, sys
tag = sys.argv[1] if len(sys.argv) > 1 else "lf"; WARM = {"en-s01", "en-s02"}
def pct(xs, q):
    xs = sorted(xs); return xs[min(len(xs) - 1, round(q * (len(xs) - 1)))] if xs else None
rows = []
for kind, pat in (("cascade", f"/tmp/bl/ab/{tag}-{{arm}}-r*.jsonl"), ("realtime", f"/tmp/bl/ab/{tag}-rt-{{arm}}-r*.jsonl")):
    for arm in ("off", "on"):
        for f in sorted(glob.glob(pat.format(arm=arm))):
            rnd = int(f.rsplit("-r", 1)[1].split(".")[0])
            for line in open(f):
                r = json.loads(line)
                r.update(kind=kind, arm=arm, round=rnd, warmup=kind == "cascade" and r["id"] in WARM)
                rows.append(r)
out = {}
g = lambda rs, k: [r[k] for r in rs if r.get(k) is not None]
for kind in ("cascade", "realtime"):
    for arm in ("off", "on"):
        sc = [r for r in rows if r["kind"] == kind and r["arm"] == arm and not r["warmup"]]
        ok = [r for r in sc if r["status"] == "done" and r.get("H_ms") is not None]
        sh = [r for r in ok if r.get("size") == "short"]
        o = dict(n=len(ok), n_scored=len(sc), n_short=len(sh),
                 short_H_p50=st.median(g(sh, "H_ms")) if sh else None, short_H_p90=pct(g(sh, "H_ms"), .9),
                 short_Hgap_p50=st.median(g(sh, "H_minus_lag_ms")) if sh else None,
                 all_H_p50=st.median(g(ok, "H_ms")) if ok else None, all_H_p90=pct(g(ok, "H_ms"), .9),
                 tail_p50=st.median(g(ok, "tail_est_ms")) if g(ok, "tail_est_ms") else None)
        out[f"{kind}-{arm}"] = o
        print(kind, arm, {k: (round(v) if isinstance(v, float) else v) for k, v in o.items()})
json.dump(out, open("summary.json", "w"), indent=1)
with open(f"2026-10-10-langfuse-ab.csv", "w", newline="") as fh:
    w = csv.writer(fh); w.writerow(["kind", "arm", "round", "id", "size", "warmup", "status", "H_ms", "H_minus_lag_ms", "tail_est_ms"])
    for r in rows:
        w.writerow([r["kind"], r["arm"], r["round"], r["id"], r.get("size"), r["warmup"], r["status"],
                    *(round(r[k], 1) if r.get(k) is not None else "" for k in ("H_ms", "H_minus_lag_ms", "tail_est_ms"))])
