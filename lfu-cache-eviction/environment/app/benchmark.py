#!/usr/bin/env python3
"""
Benchmark runner for cache eviction policies.

Runs all policy/workload combinations and writes results to /app/results.json.

"""

import json
import sys

sys.path.insert(0, '/app')

from cache import CacheSimulator
from workload import (
    zipfian_workload, uniform_workload,
    temporal_locality_workload, scan_mixed_workload,
)

SCENARIOS = [
    {
        "name": "zipfian_standard",
        "workload": "zipfian",
        "n_requests": 100000,
        "n_keys": 10000,
        "cache_size": 1000,
        "params": {"alpha": 1.0},
    },
    {
        "name": "zipfian_mild",
        "workload": "zipfian",
        "n_requests": 100000,
        "n_keys": 10000,
        "cache_size": 500,
        "params": {"alpha": 0.8},
    },
    {
        "name": "uniform",
        "workload": "uniform",
        "n_requests": 100000,
        "n_keys": 10000,
        "cache_size": 1000,
        "params": {},
    },
    {
        "name": "temporal_locality",
        "workload": "temporal",
        "n_requests": 100000,
        "n_keys": 10000,
        "cache_size": 1000,
        "params": {"window": 200},
    },
    {
        "name": "scan_mixed",
        "workload": "scan",
        "n_requests": 100000,
        "n_keys": 10000,
        "cache_size": 1000,
        "params": {"scan_length": 500},
    },
]

POLICIES = [
    {"name": "random", "policy": "random", "samples": 5},
    {"name": "approx_lru_5", "policy": "approx_lru", "samples": 5},
    {"name": "approx_lru_10", "policy": "approx_lru", "samples": 10},
    {"name": "lfu_f10_d1", "policy": "lfu", "samples": 5,
     "log_factor": 10, "decay_time": 1},
    {"name": "lfu_f100_d1", "policy": "lfu", "samples": 5,
     "log_factor": 100, "decay_time": 1},
]


def generate_workload(scenario, seed=42):
    wl = scenario["workload"]
    n_req = scenario["n_requests"]
    n_keys = scenario["n_keys"]
    params = scenario["params"]

    if wl == "zipfian":
        return zipfian_workload(n_req, n_keys, alpha=params.get("alpha", 1.0), seed=seed)
    elif wl == "uniform":
        return uniform_workload(n_req, n_keys, seed=seed)
    elif wl == "temporal":
        return temporal_locality_workload(
            n_req, n_keys, window=params.get("window", 100), seed=seed
        )
    elif wl == "scan":
        return scan_mixed_workload(
            n_req, n_keys, scan_length=params.get("scan_length", 500), seed=seed
        )
    else:
        raise ValueError(f"Unknown workload: {wl}")


def run_benchmark():
    results = {}

    for scenario in SCENARIOS:
        name = scenario["name"]
        print(f"Running scenario: {name}")
        trace = generate_workload(scenario)
        scenario_results = {}

        for pol in POLICIES:
            cache = CacheSimulator(
                max_size=scenario["cache_size"],
                policy=pol["policy"],
                samples=pol.get("samples", 5),
                log_factor=pol.get("log_factor", 10),
                decay_time=pol.get("decay_time", 1),
                seed=42,
            )

            for key in trace:
                cache.access(key)

            stats = cache.stats()
            scenario_results[pol["name"]] = stats
            print(f"  {pol['name']}: hit_ratio={stats['hit_ratio']:.4f}")

        results[name] = scenario_results

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("\nResults written to /app/results.json")


if __name__ == "__main__":
    run_benchmark()
