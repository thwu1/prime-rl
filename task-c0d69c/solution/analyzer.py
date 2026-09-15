#!/usr/bin/env python3
"""
Differential CPU profile analyzer.

Reads two folded-stack files (baseline and regression), computes normalized
deltas, identifies new/removed leaf functions, and clusters new functions
by their shallowest emerged call-chain ancestor.

"""

import json
import sys
from collections import defaultdict


def parse_folded(path):
    stacks = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.rsplit(" ", 1)
            if len(parts) != 2:
                continue
            stack_str, count_str = parts
            stacks[stack_str] = stacks.get(stack_str, 0) + int(count_str)
    return stacks


def leaf(stack_str):
    return stack_str.split(";")[-1]


def exclusive_counts(stacks):
    counts = defaultdict(int)
    for s, c in stacks.items():
        counts[leaf(s)] += c
    return dict(counts)


def all_intermediates(stacks):
    intermediates = set()
    for s in stacks:
        parts = s.split(";")
        for fn in parts[:-1]:
            intermediates.add(fn)
    return intermediates


def analyze(baseline_path, regression_path):
    baseline = parse_folded(baseline_path)
    regression = parse_folded(regression_path)

    b_total = sum(baseline.values())
    r_total = sum(regression.values())
    nf = r_total / b_total

    b_excl = exclusive_counts(baseline)
    r_excl = exclusive_counts(regression)

    b_leaves = set(b_excl)
    r_leaves = set(r_excl)

    new_fns = sorted(r_leaves - b_leaves)
    removed_fns = sorted(b_leaves - r_leaves)

    # Normalized deltas
    deltas = {}
    for fn in r_leaves:
        deltas[fn] = r_excl[fn] - b_excl.get(fn, 0) * nf

    positive = [(fn, d) for fn, d in deltas.items() if d > 0]
    positive.sort(key=lambda x: -x[1])
    top_10 = [{"function": fn, "impact": round(d, 4)}
              for fn, d in positive[:10]]

    # Root-cause clustering
    b_intermediates = all_intermediates(baseline)
    r_intermediates = all_intermediates(regression)
    emerged_intermediates = r_intermediates - b_intermediates

    clusters = defaultdict(set)
    for stack_str in regression:
        lf = leaf(stack_str)
        if lf not in new_fns:
            continue
        parts = stack_str.split(";")
        shallowest = None
        for fn in parts[:-1]:
            if fn in emerged_intermediates:
                shallowest = fn
                break
        key = shallowest if shallowest else lf
        clusters[key].add(lf)

    sorted_clusters = {k: sorted(v) for k, v in sorted(clusters.items())}

    report = {
        "target_pid": 4821,
        "baseline_cpu_samples": b_total,
        "regression_cpu_samples": r_total,
        "new_functions": new_fns,
        "removed_functions": removed_fns,
        "top_regressions": top_10,
        "root_cause_groups": sorted_clusters,
    }

    with open("/app/diagnosis.json", "w") as f:
        json.dump(report, f, indent=2)

    print(f"Diagnosis written to /app/diagnosis.json")
    print(f"Baseline: {b_total} samples | Regression: {r_total} samples")
    print(f"New leaf functions: {len(new_fns)} | Removed: {len(removed_fns)}")
    print(f"Root-cause groups: {len(sorted_clusters)}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: analyzer.py <baseline.folded> <regression.folded>")
        sys.exit(1)
    analyze(sys.argv[1], sys.argv[2])
