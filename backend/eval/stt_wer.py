# ruff: noqa: SIM115 - small offline analysis script
"""STT word error rate of harness runs: transcript (all segments) vs the fixture text.

    python -m eval.stt_wer run1.jsonl run2.jsonl
"""
import json
import re
import sys
from pathlib import Path

import yaml

ref = {}
for items in yaml.safe_load(open(Path(__file__).resolve().parents[2] / 'docs/benchmarks/utterances.yaml')).values():
    for u in items: ref[u['id']] = u['text']
def toks(s): return re.sub(r"[^\w\s']", " ", s.lower()).split()
def wer(r, h):
    r, h = toks(r), toks(h)
    d = list(range(len(h)+1))
    for i in range(1, len(r)+1):
        p, d[0] = d[0], i
        for j in range(1, len(h)+1):
            p, d[j] = d[j], min(d[j]+1, d[j-1]+1, p + (r[i-1] != h[j-1]))
    return d[len(h)], len(r)
for f in sys.argv[1:]:
    e = n = 0; rows = 0
    for r in map(json.loads, open(f)):
        if r.get('status') != 'done': continue
        a, b = wer(ref[r['id']], r['source'].replace(' / ', ' ')); e += a; n += b; rows += 1
    print(f"{f}: WER {e/n:.3f} over {rows} turns")
