#!/usr/bin/env python3
"""
Cache performance analyzer orchestrator.
Reads queries from /app/queries.json and produces /app/results.json.
Uses the compiled C cache_core binary for cache simulations.

"""

import json
import os
import subprocess
from collections import defaultdict


def run_sim(trace_file, cache_size, block_size, assoc):
    """Run the C cache_core binary and parse its key=value output."""
    cmd = ["/app/src/cache_core", trace_file,
           str(cache_size), str(block_size), str(assoc)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"cache_core failed (exit {proc.returncode}): {proc.stderr.strip()}")
    stats = {}
    for line in proc.stdout.strip().splitlines():
        k, v = line.split("=", 1)
        stats[k] = int(v)
    total = stats["total_accesses"]
    stats["hit_rate"] = round(stats["hits"] / total, 6) if total else 0.0
    stats["miss_rate"] = round(stats["misses"] / total, 6) if total else 0.0
    return stats


def parse_trace(filepath):
    """Parse a text-format memory access trace."""
    trace = []
    with open(filepath) as f:
        for line in f:
            parts = line.split()
            if len(parts) != 2:
                continue
            trace.append((parts[0], int(parts[1], 16)))
    return trace


def compute_stack_distance(trace, block_size):
    """Compute reuse distance histogram for the trace."""
    stack = []
    histogram = defaultdict(int)
    for _, addr in trace:
        block_addr = addr // block_size
        if block_addr in stack:
            pos = stack.index(block_addr)
            histogram[pos] += 1
            stack.insert(0, block_addr)
        else:
            histogram["inf"] += 1
            stack.insert(0, block_addr)
    return dict(histogram), len(trace)


def predict_miss_rate(histogram, num_blocks):
    """Predict fully-associative miss rate from reuse distance histogram."""
    total = sum(histogram.values())
    misses = histogram.get("inf", 0)
    for dist, count in histogram.items():
        if dist == "inf":
            continue
        if dist > num_blocks:
            misses += count
    return round(misses / total, 6) if total else 0.0


def find_optimal(trace_file, cache_sizes, block_sizes, assocs, target_mr):
    """Search for minimum-cost cache configuration meeting target miss rate."""
    best = None
    for cs in sorted(cache_sizes):
        for bs in sorted(block_sizes):
            for a in sorted(assocs):
                if cs // (bs * a) < 1:
                    continue
                st = run_sim(trace_file, cs, bs, a)
                if st["miss_rate"] <= target_mr:
                    cost = cs * a
                    if best is None or cost <= best["best_cost"]:
                        best = {
                            "best_cache_size": cs,
                            "best_block_size": bs,
                            "best_associativity": a,
                            "best_cost": cost,
                            "achieved_miss_rate": st["miss_rate"],
                        }
    return best


def main():
    with open("/app/queries.json") as f:
        queries = json.load(f)

    results = {"simulations": {}, "stack_distance": {},
               "miss_rate_predictions": {}, "optimize": {}}

    trace_cache = {}
    sd_cache = {}

    for q in queries.get("simulations", []):
        tp = os.path.join("/app", q["trace"])
        results["simulations"][q["id"]] = run_sim(
            tp, q["cache_size_bytes"], q["block_size_bytes"],
            q["associativity"])

    for q in queries.get("stack_distance", []):
        tp = os.path.join("/app", q["trace"])
        if tp not in trace_cache:
            trace_cache[tp] = parse_trace(tp)
        hist, total = compute_stack_distance(
            trace_cache[tp], q["block_size_bytes"])
        results["stack_distance"][q["id"]] = {
            "histogram": {str(k): v for k, v in hist.items()},
            "total_accesses": total,
        }
        sd_cache[q["id"]] = hist

    for q in queries.get("miss_rate_predictions", []):
        hist = sd_cache[q["stack_distance_id"]]
        preds = {}
        for nb in q["num_blocks"]:
            preds[str(nb)] = predict_miss_rate(hist, nb)
        results["miss_rate_predictions"][q["id"]] = preds

    for q in queries.get("optimize", []):
        tp = os.path.join("/app", q["trace"])
        results["optimize"][q["id"]] = find_optimal(
            tp, q["cache_sizes"], q["block_sizes"],
            q["associativities"], q["target_miss_rate"])

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("Analysis complete. Results written to /app/results.json")


if __name__ == "__main__":
    main()
