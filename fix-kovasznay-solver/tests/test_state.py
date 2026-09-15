
import json
import os

import pytest

RESULTS_FILE = "/app/results.json"


@pytest.fixture
def results():
    """Load solver results from JSON output."""
    assert os.path.exists(RESULTS_FILE), (
        f"{RESULTS_FILE} not found -- the solver likely crashed before writing output"
    )
    with open(RESULTS_FILE) as f:
        data = json.load(f)
    required_keys = {"e_u", "e_p", "e_div", "iterations"}
    assert required_keys.issubset(data.keys()), (
        f"Missing keys in results: {required_keys - data.keys()}"
    )
    return data


def test_velocity_l2_error(results):
    """L2 velocity error must be below 5e-3 for a correct Navier-Stokes solution."""
    threshold = 5e-3
    assert results["e_u"] < threshold, (
        f"L2 velocity error {results['e_u']:.6e} exceeds threshold {threshold:.0e}. "
        "Check the weak form coefficients and boundary conditions."
    )


def test_pressure_l2_error(results):
    """L2 pressure error (mean-adjusted) must be below 5e-2."""
    threshold = 5e-2
    assert results["e_p"] < threshold, (
        f"L2 pressure error {results['e_p']:.6e} exceeds threshold {threshold:.0e}. "
        "Check the pressure-velocity coupling sign and boundary conditions."
    )
