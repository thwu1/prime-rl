#!/usr/bin/env python3
"""

HPC Procurement Benchmark Evaluation Solver.
Parses heterogeneous benchmark logs, cleans data, and produces
a structured procurement evaluation report.
"""

import csv
import json
import math
import os
import re
import statistics


DATA_DIR = "/data"
BENCHMARK_DIR = os.path.join(DATA_DIR, "benchmark_data")
OUTPUT_PATH = "/app/results/evaluation.json"

SYSTEMS = ["pinnacle", "horizon", "nexus", "vanguard", "summit_x"]
BENCHMARKS = [
    "stencil3d", "sparse_matvec", "global_fft",
    "deep_train", "genome_search", "mol_dynamics",
]


def load_json(path):
    with open(path) as f:
        return json.load(f)


# ---- Parsers for each system's log format ----

def parse_pinnacle():
    results = {}
    path = os.path.join(BENCHMARK_DIR, "pinnacle", "results.csv")
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            bm = row["benchmark"].strip()
            time_key = [k for k in row.keys() if k.strip().startswith("time_s")][0]
            t = float(row[time_key].strip())
            results.setdefault(bm, []).append(t)
    return results


def parse_horizon():
    results = {}
    path = os.path.join(BENCHMARK_DIR, "horizon", "benchmark_log.jsonl")
    # Read format description to discover units
    fmt_path = os.path.join(BENCHMARK_DIR, "horizon", "format.txt")
    with open(fmt_path) as f:
        fmt_text = f.read()
    # format.txt states runtime is in milliseconds
    ms_to_s = "milliseconds" in fmt_text.lower()

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            if entry.get("status") != "success":
                continue
            bm = entry["benchmark"]
            t = entry["runtime"]
            if ms_to_s:
                t /= 1000.0
            results.setdefault(bm, []).append(t)
    return results


def parse_nexus():
    results = {}
    path = os.path.join(BENCHMARK_DIR, "nexus", "execution.log")
    pattern = re.compile(
        r"benchmark=(\S+)\s+trial=(\d+)\s+time=([\d.]+)s\s+STATUS=OK"
    )
    with open(path) as f:
        for line in f:
            m = pattern.search(line)
            if m:
                bm = m.group(1)
                t = float(m.group(3))
                results.setdefault(bm, []).append(t)
    return results


def parse_vanguard():
    raw = {}
    path = os.path.join(BENCHMARK_DIR, "vanguard", "perf_data.tsv")
    with open(path) as f:
        f.readline()  # skip header
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            bm, trial, t = parts[0], int(parts[1]), float(parts[2])
            raw[(bm, trial)] = t  # last occurrence wins (dedup)

    results = {}
    for (bm, _), t in raw.items():
        results.setdefault(bm, []).append(t)
    return results


def parse_summit_x():
    workload = load_json(os.path.join(DATA_DIR, "workload_specs.json"))
    raw_tp = {}
    path = os.path.join(BENCHMARK_DIR, "summit_x", "throughput_results.csv")
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            bm = row["benchmark"].strip()
            tp = float(row["throughput_gflops"].strip())
            raw_tp.setdefault(bm, []).append(tp)

    results = {}
    for bm, tp_list in raw_tp.items():
        total_flops = workload[bm]["total_flops"]
        results[bm] = [total_flops / (tp * 1e9) for tp in tp_list]
    return results


PARSERS = {
    "pinnacle": parse_pinnacle,
    "horizon": parse_horizon,
    "nexus": parse_nexus,
    "vanguard": parse_vanguard,
    "summit_x": parse_summit_x,
}


# ---- Statistical cleaning ----

def iqr_clean(values):
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    q1_idx = (n - 1) * 0.25
    q3_idx = (n - 1) * 0.75

    def interp(idx):
        lo = int(math.floor(idx))
        hi = int(math.ceil(idx))
        if lo == hi:
            return sorted_vals[lo]
        frac = idx - lo
        return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac

    q1 = interp(q1_idx)
    q3 = interp(q3_idx)
    iqr = q3 - q1
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr

    cleaned = [v for v in values if lower <= v <= upper]
    removed = len(values) - len(cleaned)
    return cleaned, removed


# ---- Main analysis ----

def main():
    workload = load_json(os.path.join(DATA_DIR, "workload_specs.json"))
    sys_specs = load_json(os.path.join(DATA_DIR, "system_specs.json"))
    proc = load_json(os.path.join(DATA_DIR, "procurement_requirements.json"))

    ref_times = proc["reference_system"]["benchmark_times_s"]
    budget = proc["budget_usd"]
    power_limit = proc["power_envelope_kw"]
    perf_threshold = proc["performance_requirement"]["threshold_fraction"]

    # 1. Parse and clean
    cleaned_performance = {}
    for sys_name in SYSTEMS:
        raw = PARSERS[sys_name]()
        cleaned_performance[sys_name] = {}
        for bm in BENCHMARKS:
            if bm not in raw:
                continue
            cleaned, n_removed = iqr_clean(raw[bm])
            median_time = statistics.median(cleaned)
            cleaned_performance[sys_name][bm] = {
                "median_time_s": round(median_time, 6),
                "num_valid_trials": len(cleaned),
                "num_outliers_removed": n_removed,
            }

    # 2. Speedups
    speedups = {}
    for sys_name in SYSTEMS:
        speedups[sys_name] = {}
        for bm in BENCHMARKS:
            if bm in cleaned_performance[sys_name]:
                sys_time = cleaned_performance[sys_name][bm]["median_time_s"]
                speedups[sys_name][bm] = round(ref_times[bm] / sys_time, 6)

    # 3. Composite scores (weighted arithmetic mean of speedups)
    composite_scores = {}
    for sys_name in SYSTEMS:
        total_weight = 0.0
        weighted_sum = 0.0
        for bm in BENCHMARKS:
            if bm in speedups[sys_name]:
                w = workload[bm]["priority_weight"]
                weighted_sum += w * speedups[sys_name][bm]
                total_weight += w
        if total_weight > 0:
            composite_scores[sys_name] = round(weighted_sum / total_weight, 6)
        else:
            composite_scores[sys_name] = 0.0

    # 4. Feasibility
    feasibility = {}
    for sys_name in SYSTEMS:
        spec = sys_specs[sys_name]
        nodes = spec["node_count"]
        total_cost = nodes * spec["cost_per_node_usd"]
        total_power = nodes * spec["power_per_node_kw"]

        budget_ok = total_cost <= budget
        power_ok = total_power <= power_limit

        perf_ok = True
        for bm in BENCHMARKS:
            if bm not in cleaned_performance[sys_name]:
                perf_ok = False
                break
            max_time = ref_times[bm] / perf_threshold
            if cleaned_performance[sys_name][bm]["median_time_s"] > max_time:
                perf_ok = False
                break

        feasibility[sys_name] = {
            "budget_ok": budget_ok,
            "power_ok": power_ok,
            "performance_ok": perf_ok,
            "feasible": budget_ok and power_ok and perf_ok,
        }

    feasible_systems = [s for s in SYSTEMS if feasibility[s]["feasible"]]

    # 5. Cost-efficiency
    cost_efficiency = {}
    cost_millions = {}
    for sys_name in feasible_systems:
        spec = sys_specs[sys_name]
        cm = spec["node_count"] * spec["cost_per_node_usd"] / 1e6
        cost_millions[sys_name] = cm
        cost_efficiency[sys_name] = round(composite_scores[sys_name] / cm, 6)

    # 6. Pareto optimal (minimize cost, maximize composite)
    pareto_optimal = []
    for s in feasible_systems:
        dominated = False
        for t in feasible_systems:
            if t == s:
                continue
            t_cost = cost_millions[t]
            s_cost = cost_millions[s]
            t_comp = composite_scores[t]
            s_comp = composite_scores[s]
            if (t_cost <= s_cost and t_comp >= s_comp and
                    (t_cost < s_cost or t_comp > s_comp)):
                dominated = True
                break
        if not dominated:
            pareto_optimal.append(s)

    # 7. Ranking
    ranking = sorted(feasible_systems, key=lambda s: cost_efficiency[s], reverse=True)

    # 8. Recommendation
    recommendation = ranking[0] if ranking else None

    result = {
        "cleaned_performance": cleaned_performance,
        "speedups": speedups,
        "composite_scores": composite_scores,
        "feasibility": feasibility,
        "pareto_optimal": sorted(pareto_optimal),
        "cost_efficiency": cost_efficiency,
        "ranking": ranking,
        "recommendation": recommendation,
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(result, f, indent=2)

    print(f"Evaluation complete. Results at {OUTPUT_PATH}")
    print(f"Feasible systems: {feasible_systems}")
    print(f"Pareto-optimal: {pareto_optimal}")
    print(f"Ranking: {ranking}")
    print(f"Recommendation: {recommendation}")


if __name__ == "__main__":
    main()
