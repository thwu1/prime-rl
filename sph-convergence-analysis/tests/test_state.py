"""
Tests for SPH simulation quality assessment.

Validates the analysis pipeline output against known data properties
including planted outliers and 2nd-order convergence structure.

"""
import json
import math
import os
import subprocess

import pytest


@pytest.fixture(scope="session")
def run_analysis():
    """Run the analysis script."""
    result = subprocess.run(
        ["python3", "/app/sph_regression.py"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=120,
    )
    return result


@pytest.fixture(scope="session")
def results(run_analysis):
    """Load results JSON, asserting the script succeeded."""
    assert run_analysis.returncode == 0, (
        "sph_regression.py failed (exit {})\nstderr: {}\nstdout: {}".format(
            run_analysis.returncode, run_analysis.stderr, run_analysis.stdout
        )
    )
    results_path = "/app/results.json"
    assert os.path.exists(results_path), "results.json not created"
    with open(results_path) as f:
        data = json.load(f)
    return data


# -- Build System -------------------------------------------------------------


class TestBuildSystem:
    """Verify the validation and analysis pipeline."""

    def test_make_check_succeeds(self):
        """The Makefile check target must complete successfully."""
        result = subprocess.run(
            ["make", "-C", "/app", "check"],
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert result.returncode == 0, (
            "make check failed:\nstdout: {}\nstderr: {}".format(
                result.stdout, result.stderr
            )
        )


# -- Structure -----------------------------------------------------------------


class TestOutputStructure:
    def test_top_level_keys(self, results):
        required = {
            "similarity_analysis",
            "ensemble_convergence",
            "spatial_convergence",
            "outlier_detection",
            "overall_assessment",
        }
        assert required.issubset(set(results.keys()))

    def test_similarity_has_all_resolutions(self, results):
        for res in ["fine", "medium", "coarse"]:
            assert res in results["similarity_analysis"], "Missing resolution " + res

    def test_similarity_has_all_quantities(self, results):
        for res in ["fine", "medium", "coarse"]:
            for qty in ["Pressure", "TotalMechanicalEnergy"]:
                assert qty in results["similarity_analysis"][res]

    def test_similarity_entry_fields(self, results):
        entry = results["similarity_analysis"]["fine"]["Pressure"]["run_0"]
        assert "distance" in entry
        assert "within_threshold" in entry
        assert isinstance(entry["distance"], (int, float))
        assert isinstance(entry["within_threshold"], bool)

    def test_convergence_has_quantities(self, results):
        for qty in ["Pressure", "TotalMechanicalEnergy"]:
            r = results["spatial_convergence"][qty]
            assert "convergence_order" in r
            assert "extrapolated_value" in r
            assert "values_used" in r
            for res in ["fine", "medium", "coarse"]:
                assert res in r["values_used"]

    def test_overall_assessment_fields(self, results):
        oa = results["overall_assessment"]
        assert "all_similarity_pass" in oa
        assert "all_converged" in oa
        assert "expected_convergence_order" in oa
        assert "outlier_runs" in oa
        assert isinstance(oa["outlier_runs"], list)


# -- Similarity Computation ---------------------------------------------------


class TestSimilarityComputation:
    def test_identical_series_zero_distance(self, results):
        """Identical series should yield zero distance."""
        d = results["similarity_analysis"]["fine"]["Pressure"]["run_0"]["distance"]
        assert abs(d) < 1e-10, "Expected ~0 for identical series, got {}".format(d)

    def test_zero_offset_energy(self, results):
        d = results["similarity_analysis"]["coarse"]["TotalMechanicalEnergy"]["run_0"]["distance"]
        assert abs(d) < 1e-10

    def test_small_offset_nonzero(self, results):
        d = results["similarity_analysis"]["fine"]["Pressure"]["run_1"]["distance"]
        assert 0 < d < 0.001

    def test_positive_negative_symmetry(self, results):
        """Equal positive and negative offsets should give identical distances."""
        d1 = results["similarity_analysis"]["fine"]["Pressure"]["run_1"]["distance"]
        d3 = results["similarity_analysis"]["fine"]["Pressure"]["run_3"]["distance"]
        assert abs(d1 - d3) < 1e-12

    def test_larger_offset_larger_distance(self, results):
        d1 = results["similarity_analysis"]["fine"]["Pressure"]["run_1"]["distance"]
        d2 = results["similarity_analysis"]["fine"]["Pressure"]["run_2"]["distance"]
        assert d2 > d1

    def test_offset_ratio(self, results):
        """Distance should scale proportionally with constant offset magnitude."""
        d1 = results["similarity_analysis"]["fine"]["Pressure"]["run_1"]["distance"]
        d2 = results["similarity_analysis"]["fine"]["Pressure"]["run_2"]["distance"]
        ratio = d2 / d1
        assert 1.8 < ratio < 2.2, "Expected ratio ~2, got {}".format(ratio)

    def test_outlier_much_larger(self, results):
        """Outlier run distance should be orders of magnitude larger."""
        d0 = results["similarity_analysis"]["medium"]["Pressure"]["run_1"]["distance"]
        d5 = results["similarity_analysis"]["medium"]["Pressure"]["run_5"]["distance"]
        assert d5 > 100 * d0

    def test_all_pass_threshold(self, results):
        for res in results["similarity_analysis"]:
            for qty in results["similarity_analysis"][res]:
                for run, entry in results["similarity_analysis"][res][qty].items():
                    assert entry["within_threshold"], (
                        "{}/{}/{}: distance {} not within threshold".format(
                            res, qty, run, entry["distance"]
                        )
                    )

    def test_non_negative(self, results):
        for res in results["similarity_analysis"]:
            for qty in results["similarity_analysis"][res]:
                for run, entry in results["similarity_analysis"][res][qty].items():
                    assert entry["distance"] >= 0

    def test_cross_quantity_consistency(self, results):
        """Same constant offset should produce same distance regardless of quantity."""
        d_p = results["similarity_analysis"]["fine"]["Pressure"]["run_1"]["distance"]
        d_e = results["similarity_analysis"]["fine"]["TotalMechanicalEnergy"]["run_1"]["distance"]
        assert abs(d_p - d_e) < 1e-10


# -- Outlier Detection --------------------------------------------------------


class TestOutlierDetection:
    def test_pressure_outlier_detected(self, results):
        entry = results["outlier_detection"]["medium"]["Pressure"]["run_5"]
        assert entry["is_outlier"], "run_5 should be flagged for Pressure"

    def test_energy_outlier_detected(self, results):
        entry = results["outlier_detection"]["medium"]["TotalMechanicalEnergy"]["run_5"]
        assert entry["is_outlier"], "run_5 should be flagged for Energy"

    def test_outlier_score_exceeds_threshold(self, results):
        z = results["outlier_detection"]["medium"]["Pressure"]["run_5"]["outlier_score"]
        assert abs(z) > 3.5

    def test_fine_no_outliers(self, results):
        for qty in results["outlier_detection"]["fine"]:
            for run, entry in results["outlier_detection"]["fine"][qty].items():
                assert not entry["is_outlier"], (
                    "fine/{}/{} falsely flagged".format(qty, run)
                )

    def test_coarse_no_outliers(self, results):
        for qty in results["outlier_detection"]["coarse"]:
            for run, entry in results["outlier_detection"]["coarse"][qty].items():
                assert not entry["is_outlier"], (
                    "coarse/{}/{} falsely flagged".format(qty, run)
                )

    def test_medium_normal_runs_clean(self, results):
        for qty in ["Pressure", "TotalMechanicalEnergy"]:
            for i in range(5):
                run = "run_{}".format(i)
                entry = results["outlier_detection"]["medium"][qty][run]
                assert not entry["is_outlier"], (
                    "medium/{}/{} falsely flagged, score={}".format(
                        qty, run, entry["outlier_score"]
                    )
                )


# -- Spatial Convergence -------------------------------------------------------


class TestSpatialConvergence:
    def test_pressure_convergence_order(self, results):
        p = results["spatial_convergence"]["Pressure"]["convergence_order"]
        assert abs(p - 2.0) < 0.05, "Expected p~2.0, got {}".format(p)

    def test_energy_convergence_order(self, results):
        p = results["spatial_convergence"]["TotalMechanicalEnergy"]["convergence_order"]
        assert abs(p - 2.0) < 0.05, "Expected p~2.0, got {}".format(p)

    def test_extrapolated_refines_fine(self, results):
        r = results["spatial_convergence"]["Pressure"]
        f_ext = r["extrapolated_value"]
        f_fine = r["values_used"]["fine"]
        f_med = r["values_used"]["medium"]
        assert abs(f_ext - f_fine) < abs(f_fine - f_med)

    def test_monotone_resolution_ordering(self, results):
        r = results["spatial_convergence"]["Pressure"]
        f_ext = r["extrapolated_value"]
        d_fine = abs(r["values_used"]["fine"] - f_ext)
        d_med = abs(r["values_used"]["medium"] - f_ext)
        d_coarse = abs(r["values_used"]["coarse"] - f_ext)
        assert d_fine < d_med < d_coarse

    def test_values_plausible_range(self, results):
        for qty in ["Pressure", "TotalMechanicalEnergy"]:
            for res in ["fine", "medium", "coarse"]:
                v = results["spatial_convergence"][qty]["values_used"][res]
                assert 0.0 < v < 2.0, "{}/{} value {} out of range".format(qty, res, v)

    def test_convergence_order_with_clean_data(self, results):
        p = results["spatial_convergence"]["Pressure"]["convergence_order"]
        assert p > 1.5, "Order {} too low -- data quality issue".format(p)


# -- Ensemble Convergence -----------------------------------------------------


class TestEnsembleConvergence:
    def test_all_mean_converged(self, results):
        for res in results["ensemble_convergence"]:
            for qty in results["ensemble_convergence"][res]:
                assert results["ensemble_convergence"][res][qty]["mean_converged"], (
                    "{}/{} mean not converged".format(res, qty)
                )

    def test_all_variance_converged(self, results):
        for res in results["ensemble_convergence"]:
            for qty in results["ensemble_convergence"][res]:
                assert results["ensemble_convergence"][res][qty]["variance_converged"], (
                    "{}/{} variance not converged".format(res, qty)
                )

    def test_variance_non_negative(self, results):
        for res in results["ensemble_convergence"]:
            for qty in results["ensemble_convergence"][res]:
                v = results["ensemble_convergence"][res][qty]["temporal_mean_of_ensemble_variance"]
                assert v >= 0

    def test_variance_very_small(self, results):
        for res in results["ensemble_convergence"]:
            for qty in results["ensemble_convergence"][res]:
                v = results["ensemble_convergence"][res][qty]["temporal_mean_of_ensemble_variance"]
                assert v < 1e-5, "{}/{} variance {} too large".format(res, qty, v)

    def test_mean_plausible(self, results):
        for res in results["ensemble_convergence"]:
            for qty in results["ensemble_convergence"][res]:
                m = results["ensemble_convergence"][res][qty]["temporal_mean_of_ensemble_mean"]
                assert 0.0 < m < 2.0


# -- Overall Assessment -------------------------------------------------------


class TestOverallAssessment:
    def test_all_similarity_pass(self, results):
        assert results["overall_assessment"]["all_similarity_pass"] is True

    def test_all_converged(self, results):
        assert results["overall_assessment"]["all_converged"] is True

    def test_convergence_order_near_two(self, results):
        p = results["overall_assessment"]["expected_convergence_order"]
        assert abs(p - 2.0) < 0.1

    def test_outliers_include_medium(self, results):
        outliers = results["overall_assessment"]["outlier_runs"]
        medium_outliers = [r for r in outliers if "medium" in r and "run_5" in r]
        assert len(medium_outliers) >= 2, (
            "Expected at least 2 medium/*/run_5 entries, got {}".format(medium_outliers)
        )

    def test_no_false_positives_in_list(self, results):
        outliers = results["overall_assessment"]["outlier_runs"]
        for entry in outliers:
            assert "medium" in entry and "run_5" in entry, (
                "Unexpected entry: {}".format(entry)
            )


# -- Data Quality Dependencies -------------------------------------------------


class TestDataQualityDependencies:
    def test_medium_mean_convergence(self, results):
        assert results["ensemble_convergence"]["medium"]["Pressure"]["mean_converged"]

    def test_convergence_order_consistency(self, results):
        p = results["spatial_convergence"]["Pressure"]["convergence_order"]
        assert abs(p - 2.0) < 0.1
