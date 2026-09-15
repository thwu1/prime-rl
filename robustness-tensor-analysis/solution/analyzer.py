#!/usr/bin/env python3
"""REALM Robustness Meta-Analysis — reference implementation."""

import csv
import json
import math
import os

import numpy as np
import yaml

Z_95 = 1.959963984540054


def load_config():
    with open("/app/config/analysis.yaml") as f:
        return yaml.safe_load(f)


def load_taxonomy():
    with open("/app/config/taxonomy.json") as f:
        return json.load(f)


def load_data():
    """Load per-model CSV data into {model: {(p_id, t_id): info}}."""
    data = {}
    results_dir = "/app/data/results"
    for fname in sorted(os.listdir(results_dir)):
        if not fname.endswith(".csv"):
            continue
        model = fname[:-4]
        data[model] = {}
        with open(os.path.join(results_dir, fname)) as f:
            reader = csv.DictReader(f)
            for row in reader:
                p_id = int(row["perturbation_id"])
                t_id = int(row["task_id"])
                successes = int(row["successes"])
                total = int(row["total_rollouts"])
                data[model][(p_id, t_id)] = {
                    "successes": successes,
                    "total": total,
                    "rate": successes / total,
                    "perturbation_name": row["perturbation_name"],
                }
    return data


def wilson_ci(successes, total):
    n = total
    p_hat = successes / n
    z = Z_95
    denom = 1 + z ** 2 / n
    center = p_hat + z ** 2 / (2 * n)
    spread = z * math.sqrt(p_hat * (1 - p_hat) / n + z ** 2 / (4 * n ** 2))
    return (center - spread) / denom, (center + spread) / denom


def compute_wilson_intervals(data, models):
    result = {}
    for model in models:
        result[model] = {}
        for (p_id, t_id), info in data[model].items():
            p_key = str(p_id)
            t_key = str(t_id)
            if p_key not in result[model]:
                result[model][p_key] = {}
            lo, hi = wilson_ci(info["successes"], info["total"])
            result[model][p_key][t_key] = {
                "rate": info["rate"],
                "ci_lower": lo,
                "ci_upper": hi,
            }
    return result


def get_perturbation_names(data, models):
    """Extract ordered non-default perturbation names."""
    names = []
    for (p_id, t_id), info in sorted(data[models[0]].items()):
        if p_id > 0 and t_id == 0:
            names.append(info["perturbation_name"])
    return names


def compute_effect_matrix(data, models, perturbation_names, num_tasks):
    """Compute E[m,p] and return both dict and numpy array."""
    result = {}
    E = np.zeros((len(models), len(perturbation_names)))
    for m_idx, model in enumerate(models):
        result[model] = {}
        for p_idx, p_name in enumerate(perturbation_names):
            p_id = p_idx + 1
            effects = []
            for t in range(num_tasks):
                rate_p = data[model][(p_id, t)]["rate"]
                rate_d = data[model][(0, t)]["rate"]
                effects.append(rate_p - rate_d)
            e_val = sum(effects) / len(effects)
            result[model][p_name] = e_val
            E[m_idx, p_idx] = e_val
    return result, E


def compute_eigendecomposition(E, rank):
    EtE = E.T @ E
    eigenvalues, eigenvectors = np.linalg.eigh(EtE)
    idx = np.argsort(eigenvalues)[::-1]
    eigenvalues = eigenvalues[idx]
    eigenvectors = eigenvectors[:, idx]
    return {
        "eigenvalues": eigenvalues[:rank].tolist(),
        "eigenvectors": [eigenvectors[:, i].tolist() for i in range(rank)],
    }


def compute_category_robustness(effect_dict, models, taxonomy):
    all_categories = {}
    for cat, perts in taxonomy["categories"].items():
        all_categories[cat] = perts
    for cat, info in taxonomy["compound_categories"].items():
        all_categories[cat] = info["perturbations"]

    result = {}
    for model in models:
        result[model] = {}
        for cat, perts in all_categories.items():
            mean_e_sq = sum(effect_dict[model][p] ** 2 for p in perts) / len(perts)
            result[model][cat] = 1 - math.sqrt(mean_e_sq)

    return result, all_categories


def compute_interaction_strength(effect_dict, models, taxonomy):
    result = {}
    for comp_cat, info in taxonomy["compound_categories"].items():
        comp_perts = info["perturbations"]
        component_cats = info["components"]

        pis_per_model = []
        for model in models:
            mean_compound = sum(
                abs(effect_dict[model][p]) for p in comp_perts
            ) / len(comp_perts)

            sum_components = 0.0
            for c_name in component_cats:
                c_perts = taxonomy["categories"][c_name]
                mean_c = sum(
                    abs(effect_dict[model][p]) for p in c_perts
                ) / len(c_perts)
                sum_components += mean_c

            pis_per_model.append(mean_compound - sum_components)

        result[comp_cat] = sum(pis_per_model) / len(pis_per_model)

    return result


def compute_model_ranking(crs, models, all_categories):
    ranking = []
    for model in models:
        n = len(all_categories)
        h_mean = n / sum(1 / crs[model][c] for c in all_categories)
        ranking.append({"model": model, "score": h_mean})
    ranking.sort(key=lambda x: x["score"], reverse=True)
    return ranking


def compute_pairwise_tests(data, models, num_tasks, perturbation_names, config):
    rng = np.random.RandomState(config["random_seed"])
    B = config["bootstrap_samples"]

    result = {}
    for i in range(len(models)):
        for j in range(i + 1, len(models)):
            m1, m2 = models[i], models[j]

            d = []
            for p_idx in range(len(perturbation_names)):
                p_id = p_idx + 1
                for t in range(num_tasks):
                    eff1 = data[m1][(p_id, t)]["rate"] - data[m1][(0, t)]["rate"]
                    eff2 = data[m2][(p_id, t)]["rate"] - data[m2][(0, t)]["rate"]
                    d.append(eff1 - eff2)

            d = np.array(d)
            T_obs = float(np.mean(d))

            count = 0
            for _ in range(B):
                signs = rng.choice([-1, 1], size=len(d))
                T_perm = float(np.mean(d * signs))
                if abs(T_perm) >= abs(T_obs):
                    count += 1

            p_value = (1 + count) / (1 + B)

            result[f"{m1}_vs_{m2}"] = {
                "statistic": T_obs,
                "p_value": p_value,
            }

    return result


def main():
    config = load_config()
    taxonomy = load_taxonomy()
    data = load_data()

    models = sorted(data.keys())
    num_tasks = 10

    perturbation_names = get_perturbation_names(data, models)

    wilson = compute_wilson_intervals(data, models)
    effect_dict, E = compute_effect_matrix(data, models, perturbation_names, num_tasks)
    eigen = compute_eigendecomposition(E, config["decomposition_rank"])
    crs, all_categories = compute_category_robustness(effect_dict, models, taxonomy)
    interaction = compute_interaction_strength(effect_dict, models, taxonomy)
    ranking = compute_model_ranking(crs, models, all_categories)
    pairwise = compute_pairwise_tests(
        data, models, num_tasks, perturbation_names, config
    )

    report = {
        "wilson_intervals": wilson,
        "effect_matrix": effect_dict,
        "eigendecomposition": eigen,
        "category_robustness": crs,
        "interaction_strength": interaction,
        "model_ranking": ranking,
        "pairwise_tests": pairwise,
    }

    os.makedirs(os.path.dirname(config["output_path"]), exist_ok=True)
    with open(config["output_path"], "w") as f:
        json.dump(report, f, indent=2)


if __name__ == "__main__":
    main()
