"""Tests for search evaluation pipeline output correctness."""

import json
import os
import pytest

RESULTS_PATH = "/app/results.json"

# Reference metric values computed with correct formulas and aggregation.
REF = {
    'bm25':   {'ndcg@10': 0.7231, 'map@10': 0.5386, 'mrr': 0.6875, 'p@10': 0.6125},
    'dense':  {'ndcg@10': 0.9375, 'map@10': 1.0,    'mrr': 1.0,    'p@10': 0.675},
    'sparse': {'ndcg@10': 0.9867, 'map@10': 0.9886, 'mrr': 1.0,    'p@10': 0.675},
}
REF_FUSION = {
    'rrf':     {'ndcg@10': 0.9823},
    'combsum': {'ndcg@10': 0.9956},
    'combmnz': {'ndcg@10': 0.9841},
}

TOLERANCE = 0.01


@pytest.fixture
def results():
    """Load results.json produced by the pipeline."""
    assert os.path.exists(RESULTS_PATH), \
        f"{RESULTS_PATH} not found - pipeline may not have been run"
    with open(RESULTS_PATH) as f:
        return json.load(f)


class TestOutputSchema:
    """Verify the output JSON has all required fields and structure."""

    def test_top_level_keys(self, results):
        required = {"individual_systems", "fusion_methods", "best_method",
                     "best_ndcg", "improvement_over_best_single",
                     "significance_tests"}
        missing = required - set(results.keys())
        assert not missing, f"Missing top-level keys: {missing}"

    def test_individual_system_keys(self, results):
        for sys_name in ["bm25", "dense", "sparse"]:
            assert sys_name in results["individual_systems"], \
                f"Missing system: {sys_name}"
            for metric in ["ndcg@10", "map@10", "mrr", "p@10"]:
                assert metric in results["individual_systems"][sys_name], \
                    f"Missing metric {metric} for {sys_name}"

    def test_fusion_method_keys(self, results):
        for method in ["rrf", "combsum", "combmnz"]:
            assert method in results["fusion_methods"], \
                f"Missing fusion method: {method}"
            for metric in ["ndcg@10", "map@10", "mrr", "p@10"]:
                assert metric in results["fusion_methods"][method], \
                    f"Missing metric {metric} for fusion method {method}"
        assert "best_k" in results["fusion_methods"]["rrf"], \
            "RRF must include best_k"
        assert "best_weights" in results["fusion_methods"]["combsum"], \
            "CombSUM must include best_weights"

    def test_best_weights_format(self, results):
        w = results["fusion_methods"]["combsum"]["best_weights"]
        assert isinstance(w, list) and len(w) == 3, \
            "best_weights must be a list of 3 floats"
        assert all(isinstance(x, (int, float)) for x in w), \
            "best_weights elements must be numeric"
        assert sum(w) > 0, "best_weights must not be all-zero"

    def test_significance_tests_structure(self, results):
        sig = results["significance_tests"]
        for pair in ["bm25_vs_dense", "bm25_vs_sparse", "dense_vs_sparse"]:
            assert pair in sig, f"Missing significance pair: {pair}"
            assert "p_value" in sig[pair], \
                f"Missing p_value for {pair}"
            assert "significant" in sig[pair], \
                f"Missing significant flag for {pair}"


class TestIndividualSystems:
    """Verify individual system metrics match reference values."""

    @pytest.mark.parametrize("sys_name,metric", [
        (s, m) for s in ["bm25", "dense", "sparse"]
        for m in ["ndcg@10", "map@10", "mrr", "p@10"]
    ])
    def test_system_metric(self, results, sys_name, metric):
        val = results["individual_systems"][sys_name][metric]
        ref = REF[sys_name][metric]
        assert abs(val - ref) < TOLERANCE, \
            f"{sys_name} {metric}: got {val:.4f}, expected ~{ref:.4f}"


class TestFusionMethods:
    """Verify fusion method results are correct."""

    @pytest.mark.parametrize("method", ["rrf", "combsum", "combmnz"])
    def test_fusion_ndcg(self, results, method):
        val = results["fusion_methods"][method]["ndcg@10"]
        ref = REF_FUSION[method]["ndcg@10"]
        assert abs(val - ref) < TOLERANCE, \
            f"{method} nDCG@10: got {val:.4f}, expected ~{ref:.4f}"

    def test_rrf_best_k_positive_int(self, results):
        k = results["fusion_methods"]["rrf"]["best_k"]
        assert isinstance(k, int) and k > 0, \
            f"best_k must be a positive integer, got {k}"

    def test_rrf_beats_bm25(self, results):
        rrf = results["fusion_methods"]["rrf"]["ndcg@10"]
        bm25 = results["individual_systems"]["bm25"]["ndcg@10"]
        assert rrf > bm25, "RRF should outperform BM25"

    def test_combsum_competitive(self, results):
        combsum = results["fusion_methods"]["combsum"]["ndcg@10"]
        best_single = max(
            results["individual_systems"][s]["ndcg@10"]
            for s in ["bm25", "dense", "sparse"]
        )
        assert combsum >= best_single - TOLERANCE, \
            "CombSUM should be competitive with best individual system"

    def test_combmnz_beats_bm25(self, results):
        combmnz = results["fusion_methods"]["combmnz"]["ndcg@10"]
        bm25 = results["individual_systems"]["bm25"]["ndcg@10"]
        assert combmnz > bm25, "CombMNZ should outperform BM25"

    def test_fusion_metrics_all_present(self, results):
        """Each fusion method must report all four metrics."""
        for method in ["rrf", "combsum", "combmnz"]:
            for metric in ["ndcg@10", "map@10", "mrr", "p@10"]:
                val = results["fusion_methods"][method][metric]
                assert isinstance(val, float), \
                    f"{method} {metric} should be float, got {type(val)}"


class TestBestMethod:
    """Verify the best method is correctly identified."""

    def test_best_method_valid(self, results):
        valid = {"bm25", "dense", "sparse", "rrf", "combsum", "combmnz"}
        assert results["best_method"] in valid, \
            f"best_method must be one of {valid}"

    def test_best_method_is_combsum(self, results):
        assert results["best_method"] == "combsum", \
            f"Expected best_method='combsum', got '{results['best_method']}'"

    def test_best_ndcg_consistent(self, results):
        best = results["best_method"]
        if best in results["individual_systems"]:
            expected = results["individual_systems"][best]["ndcg@10"]
        else:
            expected = results["fusion_methods"][best]["ndcg@10"]
        assert abs(results["best_ndcg"] - expected) < 0.001, \
            "best_ndcg must match the nDCG@10 of best_method"

    def test_improvement_positive(self, results):
        assert results["improvement_over_best_single"] > 0, \
            "Improvement over best single system should be positive"

    def test_improvement_consistent(self, results):
        best_single_ndcg = max(
            results["individual_systems"][s]["ndcg@10"]
            for s in ["bm25", "dense", "sparse"]
        )
        expected = results["best_ndcg"] - best_single_ndcg
        assert abs(results["improvement_over_best_single"] - expected) < 0.001, \
            "improvement_over_best_single must equal best_ndcg - best_single_ndcg"


class TestSignificanceTests:
    """Verify significance tests are correctly computed."""

    def test_p_values_in_range(self, results):
        for pair in ["bm25_vs_dense", "bm25_vs_sparse", "dense_vs_sparse"]:
            p = results["significance_tests"][pair]["p_value"]
            assert 0.0 <= p <= 1.0, \
                f"{pair} p_value={p} not in [0, 1]"

    def test_significant_is_boolean(self, results):
        for pair in ["bm25_vs_dense", "bm25_vs_sparse", "dense_vs_sparse"]:
            sig = results["significance_tests"][pair]["significant"]
            assert isinstance(sig, bool), \
                f"{pair} 'significant' should be bool, got {type(sig)}"

    def test_significant_consistency(self, results):
        """significant should be True iff p_value < 0.05."""
        for pair in ["bm25_vs_dense", "bm25_vs_sparse", "dense_vs_sparse"]:
            p = results["significance_tests"][pair]["p_value"]
            sig = results["significance_tests"][pair]["significant"]
            assert sig == (p < 0.05), \
                f"{pair}: significant={sig} but p_value={p:.4f}"

    def test_bm25_vs_sparse_significant(self, results):
        """BM25 and sparse have very different nDCG@10 -- should be significant."""
        p = results["significance_tests"]["bm25_vs_sparse"]["p_value"]
        assert p < 0.10, \
            f"bm25 vs sparse should be significant (p={p:.4f}), " \
            f"large performance gap (0.72 vs 0.99)"

    def test_bm25_vs_dense_significant(self, results):
        """BM25 and dense have meaningfully different nDCG@10."""
        p = results["significance_tests"]["bm25_vs_dense"]["p_value"]
        assert p < 0.10, \
            f"bm25 vs dense should be significant (p={p:.4f}), " \
            f"large performance gap (0.72 vs 0.94)"


class TestMetricRanges:
    """Verify all metric values are in valid ranges."""

    def test_individual_metrics_in_range(self, results):
        for sys_name in ["bm25", "dense", "sparse"]:
            for metric in ["ndcg@10", "map@10", "mrr", "p@10"]:
                val = results["individual_systems"][sys_name][metric]
                assert 0.0 <= val <= 1.0, \
                    f"{sys_name} {metric} = {val} not in [0, 1]"

    def test_fusion_metrics_in_range(self, results):
        for method in ["rrf", "combsum", "combmnz"]:
            for metric in ["ndcg@10", "map@10", "mrr", "p@10"]:
                val = results["fusion_methods"][method][metric]
                assert 0.0 <= val <= 1.0, \
                    f"{method} {metric} = {val} not in [0, 1]"

    def test_system_ordering(self, results):
        """Sparse should outperform BM25 on nDCG@10."""
        sparse = results["individual_systems"]["sparse"]["ndcg@10"]
        bm25 = results["individual_systems"]["bm25"]["ndcg@10"]
        assert sparse > bm25, "Sparse nDCG should be higher than BM25 nDCG"

    def test_dense_beats_bm25(self, results):
        """Dense should outperform BM25 on nDCG@10."""
        dense = results["individual_systems"]["dense"]["ndcg@10"]
        bm25 = results["individual_systems"]["bm25"]["ndcg@10"]
        assert dense > bm25, "Dense nDCG should be higher than BM25 nDCG"
