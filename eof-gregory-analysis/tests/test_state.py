"""
Verify corrected EOF analysis results and audit findings.

"""
import json
import os
import pytest


RESULTS_PATH = "/app/results.json"
AUDIT_PATH = "/app/audit.json"

# Expected correct values (deterministic dataset, seed=42)
EXPECTED_N_MODES = 4
EXPECTED_PERIODS_SORTED = [25.0, 30.0, 50.0, 60.0]
EXPECTED_VAR_PCT = [36.37, 17.85, 10.18, 9.05]
EXPECTED_ECS = 3.3266
EXPECTED_FEEDBACK = -1.2013
EXPECTED_TOTAL_VAR = 73.46

PERIOD_TOL = 5.0
VAR_PCT_TOL = 3.0
ECS_TOL = 0.5
FEEDBACK_TOL = 0.2
TOTAL_VAR_TOL = 5.0


@pytest.fixture
def results():
    assert os.path.isfile(RESULTS_PATH), (
        f"Results file not found at {RESULTS_PATH}"
    )
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return data


@pytest.fixture
def audit():
    assert os.path.isfile(AUDIT_PATH), (
        f"Audit file not found at {AUDIT_PATH}"
    )
    with open(AUDIT_PATH) as f:
        data = json.load(f)
    return data


# ---- Corrected results tests ----


def test_results_file_valid_json(results):
    """results.json exists and is parseable."""
    assert isinstance(results, dict), "results.json must be a JSON object"


def test_n_significant_modes(results):
    """Correct number of significant modes must be identified."""
    n = results.get("n_significant_modes")
    assert n is not None, "Missing key 'n_significant_modes'"
    assert isinstance(n, int), "n_significant_modes must be an integer"
    assert n == EXPECTED_N_MODES, (
        f"Expected {EXPECTED_N_MODES} significant modes, got {n}"
    )


def test_mode_periods(results):
    """Dominant periods must match expected values (sorted ascending)."""
    periods = results.get("mode_periods")
    assert periods is not None, "Missing key 'mode_periods'"
    assert isinstance(periods, list), "mode_periods must be a list"
    assert len(periods) == EXPECTED_N_MODES, (
        f"Expected {EXPECTED_N_MODES} periods, got {len(periods)}"
    )
    periods_sorted = sorted(periods)
    for i, (got, expected) in enumerate(
        zip(periods_sorted, EXPECTED_PERIODS_SORTED)
    ):
        assert abs(got - expected) <= PERIOD_TOL, (
            f"Period {i}: expected ~{expected}, got {got} "
            f"(tolerance +/-{PERIOD_TOL})"
        )


def test_explained_variance_pct(results):
    """Explained variance percentages must be close to expected values."""
    var_pct = results.get("explained_variance_pct")
    assert var_pct is not None, "Missing key 'explained_variance_pct'"
    assert isinstance(var_pct, list), "explained_variance_pct must be a list"
    assert len(var_pct) == EXPECTED_N_MODES, (
        f"Expected {EXPECTED_N_MODES} variance values, got {len(var_pct)}"
    )
    for i in range(len(var_pct) - 1):
        assert var_pct[i] >= var_pct[i + 1], (
            f"explained_variance_pct must be in descending order, "
            f"but index {i} ({var_pct[i]}) < index {i+1} ({var_pct[i+1]})"
        )
    for i, (got, expected) in enumerate(zip(var_pct, EXPECTED_VAR_PCT)):
        assert abs(got - expected) <= VAR_PCT_TOL, (
            f"Variance mode {i}: expected ~{expected}%, got {got}% "
            f"(tolerance +/-{VAR_PCT_TOL}%)"
        )


def test_ecs_estimate(results):
    """ECS estimate should be close to expected Gregory method value."""
    ecs = results.get("ecs_estimate")
    assert ecs is not None, "Missing key 'ecs_estimate'"
    assert isinstance(ecs, (int, float)), "ecs_estimate must be numeric"
    assert abs(ecs - EXPECTED_ECS) <= ECS_TOL, (
        f"ECS: expected ~{EXPECTED_ECS} K, got {ecs} K "
        f"(tolerance +/-{ECS_TOL})"
    )


def test_feedback_parameter(results):
    """Feedback parameter (regression slope) must be close to expected."""
    fb = results.get("feedback_parameter")
    assert fb is not None, "Missing key 'feedback_parameter'"
    assert isinstance(fb, (int, float)), "feedback_parameter must be numeric"
    assert fb < 0, f"Feedback parameter should be negative, got {fb}"
    assert abs(fb - EXPECTED_FEEDBACK) <= FEEDBACK_TOL, (
        f"Feedback: expected ~{EXPECTED_FEEDBACK} W/m^2/K, got {fb} "
        f"(tolerance +/-{FEEDBACK_TOL})"
    )


def test_total_variance_explained(results):
    """Total variance explained by significant modes."""
    total = results.get("total_variance_explained_pct")
    assert total is not None, "Missing key 'total_variance_explained_pct'"
    assert isinstance(total, (int, float)), (
        "total_variance_explained_pct must be numeric"
    )
    assert abs(total - EXPECTED_TOTAL_VAR) <= TOTAL_VAR_TOL, (
        f"Total variance: expected ~{EXPECTED_TOTAL_VAR}%, got {total}% "
        f"(tolerance +/-{TOTAL_VAR_TOL}%)"
    )


def test_total_variance_consistency(results):
    """Total variance should equal sum of individual variances."""
    var_pct = results.get("explained_variance_pct", [])
    total = results.get("total_variance_explained_pct")
    if var_pct and total is not None:
        computed_total = sum(var_pct)
        assert abs(computed_total - total) <= 1.0, (
            f"total_variance_explained_pct ({total}) should equal sum of "
            f"explained_variance_pct ({computed_total})"
        )


def test_ecs_physically_reasonable(results):
    """ECS must be in a physically plausible range (1-6 K)."""
    ecs = results.get("ecs_estimate", 0)
    assert 1.0 <= ecs <= 6.0, (
        f"ECS of {ecs} K is outside physically plausible range [1, 6] K"
    )


# ---- Audit report tests ----


def test_audit_file_exists():
    """Audit report must exist."""
    assert os.path.isfile(AUDIT_PATH), (
        f"Audit file not found at {AUDIT_PATH}"
    )


def test_audit_structure(audit):
    """Audit report must contain required keys with correct types."""
    assert "n_errors" in audit, "Missing key 'n_errors'"
    assert "errors_found" in audit, "Missing key 'errors_found'"
    assert isinstance(audit["n_errors"], int), "n_errors must be an integer"
    assert isinstance(audit["errors_found"], list), (
        "errors_found must be a list"
    )


def test_audit_error_count(audit):
    """At least 4 distinct methodological errors must be identified."""
    assert audit["n_errors"] >= 4, (
        f"Expected at least 4 errors identified, got {audit['n_errors']}"
    )
    assert len(audit["errors_found"]) >= 4, (
        f"Expected at least 4 error entries, got {len(audit['errors_found'])}"
    )


def test_audit_error_entries(audit):
    """Each error entry must have a category and substantive description."""
    for i, err in enumerate(audit["errors_found"]):
        assert isinstance(err, dict), f"Error {i} must be a dict"
        assert "category" in err, f"Error {i} missing 'category'"
        assert "description" in err, f"Error {i} missing 'description'"
        assert isinstance(err["category"], str) and len(err["category"]) > 0, (
            f"Error {i} has empty or non-string category"
        )
        assert isinstance(err["description"], str) and len(err["description"]) > 15, (
            f"Error {i} has insufficient description (must be >15 chars)"
        )
