# ruff: noqa: SIM115 - small offline analysis script
"""Soak report: stability probes (heap, backend RSS, transports, errors) and latency drift.

    python -m eval.soak_report soak.jsonl [--ref same-config-run.jsonl]
"""
import json
import statistics
import sys


def report(f):
    rs = [json.loads(l) for l in open(f)]
    done = [r for r in rs if r['status'] == 'done']
    bad = [(r['id'], r['status']) for r in rs if r['status'] != 'done']
    span = rs[-1]['t_s']
    half = span / 2
    a = [r['H_minus_lag_ms'] for r in done if r['t_s'] <= half and r.get('H_minus_lag_ms') is not None]
    b = [r['H_minus_lag_ms'] for r in done if r['t_s'] > half and r.get('H_minus_lag_ms') is not None]
    ha = [r['H_ms'] for r in done if r['t_s'] <= half]; hb = [r['H_ms'] for r in done if r['t_s'] > half]
    pr = [(r['t_s'], r['probe']) for r in rs if 'probe' in r]
    print(f"{f}: turns={len(rs)} done={len(done)} not_done={bad} span={span:.0f}s")
    print(f"  H p50 first half {statistics.median(ha):.0f} / second half {statistics.median(hb):.0f}; H-gap {statistics.median(a):.0f} / {statistics.median(b):.0f}")
    for t, p in pr:
        d = p['diag']
        print(f"  t={t:5.0f}s heap={p['heap']/1e6:5.1f}MB rss={p['backend_rss_mb']}MB openTransports={d['openTransports']} created={d['created']} engineNodes={d['engineNodes']} errors={p['errors']} state={p['state']}")

def drift(soak, ref):
    base = {r['id']: r for r in map(json.loads, open(ref)) if r['status'] == 'done'}
    rs = [r for r in map(json.loads, open(soak)) if r['status'] == 'done' and r['id'] in base]
    half = rs[-1]['t_s'] / 2
    key = 'tail_est_ms' if rs[0].get('tail_est_ms') is not None else 'H_ms'
    d1 = [r[key] - base[r['id']][key] for r in rs if r['t_s'] <= half and r.get(key) and base[r['id']].get(key)]
    d2 = [r[key] - base[r['id']][key] for r in rs if r['t_s'] > half and r.get(key) and base[r['id']].get(key)]
    print(f"  drift ({key}, soak minus same utterance in {ref}): first half median {statistics.median(d1):+.0f} ms (n={len(d1)}), second half {statistics.median(d2):+.0f} ms (n={len(d2)})")


if __name__ == "__main__":
    args = sys.argv[1:]
    ref = None
    if "--ref" in args:
        i = args.index("--ref")
        ref = args[i + 1]
        args = args[:i] + args[i + 2:]
    for f in args:
        report(f)
        if ref:
            drift(f, ref)
