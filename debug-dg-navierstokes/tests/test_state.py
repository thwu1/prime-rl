"""
Verification tests for the DG Navier-Stokes Kovasznay flow solver.

Tests check that the solver produces correct results within expected
error tolerances and that the implementation is non-trivial.
"""


import json
import math
import os
import pytest


RESULTS_PATH = "/app/results.json"
SOLVER_PATH = "/app/solver.py"


@pytest.fixture
def results():
    """Load solver results from the JSON output file."""
    if not os.path.isfile(RESULTS_PATH):
        pytest.fail(
            f"Results file {RESULTS_PATH} not found. "
            "The solver did not produce output."
        )
    with open(RESULTS_PATH) as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            pytest.fail(f"Results file {RESULTS_PATH} contains invalid JSON.")
    return data


def test_results_has_required_keys(results):
    """Results must contain all required error metric keys."""
    required = ["velocity_l2_error", "pressure_l2_error", "divergence_l2_error"]
    for key in required:
        assert key in results, f"Missing key '{key}' in results"
        assert isinstance(results[key], (int, float)), (
            f"Value for '{key}' must be numeric, got {type(results[key])}"
        )


def test_errors_are_positive_finite(results):
    """All error metrics must be non-negative finite numbers."""
    for key in ["velocity_l2_error", "pressure_l2_error", "divergence_l2_error"]:
        val = results[key]
        assert math.isfinite(val), f"{key} = {val} is not finite"
        assert val >= 0, f"{key} = {val} is negative"


def test_velocity_l2_error(results):
    """Velocity L2 error must be below 5e-2.

    For a correct SIP-DG method with RT2/DG1 elements on a 16x16 mesh
    at Re=25, the expected velocity error is O(h^2) ~ 4e-3.
    """
    tol = 5e-2
    err = results["velocity_l2_error"]
    assert err < tol, (
        f"Velocity L2 error {err:.4e} exceeds tolerance {tol:.0e}"
    )


def test_pressure_l2_error(results):
    """Pressure L2 error must be below 5e-1."""
    tol = 5e-1
    err = results["pressure_l2_error"]
    assert err < tol, (
        f"Pressure L2 error {err:.4e} exceeds tolerance {tol:.0e}"
    )


def test_mass_conservation(results):
    """Divergence-conforming elements must conserve mass exactly.

    The divergence of the velocity in an H(div)-conforming space
    should be zero to machine precision.
    """
    tol = 1e-8
    err = results["divergence_l2_error"]
    assert err < tol, (
        f"Divergence L2 error {err:.4e} exceeds tolerance {tol:.0e} "
        "-- mass conservation violated"
    )


def test_velocity_error_plausible(results):
    """Velocity error should be plausible for a 16x16 mesh discretization.

    Implausibly small values suggest hardcoded or fabricated results
    rather than a genuine FEM computation.
    """
    err = results["velocity_l2_error"]
    assert err > 1e-5, (
        f"Velocity L2 error {err:.4e} is implausibly small for a 16x16 mesh"
    )


def test_pressure_error_plausible(results):
    """Pressure error should be plausible for a 16x16 mesh discretization."""
    err = results["pressure_l2_error"]
    assert err > 1e-5, (
        f"Pressure L2 error {err:.4e} is implausibly small for a 16x16 mesh"
    )


def test_solver_is_nontrivial():
    """Verify solver.py is a genuine FEM implementation, not a stub.

    A real DG Navier-Stokes solver requires substantial code for
    variational forms, solver configuration, and time-stepping.
    """
    assert os.path.isfile(SOLVER_PATH), "solver.py does not exist"
    with open(SOLVER_PATH) as f:
        content = f.read()
    # Count non-empty, non-comment lines
    lines = [
        ln for ln in content.strip().split("\n")
        if ln.strip() and not ln.strip().startswith("#")
    ]
    assert len(lines) >= 50, (
        f"solver.py has only {len(lines)} non-empty non-comment lines "
        "-- expected a real FEM implementation (50+ lines)"
    )
    assert "dolfinx" in content or "ufl" in content, (
        "solver.py does not appear to use DOLFINx or UFL"
    )
