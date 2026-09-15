#!/usr/bin/env python3
"""
HLS Design Space Exploration Analysis Framework.

Expands a YAML-defined DSE space, evaluates all configurations using the
provided cost model, computes Pareto fronts, Pass@K statistics, and
normalized differential PPA comparisons.
"""

import sys
import os
import json
import csv
import math
import itertools
from pathlib import Path

sys.path.insert(0, "/app")

import yaml
from cost_model import evaluate_config, compute_composite_area


def load_dse_space(yaml_path):
    with open(yaml_path) as f:
        return yaml.safe_load(f)


def expand_configurations(space):
    keys = list(space.keys())
    values = [space[k] for k in keys]
    configs = []
    for combo in itertools.product(*values):
        configs.append(dict(zip(keys, combo)))
    return configs


def load_designs(designs_dir):
    designs = []
    for f in sorted(Path(designs_dir).glob("*.json")):
        with open(f) as fh:
            designs.append(json.load(fh))
    return designs


def compute_pareto_front(results):
    """Find indices of Pareto-optimal points minimizing
    (latency_ns, composite_area, power_mw)."""
    n = len(results)
    is_pareto = [True] * n

    for i in range(n):
        if not is_pareto[i]:
            continue
        for j in range(n):
            if i == j or not is_pareto[j]:
                continue
            ri = results[i]
            rj = results[j]
            if (rj["latency_ns"] <= ri["latency_ns"]
                    and rj["composite_area"] <= ri["composite_area"]
                    and rj["power_mw"] <= ri["power_mw"]
                    and (rj["latency_ns"] < ri["latency_ns"]
                         or rj["composite_area"] < ri["composite_area"]
                         or rj["power_mw"] < ri["power_mw"])):
                is_pareto[i] = False
                break

    return [i for i in range(n) if is_pareto[i]]


def compute_pass_at_k(n, c, k):
    """Pass@K = 1 - C(n-c, k) / C(n, k) computed in log-space."""
    if n < k:
        return 1.0 if c > 0 else 0.0
    if c >= n:
        return 1.0
    if c == 0:
        return 0.0

    log_ratio = 0.0
    for i in range(k):
        if n - c - i <= 0:
            return 1.0
        log_ratio += math.log(n - c - i) - math.log(n - i)

    return 1.0 - math.exp(log_ratio)


def compute_differential_ppa(result, reference):
    """(generated - reference) / reference * 100 for each metric."""
    diffs = {}
    for metric in ["latency_ns", "luts", "ffs", "power_mw"]:
        ref_val = reference[metric]
        gen_val = result[metric]
        if ref_val == 0:
            diffs[metric] = 0.0
        else:
            diffs[metric] = (gen_val - ref_val) / ref_val * 100.0
    return diffs


def main():
    os.makedirs("/app/output", exist_ok=True)

    space = load_dse_space("/app/dse_space.yaml")
    configs = expand_configurations(space)
    designs = load_designs("/app/designs")

    all_pareto_fronts = {}
    all_pass_at_k = {}
    all_dse_summary = {}
    all_rows = []

    csv_keys = set()

    for design in designs:
        name = design["name"]
        reference = design["reference_ppa"]

        synth_results = []
        n_total = len(configs)
        n_compile = 0
        n_sim = 0
        n_synth = 0

        for idx, config in enumerate(configs):
            result = evaluate_config(design, config)

            if result["compile_pass"]:
                n_compile += 1
            if result.get("sim_pass", False):
                n_sim += 1
            if result.get("synth_pass", False):
                n_synth += 1
                synth_results.append(result)

            row = {
                "design": name,
                "config_id": idx,
                "compile_pass": result["compile_pass"],
                "sim_pass": result.get("sim_pass", False),
                "synth_pass": result.get("synth_pass", False),
            }
            row.update(config)
            if result.get("synth_pass", False):
                for key in ["latency_ns", "luts", "ffs", "dsps", "brams",
                            "power_mw", "composite_area"]:
                    row[key] = result[key]
            all_rows.append(row)
            csv_keys.update(row.keys())

        # Pareto front
        if synth_results:
            pareto_indices = compute_pareto_front(synth_results)
            pareto_points = []
            for pi in pareto_indices:
                r = synth_results[pi]
                diff = compute_differential_ppa(r, reference)
                pareto_points.append({
                    "config": r["config"],
                    "latency_ns": r["latency_ns"],
                    "luts": r["luts"],
                    "ffs": r["ffs"],
                    "dsps": r["dsps"],
                    "brams": r["brams"],
                    "power_mw": r["power_mw"],
                    "composite_area": r["composite_area"],
                    "differential_ppa": diff,
                })
        else:
            pareto_points = []

        all_pareto_fronts[name] = {
            "num_pareto_points": len(pareto_points),
            "pareto_points": pareto_points,
        }

        # Pass@K
        pass_at_k = {
            "n_total": n_total,
            "n_compile": n_compile,
            "n_sim": n_sim,
            "n_synth": n_synth,
        }
        for k in [1, 5, 10]:
            pass_at_k[f"compile_pass_at_{k}"] = round(
                compute_pass_at_k(n_total, n_compile, k), 6
            )
            pass_at_k[f"sim_pass_at_{k}"] = round(
                compute_pass_at_k(n_total, n_sim, k), 6
            )
            pass_at_k[f"synth_pass_at_{k}"] = round(
                compute_pass_at_k(n_total, n_synth, k), 6
            )
        all_pass_at_k[name] = pass_at_k

        # DSE improvement summary
        best_improvements = {
            "latency_ns": 0.0,
            "luts": 0.0,
            "ffs": 0.0,
            "power_mw": 0.0,
        }
        has_improvement = False

        for pp in pareto_points:
            diff = pp["differential_ppa"]
            for metric in best_improvements:
                if diff[metric] < best_improvements[metric]:
                    best_improvements[metric] = diff[metric]
            if any(diff[m] < -20.0 for m in diff):
                has_improvement = True

        all_dse_summary[name] = {
            "n_total_configs": n_total,
            "n_synthesizable": n_synth,
            "n_pareto_points": len(pareto_points),
            "dse_improvement_gt_20pct": has_improvement,
            "best_improvements_pct": {
                k: round(v, 4) for k, v in best_improvements.items()
            },
        }

    # Write outputs
    with open("/app/output/pareto_fronts.json", "w") as f:
        json.dump(all_pareto_fronts, f, indent=2)

    with open("/app/output/pass_at_k.json", "w") as f:
        json.dump(all_pass_at_k, f, indent=2)

    with open("/app/output/dse_summary.json", "w") as f:
        json.dump(all_dse_summary, f, indent=2)

    fieldnames = sorted(csv_keys)
    with open("/app/output/full_results.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames,
                                extrasaction="ignore",
                                restval="")
        writer.writeheader()
        for row in all_rows:
            writer.writerow(row)

    print(f"DSE analysis complete.")
    print(f"Total designs: {len(designs)}")
    print(f"Configurations per design: {len(configs)}")
    for name in all_dse_summary:
        s = all_dse_summary[name]
        pk = all_pass_at_k[name]
        print(
            f"  {name}: "
            f"{s['n_synthesizable']}/{s['n_total_configs']} synthesizable, "
            f"{s['n_pareto_points']} Pareto points, "
            f"DSE>20%: {s['dse_improvement_gt_20pct']}, "
            f"sim_pass@10: {pk['sim_pass_at_10']:.4f}"
        )


if __name__ == "__main__":
    main()
