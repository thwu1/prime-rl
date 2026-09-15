#!/usr/bin/env python3
"""Compute effect sizes, normalized scores, and equivalent groups."""

import json
import csv
from collections import defaultdict


def median(lst):
    """Compute median of a list of numbers."""
    s = sorted(lst)
    n = len(s)
    if n % 2 == 0:
        return (s[n // 2 - 1] + s[n // 2]) / 2
    return s[n // 2]


def a12(x, y):
    """Vargha-Delaney A12 effect size measure."""
    m, n = len(x), len(y)
    r = 0.0
    for xi in x:
        for yj in y:
            if xi > yj:
                r += 1.0
    return r / (m * n)


# Read final coverage data from CSV
data = []
with open('/app/pipeline/tmp/final_coverage.csv') as f:
    reader = csv.DictReader(f)
    for row in reader:
        data.append({
            'fuzzer': row['fuzzer'],
            'benchmark': row['benchmark'],
            'trial_id': int(row['trial_id']),
            'final_edges': int(row['final_edges']),
        })

# Read stats for pairwise p-values (needed for equivalent groups)
with open('/app/pipeline/tmp/stats_output.json') as f:
    stats = json.load(f)

fuzzers = sorted(set(r['fuzzer'] for r in data))
benchmarks = sorted(set(r['benchmark'] for r in data))
k = len(fuzzers)

# Organize data by (fuzzer, benchmark)
by_fb = defaultdict(list)
for r in data:
    by_fb[(r['fuzzer'], r['benchmark'])].append(r['final_edges'])

# Normalized scores
norm_scores = {f: [] for f in fuzzers}
for benchmark in benchmarks:
    all_edges = []
    for fuzzer in fuzzers:
        all_edges.extend(by_fb[(fuzzer, benchmark)])
    min_cov = min(all_edges)
    max_cov = max(all_edges)
    for fuzzer in fuzzers:
        trials = by_fb[(fuzzer, benchmark)]
        if max_cov > min_cov:
            normalized = [(x - min_cov) / (max_cov - min_cov) for x in trials]
        else:
            normalized = [1.0] * len(trials)
        norm_scores[fuzzer].append(median(normalized))

avg_norm = {f: round(sum(v) / len(v), 6) for f, v in norm_scores.items()}

# Pairwise effect sizes (A12) per benchmark
effect_sizes = {}
for benchmark in benchmarks:
    pairs = {}
    for i in range(k):
        for j in range(i + 1, k):
            fi, fj = fuzzers[i], fuzzers[j]
            x = by_fb[(fi, benchmark)]
            y = by_fb[(fj, benchmark)]
            pairs[f"{fi}_vs_{fj}"] = round(a12(x, y), 6)
    effect_sizes[benchmark] = pairs

# Equivalent groups via BFS on non-significant pairs
pairwise = stats['pairwise_p_values']
adj = {f: set() for f in fuzzers}
for i in range(k):
    for j in range(i + 1, k):
        fi, fj = sorted([fuzzers[i], fuzzers[j]])
        key = f"{fi}_vs_{fj}"
        if pairwise.get(key, 0) > 0.05:
            adj[fi].add(fj)
            adj[fj].add(fi)

visited = set()
groups = []
for f in sorted(fuzzers):
    if f in visited:
        continue
    component = set()
    queue = [f]
    while queue:
        node = queue.pop(0)
        if node in visited:
            continue
        visited.add(node)
        component.add(node)
        for neighbor in adj[node]:
            if neighbor not in visited:
                queue.append(neighbor)
    groups.append(sorted(component))
groups.sort(key=lambda g: g[0])

output = {
    'average_normalized_scores': avg_norm,
    'pairwise_effect_sizes': effect_sizes,
    'equivalent_groups': groups,
}

with open('/app/pipeline/tmp/metrics_output.json', 'w') as f:
    json.dump(output, f, indent=2)

print("Metrics computation complete.")
