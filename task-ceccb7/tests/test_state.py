
import json
import os
import pytest


@pytest.fixture(scope="module")
def results():
    path = "/app/results.json"
    assert os.path.isfile(path), "results.json not found at /app/results.json"
    with open(path) as f:
        data = json.load(f)
    return data


# -- Structure tests ----------------------------------------------------------

def test_top_level_keys(results):
    assert "polynomials" in results, "Missing 'polynomials' key"
    assert "scenarios" in results, "Missing 'scenarios' key"


def test_polynomial_count(results):
    assert len(results["polynomials"]) == 5


EXPECTED_POLYS = ["0xe7", "0x97", "0x9b", "0xea", "0xa6"]

def test_all_polynomials_present(results):
    for p in EXPECTED_POLYS:
        assert p in results["polynomials"], f"Missing polynomial {p}"


def test_polynomial_fields(results):
    required = {"explicit_plus_1", "reciprocal_koopman", "is_primitive",
                "has_x_plus_1_factor", "hd_profile"}
    for p in EXPECTED_POLYS:
        entry = results["polynomials"][p]
        for field in required:
            assert field in entry, f"{p} missing field '{field}'"


# -- Notation conversion tests ------------------------------------------------

EXPLICIT_MAP = {
    "0xe7": "0x1cf",
    "0x97": "0x12f",
    "0x9b": "0x137",
    "0xea": "0x1d5",
    "0xa6": "0x14d",
}

RECIPROCAL_MAP = {
    "0xe7": "0xf3",
    "0x97": "0xf4",
    "0x9b": "0xec",
    "0xea": "0xab",
    "0xa6": "0xb2",
}


def _norm_hex(s):
    """Normalize hex string: lowercase, strip leading zeros after 0x."""
    s = s.strip().lower()
    if s.startswith("0x"):
        return hex(int(s, 16))
    return s


@pytest.mark.parametrize("poly", EXPECTED_POLYS)
def test_explicit_plus_1(results, poly):
    got = _norm_hex(results["polynomials"][poly]["explicit_plus_1"])
    expected = _norm_hex(EXPLICIT_MAP[poly])
    assert got == expected, f"{poly}: explicit_plus_1 {got} != {expected}"


@pytest.mark.parametrize("poly", EXPECTED_POLYS)
def test_reciprocal_koopman(results, poly):
    got = _norm_hex(results["polynomials"][poly]["reciprocal_koopman"])
    expected = _norm_hex(RECIPROCAL_MAP[poly])
    assert got == expected, f"{poly}: reciprocal {got} != {expected}"


# -- Algebraic property tests -------------------------------------------------

PRIMITIVE_MAP = {
    "0xe7": True,
    "0x97": False,
    "0x9b": False,
    "0xea": False,
    "0xa6": True,
}

X_PLUS_1_MAP = {
    "0xe7": False,
    "0x97": True,
    "0x9b": True,
    "0xea": True,
    "0xa6": False,
}


@pytest.mark.parametrize("poly", EXPECTED_POLYS)
def test_is_primitive(results, poly):
    got = results["polynomials"][poly]["is_primitive"]
    expected = PRIMITIVE_MAP[poly]
    assert got == expected, f"{poly}: is_primitive {got} != {expected}"


@pytest.mark.parametrize("poly", EXPECTED_POLYS)
def test_has_x_plus_1_factor(results, poly):
    got = results["polynomials"][poly]["has_x_plus_1_factor"]
    expected = X_PLUS_1_MAP[poly]
    assert got == expected, f"{poly}: has_x_plus_1_factor {got} != {expected}"


# -- Hamming Distance profile tests -------------------------------------------

HD_PROFILES = {
    "0xe7": [247, 19, 1, 1, 1],
    "0x97": [119, 119, 3, 3],
    "0x9b": [118, 118, 4, 4],
    "0xea": [85, 85, 2, 2],
    "0xa6": [247, 15, 6],
}


@pytest.mark.parametrize("poly", EXPECTED_POLYS)
def test_hd_profile(results, poly):
    got = results["polynomials"][poly]["hd_profile"]
    expected = HD_PROFILES[poly]
    assert got == expected, f"{poly}: hd_profile {got} != {expected}"


def test_primitive_polynomials_have_hd3_equal_247(results):
    """Primitive 8-bit CRC polynomials have HD3 max = 2^8 - 8 - 1 = 247."""
    for poly in ["0xe7", "0xa6"]:
        profile = results["polynomials"][poly]["hd_profile"]
        assert profile[0] == 247, f"{poly}: HD3 should be 247 for primitive poly"


def test_odd_detecting_hd_pairs(results):
    """Polynomials with (x+1) factor have paired HD levels."""
    for poly in ["0x97", "0x9b", "0xea"]:
        profile = results["polynomials"][poly]["hd_profile"]
        assert profile[0] == profile[1], f"{poly}: HD3 should equal HD4"
        if len(profile) >= 4:
            assert profile[2] == profile[3], f"{poly}: HD5 should equal HD6"


# -- Scenario evaluation tests ------------------------------------------------

SCENARIO_EVALUATIONS = {
    "long_range": {
        "0xe7": {"achieved_hd": 3, "meets_requirement": True},
        "0x97": {"achieved_hd": 2, "meets_requirement": False},
        "0x9b": {"achieved_hd": 2, "meets_requirement": False},
        "0xea": {"achieved_hd": 2, "meets_requirement": False},
        "0xa6": {"achieved_hd": 3, "meets_requirement": True},
    },
    "control_bus": {
        "0xe7": {"achieved_hd": 3, "meets_requirement": False},
        "0x97": {"achieved_hd": 4, "meets_requirement": True},
        "0x9b": {"achieved_hd": 4, "meets_requirement": True},
        "0xea": {"achieved_hd": 2, "meets_requirement": False},
        "0xa6": {"achieved_hd": 3, "meets_requirement": False},
    },
    "short_cmd": {
        "0xe7": {"achieved_hd": 4, "meets_requirement": False},
        "0x97": {"achieved_hd": 6, "meets_requirement": True},
        "0x9b": {"achieved_hd": 6, "meets_requirement": True},
        "0xea": {"achieved_hd": 4, "meets_requirement": False},
        "0xa6": {"achieved_hd": 5, "meets_requirement": True},
    },
}

BEST_POLY = {
    "long_range": "0xa6",
    "control_bus": "0x97",
    "short_cmd": "0x9b",
}


def test_scenario_count(results):
    assert len(results["scenarios"]) == 3


@pytest.mark.parametrize("scenario", ["long_range", "control_bus", "short_cmd"])
def test_scenario_present(results, scenario):
    assert scenario in results["scenarios"], f"Missing scenario '{scenario}'"


@pytest.mark.parametrize("scenario,poly", [
    (s, p) for s in SCENARIO_EVALUATIONS for p in EXPECTED_POLYS
])
def test_scenario_achieved_hd(results, scenario, poly):
    evals = results["scenarios"][scenario]["evaluations"]
    assert poly in evals, f"Missing {poly} in {scenario} evaluations"
    got_hd = evals[poly]["achieved_hd"]
    exp_hd = SCENARIO_EVALUATIONS[scenario][poly]["achieved_hd"]
    assert got_hd == exp_hd, (
        f"{scenario}/{poly}: achieved_hd {got_hd} != {exp_hd}"
    )


@pytest.mark.parametrize("scenario,poly", [
    (s, p) for s in SCENARIO_EVALUATIONS for p in EXPECTED_POLYS
])
def test_scenario_meets_requirement(results, scenario, poly):
    evals = results["scenarios"][scenario]["evaluations"]
    got = evals[poly]["meets_requirement"]
    exp = SCENARIO_EVALUATIONS[scenario][poly]["meets_requirement"]
    assert got == exp, (
        f"{scenario}/{poly}: meets_requirement {got} != {exp}"
    )


@pytest.mark.parametrize("scenario", ["long_range", "control_bus", "short_cmd"])
def test_best_polynomial(results, scenario):
    got = results["scenarios"][scenario]["best_polynomial"]
    expected = BEST_POLY[scenario]
    assert got == expected, f"{scenario}: best_polynomial {got} != {expected}"
