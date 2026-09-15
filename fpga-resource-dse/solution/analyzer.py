
"""
FPGA Design Space Exploration Engine
Analyzes FPGA synthesis results: Pareto frontiers, weighted cost rankings,
hypervolume indicators, and per-model summary statistics.
"""

import json

DIMS = ["LUT", "FF", "DSP", "BRAM"]


def load_data():
    with open("/app/solutions_data.json") as f:
        solutions = json.load(f)
    with open("/app/resource_weights.json") as f:
        weights = json.load(f)
    return solutions, weights


def is_passing(sol):
    p = sol.get("pass", "")
    if not isinstance(p, str):
        return False
    return p.strip().lower() == "true"


def has_valid_resources(sol):
    ru = sol.get("resource usage", {})
    opt = ru.get("optimized", {})
    for key in DIMS:
        val = opt.get(key)
        if val is None or not isinstance(val, (int, float)):
            return False
    return True


def get_resources(sol):
    opt = sol["resource usage"]["optimized"]
    return {k: int(opt[k]) for k in DIMS}


def weighted_cost(res, weights):
    return sum(res[k] * weights[k] for k in DIMS)


def dominates(a, b):
    """True if a dominates b: a <= b on all dims, a < b on at least one."""
    strict = False
    for k in DIMS:
        if a[k] > b[k]:
            return False
        if a[k] < b[k]:
            strict = True
    return strict


def compute_pareto_frontier(solutions):
    """Returns indices of Pareto-optimal solutions."""
    n = len(solutions)
    is_pareto = [True] * n
    for i in range(n):
        if not is_pareto[i]:
            continue
        for j in range(n):
            if i == j:
                continue
            if dominates(solutions[j]["resources"], solutions[i]["resources"]):
                is_pareto[i] = False
                break
    return [i for i in range(n) if is_pareto[i]]


def compute_hypervolume(pareto_points, ref):
    """
    4D hypervolume via inclusion-exclusion over all non-empty subsets.
    pareto_points: list of dicts with LUT, FF, DSP, BRAM
    ref: dict with LUT, FF, DSP, BRAM (reference point)
    """
    n = len(pareto_points)
    if n == 0:
        return 0.0

    total = 0.0
    for mask in range(1, 1 << n):
        corner = {k: 0 for k in DIMS}
        subset_size = 0
        for i in range(n):
            if mask & (1 << i):
                subset_size += 1
                for k in DIMS:
                    corner[k] = max(corner[k], pareto_points[i][k])

        vol = 1.0
        for k in DIMS:
            vol *= max(0, ref[k] - corner[k])

        if subset_size % 2 == 1:
            total += vol
        else:
            total -= vol

    return total


def main():
    solutions_data, weights = load_data()

    # Collect all valid passing solutions per module
    module_solutions = {}

    for model_name, categories in solutions_data.items():
        for category_name, modules in categories.items():
            for module_entry in modules:
                module_name = module_entry["module"]
                if module_name not in module_solutions:
                    module_solutions[module_name] = []
                for sol_idx, sol in enumerate(module_entry["solutions"]):
                    if is_passing(sol) and has_valid_resources(sol):
                        res = get_resources(sol)
                        cost = weighted_cost(res, weights)
                        module_solutions[module_name].append({
                            "model": model_name,
                            "solution_index": sol_idx,
                            "resources": res,
                            "cost": cost,
                        })

    report = {"modules": {}, "model_summary": {}}

    # Per-module analysis
    module_best_costs = {}
    module_pareto_sets = {}

    for module_name in sorted(module_solutions.keys()):
        sols = module_solutions[module_name]

        # Pareto frontier
        pf_indices = compute_pareto_frontier(sols)
        pf_id_set = {
            (sols[i]["model"], sols[i]["solution_index"]) for i in pf_indices
        }
        module_pareto_sets[module_name] = pf_id_set

        # Rankings: sort by (cost, LUT, FF, model_name, solution_index)
        ranked = sorted(
            sols,
            key=lambda s: (
                s["cost"],
                s["resources"]["LUT"],
                s["resources"]["FF"],
                s["model"],
                s["solution_index"],
            ),
        )

        best_cost = ranked[0]["cost"] if ranked else 0.0
        worst_cost = ranked[-1]["cost"] if ranked else 0.0
        module_best_costs[module_name] = best_cost

        # Pareto frontier output (sorted by cost, LUT, model)
        pf_sols = [sols[i] for i in pf_indices]
        pf_sols_sorted = sorted(
            pf_sols,
            key=lambda s: (s["cost"], s["resources"]["LUT"], s["model"]),
        )

        # Hypervolume
        ref = {}
        for k in DIMS:
            ref[k] = max(s["resources"][k] for s in sols) + 1

        pf_resources = [sols[i]["resources"] for i in pf_indices]
        hv = compute_hypervolume(pf_resources, ref)

        # Build rankings list
        rankings = []
        for rank, s in enumerate(ranked, 1):
            is_pf = (s["model"], s["solution_index"]) in pf_id_set
            rankings.append({
                "rank": rank,
                "model": s["model"],
                "solution_index": s["solution_index"],
                "weighted_cost": s["cost"],
                "is_pareto": is_pf,
            })

        report["modules"][module_name] = {
            "total_passing": len(sols),
            "pareto_frontier_size": len(pf_indices),
            "pareto_frontier": [
                {
                    "model": s["model"],
                    "solution_index": s["solution_index"],
                    "LUT": s["resources"]["LUT"],
                    "FF": s["resources"]["FF"],
                    "DSP": s["resources"]["DSP"],
                    "BRAM": s["resources"]["BRAM"],
                    "weighted_cost": s["cost"],
                }
                for s in pf_sols_sorted
            ],
            "rankings": rankings,
            "best_cost": best_cost,
            "cost_spread": worst_cost - best_cost,
            "hypervolume": hv,
        }

    # Per-model summary
    model_stats = {}

    for module_name, sols in module_solutions.items():
        best_cost = module_best_costs[module_name]
        pf_id_set = module_pareto_sets[module_name]

        for s in sols:
            model = s["model"]
            if model not in model_stats:
                model_stats[model] = {
                    "costs": [],
                    "pareto_count": 0,
                    "nres": [],
                }
            model_stats[model]["costs"].append(s["cost"])
            nre = best_cost / s["cost"] if s["cost"] > 0 else 0.0
            model_stats[model]["nres"].append(nre)
            if (s["model"], s["solution_index"]) in pf_id_set:
                model_stats[model]["pareto_count"] += 1

    for model_name in sorted(model_stats.keys()):
        stats = model_stats[model_name]
        total = len(stats["costs"])
        report["model_summary"][model_name] = {
            "total_passing": total,
            "total_pareto": stats["pareto_count"],
            "pareto_fraction": (
                stats["pareto_count"] / total if total > 0 else 0.0
            ),
            "avg_weighted_cost": (
                sum(stats["costs"]) / total if total > 0 else 0.0
            ),
            "avg_nre": (
                sum(stats["nres"]) / total if total > 0 else 0.0
            ),
        }

    with open("/app/dse_report.json", "w") as f:
        json.dump(report, f, indent=2)


if __name__ == "__main__":
    main()
