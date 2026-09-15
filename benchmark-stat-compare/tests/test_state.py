"""Statistical benchmark analysis tool verification tests."""

import json
import os
import subprocess
import tempfile

import numpy as np
import pytest


RESULTS_DIR = "/app/data/results"
ANALYZE_SCRIPT = "/app/analyze.py"


def run_analysis(metric, alpha=0.05, tmp_path=None):
    """Run the analysis tool and return parsed output."""
    if tmp_path is None:
        tmp_path = tempfile.mkdtemp()
    output_path = os.path.join(tmp_path, f"output_{metric.replace(' ', '_')}.json")
    result = subprocess.run(
        [
            "python3",
            ANALYZE_SCRIPT,
            "--results-dir",
            RESULTS_DIR,
            "--output",
            output_path,
            "--metric",
            metric,
            "--alpha",
            str(alpha),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"analyze.py failed with code {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert os.path.exists(output_path), f"Output file not created at {output_path}"
    with open(output_path) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def auc_output(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("auc")
    return run_analysis("AUC", tmp_path=str(tmp))


@pytest.fixture(scope="module")
def logloss_output(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("logloss")
    return run_analysis("Log Loss", tmp_path=str(tmp))


@pytest.fixture(scope="module")
def auc_alpha10(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("auc_alpha10")
    return run_analysis("AUC", alpha=0.10, tmp_path=str(tmp))


class TestOutputCompleteness:
    """Verify all required fields are present."""

    def test_required_fields(self, auc_output):
        required = [
            "metric",
            "direction",
            "alpha",
            "n_models",
            "n_datasets",
            "model_dataset_means",
            "average_ranks",
            "friedman_chi2",
            "friedman_p_value",
            "iman_davenport_f",
            "iman_davenport_p_value",
            "nemenyi_cd",
            "significant_pairs",
            "cliques",
            "pairwise_wilcoxon",
        ]
        for field in required:
            assert field in auc_output, f"Missing required field: {field}"


class TestDirectionInference:
    """Verify metric direction is correctly inferred."""

    def test_auc_maximize(self, auc_output):
        assert auc_output["direction"] == "maximize"

    def test_logloss_minimize(self, logloss_output):
        assert logloss_output["direction"] == "minimize"


class TestRobustness:
    """Verify the tool handles non-model JSON files in the results directory."""

    def test_n_models_correct(self, auc_output):
        """Non-model JSON files must be silently skipped."""
        assert auc_output["n_models"] == 5

    def test_no_spurious_models(self, auc_output):
        """Only actual model results should appear in output."""
        expected_models = {"XGBoost", "LightGBM", "CatBoost", "RandomForest", "LinearModel"}
        actual_models = set(auc_output["model_dataset_means"].keys())
        assert actual_models == expected_models, (
            f"Unexpected models in output: {actual_models - expected_models}"
        )


class TestMetadata:
    """Verify basic metadata."""

    def test_n_models(self, auc_output):
        assert auc_output["n_models"] == 5

    def test_n_datasets(self, auc_output):
        assert auc_output["n_datasets"] == 8

    def test_metric_name(self, auc_output):
        assert auc_output["metric"] == "AUC"

    def test_alpha(self, auc_output):
        assert auc_output["alpha"] == 0.05


class TestNaNHandling:
    """Verify NaN fold values are excluded from mean computation."""

    def test_nan_excluded_auc(self, auc_output):
        # LinearModel on jasmine: [0.710, 0.700, null, 0.690, 0.710]
        # Mean should be (0.710+0.700+0.690+0.710)/4 = 0.7025
        lm_jasmine = auc_output["model_dataset_means"]["LinearModel"]["jasmine"]
        assert abs(lm_jasmine - 0.7025) < 1e-6, (
            f"LinearModel jasmine AUC mean should be 0.7025 (NaN excluded), got {lm_jasmine}"
        )

    def test_nan_excluded_logloss(self, logloss_output):
        # LinearModel on jasmine Log Loss: [0.650, 0.670, null, 0.680, 0.650]
        # Mean should be (0.650+0.670+0.680+0.650)/4 = 0.6625
        lm_jasmine = logloss_output["model_dataset_means"]["LinearModel"]["jasmine"]
        assert abs(lm_jasmine - 0.6625) < 1e-6, (
            f"LinearModel jasmine Log Loss mean should be 0.6625, got {lm_jasmine}"
        )


class TestMeanComputation:
    """Verify per-model per-dataset means are correct."""

    EXPECTED_AUC_MEANS = {
        "XGBoost": {
            "credit-g": 0.790,
            "phoneme": 0.914,
            "electricity": 0.876,
            "vehicle": 0.946,
            "jasmine": 0.826,
            "credit-approval": 0.906,
            "balance-scale": 0.866,
            "splice": 0.936,
        },
        "LightGBM": {
            "credit-g": 0.790,
            "phoneme": 0.904,
            "electricity": 0.866,
            "vehicle": 0.936,
            "jasmine": 0.836,
            "credit-approval": 0.896,
            "balance-scale": 0.856,
            "splice": 0.926,
        },
        "CatBoost": {
            "credit-g": 0.800,
            "phoneme": 0.896,
            "electricity": 0.886,
            "vehicle": 0.926,
            "jasmine": 0.816,
            "credit-approval": 0.916,
            "balance-scale": 0.876,
            "splice": 0.916,
        },
        "RandomForest": {
            "credit-g": 0.750,
            "phoneme": 0.866,
            "electricity": 0.826,
            "vehicle": 0.896,
            "jasmine": 0.786,
            "credit-approval": 0.866,
            "balance-scale": 0.826,
            "splice": 0.886,
        },
        "LinearModel": {
            "credit-g": 0.710,
            "phoneme": 0.786,
            "electricity": 0.746,
            "vehicle": 0.816,
            "jasmine": 0.7025,
            "credit-approval": 0.786,
            "balance-scale": 0.746,
            "splice": 0.806,
        },
    }

    def test_all_means(self, auc_output):
        for model, datasets in self.EXPECTED_AUC_MEANS.items():
            for dataset, expected in datasets.items():
                actual = auc_output["model_dataset_means"][model][dataset]
                assert abs(actual - expected) < 1e-6, (
                    f"Mean mismatch {model}/{dataset}: expected {expected}, got {actual}"
                )


class TestRankComputation:
    """Verify average rank computation including tie handling."""

    def test_auc_ranks_with_tie(self, auc_output):
        # XGBoost and LightGBM tie on credit-g (both 0.790)
        expected = {
            "XGBoost": 1.6875,
            "CatBoost": 2.0,
            "LightGBM": 2.3125,
            "RandomForest": 4.0,
            "LinearModel": 5.0,
        }
        for model, exp_rank in expected.items():
            actual = auc_output["average_ranks"][model]
            assert abs(actual - exp_rank) < 1e-3, (
                f"Rank mismatch for {model}: expected {exp_rank}, got {actual}"
            )

    def test_logloss_ranks_no_tie(self, logloss_output):
        expected = {
            "XGBoost": 1.625,
            "CatBoost": 2.0,
            "LightGBM": 2.375,
            "RandomForest": 4.0,
            "LinearModel": 5.0,
        }
        for model, exp_rank in expected.items():
            actual = logloss_output["average_ranks"][model]
            assert abs(actual - exp_rank) < 1e-3, (
                f"Log Loss rank mismatch for {model}: expected {exp_rank}, got {actual}"
            )

    def test_tie_changes_ranks(self, auc_output, logloss_output):
        """The AUC tie on credit-g should make XGBoost/LightGBM ranks differ from Log Loss."""
        auc_xg = auc_output["average_ranks"]["XGBoost"]
        ll_xg = logloss_output["average_ranks"]["XGBoost"]
        assert abs(auc_xg - ll_xg) > 0.01, (
            "AUC and Log Loss should produce different XGBoost ranks due to tie on credit-g"
        )


class TestFriedmanTest:
    """Verify Friedman chi-squared test computation."""

    def test_friedman_chi2_auc(self, auc_output):
        assert abs(auc_output["friedman_chi2"] - 26.225) < 0.5, (
            f"Friedman chi2 expected ~26.225, got {auc_output['friedman_chi2']}"
        )

    def test_friedman_significant(self, auc_output):
        assert auc_output["friedman_p_value"] < 0.001, (
            "Friedman test should be highly significant"
        )

    def test_friedman_chi2_logloss(self, logloss_output):
        assert abs(logloss_output["friedman_chi2"] - 26.5) < 0.5, (
            f"Log Loss Friedman chi2 expected ~26.5, got {logloss_output['friedman_chi2']}"
        )

    def test_friedman_differs_by_metric(self, auc_output, logloss_output):
        """Different metrics should produce different Friedman statistics (tie effect)."""
        assert abs(auc_output["friedman_chi2"] - logloss_output["friedman_chi2"]) > 0.1


class TestImanDavenport:
    """Verify Iman-Davenport corrected F-statistic."""

    def test_iman_davenport_f(self, auc_output):
        assert abs(auc_output["iman_davenport_f"] - 31.788) < 1.0, (
            f"Iman-Davenport F expected ~31.788, got {auc_output['iman_davenport_f']}"
        )

    def test_iman_davenport_significant(self, auc_output):
        assert auc_output["iman_davenport_p_value"] < 0.001


class TestNemenyiCD:
    """Verify Nemenyi critical difference computation."""

    def test_nemenyi_cd_value(self, auc_output):
        assert abs(auc_output["nemenyi_cd"] - 2.157) < 0.15, (
            f"Nemenyi CD expected ~2.157, got {auc_output['nemenyi_cd']}"
        )

    def test_cd_positive(self, auc_output):
        assert auc_output["nemenyi_cd"] > 0


class TestSignificantPairs:
    """Verify identification of significantly different model pairs."""

    def test_significant_pairs_auc(self, auc_output):
        expected = {
            ("CatBoost", "LinearModel"),
            ("LightGBM", "LinearModel"),
            ("LinearModel", "XGBoost"),
            ("RandomForest", "XGBoost"),
        }
        actual = {tuple(sorted(p)) for p in auc_output["significant_pairs"]}
        assert actual == expected, (
            f"Significant pairs mismatch.\nExpected: {expected}\nActual: {actual}"
        )

    def test_pairs_sorted_alphabetically(self, auc_output):
        for pair in auc_output["significant_pairs"]:
            assert pair == sorted(pair), f"Pair {pair} not sorted alphabetically"


class TestCliques:
    """Verify identification of model cliques (CD diagram groups)."""

    def test_cliques_auc(self, auc_output):
        clique_sets = [frozenset(c) for c in auc_output["cliques"]]
        expected = [
            frozenset({"XGBoost", "CatBoost", "LightGBM"}),
            frozenset({"CatBoost", "LightGBM", "RandomForest"}),
            frozenset({"RandomForest", "LinearModel"}),
        ]
        for exp_clique in expected:
            assert exp_clique in clique_sets, (
                f"Expected clique {exp_clique} not found in {clique_sets}"
            )

    def test_cliques_count(self, auc_output):
        assert len(auc_output["cliques"]) == 3, (
            f"Expected 3 cliques, got {len(auc_output['cliques'])}"
        )

    def test_cliques_sorted_by_rank(self, auc_output):
        """Each clique should be sorted by average rank ascending."""
        ranks = auc_output["average_ranks"]
        for clique in auc_output["cliques"]:
            clique_ranks = [ranks[m] for m in clique]
            assert clique_ranks == sorted(clique_ranks), (
                f"Clique {clique} not sorted by rank"
            )

    def test_cliques_ordered_by_best_rank(self, auc_output):
        """Cliques should be ordered by their best (lowest) rank."""
        ranks = auc_output["average_ranks"]
        best_ranks = [ranks[c[0]] for c in auc_output["cliques"]]
        assert best_ranks == sorted(best_ranks), "Cliques not ordered by best rank"


class TestAlphaVariation:
    """Verify behavior changes appropriately with different significance levels."""

    def test_alpha_preserved(self, auc_alpha10):
        assert auc_alpha10["alpha"] == 0.10

    def test_cd_decreases_with_higher_alpha(self, auc_output, auc_alpha10):
        """Higher alpha (less conservative) should produce smaller critical difference."""
        assert auc_alpha10["nemenyi_cd"] < auc_output["nemenyi_cd"], (
            f"CD at alpha=0.10 ({auc_alpha10['nemenyi_cd']}) should be smaller "
            f"than CD at alpha=0.05 ({auc_output['nemenyi_cd']})"
        )

    def test_at_least_as_many_significant_pairs(self, auc_output, auc_alpha10):
        """Higher alpha should find at least as many significant pairs."""
        assert len(auc_alpha10["significant_pairs"]) >= len(auc_output["significant_pairs"]), (
            f"Alpha=0.10 found {len(auc_alpha10['significant_pairs'])} pairs, "
            f"alpha=0.05 found {len(auc_output['significant_pairs'])} pairs"
        )

    def test_cd_positive(self, auc_alpha10):
        assert auc_alpha10["nemenyi_cd"] > 0


class TestWilcoxonPairwise:
    """Verify pairwise Wilcoxon signed-rank tests."""

    def test_pair_count(self, auc_output):
        # C(5,2) = 10 pairs
        assert len(auc_output["pairwise_wilcoxon"]) == 10

    def test_pair_format(self, auc_output):
        for key, val in auc_output["pairwise_wilcoxon"].items():
            assert "-" in key, f"Pair key '{key}' should contain '-'"
            parts = key.split("-")
            assert len(parts) == 2, f"Pair key '{key}' should have exactly 2 models"
            assert parts[0] < parts[1], (
                f"Pair key '{key}' models not in alphabetical order"
            )
            assert "statistic" in val, f"Missing 'statistic' in {key}"
            assert "p_value" in val, f"Missing 'p_value' in {key}"
            assert "p_corrected" in val, f"Missing 'p_corrected' in {key}"
            assert "significant" in val, f"Missing 'significant' in {key}"
            assert isinstance(val["significant"], bool)

    def test_corrected_geq_raw(self, auc_output):
        """Corrected p-values should be >= raw p-values."""
        for key, val in auc_output["pairwise_wilcoxon"].items():
            assert val["p_corrected"] >= val["p_value"] - 1e-10, (
                f"Corrected p-value < raw for {key}: "
                f"{val['p_corrected']} < {val['p_value']}"
            )

    def test_p_values_bounded(self, auc_output):
        """All p-values should be in [0, 1]."""
        for key, val in auc_output["pairwise_wilcoxon"].items():
            assert 0 <= val["p_value"] <= 1, (
                f"Raw p-value out of range for {key}: {val['p_value']}"
            )
            assert 0 <= val["p_corrected"] <= 1, (
                f"Corrected p-value out of range for {key}: {val['p_corrected']}"
            )

    def test_significance_consistent(self, auc_output):
        """significant flag should match p_corrected < alpha."""
        alpha = auc_output["alpha"]
        for key, val in auc_output["pairwise_wilcoxon"].items():
            expected_sig = val["p_corrected"] < alpha
            assert val["significant"] == expected_sig, (
                f"Significance flag inconsistent for {key}: "
                f"p_corrected={val['p_corrected']}, alpha={alpha}, "
                f"flag={val['significant']}"
            )

    def test_extreme_pair_has_small_pvalue(self, auc_output):
        """XGBoost vs LinearModel should have a small raw p-value."""
        key = "LinearModel-XGBoost"
        val = auc_output["pairwise_wilcoxon"][key]
        assert val["p_value"] < 0.02, (
            f"XGBoost vs LinearModel raw p-value should be < 0.02, got {val['p_value']}"
        )

    def test_step_down_not_uniform(self, auc_output):
        """Correction must use step-down procedure, not uniform Bonferroni scaling."""
        pairs = auc_output["pairwise_wilcoxon"]
        n_pairs = len(pairs)
        has_tighter = False
        for val in pairs.values():
            bonf = min(val["p_value"] * n_pairs, 1.0)
            if val["p_corrected"] < bonf - 1e-10:
                has_tighter = True
                break
        assert has_tighter, (
            "All corrected p-values match uniform Bonferroni scaling — "
            "a step-down correction procedure is required"
        )

    def test_corrected_monotone_by_raw(self, auc_output):
        """Corrected p-values must be non-decreasing when sorted by raw p-value."""
        pairs = auc_output["pairwise_wilcoxon"]
        sorted_items = sorted(pairs.items(), key=lambda x: x[1]["p_value"])
        for i in range(1, len(sorted_items)):
            prev_corr = sorted_items[i - 1][1]["p_corrected"]
            curr_corr = sorted_items[i][1]["p_corrected"]
            assert curr_corr >= prev_corr - 1e-10, (
                f"Corrected p-values not monotone: "
                f"{sorted_items[i - 1][0]} ({prev_corr:.6f}) > "
                f"{sorted_items[i][0]} ({curr_corr:.6f})"
            )
