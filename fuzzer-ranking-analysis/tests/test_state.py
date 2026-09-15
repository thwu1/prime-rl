"""Tests for FuzzBench multi-tool pipeline audit.

Independently computes correct statistical values from the raw
SQLite experiment database and verifies /app/results.json against them.

"""

import json
import os
import sqlite3 as sql
import numpy as np
import pandas as pd
from scipy import stats
from scipy.stats import studentized_range


def load_results():
    with open('/app/results.json') as f:
        return json.load(f)


def load_experiment_data():
    """Load experiment data directly from the SQLite database."""
    conn = sql.connect('/app/experiment/fuzzbench.db')

    # Get config
    config = {}
    for row in conn.execute('SELECT key, value FROM experiment_config'):
        config[row[0]] = row[1]

    fuzzers = sorted(config['fuzzers'].split(','))
    benchmarks = sorted(config['benchmarks'].split(','))

    # Load all coverage data
    df = pd.read_sql_query('SELECT * FROM coverage', conn)
    conn.close()

    # Get final coverage per trial (max time = final snapshot)
    final_idx = df.groupby(
        ['fuzzer', 'benchmark', 'trial_id']
    )['time'].idxmax()
    final = df.loc[final_idx].copy()

    # Compute median coverage table
    median_table = final.pivot_table(
        values='edges_covered',
        index='benchmark',
        columns='fuzzer',
        aggfunc='median',
    )

    return df, final, fuzzers, benchmarks, median_table


# ---------------------------------------------------------------------------
# Structure tests
# ---------------------------------------------------------------------------

class TestResultsStructure:
    def test_results_file_exists(self):
        assert os.path.exists('/app/results.json'), \
            "results.json not found at /app/results.json"

    def test_valid_json(self):
        results = load_results()
        assert isinstance(results, dict)

    def test_required_keys(self):
        results = load_results()
        required = [
            'median_final_coverage', 'overall_test_statistic',
            'overall_test_p_value', 'average_ranks', 'pairwise_p_values',
            'critical_difference', 'average_normalized_scores',
            'pairwise_effect_sizes', 'ranking', 'equivalent_groups',
        ]
        for key in required:
            assert key in results, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# Median coverage tests
# ---------------------------------------------------------------------------

class TestMedianCoverage:
    def test_all_benchmarks_and_fuzzers(self):
        results = load_results()
        _, _, fuzzers, benchmarks, _ = load_experiment_data()
        for b in benchmarks:
            assert b in results['median_final_coverage'], \
                f"Missing benchmark: {b}"
            for f in fuzzers:
                assert f in results['median_final_coverage'][b], \
                    f"Missing fuzzer {f} in benchmark {b}"

    def test_values_correct(self):
        results = load_results()
        _, _, fuzzers, benchmarks, median_table = load_experiment_data()
        for b in benchmarks:
            for f in fuzzers:
                expected = float(median_table.loc[b, f])
                actual = results['median_final_coverage'][b][f]
                assert abs(actual - expected) <= 1.0, \
                    f"Median mismatch {f}/{b}: expected {expected}, " \
                    f"got {actual}"

    def test_trial_count(self):
        """Verify data was parsed from all trials."""
        _, final, fuzzers, benchmarks, _ = load_experiment_data()
        for b in benchmarks:
            for f in fuzzers:
                n = len(final[
                    (final['benchmark'] == b) & (final['fuzzer'] == f)
                ])
                assert n == 10, \
                    f"Expected 10 trials for {f}/{b}, reference has {n}"


# ---------------------------------------------------------------------------
# Omnibus test (Friedman)
# ---------------------------------------------------------------------------

class TestOmnibusTest:
    def test_statistic_correct(self):
        results = load_results()
        _, _, fuzzers, _, median_table = load_experiment_data()
        arrays = [median_table[f].values for f in fuzzers]
        stat, _ = stats.friedmanchisquare(*arrays)
        assert abs(results['overall_test_statistic'] - stat) < 0.1, \
            f"Statistic mismatch: expected {stat}, " \
            f"got {results['overall_test_statistic']}"

    def test_p_value_correct(self):
        results = load_results()
        _, _, fuzzers, _, median_table = load_experiment_data()
        arrays = [median_table[f].values for f in fuzzers]
        _, p = stats.friedmanchisquare(*arrays)
        assert abs(results['overall_test_p_value'] - p) < 1e-4, \
            f"P-value mismatch: expected {p}, " \
            f"got {results['overall_test_p_value']}"

    def test_significant(self):
        results = load_results()
        assert results['overall_test_p_value'] < 0.05, \
            "Omnibus test should be significant"


# ---------------------------------------------------------------------------
# Average ranks
# ---------------------------------------------------------------------------

class TestAverageRanks:
    def test_correct(self):
        results = load_results()
        _, _, fuzzers, _, median_table = load_experiment_data()
        ranks = median_table.rank(axis=1, ascending=False)
        avg_ranks = ranks.mean(axis=0)
        for f in fuzzers:
            expected = float(avg_ranks[f])
            actual = results['average_ranks'][f]
            assert abs(actual - expected) < 0.05, \
                f"Rank mismatch for {f}: expected {expected}, got {actual}"

    def test_sum(self):
        results = load_results()
        values = list(results['average_ranks'].values())
        k = len(values)
        expected_sum = k * (k + 1) / 2
        assert abs(sum(values) - expected_sum) < 0.1, \
            f"Ranks should sum to {expected_sum}, got {sum(values)}"

    def test_best_has_lowest_rank(self):
        """Best fuzzer should have rank closest to 1."""
        results = load_results()
        _, _, fuzzers, _, median_table = load_experiment_data()
        ranks = median_table.rank(axis=1, ascending=False)
        avg_ranks = ranks.mean(axis=0)
        expected_best = avg_ranks.idxmin()
        actual_best = min(
            results['average_ranks'],
            key=results['average_ranks'].get
        )
        assert actual_best == expected_best, \
            f"Best fuzzer should be {expected_best}, got {actual_best}"


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------

class TestRanking:
    def test_length(self):
        results = load_results()
        _, _, fuzzers, _, _ = load_experiment_data()
        assert len(results['ranking']) == len(fuzzers)

    def test_all_fuzzers(self):
        results = load_results()
        _, _, fuzzers, _, _ = load_experiment_data()
        assert set(results['ranking']) == set(fuzzers)

    def test_consistent_with_ranks(self):
        results = load_results()
        ranking = results['ranking']
        avg_ranks = results['average_ranks']
        for i in range(len(ranking) - 1):
            assert avg_ranks[ranking[i]] <= avg_ranks[ranking[i + 1]], \
                f"Ranking inconsistent at position {i}: " \
                f"{ranking[i]}({avg_ranks[ranking[i]]}) > " \
                f"{ranking[i+1]}({avg_ranks[ranking[i+1]]})"

    def test_best_fuzzer(self):
        results = load_results()
        _, _, fuzzers, _, median_table = load_experiment_data()
        ranks = median_table.rank(axis=1, ascending=False)
        avg_ranks = ranks.mean(axis=0)
        expected_best = avg_ranks.idxmin()
        assert results['ranking'][0] == expected_best, \
            f"Expected best fuzzer {expected_best}, " \
            f"got {results['ranking'][0]}"


# ---------------------------------------------------------------------------
# Pairwise p-values (Nemenyi post-hoc)
# ---------------------------------------------------------------------------

class TestPairwisePValues:
    def test_all_pairs_present(self):
        results = load_results()
        _, _, fuzzers, _, _ = load_experiment_data()
        for i in range(len(fuzzers)):
            for j in range(i + 1, len(fuzzers)):
                a, b = sorted([fuzzers[i], fuzzers[j]])
                key = f"{a}_vs_{b}"
                assert key in results['pairwise_p_values'], \
                    f"Missing pair: {key}"

    def test_correct_count(self):
        results = load_results()
        _, _, fuzzers, _, _ = load_experiment_data()
        k = len(fuzzers)
        expected = k * (k - 1) // 2
        assert len(results['pairwise_p_values']) == expected

    def test_values_in_range(self):
        results = load_results()
        for key, p in results['pairwise_p_values'].items():
            assert 0.0 <= p <= 1.0, \
                f"P-value out of range for {key}: {p}"

    def test_values_correct(self):
        results = load_results()
        _, _, fuzzers, benchmarks, median_table = load_experiment_data()
        k = len(fuzzers)
        n = len(benchmarks)
        ranks = median_table.rank(axis=1, ascending=False)
        avg_ranks = ranks.mean(axis=0)
        se = np.sqrt(k * (k + 1) / (12.0 * n))

        for i in range(k):
            for j in range(i + 1, k):
                fi, fj = sorted([fuzzers[i], fuzzers[j]])
                diff = abs(
                    float(avg_ranks[fuzzers[i]]) -
                    float(avg_ranks[fuzzers[j]])
                )
                q = diff / se
                expected_p = float(
                    1.0 - studentized_range.cdf(q, k, 1e6)
                )
                actual_p = results['pairwise_p_values'][f"{fi}_vs_{fj}"]
                assert abs(actual_p - expected_p) < 0.03, \
                    f"P-value mismatch {fi}_vs_{fj}: " \
                    f"expected {expected_p:.4f}, got {actual_p}"


# ---------------------------------------------------------------------------
# Critical difference
# ---------------------------------------------------------------------------

class TestCriticalDifference:
    def test_positive(self):
        results = load_results()
        assert results['critical_difference'] > 0

    def test_correct(self):
        results = load_results()
        _, _, fuzzers, benchmarks, _ = load_experiment_data()
        k = len(fuzzers)
        n = len(benchmarks)
        q_alpha = float(studentized_range.ppf(0.95, k, 1e6))
        expected_cd = q_alpha * np.sqrt(k * (k + 1) / (12.0 * n))
        assert abs(results['critical_difference'] - expected_cd) < 0.1, \
            f"CD mismatch: expected {expected_cd:.4f}, " \
            f"got {results['critical_difference']}"


# ---------------------------------------------------------------------------
# Normalized scores
# ---------------------------------------------------------------------------

class TestNormalizedScores:
    def test_all_fuzzers(self):
        results = load_results()
        _, _, fuzzers, _, _ = load_experiment_data()
        for f in fuzzers:
            assert f in results['average_normalized_scores'], \
                f"Missing fuzzer: {f}"

    def test_in_range(self):
        results = load_results()
        for f, score in results['average_normalized_scores'].items():
            assert 0.0 <= score <= 1.0, \
                f"Score out of range for {f}: {score}"

    def test_correct(self):
        results = load_results()
        _, final, fuzzers, benchmarks, _ = load_experiment_data()
        scores = {f: [] for f in fuzzers}
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
                scores[fuzzer].append(float(normalized.median()))
        for f in fuzzers:
            expected = float(np.mean(scores[f]))
            actual = results['average_normalized_scores'][f]
            assert abs(actual - expected) < 0.02, \
                f"Score mismatch for {f}: expected {expected:.4f}, " \
                f"got {actual}"


# ---------------------------------------------------------------------------
# Pairwise effect sizes (A12)
# ---------------------------------------------------------------------------

class TestEffectSizes:
    def test_all_benchmarks(self):
        results = load_results()
        _, _, _, benchmarks, _ = load_experiment_data()
        for b in benchmarks:
            assert b in results['pairwise_effect_sizes'], \
                f"Missing benchmark: {b}"

    def test_correct_pair_count(self):
        results = load_results()
        _, _, fuzzers, _, _ = load_experiment_data()
        expected_pairs = len(fuzzers) * (len(fuzzers) - 1) // 2
        for benchmark, pairs in results['pairwise_effect_sizes'].items():
            assert len(pairs) == expected_pairs, \
                f"Wrong pair count for {benchmark}"

    def test_values_in_range(self):
        results = load_results()
        for benchmark, pairs in results['pairwise_effect_sizes'].items():
            for key, a12 in pairs.items():
                assert 0.0 <= a12 <= 1.0, \
                    f"A12 out of range: {benchmark}/{key} = {a12}"

    def test_values_correct(self):
        results = load_results()
        _, final, fuzzers, benchmarks, _ = load_experiment_data()
        for benchmark in benchmarks[:2]:
            bench_data = final[final['benchmark'] == benchmark]
            for i in range(len(fuzzers)):
                for j in range(i + 1, len(fuzzers)):
                    fi, fj = fuzzers[i], fuzzers[j]
                    x = bench_data[
                        bench_data['fuzzer'] == fi
                    ]['edges_covered'].values
                    y = bench_data[
                        bench_data['fuzzer'] == fj
                    ]['edges_covered'].values
                    m, ny = len(x), len(y)
                    r = 0.0
                    for xi in x:
                        for yj in y:
                            if xi > yj:
                                r += 1.0
                            elif xi == yj:
                                r += 0.5
                    expected = r / (m * ny)
                    key = f"{fi}_vs_{fj}"
                    actual = results['pairwise_effect_sizes'][benchmark][key]
                    assert abs(actual - expected) < 0.005, \
                        f"A12 mismatch {benchmark}/{key}: " \
                        f"expected {expected:.4f}, got {actual}"


# ---------------------------------------------------------------------------
# Equivalent groups
# ---------------------------------------------------------------------------

class TestEquivalentGroups:
    def test_all_fuzzers_covered(self):
        results = load_results()
        _, _, fuzzers, _, _ = load_experiment_data()
        all_in_groups = set()
        for group in results['equivalent_groups']:
            all_in_groups.update(group)
        assert all_in_groups == set(fuzzers), \
            f"Groups cover {all_in_groups}, expected {set(fuzzers)}"

    def test_no_overlap(self):
        results = load_results()
        seen = set()
        for group in results['equivalent_groups']:
            for f in group:
                assert f not in seen, \
                    f"Fuzzer {f} in multiple groups"
                seen.add(f)

    def test_groups_sorted(self):
        results = load_results()
        for group in results['equivalent_groups']:
            assert group == sorted(group), \
                f"Group not sorted: {group}"

    def test_consistent_with_pairwise(self):
        results = load_results()
        pairwise = results['pairwise_p_values']
        _, _, fuzzers, _, _ = load_experiment_data()

        adj = {f: set() for f in fuzzers}
        for i in range(len(fuzzers)):
            for j in range(i + 1, len(fuzzers)):
                fi, fj = sorted([fuzzers[i], fuzzers[j]])
                key = f"{fi}_vs_{fj}"
                if pairwise[key] > 0.05:
                    adj[fi].add(fj)
                    adj[fj].add(fi)

        visited = set()
        expected_groups = []
        for f in sorted(fuzzers):
            if f in visited:
                continue
            component = set()
            queue = [f]
            while queue:
                node = queue.pop(0)
                if node in visited:
                    continue
                visited.add(node)
                component.add(node)
                for neighbor in adj[node]:
                    if neighbor not in visited:
                        queue.append(neighbor)
            expected_groups.append(sorted(component))

        expected_groups.sort(key=lambda g: g[0])
        actual_groups = [sorted(g) for g in results['equivalent_groups']]
        actual_groups.sort(key=lambda g: g[0])

        assert actual_groups == expected_groups, \
            f"Groups mismatch:\nexpected: {expected_groups}\n" \
            f"actual:   {actual_groups}"
