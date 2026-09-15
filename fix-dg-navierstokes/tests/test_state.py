"""
Verification tests for the DG Navier-Stokes solver implementation
and mesh convergence study.

Runs the solver and convergence study as subprocesses, checks error
norms against thresholds, verifies convergence rates, and
includes structural anti-cheat measures.

"""

import json
import os
import subprocess

import pytest

SOLVER_PATH = "/app/solver.py"
RESULTS_PATH = "/app/results.json"
CONVERGENCE_SCRIPT = "/app/convergence.py"
CONVERGENCE_PATH = "/app/convergence.json"


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture(scope="session")
def solver_run():
    """Run the solver fresh and return the CompletedProcess."""
    assert os.path.exists(SOLVER_PATH), (
        f"{SOLVER_PATH} not found — solver must be implemented"
    )
    if os.path.exists(RESULTS_PATH):
        os.remove(RESULTS_PATH)
    return subprocess.run(
        ["python3", SOLVER_PATH],
        capture_output=True, text=True, timeout=300, cwd="/app",
    )


@pytest.fixture(scope="session")
def results(solver_run):
    """Load solver results from JSON, failing if the solver crashed."""
    assert solver_run.returncode == 0, (
        f"Solver exited with code {solver_run.returncode}.\n"
        f"stdout (last 1500 chars):\n{solver_run.stdout[-1500:]}\n"
        f"stderr (last 1500 chars):\n{solver_run.stderr[-1500:]}"
    )
    assert os.path.exists(RESULTS_PATH), (
        f"{RESULTS_PATH} not found after solver completed."
    )
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return data


@pytest.fixture(scope="session")
def convergence_run():
    """Run the convergence study and return the CompletedProcess."""
    assert os.path.exists(CONVERGENCE_SCRIPT), (
        f"{CONVERGENCE_SCRIPT} not found — convergence study must be implemented"
    )
    if os.path.exists(CONVERGENCE_PATH):
        os.remove(CONVERGENCE_PATH)
    return subprocess.run(
        ["python3", CONVERGENCE_SCRIPT],
        capture_output=True, text=True, timeout=600, cwd="/app",
    )


@pytest.fixture(scope="session")
def convergence_data(convergence_run):
    """Load convergence study results."""
    assert convergence_run.returncode == 0, (
        f"Convergence study failed.\n"
        f"stdout (last 1500 chars):\n{convergence_run.stdout[-1500:]}\n"
        f"stderr (last 1500 chars):\n{convergence_run.stderr[-1500:]}"
    )
    assert os.path.exists(CONVERGENCE_PATH), (
        f"{CONVERGENCE_PATH} not found after convergence study completed."
    )
    with open(CONVERGENCE_PATH) as f:
        data = json.load(f)
    return data


# ===================================================================
# Anti-cheat: structural verification
# ===================================================================

def test_solver_structure():
    """Verify solver.py is a real DG Navier-Stokes implementation,
    not hardcoded results or a trivial script."""
    assert os.path.exists(SOLVER_PATH), "solver.py not found"
    with open(SOLVER_PATH) as f:
        code = f.read()

    non_comment = [
        l for l in code.strip().split("\n")
        if l.strip() and not l.strip().startswith("#")
    ]
    assert len(non_comment) > 60, (
        f"solver.py has only {len(non_comment)} non-comment lines — "
        "too short for a real DG Navier-Stokes implementation"
    )

    # Must contain DG-specific UFL constructs
    assert "dS" in code, (
        "No interior facet integrals (dS) found — "
        "not a discontinuous Galerkin method"
    )
    assert "grad" in code, (
        "No gradient operator found — not a real FEM formulation"
    )
    assert "FacetNormal" in code or "facet_normal" in code.lower(), (
        "No facet normal — required for DG formulation"
    )

    # Must use H(div)-conforming elements
    has_hdiv = (
        "Raviart-Thomas" in code or "RT" in code
        or "BDM" in code or "Brezzi-Douglas-Marini" in code
    )
    assert has_hdiv, (
        "No H(div) elements (RT or BDM) found — "
        "required for divergence-conforming method"
    )

    # Must implement upwind/convective flux
    has_convection = (
        "lmbda" in code or "conditional" in code
        or "upwind" in code.lower()
    )
    assert has_convection, "No upwind/convective flux implementation found"

    # Must configure MUMPS for singular saddle-point system
    assert "mumps" in code.lower(), "No MUMPS solver configuration found"


def test_convergence_script_structure():
    """Verify convergence.py is a real computation, not hardcoded."""
    assert os.path.exists(CONVERGENCE_SCRIPT), "convergence.py not found"
    with open(CONVERGENCE_SCRIPT) as f:
        code = f.read()

    non_comment = [
        l for l in code.strip().split("\n")
        if l.strip() and not l.strip().startswith("#")
    ]
    assert len(non_comment) > 15, (
        f"convergence.py has only {len(non_comment)} non-comment lines — "
        "too short for a real convergence study"
    )

    # Must compute rates (log, polyfit, or explicit rate calculation)
    has_rate_calc = (
        "log" in code or "polyfit" in code
        or "rate" in code.lower()
    )
    assert has_rate_calc, "No convergence rate computation found"


# ===================================================================
# Accuracy tests — solver on 16x16 mesh
# ===================================================================

def test_solver_converged(results):
    """The solver must report successful convergence."""
    assert results.get("converged") is True, (
        "Solver did not report convergence."
    )


def test_velocity_l2_error(results):
    """Velocity L2 error must be below 0.05.

    A correct div-conforming DG solver with k=1 on a 16x16 mesh
    achieves e_u on the order of 1e-3 for Kovasznay flow at Re=25.
    """
    e_u = results["e_u"]
    assert isinstance(e_u, (int, float)), "e_u must be a number"
    assert e_u > 1e-10, (
        f"Velocity L2 error suspiciously small: {e_u:.2e}. "
        "Suggests fabricated results."
    )
    assert e_u < 0.05, (
        f"Velocity L2 error too large: {e_u:.5e} (threshold: 0.05)."
    )


def test_divergence_free(results):
    """Velocity divergence must be near machine precision.

    For a truly div-conforming method (H(div) velocity + matching
    pressure with div(V_h) = Q_h), the divergence error should be
    O(eps_mach). A nonzero divergence indicates wrong space pairing.
    """
    e_div_u = results["e_div_u"]
    assert isinstance(e_div_u, (int, float)), "e_div_u must be a number"
    assert e_div_u < 1e-8, (
        f"Divergence error too large: {e_div_u:.5e} (threshold: 1e-8). "
        "The velocity-pressure spaces do NOT satisfy div(V_h) = Q_h."
    )


def test_pressure_l2_error(results):
    """Pressure L2 error must be below 0.5.

    A correct solver achieves e_p on the order of 1e-3.
    """
    e_p = results["e_p"]
    assert isinstance(e_p, (int, float)), "e_p must be a number"
    assert e_p > 1e-10, (
        f"Pressure L2 error suspiciously small: {e_p:.2e}. "
        "Suggests fabricated results."
    )
    assert e_p < 0.5, (
        f"Pressure L2 error too large: {e_p:.5e} (threshold: 0.5)."
    )


def test_results_keys(results):
    """Cross-check that all required fields are present."""
    required_keys = {"e_u", "e_div_u", "e_p", "converged"}
    missing = required_keys - set(results.keys())
    assert not missing, f"Missing keys in results.json: {missing}"


# ===================================================================
# Convergence study tests
# ===================================================================

def test_convergence_data_complete(convergence_data):
    """Convergence data has all required fields and sufficient mesh sizes."""
    required = {"mesh_sizes", "errors_u", "errors_p", "rate_u", "rate_p"}
    missing = required - set(convergence_data.keys())
    assert not missing, f"Missing keys in convergence.json: {missing}"

    n = len(convergence_data["mesh_sizes"])
    assert n >= 3, f"Need at least 3 mesh sizes for convergence study, got {n}"
    assert len(convergence_data["errors_u"]) == n, (
        "Length mismatch: errors_u vs mesh_sizes"
    )
    assert len(convergence_data["errors_p"]) == n, (
        "Length mismatch: errors_p vs mesh_sizes"
    )


def test_convergence_monotone(convergence_data):
    """Errors must decrease monotonically as the mesh is refined."""
    for key in ["errors_u", "errors_p"]:
        errs = convergence_data[key]
        for i in range(1, len(errs)):
            assert errs[i] < errs[i - 1], (
                f"{key} not monotonically decreasing: {errs}"
            )


def test_velocity_convergence_rate(convergence_data):
    """Velocity convergence rate must be >= 1.5 (theory: ~2 for k=1 RT)."""
    rate_u = convergence_data["rate_u"]
    assert isinstance(rate_u, (int, float)), "rate_u must be a number"
    assert rate_u >= 1.5, (
        f"Velocity convergence rate {rate_u:.2f} < 1.5 — "
        "implementation does not achieve optimal convergence. "
        "Expected ~2.0 for k=1 with H(div)-conforming elements."
    )


def test_pressure_convergence_rate(convergence_data):
    """Pressure convergence rate must be >= 0.9.

    For DG Navier-Stokes with upwind convective flux, the numerical
    viscosity from upwinding limits pressure convergence to ~O(h),
    yielding rates around 1.0-1.2 rather than the theoretical O(h^2)
    that holds for the Stokes case.
    """
    rate_p = convergence_data["rate_p"]
    assert isinstance(rate_p, (int, float)), "rate_p must be a number"
    assert rate_p >= 0.9, (
        f"Pressure convergence rate {rate_p:.2f} < 0.9 — "
        "pressure convergence is too poor. "
        "For k=1 DG Navier-Stokes with upwind flux, rate >= 1.0 expected."
    )


def test_errors_plausible(convergence_data):
    """Individual errors in the convergence study must be plausible."""
    for e_u in convergence_data["errors_u"]:
        assert e_u > 1e-12, f"Velocity error {e_u:.2e} suspiciously small"
        assert e_u < 10.0, f"Velocity error {e_u:.2e} implausibly large"
    for e_p in convergence_data["errors_p"]:
        assert e_p > 1e-12, f"Pressure error {e_p:.2e} suspiciously small"
        assert e_p < 10.0, f"Pressure error {e_p:.2e} implausibly large"
