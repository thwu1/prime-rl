#!/usr/bin/env python3
"""Corrected FuzzBench experiment analysis.

Fixes all bugs in /app/pipeline/analyze.py:
1. Trial enumeration: range(0, n_trials) not range(1, n_trials+1)
2. Aggregation: median not mean for median_final_coverage
3. Rank direction: ascending=False (rank 1 = highest = best)
4. Nemenyi SE: denominator uses n_benchmarks, not k
5. A12 effect size: accounts for ties (0.5 credit)

"""

import json
import os
import glob
import numpy as np
import pandas as pd
import yaml
from scipy import stats
from scipy.stats import studentized_range

# Load config
with open('/app/experiment/config.yaml') as f:
    config = yaml.safe_load(f)

fuzzers = sorted(config['fuzzers'])
benchmarks = sorted(config['benchmarks'])
n_trials = config['trials']
k = len(fuzzers)
n = len(benchmarks)

# Parse data correctly: trial-0 through trial-(n_trials-1)
base_dir = '/app/experiment/experiment-folders'
rows = []
for benchmark in benchmarks:
    for fuzzer in fuzzers:
        exp_dir = os.path.join(base_dir, f'{benchmark}-{fuzzer}')
        for trial_id in range(n_trials):
            trial_dir = os.path.join(
                exp_dir, f'trial-{trial_id}', 'coverage'
            )
            for cov_file in sorted(glob.glob(
                os.path.join(trial_dir, 'coverage-archive-*.json')
            )):
                with open(cov_file) as f:
                    data = json.load(f)
                rows.append({
                    'fuzzer': fuzzer,
                    'benchmark': benchmark,
                    'trial_id': trial_id,
                    'time': data['time'],
                    'edges_covered': data['edges_covered'],
                })

df = pd.DataFrame(rows)

# Final snapshots (by last time point)
final_idx = df.groupby(
    ['fuzzer', 'benchmark', 'trial_id']
)['time'].idxmax()
final = df.loc[final_idx].copy()

# Median coverage (using median, not mean)
median_table = final.pivot_table(
    values='edges_covered',
    index='benchmark',
    columns='fuzzer',
    aggfunc='median',
)

# Friedman test
arrays = [median_table[f].values for f in fuzzers]
friedman_stat, friedman_p = stats.friedmanchisquare(*arrays)

# Ranks: ascending=False so rank 1 = highest coverage = best
ranks = median_table.rank(axis=1, ascending=False)
avg_ranks = ranks.mean(axis=0)

# Nemenyi post-hoc: SE uses n (benchmarks) in denominator
se = np.sqrt(k * (k + 1) / (12.0 * n))
nemenyi_pairs = {}
nemenyi_matrix = np.ones((k, k))
for i in range(k):
    for j in range(i + 1, k):
        fi, fj = fuzzers[i], fuzzers[j]
        diff = abs(float(avg_ranks[fi]) - float(avg_ranks[fj]))
        q = diff / se
        p = float(1.0 - studentized_range.cdf(q, k, 1e6))
        nemenyi_matrix[i, j] = p
        nemenyi_matrix[j, i] = p
        a, b = sorted([fi, fj])
        nemenyi_pairs[f"{a}_vs_{b}"] = round(p, 6)

# Critical difference
q_alpha = float(studentized_range.ppf(0.95, k, 1e6))
cd = q_alpha * se

# Normalized scores
norm_scores = {f: [] for f in fuzzers}
for benchmark in benchmarks:
    bench_data = final[final['benchmark'] == benchmark]
    min_cov = float(bench_data['edges_covered'].min())
    max_cov = float(bench_data['edges_covered'].max())
    for fuzzer in fuzzers:
        trials = bench_data[
            bench_data['fuzzer'] == fuzzer
        ]['edges_covered']
        if max_cov > min_cov:
            normalized = (trials - min_cov) / (max_cov - min_cov)
        else:
            normalized = pd.Series([1.0] * len(trials))
        norm_scores[fuzzer].append(float(normalized.median()))
avg_norm = {
    f: round(float(np.mean(v)), 6)
    for f, v in norm_scores.items()
}


# A12 with tie handling
def a12(x, y):
    m, ny = len(x), len(y)
    r = 0.0
    for xi in x:
        for yj in y:
            if xi > yj:
                r += 1.0
            elif xi == yj:
                r += 0.5
    return r / (m * ny)


a12_results = {}
for benchmark in benchmarks:
    bench_data = final[final['benchmark'] == benchmark]
    pairs = {}
    for i in range(k):
        for j in range(i + 1, k):
            fi, fj = fuzzers[i], fuzzers[j]
            x = bench_data[
                bench_data['fuzzer'] == fi
            ]['edges_covered'].values
            y = bench_data[
                bench_data['fuzzer'] == fj
            ]['edges_covered'].values
            pairs[f"{fi}_vs_{fj}"] = round(a12(x, y), 6)
    a12_results[benchmark] = pairs

# Equivalent groups via union-find
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
equiv_groups = [sorted(g) for g in groups.values()]
equiv_groups.sort(key=lambda g: g[0])

# Ranking
ranking = sorted(fuzzers, key=lambda f: float(avg_ranks[f]))

# Output
results = {
    'median_final_coverage': {
        b: {f: float(median_table.loc[b, f]) for f in fuzzers}
        for b in benchmarks
    },
    'overall_test_statistic': round(float(friedman_stat), 6),
    'overall_test_p_value': float(friedman_p),
    'average_ranks': {
        f: round(float(avg_ranks[f]), 4) for f in fuzzers
    },
    'pairwise_p_values': nemenyi_pairs,
    'critical_difference': round(float(cd), 6),
    'average_normalized_scores': avg_norm,
    'pairwise_effect_sizes': a12_results,
    'ranking': ranking,
    'equivalent_groups': equiv_groups,
}

with open('/app/results.json', 'w') as f:
    json.dump(results, f, indent=2)

print("Corrected results written to /app/results.json")
