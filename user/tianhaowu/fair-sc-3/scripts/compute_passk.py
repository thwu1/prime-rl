#!/usr/bin/env python
"""Compute unbiased pass@k over completed tb-pass80 eval tasks.

pass@k per task = 1 - C(n-c, k)/C(n, k) (Chen et al.), averaged over tasks with n>=k.
Infra rollouts (infra_env_error==1) are excluded — they are model-independent drops.
Usage: python compute_passk.py <step> [<step> ...]
"""
import sys, json, glob, collections
from math import comb

KS = [1, 2, 4, 8, 10]


def find(step):
    tag = "baseline" if str(step) == "baseline" else f"step{step}"
    hits = glob.glob(
        f"/checkpoint/ram/tianhaowu/eval/tb_rl_12k_100k_lr1e6_rr_v1_{tag}"
        f"/tb-pass80/evals/**/results.jsonl", recursive=True
    )
    return hits[0] if hits else None


def passk(n, c, k):
    if n - c < k:
        return 1.0
    return 1.0 - comb(n - c, k) / comb(n, k)


def analyze(step):
    label = "baseline" if str(step) == "baseline" else f"step{step}"
    rj = find(step)
    if not rj:
        print(f"{label}: no results yet")
        return
    rows = [json.loads(l) for l in open(rj)]
    valid = [r for r in rows if r.get("infra_env_error", 0.0) != 1.0]
    infra = len(rows) - len(valid)
    by = collections.defaultdict(list)
    for r in valid:
        by[r["example_id"]].append(1 if r["reward"] >= 1.0 else 0)
    out = []
    for k in KS:
        tasks = [(len(v), sum(v)) for v in by.values() if len(v) >= k]
        est = sum(passk(n, c, k) for n, c in tasks) / len(tasks) if tasks else float("nan")
        out.append(f"pass@{k}={est:.3f}(n={len(tasks)})")
    avg = sum(sum(v) for v in by.values()) / sum(len(v) for v in by.values())
    print(
        f"{label}: {len(rows)} rollouts, {len(by)}/80 tasks, {infra} infra-excl | "
        f"avg@={avg:.3f} | " + "  ".join(out)
    )


for s in sys.argv[1:] or [175, 200]:
    analyze(s)
