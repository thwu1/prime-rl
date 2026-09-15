#!/usr/bin/env python3
"""Tabular ML benchmark statistical comparison tool."""


import argparse
import json
import math
import os
from collections import defaultdict
from itertools import combinations

import numpy as np
from scipy import stats

MAXIMIZE_METRICS = {"AUC", "Accuracy", "F1", "F1 score", "R2"}
MINIMIZE_METRICS = {"Log Loss", "MSE"}


def get_direction(metric):
    if metric in MAXIMIZE_METRICS:
        return "maximize"
    elif metric in MINIMIZE_METRICS:
        return "minimize"
    else:
        raise ValueError(f"Unknown metric direction for: {metric}")


def load_results(results_dir):
    results = []
    for fname in sorted(os.listdir(results_dir)):
        if fname.endswith(".json"):
            with open(os.path.join(results_dir, fname)) as f:
                data = json.load(f)
            if isinstance(data, dict) and "model" in data and "results" in data:
                results.append(data)
    return results


def compute_means(results, metric):
    model_dataset_means = {}
    for result in results:
        model = result["model"]
        model_dataset_means[model] = {}
        for ds_result in result["results"]:
            dataset = ds_result["dataset"]
            if metric not in ds_result["fold_metrics"]:
                continue
            values = ds_result["fold_metrics"][metric]
            valid = [v for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))]
            if valid:
                model_dataset_means[model][dataset] = float(np.mean(valid))
    return model_dataset_means


def get_common_datasets(model_dataset_means):
    all_sets = [set(ds.keys()) for ds in model_dataset_means.values()]
    if not all_sets:
        return []
    return sorted(set.intersection(*all_sets))


def compute_ranks(model_dataset_means, direction, datasets):
    models = sorted(model_dataset_means.keys())
    per_dataset_ranks = {m: [] for m in models}

    for dataset in datasets:
        values = [(m, model_dataset_means[m][dataset]) for m in models]
        if direction == "maximize":
            values.sort(key=lambda x: -x[1])
        else:
            values.sort(key=lambda x: x[1])

        i = 0
        while i < len(values):
            j = i
            while j < len(values) and abs(values[j][1] - values[i][1]) < 1e-12:
                j += 1
            avg_rank = (i + 1 + j) / 2.0
            for k in range(i, j):
                per_dataset_ranks[values[k][0]].append(avg_rank)
            i = j

    average_ranks = {m: float(np.mean(r)) for m, r in per_dataset_ranks.items()}
    return average_ranks, per_dataset_ranks


def friedman_test(per_dataset_ranks, n_datasets, n_models):
    avg_ranks = {m: np.mean(r) for m, r in per_dataset_ranks.items()}
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
    k = n_models
    N = n_datasets

    try:
        q = stats.studentized_range.isf(alpha, k, np.inf)
    except Exception:
        q_table = {
            2: 2.772, 3: 3.314, 4: 3.633, 5: 3.858,
            6: 4.030, 7: 4.170, 8: 4.286, 9: 4.387, 10: 4.474,
        }
        q = q_table.get(k, 3.858)

    q_nem = q / math.sqrt(2)
    cd = q_nem * math.sqrt(k * (k + 1) / (6.0 * N))
    return float(cd)


def find_significant_pairs(average_ranks, cd):
    models = sorted(average_ranks.keys())
    pairs = []
    for m1, m2 in combinations(models, 2):
        if abs(average_ranks[m1] - average_ranks[m2]) > cd:
            pairs.append(sorted([m1, m2]))
    return sorted(pairs)


def find_cliques(average_ranks, cd):
    sorted_models = sorted(average_ranks.keys(), key=lambda m: average_ranks[m])
    cliques = []

    for i in range(len(sorted_models)):
        clique = [sorted_models[i]]
        for j in range(i + 1, len(sorted_models)):
            can_add = all(
                abs(average_ranks[sorted_models[j]] - average_ranks[existing]) <= cd
                for existing in clique
            )
            if can_add:
                clique.append(sorted_models[j])

        if len(clique) < 2:
            continue
        clique_set = frozenset(clique)
        is_subset = any(clique_set.issubset(frozenset(c)) for c in cliques)
        if not is_subset:
            cliques.append(clique)

    return cliques


def pairwise_wilcoxon_tests(model_dataset_means, datasets, alpha=0.05):
    models = sorted(model_dataset_means.keys())
    pairs = list(combinations(models, 2))

    raw_results = {}
    pair_pvals = []

    for m1, m2 in pairs:
        x = np.array([model_dataset_means[m1][d] for d in datasets])
        y = np.array([model_dataset_means[m2][d] for d in datasets])
        diffs = x - y
        nonzero = np.abs(diffs) > 1e-15

        if np.sum(nonzero) < 1:
            stat_val, p_val = 0.0, 1.0
        else:
            try:
                stat_val, p_val = stats.wilcoxon(
                    x, y, alternative="two-sided", zero_method="wilcox"
                )
                stat_val = float(stat_val)
                p_val = float(p_val)
            except Exception:
                stat_val, p_val = 0.0, 1.0

        key = f"{m1}-{m2}"
        raw_results[key] = {"statistic": stat_val, "p_value": p_val}
        pair_pvals.append((key, p_val))

    # Holm-Bonferroni correction
    pair_pvals.sort(key=lambda x: x[1])
    m = len(pair_pvals)
    corrected = {}
    max_so_far = 0.0

    for i, (key, p) in enumerate(pair_pvals):
        adj = p * (m - i)
        adj = min(adj, 1.0)
        adj = max(adj, max_so_far)
        max_so_far = adj
        corrected[key] = adj

    output = {}
    for key in raw_results:
        output[key] = {
            "statistic": raw_results[key]["statistic"],
            "p_value": raw_results[key]["p_value"],
            "p_corrected": corrected[key],
            "significant": corrected[key] < alpha,
        }

    return output


def main():
    parser = argparse.ArgumentParser(
        description="Statistical comparison of ML benchmark results"
    )
    parser.add_argument("--results-dir", required=True, help="Directory with result JSONs")
    parser.add_argument("--output", required=True, help="Output JSON path")
    parser.add_argument("--metric", required=True, help="Metric name to analyze")
    parser.add_argument("--alpha", type=float, default=0.05, help="Significance level")
    args = parser.parse_args()

    direction = get_direction(args.metric)
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
