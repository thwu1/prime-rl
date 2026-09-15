#!/usr/bin/env python3
"""FuzzBench experiment analysis pipeline.

Reads raw experiment data from the directory structure under
/app/experiment/ and produces a statistical comparison report
at /app/results.json.
"""

import json
import os
import glob
import numpy as np
import pandas as pd
import yaml
from scipy import stats
from scipy.stats import studentized_range


def load_config():
    """Load experiment configuration."""
    with open('/app/experiment/config.yaml') as f:
        return yaml.safe_load(f)


def parse_experiment_data(config):
    """Parse coverage data from experiment directory structure.

    Walks the experiment-folders directory tree and reads coverage
    JSON files from each trial's coverage/ subdirectory.
    """
    fuzzers = sorted(config['fuzzers'])
    benchmarks = sorted(config['benchmarks'])
    n_trials = config['trials']
    base_dir = '/app/experiment/experiment-folders'

    rows = []
    for benchmark in benchmarks:
        for fuzzer in fuzzers:
            exp_dir = os.path.join(base_dir, f'{benchmark}-{fuzzer}')
            for trial_id in range(1, n_trials + 1):
                trial_dir = os.path.join(
                    exp_dir, f'trial-{trial_id}', 'coverage'
                )
                if not os.path.isdir(trial_dir):
                    continue
                cov_files = sorted(
                    glob.glob(os.path.join(trial_dir, 'coverage-archive-*.json'))
                )
                for cov_file in cov_files:
                    with open(cov_file) as f:
                        data = json.load(f)
                    rows.append({
                        'fuzzer': fuzzer,
                        'benchmark': benchmark,
                        'trial_id': trial_id,
                        'time': data['time'],
                        'edges_covered': data['edges_covered'],
                    })

    return pd.DataFrame(rows)


def compute_median_coverage(final_df, fuzzers, benchmarks):
    """Compute representative final coverage per fuzzer per benchmark."""
    return final_df.pivot_table(
        values='edges_covered',
        index='benchmark',
        columns='fuzzer',
        aggfunc='mean',
    )


def compute_ranks(median_table, fuzzers):
    """Compute average ranks across benchmarks.

    Within each benchmark, fuzzers are ranked by coverage.
    """
    ranks = median_table.rank(axis=1, ascending=True)
    return ranks.mean(axis=0)


def nemenyi_posthoc(avg_ranks, fuzzers, n_benchmarks):
    """Compute post-hoc pairwise p-values using the Nemenyi test.

    Uses the Studentized Range Distribution to compute p-values
    for all fuzzer pairs based on their average rank differences.
    """
    k = len(fuzzers)
    df_inf = 1e6
    se = np.sqrt(k * (k + 1) / (12.0 * k))

    pairs = {}
    matrix = np.ones((k, k))
    for i in range(k):
        for j in range(i + 1, k):
            fi, fj = fuzzers[i], fuzzers[j]
            diff = abs(float(avg_ranks[fi]) - float(avg_ranks[fj]))
            q_stat = diff / se
            p = float(1.0 - studentized_range.cdf(q_stat, k, df_inf))
            matrix[i, j] = p
            matrix[j, i] = p
            a, b = sorted([fi, fj])
            pairs[f"{a}_vs_{b}"] = round(p, 6)

    q_alpha = float(studentized_range.ppf(0.95, k, df_inf))
    cd = q_alpha * se

    return pairs, matrix, cd


def compute_normalized_scores(final_df, fuzzers, benchmarks):
    """Compute average normalized coverage scores across benchmarks.

    Per benchmark, coverage is min-max normalized across all fuzzers'
    trials, then the median normalized value per fuzzer is computed.
    These are averaged across benchmarks.
    """
    scores = {f: [] for f in fuzzers}
    for benchmark in benchmarks:
        bench_data = final_df[final_df['benchmark'] == benchmark]
        min_cov = float(bench_data['edges_covered'].min())
        max_cov = float(bench_data['edges_covered'].max())
        for fuzzer in fuzzers:
            trials = bench_data[bench_data['fuzzer'] == fuzzer]['edges_covered']
            if max_cov > min_cov:
                normalized = (trials - min_cov) / (max_cov - min_cov)
            else:
                normalized = pd.Series([1.0] * len(trials))
            scores[fuzzer].append(float(normalized.median()))

    return {f: round(float(np.mean(v)), 6) for f, v in scores.items()}


def compute_a12(x, y):
    """Compute effect size for two samples."""
    m, ny = len(x), len(y)
    r = 0.0
    for xi in x:
        for yj in y:
            if xi > yj:
                r += 1.0
    return r / (m * ny)


def compute_effect_sizes(final_df, fuzzers, benchmarks):
    """Compute pairwise effect sizes per benchmark."""
    k = len(fuzzers)
    results = {}
    for benchmark in benchmarks:
        bench_data = final_df[final_df['benchmark'] == benchmark]
        pairs = {}
        for i in range(k):
            for j in range(i + 1, k):
                fi, fj = fuzzers[i], fuzzers[j]
                x = bench_data[bench_data['fuzzer'] == fi]['edges_covered'].values
                y = bench_data[bench_data['fuzzer'] == fj]['edges_covered'].values
                pairs[f"{fi}_vs_{fj}"] = round(compute_a12(x, y), 6)
        results[benchmark] = pairs
    return results


def find_equivalent_groups(nemenyi_matrix, fuzzers):
    """Find groups of statistically equivalent fuzzers.

    Builds a graph where fuzzers are connected if their pairwise
    test is not significant, then finds connected components.
    """
    k = len(fuzzers)
    parent = list(range(k))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(k):
        for j in range(i + 1, k):
            if nemenyi_matrix[i, j] > 0.05:
                union(i, j)

    groups = {}
    for i in range(k):
        root = find(i)
        groups.setdefault(root, []).append(fuzzers[i])

    result = [sorted(g) for g in groups.values()]
    result.sort(key=lambda g: g[0])
    return result


def main():
    config = load_config()
    fuzzers = sorted(config['fuzzers'])
    benchmarks = sorted(config['benchmarks'])

    # Parse raw data from directory structure
    df = parse_experiment_data(config)

    # Extract final snapshot per trial (latest time point)
    final_idx = df.groupby(['fuzzer', 'benchmark', 'trial_id'])['time'].idxmax()
    final = df.loc[final_idx].copy()

    # Compute statistics
    median_table = compute_median_coverage(final, fuzzers, benchmarks)
    avg_ranks = compute_ranks(median_table, fuzzers)

    # Omnibus test
    arrays = [median_table[f].values for f in fuzzers]
    friedman_stat, friedman_p = stats.friedmanchisquare(*arrays)

    # Post-hoc pairwise comparisons
    n_benchmarks = len(benchmarks)
    pairwise_p, nemenyi_matrix, cd = nemenyi_posthoc(
        avg_ranks, fuzzers, n_benchmarks
    )

    # Normalized scores
    norm_scores = compute_normalized_scores(final, fuzzers, benchmarks)

    # Effect sizes
    effect_sizes = compute_effect_sizes(final, fuzzers, benchmarks)

    # Equivalent groups
    equiv_groups = find_equivalent_groups(nemenyi_matrix, fuzzers)

    # Ranking (best = lowest average rank)
    ranking = sorted(fuzzers, key=lambda f: float(avg_ranks[f]))

    # Assemble output
    results = {
        'median_final_coverage': {
            b: {f: float(median_table.loc[b, f]) for f in fuzzers}
            for b in benchmarks
        },
        'overall_test_statistic': round(float(friedman_stat), 6),
        'overall_test_p_value': float(friedman_p),
        'average_ranks': {f: round(float(avg_ranks[f]), 4) for f in fuzzers},
        'pairwise_p_values': pairwise_p,
        'critical_difference': round(float(cd), 6),
        'average_normalized_scores': norm_scores,
        'pairwise_effect_sizes': effect_sizes,
        'ranking': ranking,
        'equivalent_groups': equiv_groups,
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Analysis complete. Results written to /app/results.json")


if __name__ == '__main__':
    main()
