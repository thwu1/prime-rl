#!/usr/bin/env python3
"""HLS Model Evaluation Analysis Pipeline.

Processes synthesis benchmark data and produces a multi-objective analysis report
covering pass-rate estimation, Pareto front identification, hypervolume coverage,
and model ranking.
"""
import json
import os


def pass_at_k(n, c, k):
    """Compute pass@k metric: probability of at least one correct in k samples."""
    if c == n:
        return 1.0
    return 1.0 - ((n - c) / n) ** k


def is_dominated(point, others):
    """Check if a point is dominated by any point in others (all objectives minimized)."""
    for q in others:
        if q == point:
            continue
        if all(q[i] <= point[i] for i in range(3)) and any(q[i] < point[i] for i in range(3)):
            return True
    return False


def pareto_front(points):
    """Extract non-dominated points and sort by first objective."""
    unique = list(set(points))
    front = [p for p in unique if not is_dominated(p, unique)]
    return sorted(front, key=lambda x: x[0])


def hypervolume_3d(front_points, reference):
    """Compute the 3D hypervolume indicator bounded by reference point."""
    if not front_points:
        return 0.0
    total = 0.0
    for p in front_points:
        vol = 1.0
        for i in range(3):
            vol *= (reference[i] - p[i])
        total += vol
    return total


def main():
    with open("/app/data/synthesis_results.json") as f:
        data = json.load(f)

    meta = data["metadata"]
    models = meta["models"]
    benchmarks = meta["benchmarks"]
    ref_point = meta["reference_point"]
    eval_data = data["evaluation_results"]

    # --- Pass@K Metrics ---
    pass_at_k_results = {}
    for model in models:
        pass_at_k_results[model] = {}
        for k_val in [1, 5, 10]:
            pass_at_k_results[model][str(k_val)] = {}
            for stage, key in [("compile", "compile_pass"),
                               ("simulate", "sim_pass"),
                               ("synthesize", "synth_pass")]:
                per_bench = []
                for bench in benchmarks:
                    bd = eval_data[model][bench]
                    per_bench.append(pass_at_k(bd["n_samples"], bd[key], k_val))
                pass_at_k_results[model][str(k_val)][stage] = sum(per_bench) / len(per_bench)

    # --- Pareto Fronts ---
    pareto_fronts = {}
    for model in models:
        pareto_fronts[model] = {}
        for bench in benchmarks:
            synth_results = eval_data[model][bench]["synthesis_results"]
            design_points = [
                (r["latency_ns"], r["area_luts"], r["power_mw"])
                for r in synth_results
            ]
            front = pareto_front(design_points)
            pareto_fronts[model][bench] = [
                {"latency_ns": p[0], "area_luts": int(p[1]), "power_mw": p[2]}
                for p in front
            ]

    # --- Hypervolume Indicator ---
    hypervolumes = {}
    for model in models:
        hypervolumes[model] = {}
        bench_hvs = []
        for bench in benchmarks:
            pts = [
                (p["latency_ns"], p["area_luts"], p["power_mw"])
                for p in pareto_fronts[model][bench]
            ]
            hv = hypervolume_3d(pts, ref_point)
            hypervolumes[model][bench] = hv
            bench_hvs.append(hv)
        hypervolumes[model]["average"] = sum(bench_hvs) / len(bench_hvs)

    # --- Model Ranking ---
    weights = meta.get("ranking_weights", {})
    w_synth = weights.get("synthesis_pass_at_1", 0.5)
    w_sim = weights.get("simulation_pass_at_1", 0.3)
    w_hv = weights.get("normalized_hypervolume", 0.2)
    ref_volume = ref_point[0] * ref_point[1] * ref_point[2]

    ranking_entries = []
    for model in models:
        score = (w_synth * pass_at_k_results[model]["1"]["synthesize"] +
                 w_sim * pass_at_k_results[model]["1"]["simulate"] +
                 w_hv * (hypervolumes[model]["average"] / ref_volume))
        ranking_entries.append({"model": model, "composite_score": score})

    ranking_entries.sort(key=lambda x: -x["composite_score"])
    for i, entry in enumerate(ranking_entries):
        entry["rank"] = i + 1

    # --- Write Output ---
    output = {
        "pass_at_k": pass_at_k_results,
        "pareto_fronts": pareto_fronts,
        "hypervolumes": hypervolumes,
        "model_ranking": ranking_entries,
    }

    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/analysis.json", "w") as f:
        json.dump(output, f, indent=2)

    print("Analysis written to /app/output/analysis.json")


if __name__ == "__main__":
    main()
