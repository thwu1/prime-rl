"""
Workload generators for cache benchmarking.

Each generator returns a list of integer keys representing an access trace.
All generators accept a seed parameter for deterministic reproducibility.

"""

import random


def zipfian_workload(n_requests, n_keys, alpha=1.0, seed=42):
    """Zipfian distribution: few keys receive most accesses."""
    rng = random.Random(seed)
    weights = [1.0 / (i ** alpha) for i in range(1, n_keys + 1)]
    total = sum(weights)
    cdf = []
    cumsum = 0.0
    for w in weights:
        cumsum += w / total
        cdf.append(cumsum)

    trace = []
    for _ in range(n_requests):
        r = rng.random()
        lo, hi = 0, n_keys - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if cdf[mid] < r:
                lo = mid + 1
            else:
                hi = mid
        trace.append(lo)
    return trace


def uniform_workload(n_requests, n_keys, seed=42):
    """Uniform random access pattern."""
    rng = random.Random(seed)
    return [rng.randint(0, n_keys - 1) for _ in range(n_requests)]


def temporal_locality_workload(n_requests, n_keys, window=100, seed=42):
    """Temporal locality: 80% of accesses target a sliding hot window."""
    rng = random.Random(seed)
    trace = []
    center = 0
    for i in range(n_requests):
        if random.random() < 0.8:
            offset = rng.randint(-window // 2, window // 2)
            key = (center + offset) % n_keys
        else:
            key = rng.randint(0, n_keys - 1)
        trace.append(key)
        if i > 0 and i % 1000 == 0:
            center = (center + window // 4) % n_keys
    return trace


def scan_mixed_workload(n_requests, n_keys, scan_length=500, seed=42):
    """Mix of sequential scans and random hot-key accesses."""
    rng = random.Random(seed)
    trace = []
    scan_pos = 0
    i = 0
    while i < n_requests:
        if rng.random() < 0.3 and i + scan_length <= n_requests:
            for j in range(scan_length):
                trace.append((scan_pos + j) % n_keys)
            scan_pos = (scan_pos + scan_length) % n_keys
            i += scan_length
        else:
            hot_key = rng.randint(0, max(1, n_keys // 10))
            trace.append(hot_key)
            i += 1
    return trace[:n_requests]
