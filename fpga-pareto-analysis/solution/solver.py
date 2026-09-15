#!/usr/bin/env python3
"""
FPGA Resource Efficiency Pareto Analysis
Processes the ResBench compact dataset and produces multi-objective design space analysis.
"""

import json
import os
import math
from itertools import combinations

SOLUTIONS_PATH = "/app/data/solutions_compact.json"
PROBLEMS_PATH = "/app/data/problems_compact.json"
RESULTS_DIR = "/app/results"

COST_WEIGHTS = {"LUT": 1.0, "FF": 0.5, "DSP": 10.0, "BRAM": 20.0, "IO": 0.2}
RESOURCE_KEYS = ["LUT", "FF", "DSP", "BRAM", "IO"]
PARETO_DIMS = ["LUT", "FF", "DSP", "BRAM"]


def load_data():
    with open(SOLUTIONS_PATH) as f:
        solutions = json.load(f)
    with open(PROBLEMS_PATH) as f:
        problems = json.load(f)
    return solutions, problems


def build_module_to_category(problems):
    mapping = {}
    for cat_name, module_names in problems.items():
        for mod_name in module_names:
            mapping[mod_name] = cat_name
    return mapping


def weighted_cost(ru):
    return sum(COST_WEIGHTS[k] * ru.get(k, 0) for k in RESOURCE_KEYS)


def has_valid_resources(sol):
    if not sol.get("pass"):
        return False
    r = sol.get("resources")
    if not r or not isinstance(r, dict):
        return False
    return all(isinstance(r.get(k), (int, float)) for k in RESOURCE_KEYS)


def dominates(a, b):
    """a dominates b if a <= b in all dims and a < b in at least one."""
    all_le = all(a[d] <= b[d] for d in PARETO_DIMS)
    any_lt = any(a[d] < b[d] for d in PARETO_DIMS)
    return all_le and any_lt


def compute_summary(data, module_to_category):
    summary = {}
    for llm in data:
        total = 0
        passing = 0
        passing_with_res = 0
        total_cost = 0.0
        category_stats = {}

        for cat in data[llm]:
            for mod_entry in data[llm][cat]:
                module_name = mod_entry["module"]
                real_cat = module_to_category.get(module_name, cat)

                if real_cat not in category_stats:
                    category_stats[real_cat] = {
                        "total": 0, "passing": 0,
                        "passing_with_resources": 0, "cost_sum": 0.0
                    }

                for sol in mod_entry.get("solutions", []):
                    total += 1
                    category_stats[real_cat]["total"] += 1

                    if sol.get("pass"):
                        passing += 1
                        category_stats[real_cat]["passing"] += 1

                        if has_valid_resources(sol):
                            ru = sol["resources"]
                            c = weighted_cost(ru)
                            passing_with_res += 1
                            total_cost += c
                            category_stats[real_cat]["passing_with_resources"] += 1
                            category_stats[real_cat]["cost_sum"] += c

        pass_rate = round(100.0 * passing / total, 2) if total > 0 else 0.0
        avg_cost = round(total_cost / passing_with_res, 2) if passing_with_res > 0 else None

        cats_out = {}
        for cat_name, cs in category_stats.items():
            cat_pr = round(100.0 * cs["passing"] / cs["total"], 2) if cs["total"] > 0 else 0.0
            cat_avg = round(cs["cost_sum"] / cs["passing_with_resources"], 2) if cs["passing_with_resources"] > 0 else None
            cats_out[cat_name] = {
                "total": cs["total"],
                "passing": cs["passing"],
                "passing_with_resources": cs["passing_with_resources"],
                "pass_rate": cat_pr,
                "avg_weighted_cost": cat_avg,
            }

        summary[llm] = {
            "total_solutions": total,
            "passing_solutions": passing,
            "passing_with_resources": passing_with_res,
            "pass_rate": pass_rate,
            "avg_weighted_cost": avg_cost,
            "categories": cats_out,
        }
    return summary


def collect_module_solutions(data):
    modules = {}
    for llm in data:
        for cat in data[llm]:
            for mod_entry in data[llm][cat]:
                mod_name = mod_entry["module"]
                if mod_name not in modules:
                    modules[mod_name] = []
                for sol in mod_entry.get("solutions", []):
                    if has_valid_resources(sol):
                        ru = sol["resources"]
                        modules[mod_name].append({
                            "LUT": ru["LUT"], "FF": ru["FF"],
                            "DSP": ru["DSP"], "BRAM": ru["BRAM"],
                            "IO": ru["IO"],
                        })
    return modules


def compute_pareto_fronts(modules):
    result = {}
    for mod_name, sols in modules.items():
        if not sols:
            continue

        # Deduplicate first by 4D resource tuple
        seen = {}
        for s in sols:
            key = (s["LUT"], s["FF"], s["DSP"], s["BRAM"])
            if key not in seen:
                seen[key] = s

        candidates = list(seen.values())

        # Find non-dominated solutions
        pareto = []
        for i, a in enumerate(candidates):
            if not any(dominates(candidates[j], a) for j in range(len(candidates)) if j != i):
                pareto.append({
                    "LUT": a["LUT"], "FF": a["FF"],
                    "DSP": a["DSP"], "BRAM": a["BRAM"],
                    "IO": a["IO"],
                    "weighted_cost": round(weighted_cost(a), 2),
                })

        pareto.sort(key=lambda x: x["weighted_cost"])
        result[mod_name] = pareto
    return result


def hypervolume_3d(points, ref):
    """Compute exact 3D hypervolume using inclusion-exclusion."""
    n = len(points)
    if n == 0:
        return 0

    total = 0
    for k in range(1, n + 1):
        sign = (-1) ** (k + 1)
        for combo in combinations(range(n), k):
            mx = max(points[i][0] for i in combo)
            my = max(points[i][1] for i in combo)
            mz = max(points[i][2] for i in combo)
            vol = max(0, ref[0] - mx) * max(0, ref[1] - my) * max(0, ref[2] - mz)
            total += sign * vol

    return total


def compute_hypervolumes(pareto_fronts):
    result = {}
    for mod_name, pts in pareto_fronts.items():
        n = len(pts)
        if n == 0:
            continue

        max_lut = max(p["LUT"] for p in pts)
        max_ff = max(p["FF"] for p in pts)
        max_dsp = max(p["DSP"] for p in pts)
        ref = [max_lut + 1, max_ff + 1, max_dsp + 1]

        points_3d = [(p["LUT"], p["FF"], p["DSP"]) for p in pts]
        hv = hypervolume_3d(points_3d, ref)

        result[mod_name] = {
            "hypervolume": hv,
            "reference_point": ref,
            "num_pareto_points": n,
        }
    return result


def compute_rankings(data, all_modules):
    llm_module_stats = {}
    for llm in data:
        llm_module_stats[llm] = {}
        for cat in data[llm]:
            for mod_entry in data[llm][cat]:
                module_name = mod_entry["module"]
                solutions = mod_entry.get("solutions", [])
                total = len(solutions)
                passing = sum(1 for s in solutions if s.get("pass"))
                costs = []
                for sol in solutions:
                    if has_valid_resources(sol):
                        costs.append(weighted_cost(sol["resources"]))

                llm_module_stats[llm][module_name] = {
                    "pass_rate": passing / total if total > 0 else 0.0,
                    "min_cost": min(costs) if costs else None,
                }

    scores = {}
    for llm in llm_module_stats:
        score = 0.0
        for mod_name in all_modules:
            stats = llm_module_stats[llm].get(mod_name, {})
            pr = stats.get("pass_rate", 0.0)
            mc = stats.get("min_cost")
            if mc is not None:
                efficiency = 1.0 / (1.0 + mc)
                score += pr * efficiency
        scores[llm] = score

    max_score = max(scores.values())
    return {llm: round(s / max_score, 4) for llm, s in scores.items()}


def kendall_tau_b(x, y):
    """Compute Kendall's tau-b rank correlation coefficient."""
    n = len(x)
    concordant = 0
    discordant = 0
    tied_x = 0
    tied_y = 0

    for i in range(n):
        for j in range(i + 1, n):
            dx = x[i] - x[j]
            dy = y[i] - y[j]
            if dx == 0 and dy == 0:
                pass  # tied on both, not counted
            elif dx == 0:
                tied_x += 1
            elif dy == 0:
                tied_y += 1
            elif (dx > 0 and dy > 0) or (dx < 0 and dy < 0):
                concordant += 1
            else:
                discordant += 1

    n_pairs = n * (n - 1) // 2
    denom = math.sqrt((n_pairs - tied_x) * (n_pairs - tied_y))
    if denom == 0:
        return 0.0
    return (concordant - discordant) / denom


def compute_correlations(data, all_modules):
    llm_costs = {}
    for llm in data:
        llm_costs[llm] = {}
        for cat in data[llm]:
            for mod_entry in data[llm][cat]:
                costs = []
                for sol in mod_entry.get("solutions", []):
                    if has_valid_resources(sol):
                        costs.append(weighted_cost(sol["resources"]))
                if costs:
                    llm_costs[llm][mod_entry["module"]] = min(costs)

    llms = sorted(data.keys())
    correlations = {}
    for l1, l2 in combinations(llms, 2):
        shared = sorted(set(llm_costs[l1].keys()) & set(llm_costs[l2].keys()))
        if len(shared) < 2:
            continue
        v1 = [llm_costs[l1][m] for m in shared]
        v2 = [llm_costs[l2][m] for m in shared]
        tau = kendall_tau_b(v1, v2)
        correlations[f"{l1}|{l2}"] = round(tau, 4)

    return correlations


def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)

    data, problems = load_data()
    module_to_category = build_module_to_category(problems)
    all_modules = set(module_to_category.keys())

    summary = compute_summary(data, module_to_category)
    with open(os.path.join(RESULTS_DIR, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)

    modules = collect_module_solutions(data)
    pareto_fronts = compute_pareto_fronts(modules)
    with open(os.path.join(RESULTS_DIR, "pareto_fronts.json"), "w") as f:
        json.dump(pareto_fronts, f, indent=2)

    hypervolumes = compute_hypervolumes(pareto_fronts)
    with open(os.path.join(RESULTS_DIR, "hypervolumes.json"), "w") as f:
        json.dump(hypervolumes, f, indent=2)

    rankings = compute_rankings(data, all_modules)
    with open(os.path.join(RESULTS_DIR, "rankings.json"), "w") as f:
        json.dump(rankings, f, indent=2)

    correlations = compute_correlations(data, all_modules)
    with open(os.path.join(RESULTS_DIR, "correlations.json"), "w") as f:
        json.dump(correlations, f, indent=2)

    print("Analysis complete. Results written to", RESULTS_DIR)


if __name__ == "__main__":
    main()
