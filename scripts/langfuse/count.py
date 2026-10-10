"""Count traces / observations / scores that arrived in Langfuse since a time (UTC ISO).

    python3 count.py --since 2026-10-10T19:00:00Z [--tag commit:abc1234]
"""
import argparse
import collections

from lf_api import all_pages, trace_url

ap = argparse.ArgumentParser()
ap.add_argument("--since", required=True)
ap.add_argument("--tag")
a = ap.parse_args()
traces = all_pages("/api/public/traces", fromTimestamp=a.since, tags=a.tag)
kinds = collections.Counter(t["name"].split(" · ")[0] for t in traces)
obs = all_pages("/api/public/observations", fromStartTime=a.since)
scores = all_pages("/api/public/scores", fromTimestamp=a.since)
print("traces:", len(traces), dict(kinds))
print("observations:", len(obs), dict(collections.Counter(o["type"] + ":" + o["name"].split(" ")[0] for o in obs)))
print("scores:", len(scores), dict(collections.Counter(s["name"] for s in scores)))
by_name = {}
for t in traces:
    by_name.setdefault(t["name"].split(" · ")[0], t)
for k, t in by_name.items():
    print("url", k, trace_url(t["id"]))
