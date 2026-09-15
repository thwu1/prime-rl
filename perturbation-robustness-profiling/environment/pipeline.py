#!/usr/bin/env python3
"""Analysis pipeline for robotics manipulation experiment data.

Reads simulation rollout data from experiment.db and real-world
validation data from CSV files. Produces analysis results in /app/results/.
"""

import csv
import json
import math
import os
import random
import sqlite3
from itertools import combinations


DB_PATH = "/app/experiment.db"
REAL_DIR = "/app/real_validation"
OUT_DIR = "/app/results"


def get_db():
    return sqlite3.connect(DB_PATH)


def load_sim_data():
    """Load simulation rollout data from SQLite database."""
    conn = get_db()
    cur = conn.cursor()

    models = [r[0] for r in cur.execute(
        "SELECT name FROM models ORDER BY id")]
    tasks = [r[0] for r in cur.execute(
        "SELECT name FROM tasks ORDER BY id")]
    perturbations = [r[0] for r in cur.execute(
        "SELECT name FROM perturbations ORDER BY id")]

    categories = {}
    for name, cat in cur.execute(
            "SELECT name, category FROM perturbations "
            "WHERE category != 'baseline' ORDER BY id"):
        categories.setdefault(cat, []).append(name)

    combined_components = {}
    for row in cur.execute("""
        SELECT p.name, cc.component_category
        FROM combined_components cc
        JOIN perturbations p ON cc.perturbation_id = p.id
        ORDER BY p.id
    """):
        combined_components.setdefault(row[0], []).append(row[1])

    rollouts = {}
    for model in models:
        rollouts[model] = {}
        for task in tasks:
            rollouts[model][task] = {}
            for pert in perturbations:
                outcomes = [r[0] for r in cur.execute("""
                    SELECT sr.success FROM sim_rollouts sr
                    JOIN models m ON sr.model_id = m.id
                    JOIN tasks t ON sr.task_id = t.id
                    JOIN perturbations p ON sr.perturbation_id = p.id
                    WHERE m.name = ? AND t.name = ? AND p.name = ?
                    ORDER BY sr.rollout_num
                """, (model, task, pert))]
                rollouts[model][task][pert] = outcomes

    conn.close()
    return models, tasks, perturbations, categories, combined_components, rollouts


def load_real_data():
    """Load real-world validation data from CSV files."""
    conn = get_db()
    cur = conn.cursor()
    models = [r[0] for r in cur.execute(
        "SELECT name FROM models ORDER BY id")]
    conn.close()

    real_data = {}
    real_tasks = set()
    real_perts = set()

    for model in models:
        csv_path = os.path.join(REAL_DIR, f"{model}.csv")
        if not os.path.exists(csv_path):
            continue
        with open(csv_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                task = row["task"]
                pert = row["perturbation"]
                success = int(row["success"])
                real_tasks.add(task)
                real_perts.add(pert)
                (real_data
                 .setdefault(model, {})
                 .setdefault(task, {})
                 .setdefault(pert, [])
                 .append(success))

    return sorted(real_tasks), sorted(real_perts), real_data


# ── Analysis 1: Success rates with confidence intervals ──────────────────

def binomial_ci(k, n, z=1.96):
    """Confidence interval for a binomial proportion."""
    if n == 0:
        return 0.0, 0.0, 0.0
    p = k / n
    margin = z * math.sqrt(p * (1 - p) / n)
    return p, max(0.0, p - margin), min(1.0, p + margin)


def compute_success_rates(models, tasks, perturbations, rollouts):
    results = {}
    for model in models:
        results[model] = {}
        for pert in perturbations:
            all_outcomes = []
            for task in tasks:
                all_outcomes.extend(rollouts[model][task][pert])
            n = len(all_outcomes)
            k = sum(all_outcomes)
            rate, ci_lo, ci_hi = binomial_ci(k, n)
            results[model][pert] = {
                "success_rate": round(rate, 6),
                "ci_lower": round(ci_lo, 6),
                "ci_upper": round(ci_hi, 6),
                "n_trials": n,
                "n_successes": k
            }
    return results


# ── Analysis 2: Sensitivity decomposition by category ────────────────────

def compute_sensitivity(models, categories, success_rates):
    results = {}
    for model in models:
        default_rate = success_rates[model]["default"]["success_rate"]
        results[model] = {}
        for cat_name, cat_perts in categories.items():
            per_pert = {}
            for pert in cat_perts:
                per_pert[pert] = round(
                    default_rate - success_rates[model][pert]["success_rate"], 6)
            degs = list(per_pert.values())
            results[model][cat_name] = {
                "mean_degradation": round(sum(degs) / len(degs), 6),
                "per_perturbation": per_pert
            }
    return results


# ── Analysis 3: Simulation-to-real rank correlation ──────────────────────

def rank_correlation(x, y):
    """Rank correlation between two vectors."""
    n = len(x)
    if n < 2:
        return 0.0
    concordant = 0
    discordant = 0
    for i in range(n):
        for j in range(i + 1, n):
            dx = x[i] - x[j]
            dy = y[i] - y[j]
            if dx * dy > 0:
                concordant += 1
            elif dx * dy < 0:
                discordant += 1
    n_pairs = n * (n - 1) / 2.0
    return (concordant - discordant) / n_pairs


def compute_correlation(models, tasks, perturbations, rollouts,
                        real_tasks, real_perts, real_data):
    sim_rates = []
    real_rates = []
    for model in models:
        if model not in real_data:
            continue
        for task in real_tasks:
            for pert in real_perts:
                sim_outcomes = rollouts[model][task][pert]
                real_outcomes = real_data[model][task][pert]
                sim_rates.append(sum(sim_outcomes) / len(sim_outcomes))
                real_rates.append(sum(real_outcomes) / len(real_outcomes))

    tau = rank_correlation(sim_rates, real_rates)

    random.seed(42)
    n = len(sim_rates)
    boot_taus = []
    for _ in range(1000):
        idx = [random.randint(0, n - 1) for _ in range(n)]
        bx = [sim_rates[i] for i in idx]
        by = [real_rates[i] for i in idx]
        boot_taus.append(rank_correlation(bx, by))
    boot_taus.sort()
    ci_lo = boot_taus[25]
    ci_hi = boot_taus[975]

    return {
        "kendall_tau_b": round(tau, 6),
        "bootstrap_ci_lower": round(ci_lo, 6),
        "bootstrap_ci_upper": round(ci_hi, 6),
        "n_conditions": n
    }


# ── Analysis 4: Interaction effects for combined perturbations ───────────

def compute_interactions(models, tasks, categories, combined_components,
                         success_rates, rollouts):
    results = {}
    for model in models:
        results[model] = {}
        default_rate = success_rates[model]["default"]["success_rate"]

        for comb_pert, components in combined_components.items():
            observed_deg = (default_rate
                            - success_rates[model][comb_pert]["success_rate"])

            expected_deg = 0.0
            for comp_cat in components:
                cat_perts = categories[comp_cat]
                cat_degs = [default_rate
                            - success_rates[model][p]["success_rate"]
                            for p in cat_perts]
                expected_deg += sum(cat_degs) / len(cat_degs)

            interaction = observed_deg - expected_deg

            all_default = []
            all_combined = []
            for task in tasks:
                all_default.extend(rollouts[model][task]["default"])
                all_combined.extend(rollouts[model][task][comb_pert])

            n_def = len(all_default)
            observed_diff = (sum(all_default) / n_def
                             - sum(all_combined) / len(all_combined))
            pooled = all_default + all_combined

            seed_val = (models.index(model) * 100
                        + list(combined_components.keys()).index(comb_pert))
            random.seed(seed_val)

            count_extreme = 0
            n_perms = 1000
            for _ in range(n_perms):
                random.shuffle(pooled)
                perm_def = pooled[:n_def]
                perm_comb = pooled[n_def:]
                perm_diff = (sum(perm_def) / len(perm_def)
                             - sum(perm_comb) / len(perm_comb))
                if perm_diff >= observed_diff:
                    count_extreme += 1

            p_value = count_extreme / n_perms

            results[model][comb_pert] = {
                "observed_degradation": round(observed_deg, 6),
                "expected_additive_degradation": round(expected_deg, 6),
                "interaction_effect": round(interaction, 6),
                "p_value": round(p_value, 6),
                "significant": p_value < 0.05,
                "component_categories": components
            }
    return results


# ── Analysis 5: Category importance attribution ─────────────────────────

def compute_importance(models, categories, success_rates):
    cat_names = list(categories.keys())
    n_cats = len(cat_names)

    results = {}
    for model in models:
        default_rate = success_rates[model]["default"]["success_rate"]

        def value_function(subset):
            if not subset:
                return 0.0
            cat_means = []
            for cat in subset:
                degs = [default_rate
                        - success_rates[model][p]["success_rate"]
                        for p in categories[cat]]
                cat_means.append(sum(degs) / len(degs))
            return sum(cat_means) / len(cat_means)

        shapley = {}
        for cat in cat_names:
            sv = 0.0
            others = [c for c in cat_names if c != cat]
            for size in range(len(others) + 1):
                for subset in combinations(others, size):
                    subset_list = list(subset)
                    with_i = value_function(subset_list + [cat])
                    without_i = value_function(subset_list)
                    marginal = with_i - without_i
                    weight = (math.factorial(len(subset_list))
                              * math.factorial(n_cats - len(subset_list) - 1)
                              ) / math.factorial(n_cats)
                    sv += weight * marginal
            shapley[cat] = round(sv, 6)

        total = value_function(cat_names)
        sv_sum = sum(shapley.values())

        results[model] = {
            "shapley_values": shapley,
            "total_degradation": round(total, 6),
            "shapley_sum": round(sv_sum, 6),
            "efficiency_check": round(abs(total - sv_sum), 8)
        }
    return results


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    (models, tasks, perturbations, categories,
     combined_components, rollouts) = load_sim_data()
    real_tasks, real_perts, real_data = load_real_data()

    sr = compute_success_rates(models, tasks, perturbations, rollouts)
    with open(os.path.join(OUT_DIR, "success_rates.json"), "w") as f:
        json.dump(sr, f, indent=2)

    sens = compute_sensitivity(models, categories, sr)
    with open(os.path.join(OUT_DIR, "sensitivity_decomposition.json"), "w") as f:
        json.dump(sens, f, indent=2)

    corr = compute_correlation(models, tasks, perturbations, rollouts,
                               real_tasks, real_perts, real_data)
    with open(os.path.join(OUT_DIR, "real_sim_correlation.json"), "w") as f:
        json.dump(corr, f, indent=2)

    inter = compute_interactions(models, tasks, categories,
                                combined_components, sr, rollouts)
    with open(os.path.join(OUT_DIR, "interactions.json"), "w") as f:
        json.dump(inter, f, indent=2)

    imp = compute_importance(models, categories, sr)
    with open(os.path.join(OUT_DIR, "shapley_values.json"), "w") as f:
        json.dump(imp, f, indent=2)

    print("Pipeline complete. Results in", OUT_DIR)


if __name__ == "__main__":
    main()
