import json, glob, statistics as st, sys, csv
tag = sys.argv[1]; WARM = {"en-s01", "en-s02"}
def pct(xs, q):
    xs = sorted(xs); return xs[min(len(xs)-1, round(q*(len(xs)-1)))]
rows = []
for arm in ("off", "on"):
    for f in sorted(glob.glob(f"/tmp/bl/ab/{tag}-{arm}-r*.jsonl")):
        r_ = f.rsplit("-r", 1)[1].split(".")[0]
        for l in open(f):
            r = json.loads(l); r["arm"] = arm; r["round"] = int(r_); r["warmup"] = r["id"] in WARM; rows.append(r)
out = {}
for arm in ("off", "on"):
    sc = [r for r in rows if r["arm"] == arm and not r["warmup"]]
    ok = [r for r in sc if r["status"] == "done" and r.get("H_ms") is not None]
    sh = [r for r in ok if r["size"] == "short"]
    g = lambda rs, k: [r[k] for r in rs if r.get(k) is not None]
    out[arm] = dict(n=len(ok), n_scored=len(sc), n_short=len(sh),
        short_H_p50=st.median(g(sh, "H_ms")), short_H_p90=pct(g(sh, "H_ms"), .9),
        short_Hgap_p50=st.median(g(sh, "H_minus_lag_ms")), short_tail_p50=st.median(g(sh, "tail_est_ms")),
        all_H_p50=st.median(g(ok, "H_ms")), all_H_p90=pct(g(ok, "H_ms"), .9), all_tail_p50=st.median(g(ok, "tail_est_ms")),
        warmup_H=[round(r["H_ms"]) for r in rows if r["arm"] == arm and r["warmup"] and r.get("H_ms")])
    print(arm, {k: (round(v) if isinstance(v, float) else v) for k, v in out[arm].items()})
json.dump(out, open(f"/tmp/bl/ab/{tag}-summary.json", "w"), indent=1)
with open(f"/tmp/bl/ab/{tag}.csv", "w", newline="") as fh:
    w = csv.writer(fh); w.writerow(["arm", "round", "id", "size", "warmup", "status", "turns", "H_ms", "H_minus_lag_ms", "tail_est_ms"])
    for r in rows:
        w.writerow([r["arm"], r["round"], r["id"], r["size"], r["warmup"], r["status"], r["turns"],
                    *(round(r[k], 1) if r.get(k) is not None else "" for k in ("H_ms", "H_minus_lag_ms", "tail_est_ms"))])
