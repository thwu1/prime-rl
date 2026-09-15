
"""Verification tests for Stokes solver implementation."""

import json
import math
import os
import shutil
import subprocess

import pytest

RESULTS_FILE = "/app/results.json"
SOLVER_FILE = "/app/stokes_solver.py"


@pytest.fixture(scope="session")
def fresh_results():
    """Re-run the solver to produce fresh results (anti-cheat measure)."""
    assert os.path.isfile(SOLVER_FILE), (
        f"Solver script {SOLVER_FILE} not found"
    )

    # Remove any pre-existing results to force re-computation
    if os.path.isfile(RESULTS_FILE):
        os.remove(RESULTS_FILE)

    result = subprocess.run(
        ["python3", SOLVER_FILE],
        capture_output=True,
        timeout=240,
        cwd="/app",
    )
    assert result.returncode == 0, (
        f"Solver failed with exit code {result.returncode}.\n"
        f"stderr: {result.stderr.decode()[:1000]}"
    )
    assert os.path.isfile(RESULTS_FILE), (
        f"Solver ran successfully but {RESULTS_FILE} was not created"
    )
    with open(RESULTS_FILE, "r") as f:
        return json.load(f)


def test_solver_script_is_nontrivial():
    """Solver must be a substantial implementation, not a stub."""
    assert os.path.isfile(SOLVER_FILE), f"{SOLVER_FILE} not found"
    with open(SOLVER_FILE) as f:
        content = f.read()
    code_lines = [
        ln for ln in content.split("\n")
        if ln.strip() and not ln.strip().startswith("#")
    ]
    assert len(code_lines) >= 80, (
        f"Solver has only {len(code_lines)} non-comment lines; "
        "expected a substantial implementation (>= 80 lines)"
    )


def test_solver_uses_framework():
    """Solver must use the provided framework utilities."""
    with open(SOLVER_FILE) as f:
        content = f.read()
    uses_framework = (
        "fem_framework" in content or "problem_spec" in content
    )
    assert uses_framework, (
        "Solver does not appear to import from fem_framework or problem_spec"
    )


def test_results_has_required_keys(fresh_results):
    """All required keys present in results."""
    required = [
        "mesh_sizes",
        "velocity_l2_errors",
        "pressure_l2_errors",
        "velocity_convergence_rates",
        "pressure_convergence_rates",
        "velocity_avg_convergence_rate",
        "pressure_avg_convergence_rate",
    ]
    for key in required:
        assert key in fresh_results, f"Missing key: {key}"


def test_mesh_sizes(fresh_results):
    """Mesh sizes must be [4, 8, 16, 32]."""
    assert fresh_results["mesh_sizes"] == [4, 8, 16, 32]


def test_four_error_values(fresh_results):
    """Must have exactly 4 error values (one per mesh size)."""
    assert len(fresh_results["velocity_l2_errors"]) == 4
    assert len(fresh_results["pressure_l2_errors"]) == 4


def test_three_rate_values(fresh_results):
    """Must have exactly 3 convergence rates (between consecutive pairs)."""
    assert len(fresh_results["velocity_convergence_rates"]) == 3
    assert len(fresh_results["pressure_convergence_rates"]) == 3


def test_velocity_errors_positive(fresh_results):
    """All velocity L2 errors must be positive."""
    for i, e in enumerate(fresh_results["velocity_l2_errors"]):
        assert e > 0, f"velocity_l2_errors[{i}] = {e} is not positive"


def test_pressure_errors_positive(fresh_results):
    """All pressure L2 errors must be positive."""
    for i, e in enumerate(fresh_results["pressure_l2_errors"]):
        assert e > 0, f"pressure_l2_errors[{i}] = {e} is not positive"


def test_velocity_errors_monotone_decrease(fresh_results):
    """Velocity errors must decrease with mesh refinement."""
    errs = fresh_results["velocity_l2_errors"]
    for i in range(len(errs) - 1):
        assert errs[i] > errs[i + 1], (
            f"Velocity errors not decreasing: e[{i}]={errs[i]:.6e} "
            f"<= e[{i+1}]={errs[i+1]:.6e}"
        )


def test_pressure_errors_monotone_decrease(fresh_results):
    """Pressure errors must decrease with mesh refinement."""
    errs = fresh_results["pressure_l2_errors"]
    for i in range(len(errs) - 1):
        assert errs[i] > errs[i + 1], (
            f"Pressure errors not decreasing: e[{i}]={errs[i]:.6e} "
            f"<= e[{i+1}]={errs[i+1]:.6e}"
        )


def test_velocity_avg_convergence_rate(fresh_results):
    """Average velocity convergence rate must be in expected range."""
    rate = fresh_results["velocity_avg_convergence_rate"]
    assert 2.5 <= rate <= 3.5, (
        f"Velocity avg convergence rate {rate:.3f} not in [2.5, 3.5]"
    )


def test_pressure_avg_convergence_rate(fresh_results):
    """Average pressure convergence rate must be in expected range."""
    rate = fresh_results["pressure_avg_convergence_rate"]
    assert 1.5 <= rate <= 2.5, (
        f"Pressure avg convergence rate {rate:.3f} not in [1.5, 2.5]"
    )


def test_velocity_individual_rates(fresh_results):
    """Each individual velocity convergence rate must be reasonable."""
    for i, r in enumerate(fresh_results["velocity_convergence_rates"]):
        assert 2.0 <= r <= 4.0, (
            f"velocity_convergence_rates[{i}] = {r:.3f} not in [2.0, 4.0]"
        )


def test_pressure_individual_rates(fresh_results):
    """Each individual pressure convergence rate must be reasonable."""
    for i, r in enumerate(fresh_results["pressure_convergence_rates"]):
        assert 1.0 <= r <= 3.0, (
            f"pressure_convergence_rates[{i}] = {r:.3f} not in [1.0, 3.0]"
        )


def test_finest_velocity_error_small(fresh_results):
    """Velocity L2 error at n=32 must be below threshold."""
    e = fresh_results["velocity_l2_errors"][-1]
    assert e < 0.005, f"Finest velocity error {e:.6e} exceeds 0.005"


def test_finest_pressure_error_small(fresh_results):
    """Pressure L2 error at n=32 must be below threshold."""
    e = fresh_results["pressure_l2_errors"][-1]
    assert e < 0.05, f"Finest pressure error {e:.6e} exceeds 0.05"


def test_convergence_rates_consistent_with_errors(fresh_results):
    """Verify that reported rates match the reported errors."""
    vel_errs = fresh_results["velocity_l2_errors"]
    vel_rates = fresh_results["velocity_convergence_rates"]
    for i in range(3):
        expected_rate = math.log(vel_errs[i] / vel_errs[i + 1]) / math.log(2.0)
        assert abs(vel_rates[i] - expected_rate) < 0.01, (
            f"velocity rate[{i}]={vel_rates[i]:.4f} inconsistent with "
            f"errors (expected {expected_rate:.4f})"
        )

    pres_errs = fresh_results["pressure_l2_errors"]
    pres_rates = fresh_results["pressure_convergence_rates"]
    for i in range(3):
        expected_rate = math.log(pres_errs[i] / pres_errs[i + 1]) / math.log(2.0)
        assert abs(pres_rates[i] - expected_rate) < 0.01, (
            f"pressure rate[{i}]={pres_rates[i]:.4f} inconsistent with "
            f"errors (expected {expected_rate:.4f})"
        )


def test_solver_is_reproducible(fresh_results):
    """Re-run the solver a second time and verify identical results."""
    if os.path.isfile(RESULTS_FILE):
        os.remove(RESULTS_FILE)

    result = subprocess.run(
        ["python3", SOLVER_FILE],
        capture_output=True,
        timeout=240,
        cwd="/app",
    )
    assert result.returncode == 0, "Solver second run failed"

    with open(RESULTS_FILE) as f:
        rerun = json.load(f)

    for key in ["velocity_l2_errors", "pressure_l2_errors"]:
        for i in range(len(fresh_results[key])):
            orig = fresh_results[key][i]
            new = rerun[key][i]
            rel_diff = abs(orig - new) / (abs(orig) + 1e-15)
            assert rel_diff < 1e-6, (
                f"Non-reproducible {key}[{i}]: {orig:.10e} vs {new:.10e}"
            )


def test_error_ratio_between_meshes(fresh_results):
    """Verify error reduction ratio is consistent with stated rates.

    The ratio e_i/e_{i+1} should equal 2^r_i where r_i is the
    convergence rate. This cross-checks that errors and rates
    are self-consistent and come from actual computation.
    """
    vel_errs = fresh_results["velocity_l2_errors"]
    for i in range(3):
        ratio = vel_errs[i] / vel_errs[i + 1]
        # For rate ~3, ratio should be ~8 (between 4 and 16)
        assert 4.0 < ratio < 16.0, (
            f"Velocity error ratio e[{i}]/e[{i+1}] = {ratio:.2f} "
            "is outside expected range [4, 16]"
        )

    pres_errs = fresh_results["pressure_l2_errors"]
    for i in range(3):
        ratio = pres_errs[i] / pres_errs[i + 1]
        # For rate ~2, ratio should be ~4 (between 2 and 8)
        assert 2.0 < ratio < 8.0, (
            f"Pressure error ratio e[{i}]/e[{i+1}] = {ratio:.2f} "
            "is outside expected range [2, 8]"
        )
