#!/usr/bin/env python3

"""
Out-of-Order Processor Design Space Optimizer.

Reads the specification from /app/spec.json, exhaustively evaluates all
microarchitectural configurations, computes per-workload IPC and geometric
mean IPC, extracts the Pareto frontier (area vs. geo-mean IPC), and finds
optimal configurations for each area budget.

Writes results to /app/results.json.
"""

import json
import math
import sys

SPEC_PATH = "/app/spec.json"
OUTPUT_PATH = "/app/results.json"


def load_spec():
    with open(SPEC_PATH) as f:
        return json.load(f)


def compute_area(w, r, i, f):
    """
    Area score = width * (2*rob + int_regs + fp_regs)
               + 4*width + 2*rob + int_regs + fp_regs

    This models the cost of wide issue (width scales register file ports
    and ROB ports), ROB storage, and register file storage.
    """
    return w * (2 * r + i + f) + 4 * w + 2 * r + i + f


def compute_ipc(w, r, i, f, wl, arch_regs):
    """
    Compute IPC for a single workload under a given configuration.

    IPC = min of all applicable constraints:
      1. width (pipeline width limit)
      2. ILP (intrinsic workload parallelism)
      3. rob_size / avg_inflight_cycles (Little's Law)
      4. (int_regs - arch_regs) / (avg_int_reg_lifetime * frac_int)
         [non-binding if frac_int == 0]
      5. (fp_regs - arch_regs) / (avg_fp_reg_lifetime * frac_fp)
         [non-binding if frac_fp == 0]
    """
    constraints = [
        float(w),
        wl["ilp"],
        r / wl["avg_inflight_cycles"],
    ]

    if wl["frac_int"] > 0:
        free_int = i - arch_regs
        constraints.append(
            free_int / (wl["avg_int_reg_lifetime"] * wl["frac_int"])
        )

    if wl["frac_fp"] > 0:
        free_fp = f - arch_regs
        constraints.append(
            free_fp / (wl["avg_fp_reg_lifetime"] * wl["frac_fp"])
        )

    return min(constraints)


def compute_geo_mean(values):
    """Geometric mean via log-sum to avoid overflow."""
    n = len(values)
    return math.exp(sum(math.log(v) for v in values) / n)


def validate_model(spec, arch_regs):
    """Check implementation against the spec's validation points."""
    workloads = spec["workloads"]
    for vp in spec["validation"]:
        c = vp["config"]
        area = compute_area(c["width"], c["rob_size"],
                            c["num_int_regs"], c["num_fp_regs"])
        if area != vp["expected_area"]:
            print(f"VALIDATION FAILED: {vp['description']} area "
                  f"expected {vp['expected_area']}, got {area}", file=sys.stderr)
            return False

        for wl_name, wl in workloads.items():
            ipc = compute_ipc(c["width"], c["rob_size"],
                              c["num_int_regs"], c["num_fp_regs"],
                              wl, arch_regs)
            expected = vp["expected_ipc"][wl_name]
            if abs(ipc - expected) > 0.001:
                print(f"VALIDATION FAILED: {vp['description']} {wl_name} IPC "
                      f"expected {expected:.4f}, got {ipc:.4f}", file=sys.stderr)
                return False

    print("All validation points passed.", file=sys.stderr)
    return True


def main():
    spec = load_spec()
    arch_regs = spec["models"]["ipc"]["arch_registers"]
    workloads = spec["workloads"]
    ps = spec["parameter_space"]
    budgets = spec["area_budgets"]
    wl_names = list(workloads.keys())

    # Validate the model implementation
    if not validate_model(spec, arch_regs):
        sys.exit(1)

    # Enumerate all configurations
    all_configs = []
    for w in ps["width"]:
        for r in ps["rob_size"]:
            for i in ps["num_int_regs"]:
                for fp in ps["num_fp_regs"]:
                    area = compute_area(w, r, i, fp)
                    per_wl = {}
                    for name in wl_names:
                        per_wl[name] = compute_ipc(
                            w, r, i, fp, workloads[name], arch_regs
                        )
                    gm = compute_geo_mean(list(per_wl.values()))
                    all_configs.append({
                        "width": w,
                        "rob_size": r,
                        "num_int_regs": i,
                        "num_fp_regs": fp,
                        "area": area,
                        "geo_mean_ipc": gm,
                        "per_workload_ipc": per_wl,
                    })

    print(f"Evaluated {len(all_configs)} configurations.", file=sys.stderr)

    # Sort by area ascending, then by geo_mean_ipc descending (for tie-breaking)
    all_configs.sort(key=lambda c: (c["area"], -c["geo_mean_ipc"]))

    # Extract Pareto frontier: walk in order of increasing area,
    # keep only configs with strictly higher IPC than all previous.
    pareto = []
    best_ipc = -1.0
    for c in all_configs:
        if c["geo_mean_ipc"] > best_ipc + 1e-12:
            pareto.append(c)
            best_ipc = c["geo_mean_ipc"]

    print(f"Pareto frontier: {len(pareto)} non-dominated configurations.",
          file=sys.stderr)

    # Find budget-optimal: for each budget, the config with highest
    # geo_mean_ipc among those with area <= budget.
    # Tie-break: prefer smaller area.
    budget_optimal = {}
    for budget in budgets:
        best = None
        for c in all_configs:
            if c["area"] <= budget:
                if best is None or c["geo_mean_ipc"] > best["geo_mean_ipc"] + 1e-12:
                    best = c
                elif (abs(c["geo_mean_ipc"] - best["geo_mean_ipc"]) < 1e-12
                      and c["area"] < best["area"]):
                    best = c
        if best is not None:
            budget_optimal[str(budget)] = best
            print(f"Budget {budget}: area={best['area']}, "
                  f"geo_mean_ipc={best['geo_mean_ipc']:.6f}", file=sys.stderr)

    # Build results
    results = {
        "configurations_evaluated": len(all_configs),
        "pareto_frontier": pareto,
        "budget_optimal": budget_optimal,
    }

    with open(OUTPUT_PATH, "w") as f:
        json.dump(results, f, indent=2)

    print(f"Results written to {OUTPUT_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
