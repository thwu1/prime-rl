
import json
import math
import os
import pytest

RESULTS_PATH = "/app/output/results.json"


@pytest.fixture(scope="session")
def results():
    assert os.path.exists(RESULTS_PATH), (
        f"Results file not found at {RESULTS_PATH}."
    )
    with open(RESULTS_PATH, "r") as f:
        data = json.load(f)
    return data


class TestPairScores:

    def test_has_pair_scores(self, results):
        assert "pair_scores" in results

    def test_pair_01(self, results):
        assert results["pair_scores"]["pair_01"] == pytest.approx(1.0, abs=1e-6)

    def test_pair_02(self, results):
        assert results["pair_scores"]["pair_02"] == pytest.approx(0.8125, abs=1e-6)

    def test_pair_03(self, results):
        assert results["pair_scores"]["pair_03"] == pytest.approx(2.0 / 29.0, abs=1e-6)

    def test_pair_04(self, results):
        assert results["pair_scores"]["pair_04"] == pytest.approx(29.0 / 32.0, abs=1e-6)

    def test_pair_05(self, results):
        assert results["pair_scores"]["pair_05"] == pytest.approx(61.0 / 64.0, abs=1e-6)

    def test_pair_06(self, results):
        assert results["pair_scores"]["pair_06"] == pytest.approx(0.5, abs=1e-6)

    def test_pair_07(self, results):
        assert results["pair_scores"]["pair_07"] == pytest.approx(1.0, abs=1e-6)

    def test_pair_08(self, results):
        assert results["pair_scores"]["pair_08"] == pytest.approx(125.0 / 128.0, abs=1e-6)

    def test_pair_09(self, results):
        assert results["pair_scores"]["pair_09"] == pytest.approx(16.0 / 87.0, abs=1e-6)

    def test_pair_10(self, results):
        assert results["pair_scores"]["pair_10"] == pytest.approx(29.0 / 48.0, abs=1e-6)

    def test_pair_11(self, results):
        assert results["pair_scores"]["pair_11"] == pytest.approx(1.0 / 33.0, abs=1e-6)

    def test_pair_12(self, results):
        assert results["pair_scores"]["pair_12"] == pytest.approx(61.0 / 64.0, abs=1e-6)


class TestTypeMeta:

    def test_has_type_meta(self, results):
        assert "type_meta" in results

    def test_meta_01(self, results):
        meta = results["type_meta"]["meta_01"]
        assert meta["depth"] == 1
        assert meta["count"] == 1

    def test_meta_02(self, results):
        meta = results["type_meta"]["meta_02"]
        assert meta["depth"] == 2
        assert meta["count"] == 2

    def test_meta_03(self, results):
        meta = results["type_meta"]["meta_03"]
        assert meta["depth"] == 3
        assert meta["count"] == 4

    def test_meta_04(self, results):
        meta = results["type_meta"]["meta_04"]
        assert meta["depth"] == 2
        assert meta["count"] == 3

    def test_meta_05(self, results):
        meta = results["type_meta"]["meta_05"]
        assert meta["depth"] == 3
        assert meta["count"] == 4

    def test_meta_06(self, results):
        meta = results["type_meta"]["meta_06"]
        assert meta["depth"] == 2
        assert meta["count"] == 3


class TestRepoEvaluation:

    def test_has_repo_evaluation(self, results):
        assert "repo_evaluation" in results

    def test_total_count(self, results):
        repo = results["repo_evaluation"]
        assert repo["total_count"] == 20

    def test_missing_count(self, results):
        repo = results["repo_evaluation"]
        assert repo["missing_count"] == 1

    def test_overall_score(self, results):
        repo = results["repo_evaluation"]
        expected = (
            1.0 + 1.0 + 5.0 / 6.0 + 31.0 / 58.0 + 1.0 + 89.0 / 116.0
            + 1.0 + 1.0 + 125.0 / 128.0 + 0.5 + 61.0 / 64.0 + 29.0 / 32.0
            + 13.0 / 20.0 + 205.0 / 232.0 + 0.0 + 0.5 + 29.0 / 32.0
            + 0.5 + 1.0 + 0.0
        ) / 20.0
        assert repo["overall_score"] == pytest.approx(expected, abs=1e-6)

    def test_overall_score_without_missing(self, results):
        repo = results["repo_evaluation"]
        expected = (
            1.0 + 1.0 + 5.0 / 6.0 + 31.0 / 58.0 + 1.0 + 89.0 / 116.0
            + 1.0 + 1.0 + 125.0 / 128.0 + 0.5 + 61.0 / 64.0 + 29.0 / 32.0
            + 13.0 / 20.0 + 205.0 / 232.0 + 0.0 + 0.5 + 29.0 / 32.0
            + 0.5 + 1.0 + 0.0
        ) / 19.0
        assert repo["overall_score_without_missing"] == pytest.approx(expected, abs=1e-6)

    def test_depth_1_score(self, results):
        repo = results["repo_evaluation"]
        expected = (1.0 + 1.0 + 5.0 / 6.0 + 1.0 + 1.0 + 1.0 + 13.0 / 20.0 + 0.0 + 1.0) / 9.0
        assert float(repo["scores_by_depth"]["1"]) == pytest.approx(expected, abs=1e-6)

    def test_depth_2_score(self, results):
        repo = results["repo_evaluation"]
        expected = (31.0 / 58.0 + 89.0 / 116.0 + 0.5 + 29.0 / 32.0 + 0.5 + 29.0 / 32.0 + 0.0) / 7.0
        assert float(repo["scores_by_depth"]["2"]) == pytest.approx(expected, abs=1e-6)

    def test_depth_3_score(self, results):
        repo = results["repo_evaluation"]
        expected = (125.0 / 128.0 + 61.0 / 64.0 + 205.0 / 232.0 + 0.5) / 4.0
        assert float(repo["scores_by_depth"]["3"]) == pytest.approx(expected, abs=1e-6)

    def test_consistency_score_gt(self, results):
        repo = results["repo_evaluation"]
        expected = math.exp(-1.5)
        assert repo["consistency_score_gt"] == pytest.approx(expected, abs=1e-6)

    def test_consistency_score_pred(self, results):
        repo = results["repo_evaluation"]
        expected = math.exp(-4.0)
        assert repo["consistency_score_pred"] == pytest.approx(expected, abs=1e-6)


class TestStructuralIntegrity:

    def test_all_pair_ids_present(self, results):
        for i in range(1, 13):
            key = f"pair_{i:02d}"
            assert key in results["pair_scores"], f"Missing: {key}"

    def test_all_meta_ids_present(self, results):
        for i in range(1, 7):
            key = f"meta_{i:02d}"
            assert key in results["type_meta"], f"Missing: {key}"

    def test_repo_required_keys(self, results):
        repo = results["repo_evaluation"]
        for key in [
            "overall_score", "overall_score_without_missing",
            "missing_count", "total_count", "scores_by_depth",
            "consistency_score_gt", "consistency_score_pred"
        ]:
            assert key in repo, f"Missing: {key}"

    def test_scores_in_valid_range(self, results):
        for key, score in results["pair_scores"].items():
            assert 0.0 <= score <= 1.0 + 1e-9, f"{key}: {score}"

    def test_meta_positive_values(self, results):
        for key, meta in results["type_meta"].items():
            assert meta["depth"] >= 1
            assert meta["count"] >= 1
