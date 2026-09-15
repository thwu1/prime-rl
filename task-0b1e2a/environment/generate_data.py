#!/usr/bin/env python3
"""Generate synthetic Prometheus metric snapshots for the SLO analyzer task.

Creates 5 snapshots simulating a load test on a 3-replica SGLang LLM serving deployment:
  snapshot_001: healthy baseline
  snapshot_002: slight load increase
  snapshot_003: degradation (cache miss + queue buildup)
  snapshot_004: severe overload
  snapshot_005: recovery

Histogram metrics are split across 3 instances (replicas) to require
correct multi-instance aggregation (sum by le) before computing percentiles.
Gauge metrics are emitted as cluster-wide aggregates (no instance label).
"""

import json
import os

MODEL = "meta-llama/Llama-3.1-8B-Instruct"
INSTANCES = ["replica-0", "replica-1", "replica-2"]

TTFT_BOUNDS = [
    0.001, 0.005, 0.01, 0.02, 0.04, 0.06, 0.08, 0.1,
    0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0,
    15.0, 20.0, 25.0, 30.0,
]

E2E_BOUNDS = [
    0.3, 0.5, 0.8, 1.0, 1.5, 2.0, 2.5, 5.0,
    10.0, 15.0, 20.0, 30.0, 40.0, 50.0, 60.0,
]

TPOT_BOUNDS = [
    0.005, 0.01, 0.015, 0.02, 0.025, 0.03, 0.04, 0.05,
    0.075, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5, 0.75, 1.0, 2.5,
]

SNAPSHOTS = [
    {
        "file": "snapshot_001.prom",
        "ts": 1718280000,
        "ttft": [0,0,5,15,40,80,130,200,500,720,850,920,975,993,998,1000,1000,1000,1000,1000],
        "ttft_sum": 432.5, "ttft_total": 1000,
        "e2e": [0,5,15,30,60,100,150,400,700,850,930,975,993,998,1000],
        "e2e_sum": 8523.4, "e2e_total": 1000,
        "tpot": [50,1500,8000,18000,32000,48000,65000,78000,90000,96000,98800,99600,99900,99960,99980,99995,99998,100000],
        "tpot_sum": 4820.3, "tpot_total": 100000,
        "queue": 50.0, "cache": 0.85, "throughput": 120.5, "running": 30.0,
        "prompt_tok": 500000, "gen_tok": 400000,
    },
    {
        "file": "snapshot_002.prom",
        "ts": 1718280300,
        "ttft": [0,0,3,10,30,60,100,150,400,620,760,860,950,985,995,999,1000,1000,1000,1000],
        "ttft_sum": 567.3, "ttft_total": 1000,
        "e2e": [0,3,10,20,45,80,120,350,630,800,900,960,988,996,1000],
        "e2e_sum": 10234.7, "e2e_total": 1000,
        "tpot": [30,1000,6000,15000,28000,42000,58000,72000,87000,94000,98000,99200,99800,99920,99970,99990,99997,100000],
        "tpot_sum": 5340.7, "tpot_total": 100000,
        "queue": 200.0, "cache": 0.65, "throughput": 100.2, "running": 80.0,
        "prompt_tok": 1200000, "gen_tok": 900000,
    },
    {
        "file": "snapshot_003.prom",
        "ts": 1718280600,
        "ttft": [0,0,2,8,20,40,65,100,280,450,580,680,830,910,950,975,992,998,1000,1000],
        "ttft_sum": 3482.1, "ttft_total": 1000,
        "e2e": [0,2,5,10,20,35,55,180,400,600,750,880,950,985,996],
        "e2e_sum": 18762.3, "e2e_total": 1000,
        "tpot": [20,500,3000,8000,16000,26000,40000,55000,75000,88000,95000,98000,99500,99800,99920,99970,99990,100000],
        "tpot_sum": 6280.4, "tpot_total": 100000,
        "queue": 1500.0, "cache": 0.05, "throughput": 45.3, "running": 150.0,
        "prompt_tok": 2100000, "gen_tok": 1300000,
    },
    {
        "file": "snapshot_004.prom",
        "ts": 1718280900,
        "ttft": [0,0,0,2,5,8,12,18,40,70,100,140,250,380,500,600,750,860,940,985],
        "ttft_sum": 11856.7, "ttft_total": 1000,
        "e2e": [0,0,2,5,10,18,30,100,250,400,550,700,820,900,955],
        "e2e_sum": 32541.8, "e2e_total": 1000,
        "tpot": [10,200,1500,4000,9000,16000,28000,42000,62000,78000,90000,95000,98500,99400,99750,99900,99960,100000],
        "tpot_sum": 7890.2, "tpot_total": 100000,
        "queue": 3000.0, "cache": 0.01, "throughput": 25.7, "running": 200.0,
        "prompt_tok": 2800000, "gen_tok": 1600000,
    },
    {
        "file": "snapshot_005.prom",
        "ts": 1718281200,
        "ttft": [0,0,5,15,45,85,140,210,480,690,830,905,968,991,997,999,1000,1000,1000,1000],
        "ttft_sum": 468.2, "ttft_total": 1000,
        "e2e": [0,5,15,28,55,95,140,380,680,840,920,972,992,998,1000],
        "e2e_sum": 8891.5, "e2e_total": 1000,
        "tpot": [40,1200,7000,16000,30000,45000,62000,76000,89000,95500,98500,99500,99880,99950,99975,99993,99998,100000],
        "tpot_sum": 5010.6, "tpot_total": 100000,
        "queue": 100.0, "cache": 0.70, "throughput": 95.8, "running": 40.0,
        "prompt_tok": 3500000, "gen_tok": 2100000,
    },
]


def split_hist_across_instances(cumcounts, total, n_instances=3):
    """Split cumulative histogram counts across instances via differential counts.

    Converts cumulative counts to differential (per-bucket) counts, splits each
    differential evenly across instances, then re-cumulates. This guarantees:
    - Each instance has non-decreasing cumulative counts
    - The sum across all instances equals the original cumulative counts exactly
    """
    n = len(cumcounts)
    # Compute differential counts
    diff = [cumcounts[0]]
    for i in range(1, n):
        diff.append(cumcounts[i] - cumcounts[i - 1])
    inf_diff = total - cumcounts[-1]

    # Split each differential across instances
    inst_diffs = [[] for _ in range(n_instances)]
    for d in diff:
        base = d // n_instances
        remainder = d - base * n_instances
        for inst in range(n_instances):
            inst_diffs[inst].append(base + (1 if inst < remainder else 0))

    # Split +Inf differential
    inf_base = inf_diff // n_instances
    inf_rem = inf_diff - inf_base * n_instances
    inf_parts = [inf_base + (1 if inst < inf_rem else 0) for inst in range(n_instances)]

    # Re-cumulate each instance
    results = []
    for inst in range(n_instances):
        cum = []
        running = 0
        for d in inst_diffs[inst]:
            running += d
            cum.append(running)
        inst_total = running + inf_parts[inst]
        results.append((cum, inst_total))

    return results


def write_hist_multi(f, name, desc, bounds, cumcounts, total, hsum, instances):
    """Write multi-instance histogram in Prometheus exposition format."""
    f.write(f"# HELP {name} {desc}\n")
    f.write(f"# TYPE {name} histogram\n")

    splits = split_hist_across_instances(cumcounts, total, len(instances))

    for idx, inst in enumerate(instances):
        counts, inst_total = splits[idx]
        inst_sum = hsum * inst_total / total if total > 0 else 0
        for b, c in zip(bounds, counts):
            f.write(f'{name}_bucket{{le="{b}",model_name="{MODEL}",instance="{inst}"}} {float(c)}\n')
        f.write(f'{name}_bucket{{le="+Inf",model_name="{MODEL}",instance="{inst}"}} {float(inst_total)}\n')
        f.write(f'{name}_sum{{model_name="{MODEL}",instance="{inst}"}} {round(inst_sum, 1)}\n')
        f.write(f'{name}_count{{model_name="{MODEL}",instance="{inst}"}} {float(inst_total)}\n')


def write_gauge(f, name, desc, val):
    """Write a cluster-wide gauge (no instance label)."""
    f.write(f"# HELP {name} {desc}\n")
    f.write(f"# TYPE {name} gauge\n")
    f.write(f'{name}{{model_name="{MODEL}"}} {val}\n')


def write_counter(f, name, desc, val):
    f.write(f"# HELP {name} {desc}\n")
    f.write(f"# TYPE {name} counter\n")
    f.write(f'{name}{{model_name="{MODEL}"}} {val}\n')


def main():
    os.makedirs("/app/metrics", exist_ok=True)

    for s in SNAPSHOTS:
        path = os.path.join("/app/metrics", s["file"])
        with open(path, "w") as f:
            f.write(f'# Scrape timestamp: {s["ts"]}\n\n')

            write_hist_multi(f, "sglang:time_to_first_token_seconds",
                             "Histogram of time to first token in seconds.",
                             TTFT_BOUNDS, s["ttft"], s["ttft_total"], s["ttft_sum"],
                             INSTANCES)
            f.write("\n")

            write_hist_multi(f, "sglang:e2e_request_latency_seconds",
                             "Histogram of End-to-end request latency in seconds",
                             E2E_BOUNDS, s["e2e"], s["e2e_total"], s["e2e_sum"],
                             INSTANCES)
            f.write("\n")

            write_hist_multi(f, "sglang:time_per_output_token_seconds",
                             "Histogram of time per output token in seconds.",
                             TPOT_BOUNDS, s["tpot"], s["tpot_total"], s["tpot_sum"],
                             INSTANCES)
            f.write("\n")

            # Gauges are cluster-wide (no instance label)
            write_gauge(f, "sglang:num_queue_reqs",
                        "The number of requests in the waiting queue",
                        s["queue"])
            f.write("\n")
            write_gauge(f, "sglang:cache_hit_rate",
                        "The cache hit rate", s["cache"])
            f.write("\n")
            write_gauge(f, "sglang:gen_throughput",
                        "The generate throughput (token/s)", s["throughput"])
            f.write("\n")
            write_gauge(f, "sglang:num_running_reqs",
                        "The number of running requests", s["running"])
            f.write("\n")

            write_counter(f, "sglang:prompt_tokens_total",
                          "Number of prefill tokens processed.",
                          s["prompt_tok"])
            f.write("\n")
            write_counter(f, "sglang:generation_tokens_total",
                          "Number of generation tokens processed.",
                          s["gen_tok"])

        print(f"  -> {path}")

    # --- SLO config ---
    cfg = {
        "slos": {
            "ttft_p99": {
                "prometheus_metric": "sglang:time_to_first_token_seconds",
                "type": "histogram_p99",
                "threshold": 10.0,
                "operator": "<"
            },
            "e2e_p99": {
                "prometheus_metric": "sglang:e2e_request_latency_seconds",
                "type": "histogram_p99",
                "threshold": 55.0,
                "operator": "<"
            },
            "tpot_p99": {
                "prometheus_metric": "sglang:time_per_output_token_seconds",
                "type": "histogram_p99",
                "threshold": 0.3,
                "operator": "<"
            },
            "queue_depth": {
                "prometheus_metric": "sglang:num_queue_reqs",
                "type": "gauge",
                "threshold": 1000.0,
                "operator": "<"
            },
            "cache_hit_rate": {
                "prometheus_metric": "sglang:cache_hit_rate",
                "type": "gauge",
                "threshold": 0.1,
                "operator": ">"
            },
            "gen_throughput": {
                "prometheus_metric": "sglang:gen_throughput",
                "type": "gauge",
                "threshold": 50.0,
                "operator": ">"
            },
        },
        "error_budget": {
            "max_violation_pct": 25.0
        },
    }
    with open("/app/slo_config.json", "w") as f:
        json.dump(cfg, f, indent=2)
    print("  -> /app/slo_config.json")


if __name__ == "__main__":
    main()
