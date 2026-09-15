#!/usr/bin/env python3
"""
Benchmark runner for cache eviction policies.

Evaluates all policy/workload combinations and writes results to results.json.

"""

import json
import sys

sys.path.insert(0, '/app')

from engine import CacheEngine
from policies import RandomPolicy, FIFOPolicy, AdaptivePolicy
from workloads import (
    zipfian_workload, uniform_workload,
    temporal_locality_workload, scan_mixed_workload,
)


SCENARIOS = {
    "zipfian_standard": {
        "generator": zipfian_workload,
        "params": {"n_requests": 100000, "n_keys": 10000, "alpha": 1.0},
        "cache_size": 200,
    },
    "zipfian_moderate": {
        "generator": zipfian_workload,
        "params": {"n_requests": 100000, "n_keys": 10000, "alpha": 0.8},
        "cache_size": 200,
    },
    "temporal_locality": {
        "generator": temporal_locality_workload,
        "params": {"n_requests": 100000, "n_keys": 10000, "window": 200},
        "cache_size": 200,
    },
    "uniform": {
        "generator": uniform_workload,
        "params": {"n_requests": 100000, "n_keys": 10000},
        "cache_size": 200,
    },
    "scan_mixed": {
        "generator": scan_mixed_workload,
        "params": {"n_requests": 100000, "n_keys": 10000, "scan_length": 500},
        "cache_size": 200,
    },
}

POLICIES = {
    "random": {"cls": RandomPolicy, "kwargs": {}},
    "fifo": {"cls": FIFOPolicy, "kwargs": {}},
    "adaptive_s5": {"cls": AdaptivePolicy, "kwargs": {"samples": 5}},
    "adaptive_s10": {"cls": AdaptivePolicy, "kwargs": {"samples": 10}},
}


def run_benchmark(seed=42):
    results = {}

    for scenario_name, scenario in SCENARIOS.items():
        print(f"\n=== {scenario_name} ===")
        trace = scenario["generator"](seed=seed, **scenario["params"])
        cache_size = scenario["cache_size"]

        scenario_results = {}
        for policy_name, policy_cfg in POLICIES.items():
            engine = CacheEngine(
                max_entries=cache_size,
                policy_cls=policy_cfg["cls"],
                seed=seed,
                **policy_cfg["kwargs"],
            )

            for key in trace:
                engine.access(key)

            stats = engine.stats()
            scenario_results[policy_name] = stats
            print(f"  {policy_name:15s}: hit_ratio={stats['hit_ratio']:.4f}  "
                  f"hits={stats['hits']}  misses={stats['misses']}")

        results[scenario_name] = scenario_results

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nResults written to /app/results.json")
    return results


if __name__ == "__main__":
    run_benchmark()
