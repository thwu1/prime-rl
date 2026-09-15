#!/usr/bin/env python3
"""
Benchmark script for the sorted set implementation.
Usage: python3 /app/benchmark.py

Profiles insertion, rank queries, and score-range queries across
increasing dataset sizes to reveal scaling characteristics.
"""
import time
import random
import sys
import tracemalloc

sys.path.insert(0, '/app')
from sorted_set import SortedSet


def run_benchmark():
    random.seed(42)

    sizes = [1000, 10000, 50000]

    for N in sizes:
        print(f"\n{'=' * 60}")
        print(f"  Dataset size: {N:,}")
        print(f"{'=' * 60}")

        ss = SortedSet()

        # --- Insertion ---
        tracemalloc.start()
        t0 = time.perf_counter()
        for i in range(N):
            ss.zadd(f"player_{i:06d}", round(random.uniform(0, 10000), 2))
        t_insert = time.perf_counter() - t0
        mem_current, mem_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        print(f"  Insert {N:,} elements: {t_insert:.3f}s")
        print(f"  Memory: current={mem_current / 1024:.0f}KB peak={mem_peak / 1024:.0f}KB")
        print(f"  Per-entry overhead: ~{mem_current / N:.1f} bytes")

        # --- Rank queries ---
        queries = [f"player_{random.randint(0, N - 1):06d}" for _ in range(min(2000, N))]
        t0 = time.perf_counter()
        for q in queries:
            ss.zrank(q)
        t_rank = time.perf_counter() - t0
        qps = len(queries) / t_rank if t_rank > 0 else float('inf')
        print(f"  Rank queries ({len(queries)}): {t_rank:.3f}s ({qps:.0f} ops/s)")

        # --- Score-range queries ---
        t0 = time.perf_counter()
        for _ in range(100):
            lo = random.uniform(0, 9000)
            hi = lo + random.uniform(100, 1000)
            ss.zrange_by_score(lo, hi)
        t_range = time.perf_counter() - t0
        print(f"  Score range queries (100): {t_range:.3f}s")

        # --- Structural info ---
        print(f"  Height: {ss.height()}, Nodes: {ss.node_count()}, Size: {ss.zcard()}")

    print(f"\n{'=' * 60}")
    print("  Scaling analysis")
    print(f"{'=' * 60}")
    print("  Compare timings across dataset sizes to identify")
    print("  operations with superlinear growth.")


if __name__ == "__main__":
    run_benchmark()
