#!/usr/bin/env python3

"""Solution: multi-objective OoO processor design space analysis.

Parses gem5-format simulation output, fixes a buggy power model,
and performs 3-objective design space optimization.
"""

import json
import math
import os
import re
import sys

import yaml

sys.path.insert(0, "/app")
from arch_model import compute_area


# ---------------------------------------------------------------------------
# Corrected power model
# ---------------------------------------------------------------------------

def compute_power_fixed(width, rob_size, num_int_regs, num_fp_regs,
                        avg_ipc, avg_l1_miss_rate, temperature=350):
    """Power model with both bugs fixed:
    1. Activity factor: multiplicative, not additive
    2. Leakage temperature coefficient: positive, not negative
    """
    V, f = 0.9, 1.0
    activity = (avg_ipc / width) * (1.0 + 0.1 * width)
    stall_factor = 1.0 / (1.0 + 2.0 * avg_l1_miss_rate)
    C_eff = 0.5 * (rob_size + 2.0 * width * width)
    dynamic = C_eff * V * V * f * activity * stall_factor
    area = compute_area(width, rob_size, num_int_regs, num_fp_regs)
    k = 0.002
    temp_factor = math.exp(k * (temperature - 300))
    leakage = 0.001 * area * temp_factor
    return round(dynamic + leakage, 4)


# ---------------------------------------------------------------------------
# Stats parsing
# ---------------------------------------------------------------------------

def parse_all_stats(sim_dir):
    """Parse all gem5-format stats files from the simulation output directory."""
    configs = {}

    for config_id in os.listdir(sim_dir):
        path = os.path.join(sim_dir, config_id, "stats.txt")
        if not os.path.isfile(path):
            continue

        with open(path) as fp:
            content = fp.read()

        sections = re.split(
            r"---------- Begin Simulation Statistics \[(\w+)\] ----------",
            content,
        )

        ipcs = {}
        l1_miss_rates = {}
        width = rob = num_int = num_fp = None

        for idx in range(1, len(sections), 2):
            wl = sections[idx]
            block = sections[idx + 1]
            stats = {}
            for line in block.strip().split("\n"):
                line = line.strip()
                if not line or line.startswith("---"):
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    stats[parts[0]] = parts[-1]

            insts = int(stats["system.cpu.committedInsts"])
            cycles = int(stats["system.cpu.numCycles"])
            ipcs[wl] = insts / cycles

            l1_h = int(stats[
                "board.cache_hierarchy.ruby_system."
                "l1_controllers0.L1Dcache.m_demand_hits"
            ])
            l1_m = int(stats[
                "board.cache_hierarchy.ruby_system."
                "l1_controllers0.L1Dcache.m_demand_misses"
            ])
            l1_miss_rates[wl] = l1_m / (l1_h + l1_m)

            if width is None:
                width = int(stats["system.cpu.fetchWidth"])
                rob = int(stats["system.cpu.numROBEntries"])
                num_int = int(stats["system.cpu.numPhysIntRegs"])
                num_fp = int(stats["system.cpu.numPhysFloatRegs"])

        configs[config_id] = {
            "width": width,
            "rob_size": rob,
            "num_int_regs": num_int,
            "num_fp_regs": num_fp,
            "ipcs": ipcs,
            "l1_miss_rates": l1_miss_rates,
        }

    return configs


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Fix the power model file on disk
    pm_path = "/app/power_model.py"
    with open(pm_path) as fp:
        code = fp.read()
    code = code.replace(
        "(avg_ipc / width) + 0.1 * width",
        "(avg_ipc / width) * (1.0 + 0.1 * width)",
    )
    code = code.replace("k = -0.002", "k = 0.002")
    with open(pm_path, "w") as fp:
        fp.write(code)

    # Parse all simulation data
    configs = parse_all_stats("/app/sim_output")

    # Read constraints
    with open("/app/constraints.yaml") as fp:
        constraints = yaml.safe_load(fp)
    weights = constraints["workload_weights"]
    baseline_id = constraints["baseline_config"]
    temperature = constraints["temperature_kelvin"]
    scenarios = constraints["budget_scenarios"]
    workloads = sorted(weights.keys())

    # ---- Area scores ----
    area_scores = {}
    for cid, cfg in configs.items():
        area_scores[cid] = compute_area(
            cfg["width"], cfg["rob_size"],
            cfg["num_int_regs"], cfg["num_fp_regs"],
        )

    # ---- Power estimates (using fixed model) ----
    power_estimates = {}
    for cid, cfg in configs.items():
        product = 1.0
        for wl in workloads:
            product *= cfg["ipcs"][wl]
        avg_ipc = product ** (1.0 / len(workloads))
        avg_miss = sum(cfg["l1_miss_rates"][wl] for wl in workloads) / len(workloads)
        power_estimates[cid] = compute_power_fixed(
            cfg["width"], cfg["rob_size"],
            cfg["num_int_regs"], cfg["num_fp_regs"],
            avg_ipc, avg_miss, temperature,
        )

    # ---- Weighted geometric-mean performance ----
    baseline_ipcs = configs[baseline_id]["ipcs"]
    weighted_perf = {}
    for cid, cfg in configs.items():
        log_sum = 0.0
        for wl in workloads:
            speedup = cfg["ipcs"][wl] / baseline_ipcs[wl]
            log_sum += weights[wl] * math.log(speedup)
        weighted_perf[cid] = round(math.exp(log_sum), 6)

    # ---- 3-objective Pareto front ----
    cids = list(configs.keys())
    pareto = []
    for cid in cids:
        dominated = False
        for other in cids:
            if other == cid:
                continue
            if (
                area_scores[other] <= area_scores[cid]
                and power_estimates[other] <= power_estimates[cid]
                and weighted_perf[other] >= weighted_perf[cid]
                and (
                    area_scores[other] < area_scores[cid]
                    or power_estimates[other] < power_estimates[cid]
                    or weighted_perf[other] > weighted_perf[cid]
                )
            ):
                dominated = True
                break
        if not dominated:
            pareto.append(cid)
    pareto.sort(key=lambda x: (area_scores[x], power_estimates[x]))

    # ---- Bottleneck identification via marginal sensitivity ----
    grid = {
        "width": sorted(set(c["width"] for c in configs.values())),
        "rob_size": sorted(set(c["rob_size"] for c in configs.values())),
        "num_int_regs": sorted(set(c["num_int_regs"] for c in configs.values())),
        "num_fp_regs": sorted(set(c["num_fp_regs"] for c in configs.values())),
    }
    bcfg = configs[baseline_id]
    base_params = {
        "width": bcfg["width"],
        "rob_size": bcfg["rob_size"],
        "num_int_regs": bcfg["num_int_regs"],
        "num_fp_regs": bcfg["num_fp_regs"],
    }

    bottlenecks = {}
    for wl in workloads:
        base_ipc = baseline_ipcs[wl]
        best_param = None
        best_delta = -1.0
        for param in ["width", "rob_size", "num_int_regs", "num_fp_regs"]:
            vals = grid[param]
            idx = vals.index(base_params[param])
            if idx + 1 >= len(vals):
                continue
            nxt = vals[idx + 1]
            tp = dict(base_params)
            tp[param] = nxt
            test_cid = (
                f"w{tp['width']}_r{tp['rob_size']}"
                f"_i{tp['num_int_regs']}_f{tp['num_fp_regs']}"
            )
            delta = configs[test_cid]["ipcs"][wl] - base_ipc
            if delta > best_delta:
                best_delta = delta
                best_param = param
        bottlenecks[wl] = best_param

    # ---- Scenario-optimal configurations ----
    scenario_optimal = {}
    for name, sc in scenarios.items():
        mx_area = sc["max_area"]
        mx_power = sc["max_power"]
        best_cid = None
        best_perf = -1.0
        best_a = float("inf")
        best_p = float("inf")
        for cid in configs:
            if area_scores[cid] <= mx_area and power_estimates[cid] <= mx_power:
                p = weighted_perf[cid]
                a = area_scores[cid]
                pw = power_estimates[cid]
                if (
                    p > best_perf
                    or (p == best_perf and a < best_a)
                    or (p == best_perf and a == best_a and pw < best_p)
                ):
                    best_perf = p
                    best_cid = cid
                    best_a = a
                    best_p = pw
        scenario_optimal[name] = best_cid

    # ---- Write results ----
    results = {
        "area_scores": area_scores,
        "power_estimates": power_estimates,
        "weighted_perf": weighted_perf,
        "pareto_front": pareto,
        "bottlenecks": bottlenecks,
        "scenario_optimal": scenario_optimal,
    }
    with open("/app/results.json", "w") as fp:
        json.dump(results, fp, indent=2)

    print("Results written to /app/results.json")


if __name__ == "__main__":
    main()
