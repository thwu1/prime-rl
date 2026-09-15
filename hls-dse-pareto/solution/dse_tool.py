#!/usr/bin/env python3
"""HLS Design Space Exploration CLI Tool."""

import argparse
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


def load_dse_space():
    with open("/app/dse_space.yaml") as f:
        return yaml.safe_load(f)


def expand_configs(space):
    keys = list(space.keys())
    values = [space[k] for k in keys]
    return [dict(zip(keys, combo)) for combo in itertools.product(*values)]


def load_designs():
    designs = []
    design_dir = Path("/app/designs")
    for f in sorted(design_dir.glob("*.json")):
        with open(f) as fh:
            designs.append(json.load(fh))
    return designs


# ---------- Mode: evaluate ----------

def mode_evaluate():
    """Evaluate all configurations against all designs."""
    os.makedirs("/app/output", exist_ok=True)

    space = load_dse_space()
    configs = expand_configs(space)
    designs = load_designs()

    all_results = {}
    all_rows = []
    csv_keys = set()

    for design in designs:
        name = design["name"]
        design_results = []

        for idx, config in enumerate(configs):
            result = evaluate_config(design, config)
            design_results.append(result)

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

        all_results[name] = design_results

    # Write CSV
    fieldnames = sorted(csv_keys)
    with open("/app/output/full_results.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames,
                                extrasaction="ignore", restval="")
        writer.writeheader()
        for row in all_rows:
            writer.writerow(row)

    # Write intermediate cache for other modes
    cache = {}
    for name, results in all_results.items():
        cache[name] = []
        for r in results:
            entry = {
                "compile_pass": r["compile_pass"],
                "sim_pass": r.get("sim_pass", False),
                "synth_pass": r.get("synth_pass", False),
            }
            if r.get("synth_pass", False):
                for k in ["latency_ns", "luts", "ffs", "dsps", "brams",
                          "power_mw", "composite_area", "config"]:
                    entry[k] = r[k]
            cache[name].append(entry)

    with open("/app/output/_eval_cache.json", "w") as f:
        json.dump(cache, f)

    print(f"Evaluated {len(configs)} configs x {len(designs)} designs")


# ---------- Mode: optimize ----------

def find_non_dominated(results):
    """Find non-dominated set for 3 objectives (minimization)."""
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


def mode_optimize():
    """Compute non-dominated sets and differential PPA."""
    with open("/app/output/_eval_cache.json") as f:
        cache = json.load(f)

    designs = load_designs()
    design_map = {d["name"]: d for d in designs}

    all_pareto = {}
    for name, results in cache.items():
        reference = design_map[name]["reference_ppa"]
        synth = [r for r in results if r["synth_pass"]]

        if synth:
            indices = find_non_dominated(synth)
            points = []
            for idx in indices:
                r = synth[idx]
                diff = compute_differential_ppa(r, reference)
                points.append({
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
            points = []

        all_pareto[name] = {
            "num_pareto_points": len(points),
            "pareto_points": points,
        }

    with open("/app/output/pareto_fronts.json", "w") as f:
        json.dump(all_pareto, f, indent=2)

    print(f"Computed non-dominated sets for {len(all_pareto)} designs")


# ---------- Mode: statistics ----------

def compute_sampling_probability(n, c, k):
    """Probability of sampling at least one success in K draws
    without replacement from a population of n with c successes.
    Computed in log-space for numerical stability."""
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


def mode_statistics():
    """Compute stage pass counts and sampling probabilities."""
    with open("/app/output/_eval_cache.json") as f:
        cache = json.load(f)

    all_stats = {}
    for name, results in cache.items():
        n_total = len(results)
        n_compile = sum(1 for r in results if r["compile_pass"])
        n_sim = sum(1 for r in results if r["sim_pass"])
        n_synth = sum(1 for r in results if r["synth_pass"])

        stats = {
            "n_total": n_total,
            "n_compile": n_compile,
            "n_sim": n_sim,
            "n_synth": n_synth,
        }

        for k in [1, 5, 10]:
            stats[f"compile_pass_at_{k}"] = round(
                compute_sampling_probability(n_total, n_compile, k), 6)
            stats[f"sim_pass_at_{k}"] = round(
                compute_sampling_probability(n_total, n_sim, k), 6)
            stats[f"synth_pass_at_{k}"] = round(
                compute_sampling_probability(n_total, n_synth, k), 6)

        all_stats[name] = stats

    with open("/app/output/pass_at_k.json", "w") as f:
        json.dump(all_stats, f, indent=2)

    print(f"Computed statistics for {len(all_stats)} designs")


# ---------- Mode: report ----------

def hypervolume_2d(points, ref_x, ref_y):
    """Compute 2D hypervolume for minimization objectives."""
    pts = [(x, y) for (x, y) in points if x < ref_x and y < ref_y]
    if not pts:
        return 0.0
    pts.sort(key=lambda p: p[0])
    front = []
    min_y = float('inf')
    for p in pts:
        if p[1] < min_y:
            front.append(p)
            min_y = p[1]
    area = 0.0
    for i, (x, y) in enumerate(front):
        x_next = front[i + 1][0] if i + 1 < len(front) else ref_x
        area += (x_next - x) * (ref_y - y)
    return area


def hypervolume_3d(points, ref):
    """Compute exact 3D hypervolume via z-coordinate sweep.
    points: list of (x, y, z) tuples (all minimization objectives)
    ref: (rx, ry, rz) reference point bounding the objective space
    """
    pts = [(x, y, z) for (x, y, z) in points
           if x < ref[0] and y < ref[1] and z < ref[2]]
    if not pts:
        return 0.0
    pts.sort(key=lambda p: p[2])
    vol = 0.0
    active = []
    for i, p in enumerate(pts):
        active.append((p[0], p[1]))
        z_next = pts[i + 1][2] if i + 1 < len(pts) else ref[2]
        dz = z_next - p[2]
        if dz > 0:
            vol += dz * hypervolume_2d(active, ref[0], ref[1])
    return vol


def mode_report():
    """Generate DSE summary with hypervolume indicators."""
    with open("/app/output/_eval_cache.json") as f:
        cache = json.load(f)
    with open("/app/output/pareto_fronts.json") as f:
        pareto = json.load(f)
    with open("/app/output/pass_at_k.json") as f:
        stats = json.load(f)

    designs = load_designs()
    design_map = {d["name"]: d for d in designs}

    summary = {}
    for name in cache:
        results = cache[name]
        synth = [r for r in results if r["synth_pass"]]
        n_synth = len(synth)

        pf = pareto[name]
        pk = stats[name]

        # Compute hypervolume
        if synth and pf["pareto_points"]:
            max_lat = max(r["latency_ns"] for r in synth) * 1.1
            max_area = max(r["composite_area"] for r in synth) * 1.1
            max_power = max(r["power_mw"] for r in synth) * 1.1

            pareto_pts = [
                (pp["latency_ns"], float(pp["composite_area"]), pp["power_mw"])
                for pp in pf["pareto_points"]
            ]
            hv = hypervolume_3d(pareto_pts, (max_lat, max_area, max_power))
        else:
            hv = 0.0

        # Check improvements
        best_improvements = {
            "latency_ns": 0.0, "luts": 0.0, "ffs": 0.0, "power_mw": 0.0
        }
        has_improvement = False

        for pp in pf["pareto_points"]:
            diff = pp["differential_ppa"]
            for metric in best_improvements:
                if diff[metric] < best_improvements[metric]:
                    best_improvements[metric] = diff[metric]
            if any(diff[m] < -20.0 for m in diff):
                has_improvement = True

        summary[name] = {
            "n_total_configs": pk["n_total"],
            "n_synthesizable": n_synth,
            "n_pareto_points": pf["num_pareto_points"],
            "hypervolume": round(hv, 4),
            "dse_improvement_gt_20pct": has_improvement,
            "best_improvements_pct": {
                k: round(v, 4) for k, v in best_improvements.items()
            },
        }

    with open("/app/output/dse_summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    print(f"Generated summary for {len(summary)} designs")


# ---------- Main ----------

def main():
    parser = argparse.ArgumentParser(description="HLS DSE Analysis Tool")
    parser.add_argument("--mode", required=True,
                        choices=["evaluate", "optimize", "statistics", "report"],
                        help="Analysis mode to run")
    args = parser.parse_args()

    modes = {
        "evaluate": mode_evaluate,
        "optimize": mode_optimize,
        "statistics": mode_statistics,
        "report": mode_report,
    }

    modes[args.mode]()


if __name__ == "__main__":
    main()
