"""Tests for the 3D Mesh Geometry Evaluation Pipeline.

Verifies that mesh_eval.py correctly loads mesh pairs, computes geometric
comparison metrics, handles mesh repair, and produces well-formed results.
"""

import json
import os

import pytest

RESULTS_PATH = "/app/results.json"


@pytest.fixture(scope="module")
def results():
    """Load results.json produced by the evaluation pipeline."""
    assert os.path.exists(RESULTS_PATH), (
        "results.json not found at /app/results.json. "
        "Did mesh_eval.py run successfully?"
    )
    with open(RESULTS_PATH) as f:
        return json.load(f)


# ------------------------------------------------------------------ schema --

class TestResultsSchema:
    """Verify the output JSON has the required structure."""

    def test_results_file_exists(self):
        assert os.path.exists(RESULTS_PATH), "results.json not found"

    def test_top_level_keys(self, results):
        assert "pairs" in results, "Missing 'pairs' key"
        assert "summary" in results, "Missing 'summary' key"

    def test_pair_count(self, results):
        assert isinstance(results["pairs"], list)
        assert len(results["pairs"]) == 5, (
            f"Expected 5 pairs, got {len(results['pairs'])}"
        )

    def test_pair_schema(self, results):
        req_keys = {"candidate", "reference", "candidate_valid", "repaired", "metrics"}
        metric_keys = {"chamfer_distance", "f1_score", "volumetric_iou"}
        for i, pair in enumerate(results["pairs"]):
            missing = req_keys - set(pair.keys())
            assert not missing, f"Pair {i} missing keys: {missing}"
            assert isinstance(pair["candidate_valid"], bool), (
                f"Pair {i}: candidate_valid must be bool"
            )
            assert isinstance(pair["repaired"], bool), (
                f"Pair {i}: repaired must be bool"
            )
            if pair["candidate_valid"]:
                missing_m = metric_keys - set(pair["metrics"].keys())
                assert not missing_m, f"Pair {i} metrics missing: {missing_m}"

    def test_summary_schema(self, results):
        required = {
            "total_pairs", "valid_candidates", "repaired_count",
            "mean_chamfer_distance", "mean_f1_score", "mean_volumetric_iou",
        }
        missing = required - set(results["summary"].keys())
        assert not missing, f"Summary missing keys: {missing}"
        assert results["summary"]["total_pairs"] == 5


# -------------------------------------------------------------- ranges --

class TestMetricRanges:
    """Verify all metric values are within mathematically valid ranges."""

    def test_chamfer_distance_nonneg(self, results):
        for i, p in enumerate(results["pairs"]):
            if p["candidate_valid"]:
                cd = p["metrics"]["chamfer_distance"]
                assert isinstance(cd, (int, float)), f"Pair {i}: CD not numeric"
                assert cd >= 0, f"Pair {i}: CD must be >= 0, got {cd}"

    def test_f1_score_range(self, results):
        for i, p in enumerate(results["pairs"]):
            if p["candidate_valid"]:
                f1 = p["metrics"]["f1_score"]
                assert isinstance(f1, (int, float)), f"Pair {i}: F1 not numeric"
                assert 0 <= f1 <= 1.0, f"Pair {i}: F1 must be in [0,1], got {f1}"

    def test_iou_range(self, results):
        for i, p in enumerate(results["pairs"]):
            if p["candidate_valid"]:
                iou = p["metrics"]["volumetric_iou"]
                assert isinstance(iou, (int, float)), f"Pair {i}: IoU not numeric"
                assert 0 <= iou <= 1.0, f"Pair {i}: IoU must be in [0,1], got {iou}"


# ------------------------------------------------ identical shapes (pair 1) --

class TestIdenticalShapes:
    """Pair 1: identical meshes should produce near-perfect metrics."""

    def test_pair1_valid(self, results):
        pair = results["pairs"][0]
        assert pair["candidate_valid"] is True
        assert pair["repaired"] is False

    def test_pair1_chamfer_near_zero(self, results):
        cd = results["pairs"][0]["metrics"]["chamfer_distance"]
        assert cd < 0.001, f"Identical meshes should have CD ~ 0, got {cd}"

    def test_pair1_f1_near_one(self, results):
        f1 = results["pairs"][0]["metrics"]["f1_score"]
        assert f1 > 0.99, f"Identical meshes should have F1 ~ 1.0, got {f1}"

    def test_pair1_iou_near_one(self, results):
        iou = results["pairs"][0]["metrics"]["volumetric_iou"]
        assert iou > 0.95, f"Identical meshes should have IoU ~ 1.0, got {iou}"


# ----------------------------------------- different shapes (pairs 2,3,5) --

class TestDifferentShapes:
    """Pairs with intentionally different geometry."""

    def test_pair2_valid_and_different(self, results):
        p = results["pairs"][1]
        assert p["candidate_valid"] is True
        assert p["metrics"]["chamfer_distance"] > 0, (
            "Pair 2 (different aspect ratios) should have CD > 0"
        )

    def test_pair3_valid_and_different(self, results):
        p = results["pairs"][2]
        assert p["candidate_valid"] is True
        assert p["metrics"]["chamfer_distance"] > 0, (
            "Pair 3 (different proportions) should have CD > 0"
        )

    def test_pair5_valid(self, results):
        assert results["pairs"][4]["candidate_valid"] is True

    def test_pair5_large_difference(self, results):
        """Cylinder vs flat plate should have much lower IoU than identical pair."""
        iou_5 = results["pairs"][4]["metrics"]["volumetric_iou"]
        iou_1 = results["pairs"][0]["metrics"]["volumetric_iou"]
        assert iou_5 < iou_1, (
            f"Very different shapes (pair 5, IoU={iou_5}) should have lower IoU "
            f"than identical shapes (pair 1, IoU={iou_1})"
        )

    def test_identical_better_cd_than_different(self, results):
        """Identical shapes must have lower CD than non-identical."""
        cd_1 = results["pairs"][0]["metrics"]["chamfer_distance"]
        cd_3 = results["pairs"][2]["metrics"]["chamfer_distance"]
        assert cd_1 < cd_3, (
            f"Identical CD ({cd_1}) should be < different CD ({cd_3})"
        )


# ------------------------------------------------ mesh repair (pair 4) --

class TestMeshRepair:
    """Pair 4: defective candidate must be detected and repaired."""

    def test_pair4_repaired(self, results):
        pair = results["pairs"][3]
        assert pair["repaired"] is True, (
            "Pair 4 (defective candidate) should be marked as repaired"
        )

    def test_pair4_valid_after_repair(self, results):
        assert results["pairs"][3]["candidate_valid"] is True, (
            "Pair 4 should be valid after repair"
        )

    def test_pair4_has_valid_metrics(self, results):
        m = results["pairs"][3]["metrics"]
        assert m["chamfer_distance"] >= 0
        assert 0 <= m["f1_score"] <= 1.0
        assert 0 <= m["volumetric_iou"] <= 1.0

    def test_pair4_near_identical_after_repair(self, results):
        """Pair 4 is the same geometry with a defective candidate; after repair
        the candidate should be geometrically equivalent to the reference."""
        p4 = results["pairs"][3]
        assert p4["metrics"]["chamfer_distance"] < 0.001, (
            f"Repaired identical geometry should have CD ~ 0, "
            f"got {p4['metrics']['chamfer_distance']}"
        )
        assert p4["metrics"]["f1_score"] > 0.99, (
            f"Repaired identical geometry should have F1 ~ 1.0, "
            f"got {p4['metrics']['f1_score']}"
        )


# ---------------------------------------------- summary consistency --

class TestSummaryConsistency:
    """Verify summary statistics match per-pair data."""

    def test_valid_count(self, results):
        expected = sum(1 for p in results["pairs"] if p["candidate_valid"])
        assert results["summary"]["valid_candidates"] == expected

    def test_repaired_count(self, results):
        expected = sum(1 for p in results["pairs"] if p["repaired"])
        assert results["summary"]["repaired_count"] == expected

    def test_mean_chamfer(self, results):
        valid = [p for p in results["pairs"] if p["candidate_valid"]]
        if not valid:
            pytest.skip("No valid pairs")
        expected = sum(p["metrics"]["chamfer_distance"] for p in valid) / len(valid)
        actual = results["summary"]["mean_chamfer_distance"]
        assert abs(actual - expected) < 1e-6, (
            f"Mean CD mismatch: summary={actual}, computed={expected}"
        )

    def test_mean_f1(self, results):
        valid = [p for p in results["pairs"] if p["candidate_valid"]]
        if not valid:
            pytest.skip("No valid pairs")
        expected = sum(p["metrics"]["f1_score"] for p in valid) / len(valid)
        actual = results["summary"]["mean_f1_score"]
        assert abs(actual - expected) < 1e-6, (
            f"Mean F1 mismatch: summary={actual}, computed={expected}"
        )

    def test_mean_iou(self, results):
        valid = [p for p in results["pairs"] if p["candidate_valid"]]
        if not valid:
            pytest.skip("No valid pairs")
        expected = sum(p["metrics"]["volumetric_iou"] for p in valid) / len(valid)
        actual = results["summary"]["mean_volumetric_iou"]
        assert abs(actual - expected) < 1e-6, (
            f"Mean IoU mismatch: summary={actual}, computed={expected}"
        )
