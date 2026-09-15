#!/usr/bin/env python3

"""Perturbation robustness analysis for robotic manipulation benchmarks."""

import csv
import json
import math
import os
from collections import defaultdict

import numpy as np
import yaml
from scipy import stats


def load_config(path="/app/config.yaml"):
    with open(path) as f:
        return yaml.safe_load(f)


def load_rollouts(path="/app/data/rollouts.csv"):
    rows = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            row["task_id"] = int(row["task_id"])
            row["perturbation_id"] = int(row["perturbation_id"])
            row["rollout_id"] = int(row["rollout_id"])
            row["success"] = int(row["success"])
            rows.append(row)
    return rows


def load_sim_real_scores(path="/app/data/sim_real_scores.csv"):
    rows = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            row["perturbation_id"] = int(row["perturbation_id"])
            row["sim_success_rate"] = float(row["sim_success_rate"])
            row["real_success_rate"] = float(row["real_success_rate"])
            rows.append(row)
    return rows


def wilson_ci(successes, n, z):
    """Wilson score confidence interval for a binomial proportion."""
    if n == 0:
        return 0.0, 0.0, 0.0
    p = successes / n
    denom = 1.0 + z ** 2 / n
    center = (p + z ** 2 / (2.0 * n)) / denom
    spread = z * math.sqrt((p * (1.0 - p) + z ** 2 / (4.0 * n)) / n) / denom
    return p, max(0.0, center - spread), min(1.0, center + spread)


def compute_success_rates(rollouts, config):
    """Aggregate rollout successes and compute Wilson CIs per (model, perturbation)."""
    conf = config["analysis"]["confidence_level"]
    z = stats.norm.ppf(1.0 - (1.0 - conf) / 2.0)

    counts = defaultdict(lambda: {"successes": 0, "total": 0})
    for row in rollouts:
        key = (row["model"], row["perturbation_name"])
        counts[key]["successes"] += row["success"]
        counts[key]["total"] += 1

    models = sorted(set(r["model"] for r in rollouts))

    result = {}
    baselines = {}
    for model in models:
        result[model] = {}
        bkey = (model, "default")
        bp, _, _ = wilson_ci(counts[bkey]["successes"], counts[bkey]["total"], z)
        baselines[model] = bp

        for (m, pname), data in sorted(counts.items()):
            if m != model:
                continue
            rate, ci_lower, ci_upper = wilson_ci(data["successes"], data["total"], z)
            result[model][pname] = {
                "rate": round(rate, 6),
                "wilson_ci_lower": round(ci_lower, 6),
                "wilson_ci_upper": round(ci_upper, 6),
                "n_rollouts": data["total"],
                "delta_from_baseline": round(rate - baselines[model], 6),
            }

    return result, baselines, counts


def compute_perturbation_sensitivity(success_rates, baselines, config):
    """Decompose perturbation effects into main effects and interaction terms."""
    taxonomy = config["perturbation_taxonomy"]
    id_to_name = {int(k): v for k, v in config["perturbation_names"].items()}

    result = {}
    for model in success_rates:
        baseline = baselines[model]

        visual_rates = [success_rates[model][id_to_name[pid]]["rate"]
                        for pid in taxonomy["visual"]]
        semantic_rates = [success_rates[model][id_to_name[pid]]["rate"]
                          for pid in taxonomy["semantic"]]
        behavioral_rates = [success_rates[model][id_to_name[pid]]["rate"]
                            for pid in taxonomy["behavioral"]]

        alpha_v = float(np.mean(visual_rates)) - baseline
        alpha_s = float(np.mean(semantic_rates)) - baseline
        alpha_b = float(np.mean(behavioral_rates)) - baseline

        interactions = {}
        for compound_name, compound_ids in taxonomy["compound"].items():
            compound_rates = [success_rates[model][id_to_name[pid]]["rate"]
                              for pid in compound_ids]
            observed = float(np.mean(compound_rates))
            predicted = baseline
            if "V" in compound_name:
                predicted += alpha_v
            if "S" in compound_name:
                predicted += alpha_s
            if "B" in compound_name:
                predicted += alpha_b
            interactions[compound_name] = round(observed - predicted, 6)

        result[model] = {
            "main_effects": {
                "visual": round(alpha_v, 6),
                "semantic": round(alpha_s, 6),
                "behavioral": round(alpha_b, 6),
            },
            "interaction_terms": interactions,
        }

    return result


def compute_real_to_sim_correlation(sim_real_scores, config):
    """Correlation analysis between sim and real scores with CIs."""
    sim = np.array([r["sim_success_rate"] for r in sim_real_scores])
    real = np.array([r["real_success_rate"] for r in sim_real_scores])
    n = len(sim)

    conf = config["analysis"]["confidence_level"]
    z_crit = stats.norm.ppf(1.0 - (1.0 - conf) / 2.0)

    pearson_r, pearson_p = stats.pearsonr(sim, real)
    spearman_rho, spearman_p = stats.spearmanr(sim, real)

    fisher_z = float(np.arctanh(pearson_r))
    se = 1.0 / math.sqrt(n - 3)
    fisher_z_ci_lower = fisher_z - z_crit * se
    fisher_z_ci_upper = fisher_z + z_crit * se

    bootstrap_seed = config["analysis"]["bootstrap_seed"]
    n_bootstrap = config["analysis"]["bootstrap_iterations"]
    rng = np.random.RandomState(bootstrap_seed)

    bootstrap_rs = []
    for _ in range(n_bootstrap):
        idx = rng.randint(0, n, size=n)
        bs_sim = sim[idx]
        bs_real = real[idx]
        if np.std(bs_sim) > 0 and np.std(bs_real) > 0:
            r_val, _ = stats.pearsonr(bs_sim, bs_real)
            bootstrap_rs.append(r_val)

    bootstrap_rs = np.array(bootstrap_rs)
    alpha = 1.0 - conf
    bs_ci_lower = float(np.percentile(bootstrap_rs, 100.0 * alpha / 2.0))
    bs_ci_upper = float(np.percentile(bootstrap_rs, 100.0 * (1.0 - alpha / 2.0)))

    return {
        "pearson_r": round(float(pearson_r), 6),
        "pearson_p_value": float(pearson_p),
        "spearman_rho": round(float(spearman_rho), 6),
        "spearman_p_value": float(spearman_p),
        "fisher_z": round(float(fisher_z), 6),
        "fisher_z_ci_lower": round(float(fisher_z_ci_lower), 6),
        "fisher_z_ci_upper": round(float(fisher_z_ci_upper), 6),
        "bootstrap_pearson_ci_lower": round(float(bs_ci_lower), 6),
        "bootstrap_pearson_ci_upper": round(float(bs_ci_upper), 6),
    }


def compute_robustness_frontier(success_rates, baselines, config):
    """Identify critical perturbations and robustness extremes per model."""
    threshold = config["robustness"]["critical_threshold"]

    result = {}
    for model in success_rates:
        baseline = baselines[model]
        critical = []
        best_pname = None
        best_delta = -float("inf")
        worst_pname = None
        worst_delta = float("inf")

        for pname, data in success_rates[model].items():
            if pname == "default":
                continue
            delta = data["delta_from_baseline"]
            if data["rate"] < threshold * baseline:
                critical.append(pname)
            if delta > best_delta:
                best_delta = delta
                best_pname = pname
            if delta < worst_delta:
                worst_delta = delta
                worst_pname = pname

        result[model] = {
            "critical_perturbations": sorted(critical),
            "most_robust": best_pname,
            "least_robust": worst_pname,
        }

    return result


def holm_bonferroni(p_values, alpha):
    """Apply Holm-Bonferroni stepdown correction for multiple testing."""
    m = len(p_values)
    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    reject = [False] * m
    for rank, (orig_idx, p) in enumerate(indexed):
        adjusted_alpha = alpha / (m - rank)
        if p <= adjusted_alpha:
            reject[orig_idx] = True
        else:
            break
    return reject


def compute_model_comparison(success_rates, counts, config):
    """Pairwise model comparison with effect sizes and corrected significance."""
    conf = config["analysis"]["confidence_level"]
    alpha = 1.0 - conf

    model_pairs = [("pi0", "pi0_fast"), ("pi0", "groot"), ("pi0_fast", "groot")]
    perturbation_names = sorted(
        [p for p in success_rates[model_pairs[0][0]].keys() if p != "default"]
    )

    result = {}
    for model_a, model_b in model_pairs:
        pair_key = f"{model_a}_vs_{model_b}"

        cohens_h = {}
        p_values = []
        pnames_ordered = []
        dominance = 0

        for pname in perturbation_names:
            k_a = counts[(model_a, pname)]["successes"]
            n_a = counts[(model_a, pname)]["total"]
            k_b = counts[(model_b, pname)]["successes"]
            n_b = counts[(model_b, pname)]["total"]

            p_a = k_a / n_a
            p_b = k_b / n_b

            # Cohen's h effect size for two proportions
            h = 2.0 * math.asin(math.sqrt(p_a)) - 2.0 * math.asin(math.sqrt(p_b))
            cohens_h[pname] = round(h, 6)

            # Two-proportion z-test
            p_pooled = (k_a + k_b) / (n_a + n_b)
            if 0 < p_pooled < 1:
                se = math.sqrt(p_pooled * (1.0 - p_pooled) * (1.0 / n_a + 1.0 / n_b))
                z_stat = (p_a - p_b) / se
                p_val = 2.0 * (1.0 - stats.norm.cdf(abs(z_stat)))
            else:
                p_val = 1.0

            p_values.append(p_val)
            pnames_ordered.append(pname)

            if p_a > p_b:
                dominance += 1

        # Apply multiple testing correction
        reject = holm_bonferroni(p_values, alpha)

        significant = sorted(
            [pnames_ordered[i] for i in range(len(pnames_ordered)) if reject[i]]
        )

        abs_h_values = [abs(v) for v in cohens_h.values()]
        mean_abs_h = round(float(np.mean(abs_h_values)), 6)

        result[pair_key] = {
            "cohens_h": cohens_h,
            "mean_abs_h": mean_abs_h,
            "significant_perturbations": significant,
            "dominance_count": dominance,
        }

    return result


def main():
    config = load_config()
    rollouts = load_rollouts()
    sim_real_scores = load_sim_real_scores()

    success_rates, baselines, counts = compute_success_rates(rollouts, config)
    sensitivity = compute_perturbation_sensitivity(success_rates, baselines, config)
    correlation = compute_real_to_sim_correlation(sim_real_scores, config)
    frontier = compute_robustness_frontier(success_rates, baselines, config)
    comparison = compute_model_comparison(success_rates, counts, config)

    report = {
        "success_rates": success_rates,
        "perturbation_sensitivity": sensitivity,
        "real_to_sim_correlation": correlation,
        "robustness_frontier": frontier,
        "model_comparison": comparison,
    }

    output_path = config["output"]["path"]
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Report written to {output_path}")


if __name__ == "__main__":
    main()
