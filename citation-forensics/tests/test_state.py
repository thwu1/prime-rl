"""
Tests for Legal Citation Evaluation Pipeline.
Verifies citation F1 with parallel citation resolution, jurisdiction-weighted
scoring, MAR, normalization, fabrication rate, error classification, and
severity-weighted accuracy across heterogeneous data sources.
"""

import json
import os
import subprocess
import sys
import pytest

RESULTS_PATH = "/app/output/results.json"
SCORE_TOL = 1.5   # tolerance for 0-100 scale
NORM_TOL = 0.03   # tolerance for 0-1 scale


@pytest.fixture(scope="session")
def results():
    """Load the results JSON, running the pipeline first if needed."""
    if not os.path.exists(RESULTS_PATH):
        for name in ["evaluate.py", "pipeline.py", "main.py"]:
            path = f"/app/{name}"
            if os.path.exists(path):
                result = subprocess.run(
                    [sys.executable, path],
                    cwd="/app",
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if result.returncode == 0:
                    break

    assert os.path.exists(RESULTS_PATH), (
        f"Results file not found at {RESULTS_PATH}. "
        "Pipeline must write output to /app/output/results.json"
    )

    with open(RESULTS_PATH) as f:
        return json.load(f)


# ================================================================
# Output structure
# ================================================================
class TestOutputStructure:
    def test_has_retrieval_f1(self, results):
        assert "retrieval_f1" in results

    def test_has_mar(self, results):
        assert "mar" in results

    def test_has_normalized_overall(self, results):
        assert "normalized_overall" in results

    def test_has_error_detection(self, results):
        assert "error_detection" in results

    def test_has_record_details(self, results):
        assert "record_details" in results

    def test_has_fabrication_rate(self, results):
        assert "fabrication_rate" in results

    def test_four_models_in_retrieval(self, results):
        assert len(results["retrieval_f1"]) == 4

    def test_record_detail_count(self, results):
        assert len(results["record_details"]) == 20

    def test_weighted_overall_present(self, results):
        """Each model in retrieval_f1 must have weighted_overall."""
        for model in results["retrieval_f1"]:
            assert "weighted_overall" in results["retrieval_f1"][model], (
                f"{model} missing weighted_overall"
            )

    def test_severity_weighted_present(self, results):
        assert "severity_weighted_accuracy" in results["error_detection"]


# ================================================================
# Retrieval F1 — unweighted averages
# ================================================================
class TestRetrievalF1:
    """
    Expected per-model per-category average F1 (0-100 scale):
      claude_sonnet: cat1=93.33  cat2=100.0  overall=96.0
      gpt4o_mini:    cat1=82.22  cat2=90.0   overall=85.33
      deepseek_v3:   cat1=20.63  cat2=33.33  overall=25.71
      llama_70b:     cat1=0.0    cat2=0.0    overall=0.0
    """

    def test_claude_sonnet_cat1(self, results):
        v = results["retrieval_f1"]["claude_sonnet"]["cat1"]
        assert abs(v - 93.33) < SCORE_TOL, f"expected ~93.33, got {v}"

    def test_claude_sonnet_cat2(self, results):
        v = results["retrieval_f1"]["claude_sonnet"]["cat2"]
        assert abs(v - 100.0) < SCORE_TOL, f"expected ~100.0, got {v}"

    def test_claude_sonnet_overall(self, results):
        v = results["retrieval_f1"]["claude_sonnet"]["overall"]
        assert abs(v - 96.0) < SCORE_TOL, f"expected ~96.0, got {v}"

    def test_gpt4o_mini_cat1(self, results):
        v = results["retrieval_f1"]["gpt4o_mini"]["cat1"]
        assert abs(v - 82.22) < SCORE_TOL, f"expected ~82.22, got {v}"

    def test_gpt4o_mini_cat2(self, results):
        v = results["retrieval_f1"]["gpt4o_mini"]["cat2"]
        assert abs(v - 90.0) < SCORE_TOL, f"expected ~90.0, got {v}"

    def test_gpt4o_mini_overall(self, results):
        v = results["retrieval_f1"]["gpt4o_mini"]["overall"]
        assert abs(v - 85.33) < SCORE_TOL, f"expected ~85.33, got {v}"

    def test_deepseek_v3_cat1(self, results):
        v = results["retrieval_f1"]["deepseek_v3"]["cat1"]
        assert abs(v - 20.63) < SCORE_TOL, f"expected ~20.63, got {v}"

    def test_deepseek_v3_cat2(self, results):
        v = results["retrieval_f1"]["deepseek_v3"]["cat2"]
        assert abs(v - 33.33) < SCORE_TOL, f"expected ~33.33, got {v}"

    def test_deepseek_v3_overall(self, results):
        v = results["retrieval_f1"]["deepseek_v3"]["overall"]
        assert abs(v - 25.71) < SCORE_TOL, f"expected ~25.71, got {v}"

    def test_llama_70b_all_zero(self, results):
        for key in ["cat1", "cat2", "overall"]:
            v = results["retrieval_f1"]["llama_70b"][key]
            assert abs(v) < SCORE_TOL, f"llama_70b {key}: expected ~0, got {v}"

    def test_best_model_overall(self, results):
        """claude_sonnet should have the highest unweighted overall score."""
        scores = {
            m: results["retrieval_f1"][m]["overall"]
            for m in results["retrieval_f1"]
        }
        best = max(scores, key=scores.get)
        assert best == "claude_sonnet", f"expected claude_sonnet, got {best}"


# ================================================================
# Jurisdiction-Weighted F1
# ================================================================
class TestWeightedF1:
    """
    Expected weighted_overall (court hierarchy weights from rec file):
      claude_sonnet: 96.25
      gpt4o_mini:    85.83
      deepseek_v3:   24.40
      llama_70b:     0.0
    """

    def test_claude_sonnet_weighted(self, results):
        v = results["retrieval_f1"]["claude_sonnet"]["weighted_overall"]
        assert abs(v - 96.25) < SCORE_TOL, f"expected ~96.25, got {v}"

    def test_gpt4o_mini_weighted(self, results):
        v = results["retrieval_f1"]["gpt4o_mini"]["weighted_overall"]
        assert abs(v - 85.83) < SCORE_TOL, f"expected ~85.83, got {v}"

    def test_deepseek_v3_weighted(self, results):
        v = results["retrieval_f1"]["deepseek_v3"]["weighted_overall"]
        assert abs(v - 24.40) < SCORE_TOL, f"expected ~24.40, got {v}"

    def test_llama_70b_weighted_zero(self, results):
        v = results["retrieval_f1"]["llama_70b"]["weighted_overall"]
        assert abs(v) < SCORE_TOL, f"expected ~0, got {v}"

    def test_weighted_ranking(self, results):
        """claude > gpt4o > deepseek > llama for weighted scores."""
        w = {m: results["retrieval_f1"][m]["weighted_overall"]
             for m in results["retrieval_f1"]}
        assert w["claude_sonnet"] > w["gpt4o_mini"] > w["deepseek_v3"]
        assert w["deepseek_v3"] > w["llama_70b"]


# ================================================================
# MAR
# ================================================================
class TestMAR:
    """
    Expected MAR (threshold=40):
      gpt4o_mini:    null
      claude_sonnet: null
      deepseek_v3:   1.0
      llama_70b:     0.0
      overall:       4/9 = 0.4444
    """

    def test_threshold_value(self, results):
        assert results["mar"]["threshold"] == 40

    def test_gpt4o_mini_is_null(self, results):
        assert results["mar"]["gpt4o_mini"] is None

    def test_claude_sonnet_is_null(self, results):
        assert results["mar"]["claude_sonnet"] is None

    def test_deepseek_v3_mar(self, results):
        v = results["mar"]["deepseek_v3"]
        assert abs(v - 1.0) < NORM_TOL, f"expected ~1.0, got {v}"

    def test_llama_70b_mar(self, results):
        v = results["mar"]["llama_70b"]
        assert abs(v - 0.0) < NORM_TOL, f"expected ~0.0, got {v}"

    def test_overall_mar(self, results):
        v = results["mar"]["overall"]
        assert abs(v - 0.4444) < NORM_TOL, f"expected ~0.4444, got {v}"


# ================================================================
# Normalized overall scores
# ================================================================
class TestNormalizedOverall:
    """
    Expected normalized scores (best model = 1.0):
      claude_sonnet: 1.0
      gpt4o_mini:    ~0.8905
      deepseek_v3:   ~0.2772
      llama_70b:     0.0
    """

    def test_claude_sonnet_normalized(self, results):
        v = results["normalized_overall"]["claude_sonnet"]
        assert abs(v - 1.0) < NORM_TOL, f"expected ~1.0, got {v}"

    def test_gpt4o_mini_normalized(self, results):
        v = results["normalized_overall"]["gpt4o_mini"]
        assert abs(v - 0.8905) < NORM_TOL, f"expected ~0.8905, got {v}"

    def test_deepseek_v3_normalized(self, results):
        v = results["normalized_overall"]["deepseek_v3"]
        assert abs(v - 0.2772) < NORM_TOL, f"expected ~0.2772, got {v}"

    def test_llama_70b_normalized(self, results):
        v = results["normalized_overall"]["llama_70b"]
        assert abs(v - 0.0) < NORM_TOL, f"expected ~0.0, got {v}"

    def test_ranking_order(self, results):
        n = results["normalized_overall"]
        assert n["claude_sonnet"] > n["gpt4o_mini"] > n["deepseek_v3"] > n["llama_70b"]


# ================================================================
# Fabrication rate
# ================================================================
class TestFabricationRate:
    """
    Expected fabrication rates:
      gpt4o_mini:    0.0    (10 preds, 0 fabricated)
      claude_sonnet: 0.0667 (15 preds, 1 fabricated)
      deepseek_v3:   0.6667 (12 preds, 8 fabricated)
      llama_70b:     0.0    (0 preds)
    """

    def test_gpt4o_mini_zero(self, results):
        v = results["fabrication_rate"]["gpt4o_mini"]
        assert abs(v - 0.0) < NORM_TOL

    def test_claude_sonnet_fabrication(self, results):
        v = results["fabrication_rate"]["claude_sonnet"]
        assert abs(v - 0.0667) < NORM_TOL, f"expected ~0.0667, got {v}"

    def test_deepseek_v3_fabrication(self, results):
        v = results["fabrication_rate"]["deepseek_v3"]
        assert abs(v - 0.6667) < NORM_TOL, f"expected ~0.6667, got {v}"

    def test_llama_70b_zero(self, results):
        v = results["fabrication_rate"]["llama_70b"]
        assert abs(v - 0.0) < NORM_TOL

    def test_fabrication_ranking(self, results):
        """deepseek should have highest fabrication rate."""
        fab = results["fabrication_rate"]
        assert fab["deepseek_v3"] > fab["claude_sonnet"] > fab["gpt4o_mini"]


# ================================================================
# Error detection
# ================================================================
class TestErrorDetection:
    """
    10 records: 7 fake (2 volume, 3 page, 2 reporter), 3 true.
    Severity weights from nested JSON: volume=3.0, reporter=2.0, page=1.0.
    """

    def test_detection_accuracy(self, results):
        v = results["error_detection"]["detection_accuracy"]
        assert abs(v - 1.0) < NORM_TOL, f"expected ~1.0, got {v}"

    def test_classification_accuracy(self, results):
        v = results["error_detection"]["classification_accuracy"]
        assert abs(v - 1.0) < NORM_TOL, f"expected ~1.0, got {v}"

    def test_severity_weighted_accuracy(self, results):
        v = results["error_detection"]["severity_weighted_accuracy"]
        assert abs(v - 1.0) < NORM_TOL, f"expected ~1.0, got {v}"

    def test_volume_count(self, results):
        c = results["error_detection"]["type_counts"]
        assert c.get("volume", 0) == 2, f"expected 2 volume, got {c.get('volume', 0)}"

    def test_page_count(self, results):
        c = results["error_detection"]["type_counts"]
        assert c.get("page", 0) == 3, f"expected 3 page, got {c.get('page', 0)}"

    def test_reporter_count(self, results):
        c = results["error_detection"]["type_counts"]
        assert c.get("reporter", 0) == 2, f"expected 2 reporter, got {c.get('reporter', 0)}"


# ================================================================
# Individual record verification — including parallel citation tests
# ================================================================
class TestRecordDetails:
    """Verify per-record F1 scores, concreteness flags, and parallel resolution."""

    def _get(self, results, rid):
        for r in results["record_details"]:
            if r["id"] == rid:
                return r
        return None

    # --- gpt4o_mini: all concrete, high scores ---
    def test_r001_high_f1(self, results):
        r = self._get(results, "r_001")
        assert r is not None, "r_001 missing"
        assert abs(r["f1_score"] - 80.0) < SCORE_TOL
        assert r["is_concrete"] is True

    def test_r002_perfect(self, results):
        r = self._get(results, "r_002")
        assert r is not None
        assert abs(r["f1_score"] - 100.0) < SCORE_TOL

    def test_r003_partial(self, results):
        """36 So.3d 84 must NOT substring-match 84 So.3d 1032."""
        r = self._get(results, "r_003")
        assert r is not None
        assert abs(r["f1_score"] - 66.67) < SCORE_TOL

    def test_r005_parallel_resolution(self, results):
        """276 P.3d 808 must match 127 Hawai'i 126 via parallel citation table."""
        r = self._get(results, "r_005")
        assert r is not None
        assert abs(r["f1_score"] - 100.0) < SCORE_TOL
        assert r["is_concrete"] is True

    # --- claude_sonnet: near-perfect, one overcitation ---
    def test_r016_perfect(self, results):
        """All three SCOTUS citations extracted and matched."""
        r = self._get(results, "r_016")
        assert r is not None
        assert abs(r["f1_score"] - 100.0) < SCORE_TOL
        assert r["is_concrete"] is True

    def test_r017_overcitation(self, results):
        """127 Hawai'i 126 is not in ground truth, reducing precision."""
        r = self._get(results, "r_017")
        assert r is not None
        assert abs(r["f1_score"] - 80.0) < SCORE_TOL
        assert r["is_concrete"] is True

    def test_r018_all_matched(self, results):
        """All four So.3d citations should match despite embedded parenthetical."""
        r = self._get(results, "r_018")
        assert r is not None
        assert abs(r["f1_score"] - 100.0) < SCORE_TOL

    def test_r019_parallel_resolution(self, results):
        """118 S. Ct. 2091 must match 524 U.S. 666 via parallel citation table."""
        r = self._get(results, "r_019")
        assert r is not None
        assert abs(r["f1_score"] - 100.0) < SCORE_TOL
        assert r["is_concrete"] is True

    # --- deepseek_v3: concrete but low scores ---
    def test_r006_parallel_resolution(self, results):
        """104 S. Ct. 2052 must match 466 U.S. 668 via parallel citation table."""
        r = self._get(results, "r_006")
        assert r is not None
        assert abs(r["f1_score"] - 33.33) < SCORE_TOL
        assert r["is_concrete"] is True

    def test_r007_zero_with_citations(self, results):
        """Near-miss: 205 A.3d 440 must not match 205 A.3d 445."""
        r = self._get(results, "r_007")
        assert r is not None
        assert r["f1_score"] < 1.0
        assert r["is_concrete"] is True

    def test_r008_partial_low(self, results):
        r = self._get(results, "r_008")
        assert r is not None
        assert abs(r["f1_score"] - 28.57) < SCORE_TOL

    def test_r009_moderate(self, results):
        r = self._get(results, "r_009")
        assert r is not None
        assert abs(r["f1_score"] - 66.67) < SCORE_TOL

    def test_r010_hawaii_mismatch(self, results):
        """127 Hawai'i 120 must not match 127 Hawai'i 126."""
        r = self._get(results, "r_010")
        assert r is not None
        assert r["f1_score"] < 1.0

    # --- llama_70b: all abstentions ---
    def test_r011_abstention(self, results):
        r = self._get(results, "r_011")
        assert r is not None
        assert r["f1_score"] < 1.0
        assert r["is_concrete"] is False

    def test_r014_abstention(self, results):
        r = self._get(results, "r_014")
        assert r is not None
        assert r["is_concrete"] is False

    def test_all_llama_abstain(self, results):
        """All llama_70b records should be non-concrete."""
        llama = [
            r for r in results["record_details"] if r["model"] == "llama_70b"
        ]
        assert len(llama) == 5
        for r in llama:
            assert r["is_concrete"] is False, f"{r['id']} should be non-concrete"

    def test_all_deepseek_concrete(self, results):
        """All deepseek_v3 records should be concrete."""
        ds = [
            r for r in results["record_details"] if r["model"] == "deepseek_v3"
        ]
        assert len(ds) == 5
        for r in ds:
            assert r["is_concrete"] is True, f"{r['id']} should be concrete"

    def test_all_claude_concrete(self, results):
        """All claude_sonnet records should be concrete."""
        cs = [
            r for r in results["record_details"] if r["model"] == "claude_sonnet"
        ]
        assert len(cs) == 5
        for r in cs:
            assert r["is_concrete"] is True, f"{r['id']} should be concrete"


# ================================================================
# Cross-consistency checks
# ================================================================
class TestConsistency:
    """Verify internal consistency between sections of the output."""

    def test_mar_consistent_with_details(self, results):
        """Re-derive overall MAR from record_details and compare."""
        threshold = results["mar"]["threshold"]
        details = results["record_details"]
        low = [d for d in details if d["f1_score"] <= threshold]
        if not low:
            assert results["mar"]["overall"] is None
        else:
            concrete_low = [d for d in low if d["is_concrete"]]
            expected_mar = len(concrete_low) / len(low)
            actual = results["mar"]["overall"]
            assert abs(actual - expected_mar) < NORM_TOL, (
                f"MAR mismatch: derived {expected_mar}, reported {actual}"
            )

    def test_normalized_best_is_one(self, results):
        """The best model's normalized score should be ~1.0."""
        n = results["normalized_overall"]
        best_val = max(n.values())
        assert abs(best_val - 1.0) < NORM_TOL, (
            f"Best normalized should be ~1.0, got {best_val}"
        )

    def test_f1_averages_consistent(self, results):
        """Re-derive per-model overall averages from record_details."""
        from collections import defaultdict

        by_model = defaultdict(list)
        for d in results["record_details"]:
            by_model[d["model"]].append(d["f1_score"])

        for model, scores in by_model.items():
            derived_avg = sum(scores) / len(scores)
            reported = results["retrieval_f1"][model]["overall"]
            assert abs(derived_avg - reported) < SCORE_TOL, (
                f"{model} overall mismatch: derived {derived_avg:.2f}, "
                f"reported {reported}"
            )

    def test_four_models_everywhere(self, results):
        """All sections should reference exactly 4 models."""
        models_f1 = set(results["retrieval_f1"].keys())
        models_norm = set(results["normalized_overall"].keys())
        models_fab = set(results["fabrication_rate"].keys())
        assert len(models_f1) == 4
        assert models_f1 == models_norm == models_fab
