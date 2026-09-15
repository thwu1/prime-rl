#!/usr/bin/env python3
"""Generate policy ranking from evaluation results."""

import json

with open('/app/results.json') as f:
    results = json.load(f)

practical_policies = ['lru', 'srrip', 'drrip', 'ship']

# Per-trace best (practical policies only, lowest miss_rate)
all_traces = sorted(
    next(iter(results["policies"].values()))["per_trace"].keys()
)
per_trace_best = {}
for tname in all_traces:
    best_policy = None
    best_mr = float('inf')
    for pname in practical_policies:
        mr = results["policies"][pname]["per_trace"][tname]["miss_rate"]
        if mr < best_mr:
            best_mr = mr
            best_policy = pname
    per_trace_best[tname] = best_policy

# Overall ranking by descending geomean_miss_rate_reduction
ranked = sorted(
    practical_policies,
    key=lambda p: results["policies"][p]["geomean_miss_rate_reduction"],
    reverse=True,
)

ranking = {
    "per_trace_best": per_trace_best,
    "overall_ranking": ranked,
    "champion": ranked[0],
}

with open('/app/policy_ranking.json', 'w') as f:
    json.dump(ranking, f, indent=2)

print("Policy ranking written to /app/policy_ranking.json")
for t, p in sorted(per_trace_best.items()):
    mr = results["policies"][p]["per_trace"][t]["miss_rate"]
    print(f"  {t}: best={p} (miss_rate={mr:.6f})")
print(f"Champion: {ranking['champion']}")
print(f"Ranking: {' > '.join(ranked)}")
