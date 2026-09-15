
import json
import math
import os
import pytest


# Reference values computed from the Fishtest SPRT statistical framework.
# Each entry: (id, LLR, decision, elo, ci_low, ci_high, LOS)
REFERENCE = {
    "run_alpha": {
        "LLR": -19.020024,
        "decision": "rejected",
        "elo": -8.6377,
        "ci": [-17.6427, 0.3736],
        "LOS": 0.030113,
    },
    "run_beta": {
        "LLR": 47.187454,
        "decision": "accepted",
        "elo": 7.6439,
        "ci": [1.1319, 14.0836],
        "LOS": 0.989053,
    },
    "run_gamma": {
        "LLR": 0.338438,
        "decision": "continue",
        "elo": 4.3982,
        "ci": [-5.9880, 14.8014],
        "LOS": 0.796903,
    },
    "run_delta": {
        "LLR": 2.162941,
        "decision": "continue",
        "elo": 0.8652,
        "ci": [0.1683, 1.5407],
        "LOS": 0.992000,
    },
    "run_epsilon": {
        "LLR": 2.131068,
        "decision": "continue",
        "elo": -0.9925,
        "ci": [-3.4885, 1.4886],
        "LOS": 0.188035,
    },
    "run_zeta": {
        "LLR": -7.088346,
        "decision": "rejected",
        "elo": 0.7183,
        "ci": [-3.5997, 5.2992],
        "LOS": 0.626147,
    },
    "run_eta": {
        "LLR": 0.868515,
        "decision": "continue",
        "elo": -0.5189,
        "ci": [-2.4646, 1.3463],
        "LOS": 0.290369,
    },
}

# Tolerances
LLR_TOL = 0.15
ELO_TOL = 1.0
CI_TOL = 1.5
LOS_TOL = 0.03

LOWER_BOUND = math.log(0.05 / 0.95)
UPPER_BOUND = math.log(0.95 / 0.05)
BOUND_TOL = 0.001


@pytest.fixture(scope="module")
def results():
    path = "/app/results.json"
    assert os.path.exists(path), f"Output file {path} does not exist"
    with open(path) as f:
        data = json.load(f)
    assert isinstance(data, list), "results.json must be a JSON array"
    return {item["id"]: item for item in data}


def test_all_runs_present(results):
    """All 7 test runs must be present in the output."""
    for run_id in REFERENCE:
        assert run_id in results, f"Missing run {run_id} in output"


@pytest.mark.parametrize("run_id", list(REFERENCE.keys()))
def test_decision(results, run_id):
    """SPRT decision must exactly match (accepted/rejected/continue)."""
    assert run_id in results, f"Missing run {run_id}"
    expected = REFERENCE[run_id]["decision"]
    actual = results[run_id]["decision"]
    assert actual == expected, (
        f"Run {run_id}: expected decision '{expected}', got '{actual}'"
    )


@pytest.mark.parametrize("run_id", list(REFERENCE.keys()))
def test_llr(results, run_id):
    """LLR must be within tolerance of reference value."""
    assert run_id in results, f"Missing run {run_id}"
    expected = REFERENCE[run_id]["LLR"]
    actual = results[run_id]["LLR"]
    assert abs(actual - expected) < LLR_TOL, (
        f"Run {run_id}: LLR expected {expected:.6f}, got {actual:.6f}, "
        f"diff={abs(actual - expected):.6f} (tol={LLR_TOL})"
    )


@pytest.mark.parametrize("run_id", list(REFERENCE.keys()))
def test_elo_estimate(results, run_id):
    """Elo estimate must be within tolerance of reference value."""
    assert run_id in results, f"Missing run {run_id}"
    expected = REFERENCE[run_id]["elo"]
    actual = results[run_id]["elo"]
    assert abs(actual - expected) < ELO_TOL, (
        f"Run {run_id}: Elo expected {expected:.4f}, got {actual:.4f}, "
        f"diff={abs(actual - expected):.4f} (tol={ELO_TOL})"
    )


@pytest.mark.parametrize("run_id", list(REFERENCE.keys()))
def test_confidence_interval(results, run_id):
    """95% CI bounds must be within tolerance of reference values."""
    assert run_id in results, f"Missing run {run_id}"
    expected_ci = REFERENCE[run_id]["ci"]
    actual_ci = results[run_id]["ci"]
    assert isinstance(actual_ci, list) and len(actual_ci) == 2, (
        f"Run {run_id}: ci must be a 2-element array, got {actual_ci}"
    )
    assert abs(actual_ci[0] - expected_ci[0]) < CI_TOL, (
        f"Run {run_id}: CI lower expected {expected_ci[0]:.4f}, got {actual_ci[0]:.4f}"
    )
    assert abs(actual_ci[1] - expected_ci[1]) < CI_TOL, (
        f"Run {run_id}: CI upper expected {expected_ci[1]:.4f}, got {actual_ci[1]:.4f}"
    )


@pytest.mark.parametrize("run_id", list(REFERENCE.keys()))
def test_los(results, run_id):
    """LOS (Likelihood of Superiority) must be within tolerance."""
    assert run_id in results, f"Missing run {run_id}"
    expected = REFERENCE[run_id]["LOS"]
    actual = results[run_id]["LOS"]
    assert abs(actual - expected) < LOS_TOL, (
        f"Run {run_id}: LOS expected {expected:.6f}, got {actual:.6f}, "
        f"diff={abs(actual - expected):.6f} (tol={LOS_TOL})"
    )


@pytest.mark.parametrize("run_id", list(REFERENCE.keys()))
def test_bounds(results, run_id):
    """SPRT bounds must be correct for alpha=beta=0.05."""
    assert run_id in results, f"Missing run {run_id}"
    r = results[run_id]
    assert abs(r["lower_bound"] - LOWER_BOUND) < BOUND_TOL, (
        f"Run {run_id}: lower_bound expected {LOWER_BOUND:.6f}, got {r['lower_bound']}"
    )
    assert abs(r["upper_bound"] - UPPER_BOUND) < BOUND_TOL, (
        f"Run {run_id}: upper_bound expected {UPPER_BOUND:.6f}, got {r['upper_bound']}"
    )


def test_decision_consistency(results):
    """Verify that decisions are consistent with LLR and bounds."""
    for run_id, r in results.items():
        if run_id not in REFERENCE:
            continue
        llr = r["LLR"]
        lb = r["lower_bound"]
        ub = r["upper_bound"]
        decision = r["decision"]
        if decision == "rejected":
            assert llr < lb + 0.1, (
                f"Run {run_id}: rejected but LLR={llr:.4f} >= lower_bound={lb:.4f}"
            )
        elif decision == "accepted":
            assert llr > ub - 0.1, (
                f"Run {run_id}: accepted but LLR={llr:.4f} <= upper_bound={ub:.4f}"
            )
        elif decision == "continue":
            assert lb - 0.1 <= llr <= ub + 0.1, (
                f"Run {run_id}: continue but LLR={llr:.4f} outside bounds"
            )


def test_ci_ordering(results):
    """Lower CI bound must be less than upper CI bound, and elo within CI."""
    for run_id, r in results.items():
        ci = r["ci"]
        assert ci[0] < ci[1], (
            f"Run {run_id}: CI lower {ci[0]} >= upper {ci[1]}"
        )
        assert ci[0] - 1.0 <= r["elo"] <= ci[1] + 1.0, (
            f"Run {run_id}: Elo {r['elo']} outside CI [{ci[0]}, {ci[1]}]"
        )


def test_los_range(results):
    """LOS must be between 0 and 1."""
    for run_id, r in results.items():
        assert 0 <= r["LOS"] <= 1, (
            f"Run {run_id}: LOS={r['LOS']} outside [0, 1]"
        )
