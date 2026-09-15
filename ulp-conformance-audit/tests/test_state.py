
import json
import os
import math
import numpy as np
import mpmath
import pytest

mpmath.mp.prec = 200

REPORT_PATH = "/app/audit_report.json"

EXPECTED_FAILING = sorted(["sin", "cos", "exp2", "log2", "sqrt", "cbrt"])
EXPECTED_PASSING = sorted(["tan", "exp", "log", "rsqrt", "asin", "erfc"])
ALL_FUNCTIONS = sorted(EXPECTED_FAILING + EXPECTED_PASSING)

# Expected max ULP errors (with tolerance for minor floating-point differences)
EXPECTED_MAX_ULP = {
    "sin": 6.0,
    "cos": 5.34,
    "tan": 4.41,
    "exp": 1.38,
    "exp2": 4.32,
    "log": 2.47,
    "log2": 4.49,
    "sqrt": 1.42,
    "rsqrt": 1.36,
    "cbrt": 3.27,
    "asin": 3.37,
    "erfc": 13.67,
}

TOLERANCES = {
    "sin": 4.0,
    "cos": 4.0,
    "tan": 5.0,
    "exp": 3.0,
    "exp2": 3.0,
    "log": 3.0,
    "log2": 3.0,
    "sqrt": 0.0,
    "rsqrt": 2.0,
    "cbrt": 2.0,
    "asin": 4.0,
    "erfc": 16.0,
}


@pytest.fixture
def report():
    assert os.path.exists(REPORT_PATH), f"Report file not found at {REPORT_PATH}"
    with open(REPORT_PATH) as f:
        data = json.load(f)
    return data


def test_report_structure(report):
    """Verify the report has the required top-level keys."""
    assert "functions" in report, "Missing 'functions' key"
    assert "overall_pass" in report, "Missing 'overall_pass' key"
    assert "functions_failing" in report, "Missing 'functions_failing' key"


def test_all_functions_present(report):
    """Verify all 12 functions are reported."""
    funcs = report["functions"]
    for fn in ALL_FUNCTIONS:
        assert fn in funcs, f"Missing function '{fn}' in report"


def test_function_entry_structure(report):
    """Verify each function entry has required fields."""
    for fn in ALL_FUNCTIONS:
        entry = report["functions"][fn]
        assert "pass" in entry, f"{fn}: missing 'pass'"
        assert "max_ulp_error" in entry, f"{fn}: missing 'max_ulp_error'"
        assert "num_test_cases" in entry, f"{fn}: missing 'num_test_cases'"
        assert "num_exceeding_tolerance" in entry, f"{fn}: missing 'num_exceeding_tolerance'"
        assert isinstance(entry["pass"], bool), f"{fn}: 'pass' must be bool"
        assert isinstance(entry["max_ulp_error"], (int, float)), f"{fn}: 'max_ulp_error' must be numeric"


def test_failing_functions(report):
    """Verify the correct set of functions are reported as failing."""
    failing = sorted(report["functions_failing"])
    assert failing == EXPECTED_FAILING, (
        f"Expected failing: {EXPECTED_FAILING}, got: {failing}"
    )


def test_passing_functions(report):
    """Verify the correct set of functions are reported as passing."""
    for fn in EXPECTED_PASSING:
        assert report["functions"][fn]["pass"] is True, (
            f"Function '{fn}' should PASS but reported as FAIL"
        )


def test_each_failing_function(report):
    """Verify each failing function is correctly identified."""
    for fn in EXPECTED_FAILING:
        entry = report["functions"][fn]
        assert entry["pass"] is False, (
            f"Function '{fn}' should FAIL (max_ulp={entry['max_ulp_error']}, "
            f"tolerance={TOLERANCES[fn]}) but reported as PASS"
        )


def test_overall_pass(report):
    """Overall pass should be False since some functions fail."""
    assert report["overall_pass"] is False, "overall_pass should be False"


def test_max_ulp_errors_approximate(report):
    """Verify max ULP errors are in the expected range (±0.5 ULP tolerance for rounding)."""
    for fn in ALL_FUNCTIONS:
        reported = report["functions"][fn]["max_ulp_error"]
        expected = EXPECTED_MAX_ULP[fn]
        assert abs(reported - expected) < 0.5, (
            f"{fn}: expected max_ulp ~{expected}, got {reported}"
        )


def test_functions_failing_sorted(report):
    """Verify functions_failing is sorted alphabetically."""
    failing = report["functions_failing"]
    assert failing == sorted(failing), "functions_failing must be sorted alphabetically"


def test_sqrt_fails_correctly_rounded(report):
    """sqrt requires correctly rounded results (0 ULP tolerance). Must fail."""
    entry = report["functions"]["sqrt"]
    assert entry["pass"] is False, "sqrt must fail (0 ULP tolerance, any error fails)"
    assert entry["max_ulp_error"] > 0.0, "sqrt must have nonzero max ULP error"


def test_num_exceeding_for_passing(report):
    """Passing functions should have 0 test cases exceeding tolerance."""
    for fn in EXPECTED_PASSING:
        entry = report["functions"][fn]
        assert entry["num_exceeding_tolerance"] == 0, (
            f"Passing function '{fn}' should have 0 exceeding, got {entry['num_exceeding_tolerance']}"
        )


def test_ftz_handling():
    """
    Verify the solver handles FTZ mode correctly by independently checking
    a known FTZ case from the test data.
    """
    with open("/app/test_data.json") as f:
        data = json.load(f)

    # sin function has FTZ test cases: denormal input, output = 0
    sin_cases = data["functions"]["sin"]["test_cases"]
    ftz_cases = []
    for tc in sin_cases:
        inp = np.uint32(int(tc["input_hex"], 16)).view(np.float32)
        out = np.uint32(int(tc["output_hex"], 16)).view(np.float32)
        # Check if input is denormal and output is zero
        inp_abs = abs(float(inp))
        if 0 < inp_abs < 1.175494e-38 and out == 0:
            ftz_cases.append(tc)

    assert len(ftz_cases) >= 1, "Expected at least 1 FTZ test case in sin data"

    # For these cases, the correct result sin(denormal) ≈ denormal (subnormal),
    # and with FTZ mode the output 0 should be accepted (0 ULP error).
    # The audit report should NOT count these as failures.
    with open(REPORT_PATH) as f:
        report = json.load(f)

    # If sin is listed as failing, it must be due to non-FTZ cases, not FTZ cases
    sin_entry = report["functions"]["sin"]
    # sin should fail, but its max ULP should come from normal-range inputs, not FTZ cases
    assert sin_entry["max_ulp_error"] > 4.0, "sin max ULP should exceed tolerance from normal inputs"


def test_ulp_computation_power_of_two_boundary():
    """
    Independently verify the solver handles the power-of-two ULP boundary.
    sin(pi/2) is just below 1.0 in infinite precision, so the ULP there is
    2^(-24), not 2^(-23). A 3-ULP bit perturbation above 1.0 (where each
    bit ULP = 2^(-23)) actually represents ~6 ULPs at the reference value.
    """
    # sin(float32(pi/2)) is very close to 1.0 but just below
    inp_hex = "3FC90FDA"  # float32(pi/2)
    inp_f32 = np.uint32(int(inp_hex, 16)).view(np.float32)

    # Compute exact reference
    ref = mpmath.sin(mpmath.mpf(float(inp_f32)))
    ref_f32 = np.float32(float(ref))

    # The reference is very close to 1.0
    # ULP at just-below-1.0 is 2^(-24) ≈ 5.96e-8
    # ULP at 1.0 and above is 2^(-23) ≈ 1.19e-7
    ref_abs = abs(float(ref))
    ref_exp = math.floor(math.log2(ref_abs))
    ulp_val = 2 ** (ref_exp - 23)

    # The test data has sin(pi/2) with a perturbation
    with open("/app/test_data.json") as f:
        data = json.load(f)

    sin_cases = data["functions"]["sin"]["test_cases"]
    case = None
    for tc in sin_cases:
        if tc["input_hex"] == inp_hex:
            case = tc
            break
    assert case is not None, "sin(pi/2) test case not found"

    out_f32 = np.uint32(int(case["output_hex"], 16)).view(np.float32)
    error = abs(float(out_f32) - float(ref))
    ulp_error = error / ulp_val

    # This case should show ~6 ULP error due to the power-of-two boundary
    assert ulp_error > 4.0, (
        f"sin(pi/2) ULP error should be >4 due to power-of-two boundary, got {ulp_error:.2f}"
    )

    # And the report should reflect this
    with open(REPORT_PATH) as f:
        report = json.load(f)
    assert report["functions"]["sin"]["max_ulp_error"] >= 5.0, (
        "sin max ULP should reflect power-of-two boundary amplification"
    )


def test_nan_handling(report):
    """NaN input → NaN output should be 0 ULP error, not counted as failure."""
    # erfc passes despite having NaN test cases
    assert report["functions"]["erfc"]["pass"] is True
    assert report["functions"]["erfc"]["num_exceeding_tolerance"] == 0


def test_num_test_cases_reasonable(report):
    """Each function should have processed a reasonable number of test cases."""
    with open("/app/test_data.json") as f:
        data = json.load(f)
    for fn in ALL_FUNCTIONS:
        expected_count = len(data["functions"][fn]["test_cases"])
        reported_count = report["functions"][fn]["num_test_cases"]
        assert reported_count == expected_count, (
            f"{fn}: expected {expected_count} test cases, got {reported_count}"
        )
