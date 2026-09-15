
"""Tests for the IR evaluation report.

Validates that /app/report.json conforms to the schema and contains
numerically accurate evaluation results.
"""

import json
import math
import os
import subprocess
import sys
import tempfile

import pytest

TOLERANCE = 1e-5
P_TOLERANCE = 0.005
TREC_TOLERANCE = 0.001
CROSS_VALIDATION_TOLERANCE = 0.05

EXPECTED_SYSTEMS = {
    "bm25": {
        "MRR@10": 0.8083333333333332,
        "nDCG@10": 0.5236951591919283,
        "MAP@10": 0.4383472222222222,
        "Recall@10": 0.51375,
        "P@10": 0.15749999999999992,
    },
    "neural": {
        "MRR@10": 0.905,
        "nDCG@10": 0.6406597131540072,
        "MAP@10": 0.6265000000000002,
        "Recall@10": 0.66625,
        "P@10": 0.23749999999999996,
    },
    "tfidf": {
        "MRR@10": 0.43019841269841275,
        "nDCG@10": 0.16367223159023314,
        "MAP@10": 0.14931216931216934,
        "Recall@10": 0.2195833333333333,
        "P@10": 0.07500000000000002,
    },
    "rrf_optimal": {
        "MRR@10": 0.9125,
        "nDCG@10": 0.6679172191726066,
        "MAP@10": 0.6654222883597883,
        "Recall@10": 0.7579166666666668,
        "P@10": 0.2674999999999999,
    },
    "combsum": {
        "MRR@10": 0.7550595238095238,
        "nDCG@10": 0.5348338169711432,
        "MAP@10": 0.4578902116402116,
        "Recall@10": 0.6441666666666668,
        "P@10": 0.22249999999999998,
    },
}

EXPECTED_SIGNIFICANCE = {
    "bm25_vs_neural": {
        "delta": -0.11696455396207879,
        "p_value": 0.0718,
        "significant_at_005": False,
    },
    "bm25_vs_tfidf": {
        "delta": 0.3600229276016952,
        "p_value": 0.0,
        "significant_at_005": True,
    },
    "neural_vs_tfidf": {
        "delta": 0.4769874815637739,
        "p_value": 0.0,
        "significant_at_005": True,
    },
}

EXPECTED_BEST_K = 5
EXPECTED_BEST_NDCG = 0.6679172191726066
EXPECTED_GRID = {
    "1": 0.6659319442343941,
    "5": 0.6679172191726066,
    "10": 0.6461159213441031,
    "20": 0.626859269797174,
    "30": 0.6160782819856003,
    "40": 0.5981984652176736,
    "50": 0.5885769154773014,
    "60": 0.589595899355405,
    "70": 0.5855567593169162,
    "80": 0.5815724126864452,
    "90": 0.5751817693064121,
    "100": 0.5687400116325657,
}

EXPECTED_RANKING = ["rrf_optimal", "neural", "combsum", "bm25", "tfidf"]


@pytest.fixture(scope="module")
def report():
    with open('/app/report.json') as f:
        return json.load(f)


class TestReportExists:
    """Check report file exists before other tests."""

    def test_report_file_exists(self):
        assert os.path.exists('/app/report.json'), \
            "/app/report.json does not exist"

    def test_report_is_valid_json(self):
        with open('/app/report.json') as f:
            data = json.load(f)
        assert isinstance(data, dict)


class TestReportStructure:
    """Verify report has required top-level sections."""

    def test_has_systems(self, report):
        assert 'systems' in report

    def test_has_trec_eval_ndcg(self, report):
        assert 'trec_eval_ndcg' in report

    def test_has_pairwise_significance(self, report):
        assert 'pairwise_significance' in report

    def test_has_fusion_optimization(self, report):
        assert 'fusion_optimization' in report

    def test_has_final_ranking(self, report):
        assert 'final_ranking' in report

    def test_systems_has_all_entries(self, report):
        for name in ['bm25', 'neural', 'tfidf', 'rrf_optimal', 'combsum']:
            assert name in report['systems'], f"Missing system '{name}'"

    def test_systems_have_all_metrics(self, report):
        for sys_name, metrics in report['systems'].items():
            for metric in ['MRR@10', 'nDCG@10', 'MAP@10', 'Recall@10', 'P@10']:
                assert metric in metrics, \
                    f"System '{sys_name}' missing metric '{metric}'"


class TestBaseSystemMetrics:
    """Verify metric values for the three base retrieval systems."""

    @pytest.mark.parametrize("sys_name", ['bm25', 'neural', 'tfidf'])
    @pytest.mark.parametrize("metric", ['MRR@10', 'nDCG@10', 'MAP@10', 'Recall@10', 'P@10'])
    def test_base_metric(self, report, sys_name, metric):
        got = report['systems'][sys_name][metric]
        exp = EXPECTED_SYSTEMS[sys_name][metric]
        assert abs(got - exp) < TOLERANCE, \
            f"{sys_name} {metric}: got {got}, expected {exp}"


class TestFusionMetrics:
    """Verify metric values for fused systems."""

    @pytest.mark.parametrize("metric", ['MRR@10', 'nDCG@10', 'MAP@10', 'Recall@10', 'P@10'])
    def test_rrf_optimal_metric(self, report, metric):
        got = report['systems']['rrf_optimal'][metric]
        exp = EXPECTED_SYSTEMS['rrf_optimal'][metric]
        assert abs(got - exp) < TOLERANCE, \
            f"rrf_optimal {metric}: got {got}, expected {exp}"

    @pytest.mark.parametrize("metric", ['MRR@10', 'nDCG@10', 'MAP@10', 'Recall@10', 'P@10'])
    def test_combsum_metric(self, report, metric):
        got = report['systems']['combsum'][metric]
        exp = EXPECTED_SYSTEMS['combsum'][metric]
        assert abs(got - exp) < TOLERANCE, \
            f"combsum {metric}: got {got}, expected {exp}"


class TestTrecEvalValidation:
    """Verify trec_eval cross-validation values.

    The trec_eval binary and the custom Python nDCG implementation may
    produce slightly different values due to implementation details
    (tie-breaking, rounding, document handling). Tests verify that:
    1. The report contains trec_eval values for all base systems.
    2. The trec_eval values cross-validate with Python nDCG within a
       reasonable tolerance.
    3. The trec_eval values preserve the same system ranking as Python.
    4. An independent trec_eval run reproduces the reported values exactly.
    """

    def test_trec_eval_has_all_systems(self, report):
        for name in ['bm25', 'neural', 'tfidf']:
            assert name in report['trec_eval_ndcg'], \
                f"Missing '{name}' in trec_eval_ndcg"

    @pytest.mark.parametrize("sys_name", ['bm25', 'neural', 'tfidf'])
    def test_trec_eval_cross_validates_python(self, report, sys_name):
        """trec_eval and Python nDCG should agree within tolerance."""
        trec_val = report['trec_eval_ndcg'][sys_name]
        python_val = report['systems'][sys_name]['nDCG@10']
        assert abs(trec_val - python_val) < CROSS_VALIDATION_TOLERANCE, \
            f"{sys_name}: trec_eval={trec_val} vs python={python_val}, " \
            f"diff={abs(trec_val - python_val)}"

    def test_trec_eval_preserves_system_ordering(self, report):
        """trec_eval nDCG ranking should match Python nDCG ranking."""
        trec = report['trec_eval_ndcg']
        python_scores = {name: report['systems'][name]['nDCG@10']
                        for name in ['bm25', 'neural', 'tfidf']}
        trec_order = sorted(trec, key=lambda x: trec[x], reverse=True)
        python_order = sorted(python_scores,
                             key=lambda x: python_scores[x], reverse=True)
        assert trec_order == python_order, \
            f"Ordering mismatch: trec={trec_order}, python={python_order}"

    def test_independent_trec_eval_verification(self, report):
        """Run trec_eval independently to verify report values."""
        tmpdir = tempfile.mkdtemp()
        for sys_name in ['bm25', 'neural', 'tfidf']:
            trec_path = os.path.join(tmpdir, f'{sys_name}.trec')
            with open(f'/app/data/run_{sys_name}.tsv') as f_in, \
                 open(trec_path, 'w') as f_out:
                for line in f_in:
                    parts = line.strip().split('\t')
                    qid, pid, rank = parts[0], parts[1], int(parts[2])
                    score = 1000 - rank + 1
                    f_out.write(f"{qid} Q0 {pid} {rank} {score} {sys_name}\n")
            result = subprocess.run(
                ['trec_eval', '-m', 'ndcg_cut.10',
                 '/app/data/qrels.tsv', trec_path],
                capture_output=True, text=True
            )
            for line in result.stdout.strip().split('\n'):
                parts = line.split()
                if len(parts) >= 3 and 'ndcg_cut_10' in parts[0]:
                    trec_val = float(parts[2])
                    report_val = report['trec_eval_ndcg'][sys_name]
                    assert abs(trec_val - report_val) < TREC_TOLERANCE, \
                        f"{sys_name}: independent trec_eval={trec_val}, " \
                        f"report={report_val}"


class TestSignificance:
    """Verify pairwise significance test results."""

    def test_significance_has_all_pairs(self, report):
        for pair in ['bm25_vs_neural', 'bm25_vs_tfidf', 'neural_vs_tfidf']:
            assert pair in report['pairwise_significance'], \
                f"Missing pair '{pair}'"

    @pytest.mark.parametrize("pair",
                             ['bm25_vs_neural', 'bm25_vs_tfidf', 'neural_vs_tfidf'])
    def test_delta(self, report, pair):
        got = report['pairwise_significance'][pair]['delta']
        exp = EXPECTED_SIGNIFICANCE[pair]['delta']
        assert abs(got - exp) < TOLERANCE, \
            f"{pair} delta: got {got}, expected {exp}"

    @pytest.mark.parametrize("pair",
                             ['bm25_vs_neural', 'bm25_vs_tfidf', 'neural_vs_tfidf'])
    def test_p_value(self, report, pair):
        got = report['pairwise_significance'][pair]['p_value']
        exp = EXPECTED_SIGNIFICANCE[pair]['p_value']
        assert abs(got - exp) < P_TOLERANCE, \
            f"{pair} p_value: got {got}, expected {exp}"

    @pytest.mark.parametrize("pair",
                             ['bm25_vs_neural', 'bm25_vs_tfidf', 'neural_vs_tfidf'])
    def test_significance_conclusion(self, report, pair):
        got = report['pairwise_significance'][pair]['significant_at_005']
        exp = EXPECTED_SIGNIFICANCE[pair]['significant_at_005']
        assert got == exp, \
            f"{pair} significant_at_005: got {got}, expected {exp}"

    def test_bm25_neural_not_significant(self, report):
        """BM25 vs Neural should NOT be significant at alpha=0.05."""
        assert report['pairwise_significance']['bm25_vs_neural'][
            'significant_at_005'] is False

    def test_tfidf_comparisons_significant(self, report):
        """TF-IDF comparisons should be significant at alpha=0.05."""
        assert report['pairwise_significance']['bm25_vs_tfidf'][
            'significant_at_005'] is True
        assert report['pairwise_significance']['neural_vs_tfidf'][
            'significant_at_005'] is True


class TestFusionOptimization:
    """Verify RRF k-parameter grid search results."""

    def test_best_k(self, report):
        assert report['fusion_optimization']['best_k'] == EXPECTED_BEST_K, \
            f"best_k: got {report['fusion_optimization']['best_k']}, " \
            f"expected {EXPECTED_BEST_K}"

    def test_best_ndcg(self, report):
        got = report['fusion_optimization']['best_ndcg_10']
        assert abs(got - EXPECTED_BEST_NDCG) < TOLERANCE, \
            f"best_ndcg_10: got {got}, expected {EXPECTED_BEST_NDCG}"

    def test_grid_has_all_k_values(self, report):
        grid = report['fusion_optimization']['grid_results']
        for k in ['1', '5', '10', '20', '30', '40', '50', '60',
                   '70', '80', '90', '100']:
            assert k in grid, f"Missing k={k} in grid_results"

    @pytest.mark.parametrize("k", ['1', '5', '10', '20', '30', '40',
                                    '50', '60', '70', '80', '90', '100'])
    def test_grid_value(self, report, k):
        got = report['fusion_optimization']['grid_results'][k]
        exp = EXPECTED_GRID[k]
        assert abs(got - exp) < TOLERANCE, \
            f"grid k={k}: got {got}, expected {exp}"

    def test_best_k_matches_grid(self, report):
        """best_k should correspond to the highest nDCG in grid_results."""
        grid = report['fusion_optimization']['grid_results']
        best_k_str = str(report['fusion_optimization']['best_k'])
        best_from_grid = max(grid.values())
        assert abs(grid[best_k_str] - best_from_grid) < TOLERANCE

    def test_best_ndcg_matches_rrf_optimal(self, report):
        """best_ndcg_10 should match rrf_optimal nDCG@10."""
        fusion_ndcg = report['fusion_optimization']['best_ndcg_10']
        system_ndcg = report['systems']['rrf_optimal']['nDCG@10']
        assert abs(fusion_ndcg - system_ndcg) < TOLERANCE


class TestFinalRanking:
    """Verify final system ranking."""

    def test_ranking_length(self, report):
        assert len(report['final_ranking']) == 5

    def test_ranking_contains_all_systems(self, report):
        expected = {'bm25', 'neural', 'tfidf', 'rrf_optimal', 'combsum'}
        assert set(report['final_ranking']) == expected

    def test_ranking_order(self, report):
        assert report['final_ranking'] == EXPECTED_RANKING, \
            f"Ranking: got {report['final_ranking']}, " \
            f"expected {EXPECTED_RANKING}"

    def test_ranking_is_ndcg_descending(self, report):
        """Verify ranking corresponds to descending nDCG@10."""
        ranking = report['final_ranking']
        ndcg_values = [report['systems'][name]['nDCG@10'] for name in ranking]
        for i in range(len(ndcg_values) - 1):
            assert ndcg_values[i] >= ndcg_values[i + 1], \
                f"Ranking not descending at position {i}: " \
                f"{ranking[i]}={ndcg_values[i]} < " \
                f"{ranking[i+1]}={ndcg_values[i+1]}"
