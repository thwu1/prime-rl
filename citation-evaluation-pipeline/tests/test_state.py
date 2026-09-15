
import json
import os
import pytest


@pytest.fixture
def results():
    path = "/app/results.json"
    assert os.path.exists(path), f"results.json not found at {path}"
    with open(path) as f:
        data = json.load(f)
    return data


class TestResultsStructure:
    def test_required_keys_present(self, results):
        required = [
            "cat1_mean_f1",
            "cat2_mean_f1",
            "cat3_mean_score",
            "cat1_mar",
            "cat2_mar",
            "overall_mar",
            "num_instances",
        ]
        for key in required:
            assert key in results, f"Missing required key: {key}"

    def test_values_are_numeric(self, results):
        for key in ["cat1_mean_f1", "cat2_mean_f1", "cat3_mean_score",
                     "cat1_mar", "cat2_mar", "overall_mar"]:
            assert isinstance(results[key], (int, float)), \
                f"{key} should be numeric, got {type(results[key])}"
        assert isinstance(results["num_instances"], int), \
            "num_instances should be an integer"

    def test_f1_in_valid_range(self, results):
        for key in ["cat1_mean_f1", "cat2_mean_f1"]:
            assert 0 <= results[key] <= 100, \
                f"{key} = {results[key]} is outside valid range [0, 100]"

    def test_cat3_in_valid_range(self, results):
        assert 0 <= results["cat3_mean_score"] <= 100, \
            f"cat3_mean_score = {results['cat3_mean_score']} is outside [0, 100]"

    def test_mar_in_valid_range(self, results):
        for key in ["cat1_mar", "cat2_mar", "overall_mar"]:
            assert 0 <= results[key] <= 1, \
                f"{key} = {results[key]} is outside valid range [0, 1]"


class TestCat1Metrics:
    """Cat1 (Citation Retrieval) F1 scores with parallel citation matching.

    Expected per-instance F1 (scaled 0-100):
      C1_001: 100.0   (3/3 matched, 3/3 GT)
      C1_002:  57.14  (2/3 matched via parallel, 2/4 GT)
      C1_003:   0.0   (abstention)
      C1_004:  85.71  (3/3 matched, 3/4 GT)
      C1_005:  66.67  (3/4 matched, 3/5 GT)
      C1_006: 100.0   (4/4 matched, 4/4 GT)
      C1_007:   0.0   (0/3 matched, all hallucinated)
      C1_008:  85.71  (3/3 matched, 3/4 GT)
      C1_009:  44.44  (2/4 matched, 2/5 GT)
      C1_010:  25.0   (1/3 matched, 1/5 GT)
    Mean: 56.468
    """

    def test_cat1_mean_f1(self, results):
        expected = 56.47
        tolerance = 1.5
        actual = results["cat1_mean_f1"]
        assert abs(actual - expected) < tolerance, \
            f"cat1_mean_f1: expected ~{expected}, got {actual}"

    def test_cat1_mar(self, results):
        """Low-scoring (F1<=40): C1_003(0), C1_007(0), C1_010(25)
        Concrete: C1_003(no), C1_007(yes), C1_010(yes) => MAR=2/3=0.667"""
        expected = 0.6667
        tolerance = 0.05
        actual = results["cat1_mar"]
        assert abs(actual - expected) < tolerance, \
            f"cat1_mar: expected ~{expected}, got {actual}"


class TestCat2Metrics:
    """Cat2 (Citation Completion) F1 scores with parallel citation matching.

    Expected per-instance F1 (scaled 0-100):
      C2_001: 100.0   (1/1 matched)
      C2_002:  66.67  (2/2 matched, 2/4 GT)
      C2_003:   0.0   (abstention)
      C2_004:  66.67  (2/2 matched, 2/4 GT)
      C2_005: 100.0   (3/3 matched)
      C2_006:  80.0   (2/2 matched, 2/3 GT)
      C2_007: 100.0   (3/3 matched)
      C2_008:  28.57  (1/3 matched, 1/4 GT)
      C2_009:  80.0   (2/2 matched, 2/3 GT)
      C2_010:  80.0   (2/2 matched via parallel, 2/3 GT)
    Mean: 70.191
    """

    def test_cat2_mean_f1(self, results):
        expected = 70.19
        tolerance = 1.5
        actual = results["cat2_mean_f1"]
        assert abs(actual - expected) < tolerance, \
            f"cat2_mean_f1: expected ~{expected}, got {actual}"

    def test_cat2_mar(self, results):
        """Low-scoring (F1<=40): C2_003(0), C2_008(28.57)
        Concrete: C2_003(no), C2_008(yes) => MAR=1/2=0.5"""
        expected = 0.5
        tolerance = 0.05
        actual = results["cat2_mar"]
        assert abs(actual - expected) < tolerance, \
            f"cat2_mar: expected ~{expected}, got {actual}"


class TestCat3Metrics:
    """Cat3 (Citation Error Detection) scores.

    Expected per-instance scores (raw 0-5):
      C3_001: 5 (3-fake: detected error, correct citation provided)
      C3_002: 5 (3-true: correctly confirmed no error)
      C3_003: 1 (3-fake: failed to detect error)
      C3_004: 5 (3-fake: detected error, correct citation provided)
      C3_005: 2 (3-true: incorrectly claimed error)
      C3_006: 5 (3-fake: detected error, correct citation provided)
      C3_007: 5 (3-true: "no error" negation correctly handled)
      C3_008: 5 (3-fake: detected error, correct citation provided)
      C3_009: 1 (3-fake: failed to detect error)
      C3_010: 5 (3-true: correctly confirmed no error)
    Mean raw: 3.9, scaled 0-100: 78.0
    """

    def test_cat3_mean_score(self, results):
        expected = 78.0
        tolerance = 2.0
        actual = results["cat3_mean_score"]
        assert abs(actual - expected) < tolerance, \
            f"cat3_mean_score: expected ~{expected}, got {actual}"


class TestOverallMetrics:
    def test_overall_mar(self, results):
        """Combined Cat1+Cat2 MAR: 3 concrete out of 5 low-scoring = 0.6"""
        expected = 0.6
        tolerance = 0.05
        actual = results["overall_mar"]
        assert abs(actual - expected) < tolerance, \
            f"overall_mar: expected ~{expected}, got {actual}"

    def test_num_instances(self, results):
        assert results["num_instances"] == 30, \
            f"num_instances: expected 30, got {results['num_instances']}"
