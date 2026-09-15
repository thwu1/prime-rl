
import json
import pytest
import os

EXPECTED = {
    "expr_01": "1337",
    "expr_02": "-1337",
    "expr_03": "5",
    "expr_04": "6",
    "expr_05": "-3",
    "expr_06": "Hello",
    "expr_07": "Hello World!",
    "expr_08": "tes",
    "expr_09": "t",
    "expr_10": "15818151",
    "expr_11": "yes",
    "expr_12": "1337",
    "expr_13": "Hello World!",
    "expr_14": "12",
    "expr_15": "5",
    "expr_16": "165580141",
    "expr_17": "1099511627776",
    "expr_18": "155117520",
}


def load_results():
    results_path = "/app/results.json"
    assert os.path.exists(results_path), (
        f"Results file not found at {results_path}"
    )
    with open(results_path) as f:
        data = json.load(f)
    assert isinstance(data, dict), "results.json must contain a JSON object"
    return data


class TestResultsExist:
    def test_results_file_loads(self):
        data = load_results()
        assert len(data) > 0, "results.json is empty"

    def test_all_expressions_present(self):
        data = load_results()
        missing = [k for k in EXPECTED if k not in data]
        assert not missing, f"Missing results for: {missing}"


class TestBasicExpressions:
    """Test basic integer, string, and operator expressions (1-11)."""

    @pytest.mark.parametrize(
        "expr_id,expected",
        [(k, v) for k, v in EXPECTED.items() if int(k.split("_")[1]) <= 11],
    )
    def test_basic(self, expr_id, expected):
        data = load_results()
        assert expr_id in data, f"Missing result for {expr_id}"
        actual = str(data[expr_id]).strip()
        assert actual == expected, (
            f"{expr_id}: expected {expected!r}, got {actual!r}"
        )


class TestLambdaExpressions:
    """Test lambda calculus expressions (12-15)."""

    @pytest.mark.parametrize(
        "expr_id,expected",
        [
            (k, v)
            for k, v in EXPECTED.items()
            if 12 <= int(k.split("_")[1]) <= 15
        ],
    )
    def test_lambda(self, expr_id, expected):
        data = load_results()
        assert expr_id in data, f"Missing result for {expr_id}"
        actual = str(data[expr_id]).strip()
        assert actual == expected, (
            f"{expr_id}: expected {expected!r}, got {actual!r}"
        )


class TestEfficiencyExpressions:
    """Test efficiency expressions requiring reverse-engineering (16-18)."""

    @pytest.mark.parametrize(
        "expr_id,expected",
        [
            (k, v)
            for k, v in EXPECTED.items()
            if int(k.split("_")[1]) >= 16
        ],
    )
    def test_efficiency(self, expr_id, expected):
        data = load_results()
        assert expr_id in data, f"Missing result for {expr_id}"
        actual = str(data[expr_id]).strip()
        assert actual == expected, (
            f"{expr_id}: expected {expected!r}, got {actual!r}"
        )
