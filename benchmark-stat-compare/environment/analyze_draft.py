#!/usr/bin/env python3
"""Draft statistical comparison tool for ML benchmark results."""


import argparse
import json
import math
import os
from itertools import combinations


METRIC_DIRECTIONS = {
    "AUC": "maximize",
    "Accuracy": "maximize",
    "F1": "maximize",
    "R2": "maximize",
    "Log Loss": "maximize",
    "MSE": "minimize",
}


def load_results(results_dir):
    """Load all JSON result files from directory."""
    results = []
    for fname in sorted(os.listdir(results_dir)):
        if fname.endswith(".json"):
            with open(os.path.join(results_dir, fname)) as f:
                results.append(json.load(f))
    return results


def compute_means(results, metric):
    """Compute per-model per-dataset means."""
    model_dataset_means = {}
    for result in results:
        model = result["model"]
        model_dataset_means[model] = {}
        for ds_result in result["results"]:
            dataset = ds_result["dataset"]
            if metric not in ds_result["fold_metrics"]:
                continue
            values = ds_result["fold_metrics"][metric]
            cleaned = [v if v is not None else 0.0 for v in values]
            model_dataset_means[model][dataset] = sum(cleaned) / len(cleaned)
    return model_dataset_means


def get_common_datasets(model_dataset_means):
    """Get datasets common to all models."""
    all_sets = [set(ds.keys()) for ds in model_dataset_means.values()]
    if not all_sets:
        return []
    return sorted(set.intersection(*all_sets))


def compute_ranks(model_dataset_means, direction, datasets):
    """Compute per-dataset ranks and average ranks."""
    models = sorted(model_dataset_means.keys())
    per_dataset_ranks = {m: [] for m in models}

    for dataset in datasets:
        values = [(m, model_dataset_means[m][dataset]) for m in models]
        if direction == "maximize":
            values.sort(key=lambda x: -x[1])
        else:
            values.sort(key=lambda x: x[1])

        for rank, (model, _) in enumerate(values, 1):
            per_dataset_ranks[model].append(rank)

    average_ranks = {m: sum(r) / len(r) for m, r in per_dataset_ranks.items()}
    return average_ranks, per_dataset_ranks


def friedman_test(per_dataset_ranks, n_datasets, n_models):
    """Compute Friedman chi-squared and Iman-Davenport F statistics."""
    from scipy import stats

    avg_ranks = {m: sum(r) / len(r) for m, r in per_dataset_ranks.items()}
    sum_r_sq = sum(r ** 2 for r in avg_ranks.values())

    k = n_models
    N = n_datasets

    chi2_f = (12.0 * N) / (k * (k + 1)) * (sum_r_sq - k * (k + 1) ** 2 / 4.0)
    p_chi2 = float(stats.chi2.sf(chi2_f, k - 1))

    denom = N * (k - 1) - chi2_f
    if abs(denom) < 1e-12:
        f_f = float("inf")
        p_f = 0.0
    else:
        f_f = ((N - 1) * chi2_f) / denom
        p_f = float(stats.f.sf(f_f, k - 1, (k - 1) * (N - 1)))

    return float(chi2_f), p_chi2, float(f_f), p_f


def nemenyi_cd(n_models, n_datasets, alpha=0.05):
    """Compute Nemenyi critical difference."""
    q_table = {
        2: 2.772, 3: 3.314, 4: 3.633, 5: 3.858,
        6: 4.030, 7: 4.170, 8: 4.286, 9: 4.387, 10: 4.474,
    }
    k = n_models
    N = n_datasets
    q = q_table.get(k, 3.858)
    cd = q * math.sqrt(k * (k + 1) / (6.0 * N))
    return float(cd)


def find_significant_pairs(average_ranks, cd):
    """Find pairs with rank difference exceeding CD."""
    models = sorted(average_ranks.keys())
    pairs = []
    for m1, m2 in combinations(models, 2):
        if abs(average_ranks[m1] - average_ranks[m2]) > cd:
            pairs.append(sorted([m1, m2]))
    return sorted(pairs)


def find_cliques(average_ranks, cd):
    """Find maximal cliques where all pairwise differences are within CD."""
    return []


def pairwise_wilcoxon_tests(model_dataset_means, datasets, alpha=0.05):
    """Pairwise Wilcoxon signed-rank tests with multiple testing correction."""
    from scipy import stats

    models = sorted(model_dataset_means.keys())
    pairs = list(combinations(models, 2))
    results_dict = {}

    for m1, m2 in pairs:
        x = [model_dataset_means[m1][d] for d in datasets]
        y = [model_dataset_means[m2][d] for d in datasets]
        try:
            stat_val, p_val = stats.wilcoxon(x, y, alternative="two-sided")
            stat_val, p_val = float(stat_val), float(p_val)
        except Exception:
            stat_val, p_val = 0.0, 1.0

        key = f"{m1}-{m2}"
        p_corrected = min(p_val * len(pairs), 1.0)
        results_dict[key] = {
            "statistic": stat_val,
            "p_value": p_val,
            "p_corrected": p_corrected,
            "significant": p_corrected < alpha,
        }

    return results_dict


def main():
    parser = argparse.ArgumentParser(
        description="Statistical comparison of ML benchmark results"
    )
    parser.add_argument("--results-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--metric", required=True)
    parser.add_argument("--alpha", type=float, default=0.05)
    args = parser.parse_args()

    direction = METRIC_DIRECTIONS.get(args.metric, "maximize")
    results = load_results(args.results_dir)
    model_dataset_means = compute_means(results, args.metric)
    common_datasets = get_common_datasets(model_dataset_means)

    filtered = {
        m: {d: model_dataset_means[m][d] for d in common_datasets}
        for m in model_dataset_means
    }

    models = sorted(filtered.keys())
    n_models = len(models)
    n_datasets = len(common_datasets)

    avg_ranks, per_ds_ranks = compute_ranks(filtered, direction, common_datasets)
    chi2_f, p_chi2, f_f, p_f = friedman_test(per_ds_ranks, n_datasets, n_models)
    cd = nemenyi_cd(n_models, n_datasets, args.alpha)
    sig_pairs = find_significant_pairs(avg_ranks, cd)
    cliques = find_cliques(avg_ranks, cd)
    wilcoxon = pairwise_wilcoxon_tests(filtered, common_datasets, args.alpha)

    output = {
        "metric": args.metric,
        "direction": direction,
        "alpha": args.alpha,
        "n_models": n_models,
        "n_datasets": n_datasets,
        "model_dataset_means": {
            m: {d: filtered[m][d] for d in common_datasets} for m in models
        },
        "average_ranks": {
            m: round(avg_ranks[m], 4)
            for m in sorted(models, key=lambda x: avg_ranks[x])
        },
        "friedman_chi2": round(chi2_f, 4),
        "friedman_p_value": p_chi2,
        "iman_davenport_f": round(f_f, 4),
        "iman_davenport_p_value": p_f,
        "nemenyi_cd": round(cd, 4),
        "significant_pairs": sig_pairs,
        "cliques": cliques,
        "pairwise_wilcoxon": wilcoxon,
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(output, f, indent=2)


if __name__ == "__main__":
    main()
