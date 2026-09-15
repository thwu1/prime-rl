#!/usr/bin/env python3
"""Fix all bugs and implement missing stages in the robustness analysis pipeline."""

import os

# =============================================================================
# Fix 1: db.py — wrong column name in SQL query (success_count -> successes)
# =============================================================================
db_code = '''\
"""Database access layer for benchmark data."""
import sqlite3

DB_PATH = "/app/data/benchmark.db"


def get_connection():
    return sqlite3.connect(DB_PATH)


def load_model_data(model_name):
    """Load benchmark results for a model.
    Returns dict: (perturbation_id, task_id) -> successes
    """
    conn = get_connection()
    cursor = conn.execute(
        "SELECT perturbation_id, task_id, successes FROM results WHERE model = ?",
        (model_name,)
    )
    data = {}
    for row in cursor:
        data[(row[0], row[1])] = row[2]
    conn.close()
    return data


def get_models():
    """Get sorted list of all model names."""
    conn = get_connection()
    cursor = conn.execute("SELECT DISTINCT model FROM results ORDER BY model")
    models = [row[0] for row in cursor]
    conn.close()
    return models


def get_perturbation_names():
    """Get mapping of perturbation_id -> perturbation_name."""
    conn = get_connection()
    cursor = conn.execute(
        "SELECT DISTINCT perturbation_id, perturbation_name "
        "FROM results ORDER BY perturbation_id"
    )
    mapping = {row[0]: row[1] for row in cursor}
    conn.close()
    return mapping


def get_total_rollouts():
    """Get the number of rollouts per cell."""
    conn = get_connection()
    cursor = conn.execute("SELECT total_rollouts FROM results LIMIT 1")
    result = cursor.fetchone()[0]
    conn.close()
    return result
'''

with open("/app/pipeline/db.py", "w") as f:
    f.write(db_code)


# =============================================================================
# Fix 2: run.py — implement topological sort for stage dependencies
# =============================================================================
run_code = '''\
#!/usr/bin/env python3
"""Workflow runner for the robustness analysis pipeline."""
import importlib
import json
import os
import sys
import yaml
from collections import deque


def load_workflow(path="/app/config/workflow.yaml"):
    with open(path) as f:
        return yaml.safe_load(f)


def load_analysis_config(path="/app/config/analysis.yaml"):
    with open(path) as f:
        return yaml.safe_load(f)


def topological_sort(stages):
    """Sort stages respecting dependency order."""
    by_name = {s["name"]: s for s in stages}
    in_degree = {s["name"]: len(s.get("depends_on", [])) for s in stages}
    graph = {s["name"]: [] for s in stages}
    for s in stages:
        for dep in s.get("depends_on", []):
            graph[dep].append(s["name"])

    queue = deque(sorted(n for n, d in in_degree.items() if d == 0))
    result = []
    while queue:
        node = queue.popleft()
        result.append(by_name[node])
        for child in sorted(graph[node]):
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)
    return result


def run_pipeline():
    sys.path.insert(0, "/app/pipeline")

    workflow = load_workflow()
    analysis_config = load_analysis_config()
    with open("/app/config/taxonomy.json") as f:
        taxonomy = json.load(f)

    stages = workflow["stages"]
    stages_sorted = topological_sort(stages)

    results = {}
    for stage_def in stages_sorted:
        name = stage_def["name"]
        module_path = stage_def["module"]
        print(f"[pipeline] Running stage: {name}")

        mod = importlib.import_module(module_path)
        result = mod.run(results, analysis_config, taxonomy)
        results[name] = result
        print(f"[pipeline] Stage \\'{name}\\' complete.")

    # Assemble final report
    report = {}
    key_mapping = {
        "confidence": "wilson_intervals",
        "effects": "effect_matrix",
        "decomposition": "eigendecomposition",
        "robustness": "category_robustness",
        "interactions": "interaction_strength",
        "ranking": "model_ranking",
        "significance": "pairwise_tests"
    }
    for stage_name, output_key in key_mapping.items():
        if stage_name in results:
            report[output_key] = results[stage_name]

    output_path = workflow.get("output_path", "/app/output/report.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"[pipeline] Report written to {output_path}")


if __name__ == "__main__":
    run_pipeline()
'''

with open("/app/pipeline/run.py", "w") as f:
    f.write(run_code)


# =============================================================================
# Fix 3: confidence.py — fix Wilson CI denominator (z/n -> z**2/n)
# =============================================================================
confidence_code = '''\
"""Wilson score confidence intervals for benchmark success rates."""
import math
from db import load_model_data, get_models, get_total_rollouts

Z_95 = 1.959963984540054


def run(prior_results, config, taxonomy):
    """Compute Wilson score 95% CI for every (model, perturbation, task) cell."""
    models = get_models()
    total = get_total_rollouts()
    intervals = {}

    for model in models:
        data = load_model_data(model)
        intervals[model] = {}
        for (p_id, t_id), successes in data.items():
            p_key = str(p_id)
            t_key = str(t_id)
            if p_key not in intervals[model]:
                intervals[model][p_key] = {}

            n = total
            p_hat = successes / n
            z = Z_95
            denom = 1 + z ** 2 / n
            center = p_hat + z ** 2 / (2 * n)
            spread = z * math.sqrt(
                p_hat * (1 - p_hat) / n + z ** 2 / (4 * n ** 2)
            )
            ci_lower = (center - spread) / denom
            ci_upper = (center + spread) / denom

            intervals[model][p_key][t_key] = {
                "rate": p_hat,
                "ci_lower": ci_lower,
                "ci_upper": ci_upper
            }

    return intervals
'''

with open("/app/pipeline/stages/confidence.py", "w") as f:
    f.write(confidence_code)


# =============================================================================
# Fix 4: decomposition.py — fix matrix orientation (E@E.T -> E.T@E)
# =============================================================================
decomposition_code = '''\
"""Eigendecomposition of the perturbation effect covariance."""
import numpy as np
from db import get_models, get_perturbation_names


def run(prior_results, config, taxonomy):
    """Eigendecomposition of E^T @ E where E is the effect matrix."""
    effect_data = prior_results["effects"]
    models = sorted(effect_data.keys())
    p_names = get_perturbation_names()
    non_default = sorted(
        [n for pid, n in p_names.items() if pid != 0],
        key=lambda n: [pid for pid, nm in p_names.items() if nm == n][0]
    )

    k = config.get("decomposition_rank", 2)

    E = np.zeros((len(models), len(non_default)))
    for m_idx, model in enumerate(models):
        for p_idx, p_name in enumerate(non_default):
            E[m_idx, p_idx] = effect_data[model][p_name]

    M = E.T @ E

    eigenvalues, eigenvectors = np.linalg.eigh(M)

    idx = np.argsort(eigenvalues)[::-1]
    eigenvalues = eigenvalues[idx]
    eigenvectors = eigenvectors[:, idx]

    top_eigenvalues = eigenvalues[:k].tolist()
    top_eigenvectors = [eigenvectors[:, i].tolist() for i in range(k)]

    return {
        "eigenvalues": top_eigenvalues,
        "eigenvectors": top_eigenvectors
    }
'''

with open("/app/pipeline/stages/decomposition.py", "w") as f:
    f.write(decomposition_code)


# =============================================================================
# Fix 5: robustness.py — implement from scratch
# =============================================================================
robustness_code = '''\
"""Category-level robustness scoring."""
import math


def run(prior_results, config, taxonomy):
    """Compute CRS[m,c] = 1 - sqrt(mean(E[m,p]^2)) for each model and category."""
    effect_data = prior_results["effects"]

    # Collect all categories (base + compound)
    all_categories = {}
    for cat, perts in taxonomy["categories"].items():
        all_categories[cat] = perts
    for cat, info in taxonomy["compound_categories"].items():
        all_categories[cat] = info["perturbations"]

    robustness = {}
    for model, effects in effect_data.items():
        robustness[model] = {}
        for cat, perts in all_categories.items():
            e_sq = [effects[p] ** 2 for p in perts]
            crs = 1 - math.sqrt(sum(e_sq) / len(e_sq))
            robustness[model][cat] = crs

    return robustness
'''

with open("/app/pipeline/stages/robustness.py", "w") as f:
    f.write(robustness_code)


# =============================================================================
# Fix 6: interactions.py — implement from scratch
# =============================================================================
interactions_code = '''\
"""Perturbation interaction strength analysis."""


def run(prior_results, config, taxonomy):
    """Compute PIS for each compound category.

    PIS = mean_over_models(
        mean(|E[m,p]| for p in compound) -
        sum_c_i(mean(|E[m,p]| for p in base_cat_c_i))
    )
    """
    effect_data = prior_results["effects"]
    models = sorted(effect_data.keys())

    results = {}
    for cat_name, cat_info in taxonomy["compound_categories"].items():
        compound_perts = cat_info["perturbations"]
        component_cats = cat_info["components"]

        pis_per_model = []
        for model in models:
            effects = effect_data[model]

            # Mean absolute effect of compound perturbations
            compound_abs = [abs(effects[p]) for p in compound_perts]
            mean_compound = sum(compound_abs) / len(compound_abs)

            # Sum of mean absolute effects of component categories
            sum_components = 0
            for comp_cat in component_cats:
                comp_perts = taxonomy["categories"][comp_cat]
                comp_abs = [abs(effects[p]) for p in comp_perts]
                sum_components += sum(comp_abs) / len(comp_abs)

            pis_per_model.append(mean_compound - sum_components)

        results[cat_name] = sum(pis_per_model) / len(pis_per_model)

    return results
'''

with open("/app/pipeline/stages/interactions.py", "w") as f:
    f.write(interactions_code)


# =============================================================================
# Fix 7: ranking.py — fix arithmetic mean -> harmonic mean
# =============================================================================
ranking_code = '''\
"""Model ranking by aggregate robustness."""


def run(prior_results, config, taxonomy):
    """Rank models by harmonic mean of category robustness scores."""
    robustness = prior_results["robustness"]

    ranking = []
    for model, categories in robustness.items():
        scores = list(categories.values())
        n = len(scores)
        harmonic_mean = n / sum(1.0 / s for s in scores)
        ranking.append({"model": model, "score": harmonic_mean})

    ranking.sort(key=lambda x: x["score"], reverse=True)
    return ranking
'''

with open("/app/pipeline/stages/ranking.py", "w") as f:
    f.write(ranking_code)


# =============================================================================
# Fix 8: significance.py — fix config key (seed -> random_seed)
# =============================================================================
significance_code = '''\
"""Pairwise permutation significance tests."""
import numpy as np
from db import load_model_data, get_models, get_total_rollouts, get_perturbation_names


def run(prior_results, config, taxonomy):
    """Paired sign-flip permutation test for each model pair."""
    models = sorted(get_models())
    total = get_total_rollouts()
    p_names = get_perturbation_names()
    non_default_pids = sorted([pid for pid in p_names.keys() if pid != 0])

    B = config.get("bootstrap_samples", 10000)
    seed = config["random_seed"]

    sample_data = load_model_data(models[0])
    task_ids = sorted(set(t for (_, t) in sample_data.keys()))

    all_data = {m: load_model_data(m) for m in models}

    results = {}
    for i in range(len(models)):
        for j in range(i + 1, len(models)):
            m1, m2 = models[i], models[j]

            d = []
            for p_id in non_default_pids:
                for t_id in task_ids:
                    eff1 = (all_data[m1][(p_id, t_id)] - all_data[m1][(0, t_id)]) / total
                    eff2 = (all_data[m2][(p_id, t_id)] - all_data[m2][(0, t_id)]) / total
                    d.append(eff1 - eff2)

            d = np.array(d)
            T_obs = np.mean(d)

            rng = np.random.RandomState(seed)
            count = 0
            for _ in range(B):
                signs = rng.choice([-1, 1], size=len(d))
                T_perm = np.mean(d * signs)
                if abs(T_perm) >= abs(T_obs):
                    count += 1

            p_value = (1 + count) / (1 + B)

            key = f"{m1}_vs_{m2}"
            results[key] = {
                "statistic": float(T_obs),
                "p_value": float(p_value)
            }

    return results
'''

with open("/app/pipeline/stages/significance.py", "w") as f:
    f.write(significance_code)


print("All pipeline fixes applied successfully.")
