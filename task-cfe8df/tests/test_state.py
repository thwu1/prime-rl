
import json
import math
import pytest

EXPECTED = {
    "alpha": {"n": 24, "k": 2, "d": 3, "kd2_over_n": 0.7500},
    "beta":  {"n": 18, "k": 4, "d": 2, "kd2_over_n": 0.8889},
    "gamma": {"n": 24, "k": 2, "d": 5, "kd2_over_n": 2.0833},
    "delta": {"n": 36, "k": 8, "d": 4, "kd2_over_n": 3.5556},
    "epsilon": {"n": 32, "k": 2, "d": 4, "kd2_over_n": 1.0000},
}

BEST_CODE = "delta"


@pytest.fixture
def results():
    with open("/app/results.json", "r") as f:
        return json.load(f)


def test_results_structure(results):
    assert "codes" in results, "results.json must have 'codes' key"
    assert "best_code" in results, "results.json must have 'best_code' key"
    for name in EXPECTED:
        assert name in results["codes"], f"Missing code '{name}' in results"


@pytest.mark.parametrize("code_name", list(EXPECTED.keys()))
def test_n_parameter(results, code_name):
    actual = results["codes"][code_name]
    assert actual["n"] == EXPECTED[code_name]["n"], (
        f"Code {code_name}: expected n={EXPECTED[code_name]['n']}, got {actual['n']}"
    )


@pytest.mark.parametrize("code_name", list(EXPECTED.keys()))
def test_k_parameter(results, code_name):
    actual = results["codes"][code_name]
    assert actual["k"] == EXPECTED[code_name]["k"], (
        f"Code {code_name}: expected k={EXPECTED[code_name]['k']}, got {actual['k']}"
    )


@pytest.mark.parametrize("code_name", list(EXPECTED.keys()))
def test_d_parameter(results, code_name):
    actual = results["codes"][code_name]
    assert actual["d"] == EXPECTED[code_name]["d"], (
        f"Code {code_name}: expected d={EXPECTED[code_name]['d']}, got {actual['d']}"
    )


@pytest.mark.parametrize("code_name", list(EXPECTED.keys()))
def test_figure_of_merit(results, code_name):
    actual = results["codes"][code_name]
    expected_fom = EXPECTED[code_name]["kd2_over_n"]
    assert math.isclose(actual["kd2_over_n"], expected_fom, abs_tol=0.001), (
        f"Code {code_name}: expected kd2/n={expected_fom}, got {actual['kd2_over_n']}"
    )


def test_best_code(results):
    assert results["best_code"] == BEST_CODE, (
        f"Expected best_code='{BEST_CODE}', got '{results['best_code']}'"
    )
