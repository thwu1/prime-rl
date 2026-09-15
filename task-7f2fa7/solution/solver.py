#!/usr/bin/env python3
"""
HLS DSE Pareto Analysis Solver with Cross-Validation and Sensitivity.

Reads /app/data/synthesis_results.json and produces /app/output/analysis.json
with Pass@K metrics, Pareto fronts, hypervolume indicators, pymoo cross-validation,
ranking sensitivity analysis, and model rankings.
Also generates gnuplot Pareto front visualizations.
"""

import json
import math
import os
import subprocess

import numpy as np
from pymoo.indicators.hv import HV


def pass_at_k(n, c, k):
    """Unbiased estimator of pass@k (Chen et al., 2021)."""
    if n - c < k:
        return 1.0
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def dominates(a, b):
    """Does point a dominate point b? All objectives minimized."""
    return (
        a[0] <= b[0]
        and a[1] <= b[1]
        and a[2] <= b[2]
        and (a[0] < b[0] or a[1] < b[1] or a[2] < b[2])
    )


def compute_pareto_front(points):
    """Return the set of non-dominated points."""
    seen = set()
    unique = []
    for p in points:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    front = []
    for p in unique:
        if not any(dominates(q, p) for q in unique if q != p):
            front.append(p)
    return sorted(front, key=lambda x: x[0])


def hypervolume_2d(points, ref):
    """Compute 2D hypervolume for minimization objectives."""
    sorted_pts = sorted(points, key=lambda p: p[0])
    hv = 0.0
    prev_y = ref[1]
    for p in sorted_pts:
        if p[1] < prev_y:
            hv += (ref[0] - p[0]) * (prev_y - p[1])
            prev_y = p[1]
    return hv


def pareto_front_2d(points):
    """Compute 2D Pareto front (both minimize)."""
    seen = set()
    unique = []
    for p in points:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    front = []
    for p in unique:
        if not any(
            q[0] <= p[0] and q[1] <= p[1] and (q[0] < p[0] or q[1] < p[1])
            for q in unique
            if q != p
        ):
            front.append(p)
    return front


def hypervolume_3d(points, ref):
    """Compute 3D hypervolume using sweep-line / slicing algorithm."""
    if not points:
        return 0.0
    sorted_pts = sorted(points, key=lambda p: p[0])
    n = len(sorted_pts)
    hv = 0.0
    for i in range(n):
        if i + 1 < n:
            x_width = sorted_pts[i + 1][0] - sorted_pts[i][0]
        else:
            x_width = ref[0] - sorted_pts[i][0]
        proj = [(p[1], p[2]) for p in sorted_pts[: i + 1]]
        pf_2d = pareto_front_2d(proj)
        hv_2d = hypervolume_2d(pf_2d, (ref[1], ref[2]))
        hv += x_width * hv_2d
    return hv


def generate_gnuplot_plots(model, bench, front_points, plots_dir):
    """Generate gnuplot 3D scatter plot and data file for a Pareto front."""
    dat_file = os.path.join(plots_dir, f"pareto_{model}_{bench}.dat")
    gp_file = os.path.join(plots_dir, f"pareto_{model}_{bench}.gp")
    svg_file = os.path.join(plots_dir, f"pareto_{model}_{bench}.svg")

    with open(dat_file, "w") as f:
        f.write("# latency_ns area_luts power_mw\n")
        for pt in front_points:
            f.write(f"{pt['latency_ns']} {pt['area_luts']} {pt['power_mw']}\n")

    with open(gp_file, "w") as f:
        f.write(f"set terminal svg size 800,600\n")
        f.write(f"set output '{svg_file}'\n")
        f.write(f"set title 'Pareto Front: {model}/{bench}'\n")
        f.write("set xlabel 'Latency (ns)'\n")
        f.write("set ylabel 'Area (LUTs)'\n")
        f.write("set zlabel 'Power (mW)'\n")
        f.write("set grid\n")
        f.write(
            f"splot '{dat_file}' using 1:2:3 with points pt 7 ps 1.5"
            f" title 'Pareto-optimal'\n"
        )

    subprocess.run(["gnuplot", gp_file], check=True, capture_output=True)


def cross_validate_hypervolumes(pareto_fronts, hypervolumes, ref_point, models, benchmarks):
    """Cross-validate sweep-line hypervolumes against pymoo's HV indicator."""
    ref_array = np.array(ref_point, dtype=float)
    hv_validation = {}

    for model in models:
        hv_validation[model] = {}
        for bench in benchmarks:
            front_pts = [
                (p["latency_ns"], float(p["area_luts"]), p["power_mw"])
                for p in pareto_fronts[model][bench]
            ]
            if not front_pts:
                pymoo_hv = 0.0
            else:
                pts_array = np.array(front_pts, dtype=float)
                ind = HV(ref_point=ref_array)
                pymoo_hv = float(ind(pts_array))

            our_hv = hypervolumes[model][bench]
            abs_diff = abs(our_hv - pymoo_hv)
            rel_diff = abs_diff / our_hv if our_hv > 0 else 0.0

            hv_validation[model][bench] = {
                "sweep_line": our_hv,
                "pymoo": pymoo_hv,
                "abs_diff": abs_diff,
                "passed": rel_diff < 0.001,
            }
        hv_validation[model]["all_passed"] = all(
            v["passed"]
            for b, v in hv_validation[model].items()
            if b != "all_passed"
        )

    hv_validation["all_passed"] = all(
        v["all_passed"]
        for m, v in hv_validation.items()
        if m != "all_passed"
    )
    return hv_validation


def compute_ranking_sensitivity(pass_at_k_results, hypervolumes, ref_volume, models):
    """Sweep weight-space grid and compute ranking stability."""
    metrics = {}
    for model in models:
        metrics[model] = {
            "synth": pass_at_k_results[model]["1"]["synthesize"],
            "sim": pass_at_k_results[model]["1"]["simulate"],
            "hv_norm": hypervolumes[model]["average"] / ref_volume,
        }

    ranking_counts = {}
    total_combos = 0

    for w_s_int in range(1, 9):
        ws = w_s_int / 10.0
        for w_m_int in range(1, 10 - w_s_int):
            wm = w_m_int / 10.0
            wh = round(1.0 - ws - wm, 10)
            if wh < 0.1 - 1e-9:
                continue

            combo_scores = []
            for model in models:
                m = metrics[model]
                score = ws * m["synth"] + wm * m["sim"] + wh * m["hv_norm"]
                combo_scores.append((model, score))
            combo_scores.sort(key=lambda x: (-x[1], x[0]))
            ranking_key = ",".join(s[0] for s in combo_scores)
            ranking_counts[ranking_key] = ranking_counts.get(ranking_key, 0) + 1
            total_combos += 1

    dominant_ranking_key = max(ranking_counts, key=ranking_counts.get)
    stability_fraction = ranking_counts[dominant_ranking_key] / total_combos

    return {
        "grid_step": 0.1,
        "min_weight": 0.1,
        "total_combinations": total_combos,
        "ranking_counts": ranking_counts,
        "dominant_ranking": dominant_ranking_key.split(","),
        "stability_fraction": stability_fraction,
    }


def main():
    with open("/app/data/synthesis_results.json") as f:
        data = json.load(f)

    metadata = data["metadata"]
    models = metadata["models"]
    benchmarks = metadata["benchmarks"]
    constraints = metadata["constraints"]
    ref_point = tuple(metadata["reference_point"])
    max_dsps = constraints["max_dsps"]
    max_brams = constraints["max_brams"]
    eval_results = data["evaluation_results"]

    # 1. Compute Pass@K
    pass_at_k_results = {}
    for model in models:
        pass_at_k_results[model] = {}
        for k in [1, 5, 10]:
            pass_at_k_results[model][str(k)] = {}
            for stage in ["compile", "simulate", "synthesize"]:
                stage_key = {
                    "compile": "compile_pass",
                    "simulate": "sim_pass",
                    "synthesize": "synth_pass",
                }[stage]
                vals = []
                for bench in benchmarks:
                    bench_data = eval_results[model][bench]
                    n = bench_data["n_samples"]
                    c = bench_data[stage_key]
                    vals.append(pass_at_k(n, c, k))
                pass_at_k_results[model][str(k)][stage] = sum(vals) / len(vals)

    # 2. Compute Pareto Fronts (with constraint filtering)
    pareto_fronts = {}
    for model in models:
        pareto_fronts[model] = {}
        for bench in benchmarks:
            synth_results = eval_results[model][bench]["synthesis_results"]
            feasible = []
            for r in synth_results:
                if r["dsps"] <= max_dsps and r["brams"] <= max_brams:
                    feasible.append(
                        (r["latency_ns"], r["area_luts"], r["power_mw"])
                    )
            front = compute_pareto_front(feasible)
            pareto_fronts[model][bench] = [
                {
                    "latency_ns": p[0],
                    "area_luts": int(p[1]),
                    "power_mw": p[2],
                }
                for p in front
            ]

    # 3. Compute Hypervolumes (sweep-line)
    hypervolumes = {}
    for model in models:
        hypervolumes[model] = {}
        bench_hvs = []
        for bench in benchmarks:
            front_pts = [
                (p["latency_ns"], p["area_luts"], p["power_mw"])
                for p in pareto_fronts[model][bench]
            ]
            hv = hypervolume_3d(front_pts, ref_point)
            hypervolumes[model][bench] = hv
            bench_hvs.append(hv)
        hypervolumes[model]["average"] = sum(bench_hvs) / len(bench_hvs)

    # 4. Cross-validate hypervolumes with pymoo
    hv_validation = cross_validate_hypervolumes(
        pareto_fronts, hypervolumes, ref_point, models, benchmarks
    )

    # 5. Generate Pareto front visualizations with gnuplot
    plots_dir = "/app/output/plots"
    os.makedirs(plots_dir, exist_ok=True)
    for model in models:
        for bench in benchmarks:
            generate_gnuplot_plots(
                model, bench, pareto_fronts[model][bench], plots_dir
            )

    # 6. Compute Model Ranking
    ref_volume = ref_point[0] * ref_point[1] * ref_point[2]
    weights = metadata.get("ranking_weights", {})
    w_synth = weights.get("synthesis_pass_at_1", 0.5)
    w_sim = weights.get("simulation_pass_at_1", 0.3)
    w_hv = weights.get("normalized_hypervolume", 0.2)

    scores = []
    for model in models:
        avg_synth_p1 = pass_at_k_results[model]["1"]["synthesize"]
        avg_sim_p1 = pass_at_k_results[model]["1"]["simulate"]
        norm_hv = hypervolumes[model]["average"] / ref_volume
        composite = w_synth * avg_synth_p1 + w_sim * avg_sim_p1 + w_hv * norm_hv
        scores.append((model, composite))
    scores.sort(key=lambda x: (-x[1], x[0]))
    model_ranking = [
        {"model": m, "composite_score": s, "rank": i + 1}
        for i, (m, s) in enumerate(scores)
    ]

    # 7. Ranking Sensitivity Analysis
    ranking_sensitivity = compute_ranking_sensitivity(
        pass_at_k_results, hypervolumes, ref_volume, models
    )

    # Write output
    output = {
        "pass_at_k": pass_at_k_results,
        "pareto_fronts": pareto_fronts,
        "hypervolumes": hypervolumes,
        "hypervolume_validation": hv_validation,
        "model_ranking": model_ranking,
        "ranking_sensitivity": ranking_sensitivity,
    }

    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/analysis.json", "w") as f:
        json.dump(output, f, indent=2)

    print("Analysis complete. Output written to /app/output/analysis.json")


if __name__ == "__main__":
    main()
