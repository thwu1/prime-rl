
"""
Verification tests for Mack Chain Ladder and Munich Chain Ladder
actuarial reserving pipeline.
"""

import json
import os
import subprocess
import pytest


@pytest.fixture(scope="session")
def pipeline_result():
    result = subprocess.run(
        ["Rscript", "/app/run_pipeline.R"],
        capture_output=True, text=True, cwd="/app", timeout=120
    )
    return result


@pytest.fixture(scope="session")
def results(pipeline_result):
    assert pipeline_result.returncode == 0, (
        f"Pipeline failed with exit code {pipeline_result.returncode}\n"
        f"stdout:\n{pipeline_result.stdout}\n"
        f"stderr:\n{pipeline_result.stderr}"
    )
    assert os.path.exists("/app/results.json"), "results.json not created"
    with open("/app/results.json") as f:
        return json.load(f)


class TestPipelineExecution:
    def test_pipeline_completes(self, pipeline_result):
        assert pipeline_result.returncode == 0

    def test_results_file_exists(self, pipeline_result):
        assert os.path.exists("/app/results.json")


class TestRequiredKeys:
    def test_has_raa_total_mack_se(self, results):
        assert "raa_total_mack_se" in results

    def test_has_genins_skewness(self, results):
        assert "genins_skewness" in results

    def test_has_genins_overall_skewness(self, results):
        assert "genins_overall_skewness" in results

    def test_has_mcl_paid_ultimate(self, results):
        assert "mcl_paid_ultimate" in results

    def test_has_mcl_incurred_ultimate(self, results):
        assert "mcl_incurred_ultimate" in results


class TestMackChainLadder:
    def test_raa_total_mack_se(self, results):
        """RAA Total Mack S.E. must equal 26880.74 (ChainLadder package golden value)."""
        assert abs(results["raa_total_mack_se"] - 26880.74) < 0.01, (
            f"RAA Total Mack S.E. = {results['raa_total_mack_se']}, expected 26880.74"
        )


class TestCornishFisherSkewness:
    def test_genins_skewness_length(self, results):
        assert len(results["genins_skewness"]) == 10, (
            f"Expected 10 skewness values, got {len(results['genins_skewness'])}"
        )

    def test_genins_skewness_values(self, results):
        """Per-origin skewness must match Dal Moro (2016) Table 1 values."""
        expected = [0.0, 0.0, -0.029, -0.043, -0.001, 0.180, 0.055, 0.267, 0.286, 0.314]
        for i, (got, exp) in enumerate(zip(results["genins_skewness"], expected)):
            assert abs(got - exp) < 0.002, (
                f"Skewness[{i}]: got {got:.6f}, expected {exp:.3f} (tol=0.002)"
            )

    def test_genins_overall_skewness(self, results):
        """Overall skewness across all origin periods must equal 0.214."""
        assert abs(results["genins_overall_skewness"] - 0.214) < 0.002, (
            f"Overall skewness = {results['genins_overall_skewness']}, expected 0.214"
        )


class TestMunichChainLadder:
    def test_mcl_paid_ultimate(self, results):
        """Total MCL Paid Ultimate must equal 34055.98 (Quarg & Mack 2004)."""
        assert abs(results["mcl_paid_ultimate"] - 34055.98) < 1.0, (
            f"MCL Paid Ultimate = {results['mcl_paid_ultimate']}, expected 34055.98"
        )

    def test_mcl_incurred_ultimate(self, results):
        """Total MCL Incurred Ultimate must equal 33291.31 (Quarg & Mack 2004)."""
        assert abs(results["mcl_incurred_ultimate"] - 33291.31) < 1.0, (
            f"MCL Incurred Ultimate = {results['mcl_incurred_ultimate']}, expected 33291.31"
        )

    def test_mcl_paid_exceeds_latest(self, results):
        """MCL Paid Ultimate must exceed Latest Paid (25525)."""
        assert results["mcl_paid_ultimate"] > 25525, (
            f"MCL Paid Ultimate ({results['mcl_paid_ultimate']}) should exceed Latest Paid (25525)"
        )

    def test_mcl_incurred_exceeds_latest(self, results):
        """MCL Incurred Ultimate must exceed Latest Incurred (29694)."""
        assert results["mcl_incurred_ultimate"] > 29694, (
            f"MCL Incurred Ultimate ({results['mcl_incurred_ultimate']}) should exceed Latest Incurred (29694)"
        )
