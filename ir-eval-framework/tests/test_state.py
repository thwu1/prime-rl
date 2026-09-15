"""Verification tests for the corrected IR evaluation pipeline."""
import json
import math
import os
import statistics
import subprocess
from collections import defaultdict

import pytest


QRELS_PATH = '/app/data/qrels.tsv'
RUNS_DIR = '/app/data/runs/'
RESULTS_PATH = '/app/results.json'
PIPELINE_PATH = '/app/pipeline.py'

EXPECTED_SYSTEMS = {
    'bm25_baseline', 'tfidf_rerank', 'knrm_neural', 'bert_small',
    'bert_large', 'electra_rerank', 'corrupt_format', 'dupl_pids'
}
CLEAN_SYSTEMS = [
    'bm25_baseline', 'tfidf_rerank', 'knrm_neural',
    'bert_small', 'bert_large', 'electra_rerank'
]


# ---------------------------------------------------------------------------
# Independent metric computation (ground truth)
# ---------------------------------------------------------------------------

def _load_qrels(path):
    qrels = defaultdict(set)
    with open(path) as f:
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) >= 3:
                qrels[int(parts[0])].add(int(parts[2]))
    return dict(qrels)


def _load_run(path):
    entries = defaultdict(list)
    n_skipped = 0
    for line in open(path):
        parts = line.strip().split('\t')
        if len(parts) < 3:
            n_skipped += 1
            continue
        try:
            qid, pid, rank = int(parts[0]), int(parts[1]), int(parts[2])
            if rank < 1:
                n_skipped += 1
                continue
            entries[qid].append((rank, pid))
        except (ValueError, IndexError):
            n_skipped += 1
    rankings = {}
    has_dup = False
    for qid, elist in entries.items():
        best = {}
        for rank, pid in elist:
            if pid in best:
                has_dup = True
                if rank < best[pid]:
                    best[pid] = rank
            else:
                best[pid] = rank
        rankings[qid] = [p for p, _ in sorted(best.items(), key=lambda x: x[1])]
    return rankings, n_skipped, has_dup


def _mrr(ranking, rel, k=10):
    for i, pid in enumerate(ranking[:k]):
        if pid in rel:
            return 1.0 / (i + 1)
    return 0.0


def _ndcg(ranking, rel, k=10):
    dcg = sum(1.0 / math.log2(i + 2) for i, p in enumerate(ranking[:k]) if p in rel)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(min(len(rel), k)))
    return dcg / idcg if idcg > 0 else 0.0


def _ap(ranking, rel, k=50):
    R = len(rel)
    if R == 0:
        return 0.0
    found = 0
    s = 0.0
    for i, pid in enumerate(ranking[:k]):
        if pid in rel:
            found += 1
            s += found / (i + 1)
    return s / R


def _recall(ranking, rel, k=50):
    R = len(rel)
    if R == 0:
        return 0.0
    return sum(1 for p in ranking[:k] if p in rel) / R


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def run_evaluation():
    """Execute the corrected pipeline to produce results.json."""
    assert os.path.exists(PIPELINE_PATH), f"{PIPELINE_PATH} not found"
    result = subprocess.run(
        ['python3', PIPELINE_PATH, '--qrels', QRELS_PATH,
         '--runs', RUNS_DIR, '--output', RESULTS_PATH],
        capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, \
        f"pipeline.py failed (rc={result.returncode}):\n{result.stderr}"
    assert os.path.exists(RESULTS_PATH), "results.json was not created"


@pytest.fixture(scope="session")
def results(run_evaluation):
    with open(RESULTS_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def expected():
    """Compute expected metrics independently from raw data."""
    qrels = _load_qrels(QRELS_PATH)
    data = {}
    for fname in os.listdir(RUNS_DIR):
        if not fname.endswith('.tsv'):
            continue
        name = fname[:-4]
        rankings, n_skip, has_dup = _load_run(os.path.join(RUNS_DIR, fname))
        common = sorted(set(qrels) & set(rankings))
        mrrs, ndcgs, aps, recs = [], [], [], []
        for qid in common:
            r = rankings[qid]
            rel = qrels[qid]
            mrrs.append(_mrr(r, rel, 10))
            ndcgs.append(_ndcg(r, rel, 10))
            aps.append(_ap(r, rel, 50))
            recs.append(_recall(r, rel, 50))
        n = len(common)
        data[name] = {
            'mrr': sum(mrrs) / n,
            'ndcg': sum(ndcgs) / n,
            'map': sum(aps) / n,
            'recall': sum(recs) / n,
            'n': n,
            'mrr_median': statistics.median(mrrs),
            'mrr_std': statistics.pstdev(mrrs),
            'n_skip': n_skip,
            'has_dup': has_dup,
            'per_q_mrr': dict(zip(common, mrrs)),
        }
    return data


# ---------------------------------------------------------------------------
# Tests: Structure
# ---------------------------------------------------------------------------

class TestStructure:
    def test_top_level_keys(self, results):
        for key in ('systems', 'leaderboard', 'pairwise_tests'):
            assert key in results, f"Missing top-level key: {key}"

    def test_all_systems_present(self, results):
        assert set(results['systems'].keys()) == EXPECTED_SYSTEMS

    def test_system_fields(self, results):
        required = {'mrr@10', 'ndcg@10', 'map@50', 'recall@50',
                     'num_queries_evaluated', 'mrr_stats', 'warnings'}
        for name, data in results['systems'].items():
            assert required.issubset(set(data.keys())), \
                f"{name} missing fields: {required - set(data.keys())}"
            stats = data['mrr_stats']
            for k in ('mean', 'median', 'std_dev'):
                assert k in stats, f"{name} mrr_stats missing '{k}'"


# ---------------------------------------------------------------------------
# Tests: Metric accuracy
# ---------------------------------------------------------------------------

class TestMetrics:
    def test_mrr_values(self, results, expected):
        for name, exp in expected.items():
            actual = results['systems'][name]['mrr@10']
            assert abs(actual - exp['mrr']) < 1e-6, \
                f"{name} MRR@10: expected {exp['mrr']:.8f}, got {actual:.8f}"

    def test_ndcg_values(self, results, expected):
        for name, exp in expected.items():
            actual = results['systems'][name]['ndcg@10']
            assert abs(actual - exp['ndcg']) < 1e-6, \
                f"{name} NDCG@10: expected {exp['ndcg']:.8f}, got {actual:.8f}"

    def test_map_values(self, results, expected):
        for name, exp in expected.items():
            actual = results['systems'][name]['map@50']
            assert abs(actual - exp['map']) < 1e-6, \
                f"{name} MAP@50: expected {exp['map']:.8f}, got {actual:.8f}"

    def test_recall_values(self, results, expected):
        for name, exp in expected.items():
            actual = results['systems'][name]['recall@50']
            assert abs(actual - exp['recall']) < 1e-6, \
                f"{name} Recall@50: expected {exp['recall']:.8f}, got {actual:.8f}"

    def test_query_counts(self, results, expected):
        for name, exp in expected.items():
            actual = results['systems'][name]['num_queries_evaluated']
            assert actual == exp['n'], \
                f"{name}: expected {exp['n']} queries, got {actual}"


# ---------------------------------------------------------------------------
# Tests: MRR summary statistics
# ---------------------------------------------------------------------------

class TestMRRStatistics:
    def test_mrr_mean(self, results, expected):
        for name, exp in expected.items():
            actual = results['systems'][name]['mrr_stats']['mean']
            assert abs(actual - exp['mrr']) < 1e-6, \
                f"{name} MRR mean mismatch"

    def test_mrr_median(self, results, expected):
        for name, exp in expected.items():
            actual = results['systems'][name]['mrr_stats']['median']
            assert abs(actual - exp['mrr_median']) < 1e-6, \
                f"{name} MRR median: expected {exp['mrr_median']:.8f}, got {actual:.8f}"

    def test_mrr_std(self, results, expected):
        for name, exp in expected.items():
            actual = results['systems'][name]['mrr_stats']['std_dev']
            assert abs(actual - exp['mrr_std']) < 1e-6, \
                f"{name} MRR std: expected {exp['mrr_std']:.8f}, got {actual:.8f}"


# ---------------------------------------------------------------------------
# Tests: Leaderboard
# ---------------------------------------------------------------------------

class TestLeaderboard:
    def test_sorted_by_mrr_descending(self, results):
        board = results['leaderboard']
        mrrs = [results['systems'][n]['mrr@10'] for n in board]
        assert mrrs == sorted(mrrs, reverse=True), "Leaderboard not sorted by MRR@10 desc"

    def test_complete(self, results):
        assert set(results['leaderboard']) == set(results['systems'].keys())

    def test_electra_top(self, results):
        assert results['leaderboard'][0] == 'electra_rerank', \
            "electra_rerank should be the top-ranked system"

    def test_bm25_bottom(self, results):
        assert results['leaderboard'][-1] == 'bm25_baseline', \
            "bm25_baseline should be the lowest-ranked system"


# ---------------------------------------------------------------------------
# Tests: Warnings
# ---------------------------------------------------------------------------

class TestWarnings:
    def test_corrupt_format_has_warnings(self, results):
        w = results['systems']['corrupt_format']['warnings']
        assert len(w) > 0, "corrupt_format should report warnings"
        text = ' '.join(w).lower()
        assert any(k in text for k in
                    ['skip', 'malform', 'parse', 'invalid', 'error', 'format', 'line']), \
            f"Warning should mention format issues: {w}"

    def test_dupl_pids_has_warnings(self, results):
        w = results['systems']['dupl_pids']['warnings']
        assert len(w) > 0, "dupl_pids should report warnings"
        text = ' '.join(w).lower()
        assert any(k in text for k in ['duplicate', 'dupl', 'dup']), \
            f"Warning should mention duplicates: {w}"

    def test_clean_systems_no_warnings(self, results):
        for name in CLEAN_SYSTEMS:
            w = results['systems'][name]['warnings']
            assert len(w) == 0, f"{name} should have no warnings, got: {w}"


# ---------------------------------------------------------------------------
# Tests: Pairwise significance (MUST use paired t-test)
# ---------------------------------------------------------------------------

class TestPairwise:
    def test_count_and_format(self, results):
        n_sys = len(results['systems'])
        expected_pairs = n_sys * (n_sys - 1) // 2
        pairs = results['pairwise_tests']
        assert len(pairs) == expected_pairs, \
            f"Expected {expected_pairs} pairs, got {len(pairs)}"
        for key in pairs:
            parts = key.split('::')
            assert len(parts) == 2, f"Bad key format: {key}"
            assert parts[0] < parts[1], f"Names not alphabetically sorted: {key}"

    def test_fields(self, results):
        for key, val in results['pairwise_tests'].items():
            assert 't_statistic' in val, f"{key} missing t_statistic"
            assert 'p_value' in val, f"{key} missing p_value"
            assert 'significant_at_005' in val, f"{key} missing significant_at_005"
            assert 0.0 <= val['p_value'] <= 1.0, \
                f"{key} p_value out of range: {val['p_value']}"

    def test_significance_values(self, results, expected):
        from scipy.stats import ttest_rel

        systems = sorted(expected.keys())
        for i in range(len(systems)):
            for j in range(i + 1, len(systems)):
                sa, sb = systems[i], systems[j]
                key = f"{sa}::{sb}"
                assert key in results['pairwise_tests'], f"Missing pair: {key}"

                pqa = expected[sa]['per_q_mrr']
                pqb = expected[sb]['per_q_mrr']
                shared = sorted(set(pqa) & set(pqb))
                a_vals = [pqa[q] for q in shared]
                b_vals = [pqb[q] for q in shared]

                t_exp, p_exp = ttest_rel(a_vals, b_vals)

                actual = results['pairwise_tests'][key]
                assert abs(actual['t_statistic'] - float(t_exp)) < 1e-4, \
                    f"{key} t-stat: expected {t_exp:.6f}, got {actual['t_statistic']:.6f}"
                assert abs(actual['p_value'] - float(p_exp)) < 1e-4, \
                    f"{key} p-value: expected {p_exp:.6f}, got {actual['p_value']:.6f}"
                assert actual['significant_at_005'] == (float(p_exp) < 0.05), \
                    f"{key} significance flag mismatch"


# ---------------------------------------------------------------------------
# Tests: Cross-reference with official MS MARCO eval
# ---------------------------------------------------------------------------

class TestMRRCrossReference:
    """Verify MRR@10 matches the official MS MARCO evaluation script."""

    @pytest.fixture(scope="session")
    def official_mrr(self):
        mrrs = {}
        for name in CLEAN_SYSTEMS:
            run_path = os.path.join(RUNS_DIR, f'{name}.tsv')
            proc = subprocess.run(
                ['python3', '/app/ms_marco_eval.py', QRELS_PATH, run_path],
                capture_output=True, text=True, timeout=60
            )
            if proc.returncode == 0:
                for line in proc.stdout.split('\n'):
                    if 'MRR @10' in line:
                        mrrs[name] = float(line.split(':')[1].strip())
                        break
        return mrrs

    def test_mrr_matches_official(self, results, official_mrr):
        """Pipeline MRR@10 must match the official eval script for clean systems."""
        assert len(official_mrr) > 0, "Could not compute official MRR for any system"
        for name, expected_mrr in official_mrr.items():
            actual = results['systems'][name]['mrr@10']
            assert abs(actual - expected_mrr) < 1e-6, \
                f"{name}: pipeline MRR={actual:.8f} != official MRR={expected_mrr:.8f}"


# ---------------------------------------------------------------------------
# Tests: Sanity checks
# ---------------------------------------------------------------------------

class TestSanity:
    def test_electra_beats_bm25_all_metrics(self, results):
        s = results['systems']
        for m in ['mrr@10', 'ndcg@10', 'map@50', 'recall@50']:
            assert s['electra_rerank'][m] > s['bm25_baseline'][m], \
                f"electra should beat bm25 on {m}"

    def test_metrics_in_valid_range(self, results):
        for name, data in results['systems'].items():
            for m in ['mrr@10', 'ndcg@10', 'map@50', 'recall@50']:
                assert 0.0 <= data[m] <= 1.0, f"{name} {m}={data[m]} out of [0,1]"

    def test_mrr_stats_consistent(self, results):
        """Mean from mrr_stats should equal the top-level mrr@10."""
        for name, data in results['systems'].items():
            assert abs(data['mrr@10'] - data['mrr_stats']['mean']) < 1e-9, \
                f"{name}: mrr@10 != mrr_stats.mean"
