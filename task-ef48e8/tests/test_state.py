"""

Tests for the clinical evidence evaluation framework.
Runs the evaluation pipeline and verifies all output scores against
hand-computed expected values.
"""
import subprocess
import json
import math
import os
import pytest


@pytest.fixture(scope="module")
def scores():
    """Run the evaluation pipeline and return the output scores."""
    output_path = "/tmp/test_eval_scores.json"
    result = subprocess.run(
        ["python3", "/app/run_eval.py", "--output", output_path],
        capture_output=True,
        text=True,
        cwd="/app",
        timeout=120,
    )
    if result.returncode != 0:
        pytest.fail(
            f"Evaluation script failed (exit code {result.returncode}):\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )
    assert os.path.exists(output_path), f"Output file not created at {output_path}"
    with open(output_path) as f:
        return json.load(f)


# ---- Evidence Identification: Strict ----

class TestStrictEvidence:
    def test_micro_f1(self, scores):
        val = scores["evidence_identification"]["strict"]["micro_f1"]
        assert math.isclose(val, 20 / 29, abs_tol=1e-4), f"strict micro_f1={val}"

    def test_micro_precision(self, scores):
        val = scores["evidence_identification"]["strict"]["micro_precision"]
        assert math.isclose(val, 10 / 17, abs_tol=1e-4), f"strict micro_p={val}"

    def test_micro_recall(self, scores):
        val = scores["evidence_identification"]["strict"]["micro_recall"]
        assert math.isclose(val, 10 / 12, abs_tol=1e-4), f"strict micro_r={val}"

    def test_macro_f1(self, scores):
        val = scores["evidence_identification"]["strict"]["macro_f1"]
        assert math.isclose(val, 43 / 60, abs_tol=1e-4), f"strict macro_f1={val}"

    def test_macro_precision(self, scores):
        val = scores["evidence_identification"]["strict"]["macro_precision"]
        assert math.isclose(val, 23 / 36, abs_tol=1e-4), f"strict macro_p={val}"

    def test_macro_recall(self, scores):
        val = scores["evidence_identification"]["strict"]["macro_recall"]
        assert math.isclose(val, 31 / 36, abs_tol=1e-4), f"strict macro_r={val}"


# ---- Evidence Identification: Lenient ----

class TestLenientEvidence:
    def test_micro_f1(self, scores):
        val = scores["evidence_identification"]["lenient"]["micro_f1"]
        assert math.isclose(val, 5 / 6, abs_tol=1e-4), f"lenient micro_f1={val}"

    def test_micro_precision(self, scores):
        val = scores["evidence_identification"]["lenient"]["micro_precision"]
        assert math.isclose(val, 10 / 12, abs_tol=1e-4), f"lenient micro_p={val}"

    def test_micro_recall(self, scores):
        val = scores["evidence_identification"]["lenient"]["micro_recall"]
        assert math.isclose(val, 10 / 12, abs_tol=1e-4), f"lenient micro_r={val}"

    def test_macro_f1(self, scores):
        val = scores["evidence_identification"]["lenient"]["macro_f1"]
        assert math.isclose(val, 38 / 45, abs_tol=1e-4), f"lenient macro_f1={val}"

    def test_macro_precision(self, scores):
        val = scores["evidence_identification"]["lenient"]["macro_precision"]
        assert math.isclose(val, 8 / 9, abs_tol=1e-4), f"lenient macro_p={val}"

    def test_macro_recall(self, scores):
        val = scores["evidence_identification"]["lenient"]["macro_recall"]
        assert math.isclose(val, 31 / 36, abs_tol=1e-4), f"lenient macro_r={val}"

    def test_lenient_differs_from_strict(self, scores):
        """Lenient scores must differ from strict scores."""
        strict_f1 = scores["evidence_identification"]["strict"]["micro_f1"]
        lenient_f1 = scores["evidence_identification"]["lenient"]["micro_f1"]
        assert not math.isclose(strict_f1, lenient_f1, abs_tol=1e-4), (
            f"Lenient micro F1 ({lenient_f1}) should differ from strict ({strict_f1})"
        )


# ---- Bootstrap CIs ----

class TestBootstrapCI:
    def test_strict_ci_structure(self, scores):
        strict = scores["evidence_identification"]["strict"]
        lower = strict["bootstrap_ci_micro_f1_lower"]
        upper = strict["bootstrap_ci_micro_f1_upper"]
        micro_f1 = strict["micro_f1"]
        assert lower <= micro_f1 + 1e-4, f"CI lower {lower} > micro_f1 {micro_f1}"
        assert upper >= micro_f1 - 1e-4, f"CI upper {upper} < micro_f1 {micro_f1}"
        assert upper > lower, f"CI upper {upper} <= lower {lower}"

    def test_lenient_ci_structure(self, scores):
        lenient = scores["evidence_identification"]["lenient"]
        lower = lenient["bootstrap_ci_micro_f1_lower"]
        upper = lenient["bootstrap_ci_micro_f1_upper"]
        micro_f1 = lenient["micro_f1"]
        assert lower <= micro_f1 + 1e-4, f"CI lower {lower} > micro_f1 {micro_f1}"
        assert upper >= micro_f1 - 1e-4, f"CI upper {upper} < micro_f1 {micro_f1}"
        assert upper > lower, f"CI upper {upper} <= lower {lower}"

    def test_strict_ci_reasonable_width(self, scores):
        strict = scores["evidence_identification"]["strict"]
        width = strict["bootstrap_ci_micro_f1_upper"] - strict["bootstrap_ci_micro_f1_lower"]
        assert 0.01 < width < 0.8, f"CI width {width} seems unreasonable"


# ---- Standard Alignment ----

class TestStandardAlignment:
    def test_micro_f1(self, scores):
        val = scores["evidence_alignment"]["standard"]["micro_f1"]
        assert math.isclose(val, 13 / 17, abs_tol=1e-4), f"align micro_f1={val}"

    def test_micro_precision(self, scores):
        val = scores["evidence_alignment"]["standard"]["micro_precision"]
        assert math.isclose(val, 13 / 17, abs_tol=1e-4), f"align micro_p={val}"

    def test_micro_recall(self, scores):
        val = scores["evidence_alignment"]["standard"]["micro_recall"]
        assert math.isclose(val, 13 / 17, abs_tol=1e-4), f"align micro_r={val}"

    def test_macro_f1(self, scores):
        val = scores["evidence_alignment"]["standard"]["macro_f1"]
        assert math.isclose(val, 11 / 14, abs_tol=1e-4), f"align macro_f1={val}"


# ---- Weighted Alignment ----

class TestWeightedAlignment:
    def test_micro_f1(self, scores):
        val = scores["evidence_alignment"]["weighted"]["micro_f1"]
        assert math.isclose(val, 50 / 63, abs_tol=1e-4), f"weighted micro_f1={val}"

    def test_micro_precision(self, scores):
        val = scores["evidence_alignment"]["weighted"]["micro_precision"]
        assert math.isclose(val, 25 / 34, abs_tol=1e-4), f"weighted micro_p={val}"

    def test_micro_recall(self, scores):
        val = scores["evidence_alignment"]["weighted"]["micro_recall"]
        assert math.isclose(val, 25 / 29, abs_tol=1e-4), f"weighted micro_r={val}"

    def test_macro_f1(self, scores):
        val = scores["evidence_alignment"]["weighted"]["macro_f1"]
        assert math.isclose(val, 697 / 858, abs_tol=1e-4), f"weighted macro_f1={val}"

    def test_weighted_nonzero(self, scores):
        """Weighted alignment scores must not be zero (feature must be implemented)."""
        val = scores["evidence_alignment"]["weighted"]["micro_f1"]
        assert val > 0.01, f"Weighted alignment F1 is near zero ({val}), feature not implemented"


# ---- Krippendorff's Alpha ----

class TestKrippendorffAlpha:
    def test_alpha_value(self, scores):
        val = scores["inter_annotator_agreement"]["krippendorff_alpha"]
        assert math.isclose(val, 89 / 208, abs_tol=1e-3), f"alpha={val}"

    def test_alpha_nonzero(self, scores):
        """Alpha must not be zero (feature must be implemented)."""
        val = scores["inter_annotator_agreement"]["krippendorff_alpha"]
        assert val > 0.01, f"Alpha is near zero ({val}), feature not implemented"

    def test_alpha_range(self, scores):
        val = scores["inter_annotator_agreement"]["krippendorff_alpha"]
        assert -1.0 <= val <= 1.0, f"Alpha {val} out of valid range [-1, 1]"

    def test_alpha_is_not_kappa(self, scores):
        """Alpha must not be averaged pairwise kappa (wrong metric)."""
        val = scores["inter_annotator_agreement"]["krippendorff_alpha"]
        # Averaged pairwise kappa on the full data would give ~0.55-0.65
        # Krippendorff's alpha should be ~0.4279 (89/208)
        assert val < 0.50, (
            f"Alpha value {val} is suspiciously high — may be averaged pairwise kappa "
            f"instead of Krippendorff's alpha"
        )


# ---- R Cross-Validation ----

class TestRValidation:
    def test_r_alpha_present(self, scores):
        """R-validated alpha must be present in the output."""
        val = scores["inter_annotator_agreement"]["r_validated_alpha"]
        assert val is not None, "r_validated_alpha is None — R validation did not run"

    def test_r_alpha_matches_python(self, scores):
        """R-computed alpha must match Python-computed alpha."""
        py_alpha = scores["inter_annotator_agreement"]["krippendorff_alpha"]
        r_alpha = scores["inter_annotator_agreement"]["r_validated_alpha"]
        assert r_alpha is not None, "r_validated_alpha is None"
        assert math.isclose(py_alpha, r_alpha, abs_tol=1e-3), (
            f"R alpha ({r_alpha}) doesn't match Python alpha ({py_alpha})"
        )

    def test_r_output_file_exists(self, scores):
        """R validation output file must exist."""
        assert os.path.exists("/app/output/alpha_validation.txt"), (
            "R validation output file not found at /app/output/alpha_validation.txt"
        )

    def test_r_alpha_value_correct(self, scores):
        """R-validated alpha must match expected value."""
        r_alpha = scores["inter_annotator_agreement"]["r_validated_alpha"]
        assert r_alpha is not None, "r_validated_alpha is None"
        assert math.isclose(r_alpha, 89 / 208, abs_tol=1e-3), (
            f"R alpha ({r_alpha}) doesn't match expected 89/208"
        )


# ---- Pipeline Diagnostics ----

class TestDiagnostics:
    def test_diagnostics_present(self, scores):
        """Diagnostics section must exist in the output."""
        assert "diagnostics" in scores, "Missing 'diagnostics' section in output"

    def test_threshold_sensitivity_present(self, scores):
        ts = scores["diagnostics"]["threshold_sensitivity"]
        for t in ["1", "2", "3"]:
            assert t in ts, f"Missing threshold '{t}' in threshold_sensitivity"

    def test_threshold_1_strict(self, scores):
        val = scores["diagnostics"]["threshold_sensitivity"]["1"]["total_strict_evidence"]
        assert val == 12, f"t=1 strict={val}, expected 12"

    def test_threshold_1_lenient(self, scores):
        val = scores["diagnostics"]["threshold_sensitivity"]["1"]["total_lenient_evidence"]
        assert val == 23, f"t=1 lenient={val}, expected 23"

    def test_threshold_2_strict(self, scores):
        val = scores["diagnostics"]["threshold_sensitivity"]["2"]["total_strict_evidence"]
        assert val == 12, f"t=2 strict={val}, expected 12"

    def test_threshold_2_lenient(self, scores):
        val = scores["diagnostics"]["threshold_sensitivity"]["2"]["total_lenient_evidence"]
        assert val == 19, f"t=2 lenient={val}, expected 19"

    def test_threshold_3_strict(self, scores):
        val = scores["diagnostics"]["threshold_sensitivity"]["3"]["total_strict_evidence"]
        assert val == 12, f"t=3 strict={val}, expected 12"

    def test_threshold_3_lenient(self, scores):
        val = scores["diagnostics"]["threshold_sensitivity"]["3"]["total_lenient_evidence"]
        assert val == 14, f"t=3 lenient={val}, expected 14"

    def test_monotonicity_lenient(self, scores):
        """Lenient evidence count must be non-increasing as threshold rises."""
        ts = scores["diagnostics"]["threshold_sensitivity"]
        t1 = ts["1"]["total_lenient_evidence"]
        t2 = ts["2"]["total_lenient_evidence"]
        t3 = ts["3"]["total_lenient_evidence"]
        assert t1 >= t2 >= t3, (
            f"Lenient evidence not monotonically non-increasing: {t1}, {t2}, {t3}"
        )

    def test_monotonicity_strict(self, scores):
        """Strict evidence count must be non-increasing as threshold rises."""
        ts = scores["diagnostics"]["threshold_sensitivity"]
        t1 = ts["1"]["total_strict_evidence"]
        t2 = ts["2"]["total_strict_evidence"]
        t3 = ts["3"]["total_strict_evidence"]
        assert t1 >= t2 >= t3, (
            f"Strict evidence not monotonically non-increasing: {t1}, {t2}, {t3}"
        )

    def test_scoring_consistency_micro(self, scores):
        """Lenient micro F1 must be >= strict micro F1."""
        sc = scores["diagnostics"]["scoring_consistency"]
        assert sc["lenient_gte_strict_micro_f1"] is True, (
            "Scoring consistency violated: lenient micro F1 < strict micro F1"
        )

    def test_scoring_consistency_macro(self, scores):
        """Lenient macro F1 must be >= strict macro F1."""
        sc = scores["diagnostics"]["scoring_consistency"]
        assert sc["lenient_gte_strict_macro_f1"] is True, (
            "Scoring consistency violated: lenient macro F1 < strict macro F1"
        )


# ---- Output Format ----

class TestOutputFormat:
    def test_top_level_keys(self, scores):
        assert "evidence_identification" in scores
        assert "evidence_alignment" in scores
        assert "inter_annotator_agreement" in scores
        assert "diagnostics" in scores

    def test_evidence_subkeys(self, scores):
        assert "strict" in scores["evidence_identification"]
        assert "lenient" in scores["evidence_identification"]

    def test_alignment_subkeys(self, scores):
        assert "standard" in scores["evidence_alignment"]
        assert "weighted" in scores["evidence_alignment"]

    def test_iaa_subkeys(self, scores):
        assert "krippendorff_alpha" in scores["inter_annotator_agreement"]
        assert "r_validated_alpha" in scores["inter_annotator_agreement"]

    def test_diagnostics_subkeys(self, scores):
        assert "threshold_sensitivity" in scores["diagnostics"]
        assert "scoring_consistency" in scores["diagnostics"]

    def test_all_metrics_present(self, scores):
        for mode in ["strict", "lenient"]:
            section = scores["evidence_identification"][mode]
            for key in ["micro_precision", "micro_recall", "micro_f1",
                        "macro_precision", "macro_recall", "macro_f1",
                        "bootstrap_ci_micro_f1_lower", "bootstrap_ci_micro_f1_upper"]:
                assert key in section, f"Missing key {key} in {mode}"

        for mode in ["standard", "weighted"]:
            section = scores["evidence_alignment"][mode]
            for key in ["micro_precision", "micro_recall", "micro_f1",
                        "macro_precision", "macro_recall", "macro_f1"]:
                assert key in section, f"Missing key {key} in {mode}"
