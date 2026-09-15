"""
Tests for topology optimization implementation.
Verifies element stiffness, DOF mapping, assembly, sensitivities,
OC update, and full optimization convergence.
"""

import pytest
import numpy as np
import json
import subprocess
import sys
import os

sys.path.insert(0, "/app")


# ===================== Unit Tests: Element Stiffness =====================


def test_element_stiffness_shape():
    from framework import compute_element_stiffness

    KE = compute_element_stiffness(0.3)
    assert KE.shape == (8, 8), f"KE shape should be (8,8), got {KE.shape}"


def test_element_stiffness_symmetry():
    from framework import compute_element_stiffness

    KE = compute_element_stiffness(0.3)
    assert np.allclose(KE, KE.T, atol=1e-12), "KE must be symmetric"


def test_element_stiffness_eigenvalues():
    """Q4 plane-stress element: exactly 3 zero eigenvalues (rigid body modes)."""
    from framework import compute_element_stiffness

    KE = compute_element_stiffness(0.3)
    eigvals = np.linalg.eigvalsh(KE)
    n_zero = int(np.sum(np.abs(eigvals) < 1e-10))
    n_positive = int(np.sum(eigvals > 1e-10))
    assert n_zero == 3, f"Expected 3 zero eigenvalues, got {n_zero}"
    assert n_positive == 5, f"Expected 5 positive eigenvalues, got {n_positive}"


def test_element_stiffness_known_entries():
    """Check specific entries against the analytical plane-stress formula."""
    from framework import compute_element_stiffness

    KE = compute_element_stiffness(0.3)
    nu = 0.3
    factor = 1.0 / (1.0 - nu ** 2)

    k0 = 1.0 / 2 - nu / 6  # 0.45
    k1 = 1.0 / 8 + nu / 8  # 0.1625
    k2 = -1.0 / 4 - nu / 12  # -0.275
    k6 = nu / 6  # 0.05
    k7 = 1.0 / 8 - 3 * nu / 8  # 0.0125

    assert np.isclose(KE[0, 0], factor * k0, rtol=1e-10), (
        f"KE[0,0]={KE[0,0]:.10f}, expected {factor * k0:.10f}"
    )
    assert np.isclose(KE[0, 1], factor * k1, rtol=1e-10), (
        f"KE[0,1]={KE[0,1]:.10f}, expected {factor * k1:.10f}"
    )
    assert np.isclose(KE[0, 2], factor * k2, rtol=1e-10), (
        f"KE[0,2]={KE[0,2]:.10f}, expected {factor * k2:.10f}"
    )
    assert np.isclose(KE[0, 6], factor * k6, rtol=1e-10), (
        f"KE[0,6]={KE[0,6]:.10f}, expected {factor * k6:.10f}"
    )
    assert np.isclose(KE[1, 0], factor * k1, rtol=1e-10), (
        f"KE[1,0]={KE[1,0]:.10f}, expected {factor * k1:.10f}"
    )
    assert np.isclose(KE[0, 7], factor * k7, rtol=1e-10), (
        f"KE[0,7]={KE[0,7]:.10f}, expected {factor * k7:.10f}"
    )


def test_element_stiffness_different_nu():
    """KE must change when Poisson's ratio changes."""
    from framework import compute_element_stiffness

    KE1 = compute_element_stiffness(0.3)
    KE2 = compute_element_stiffness(0.2)
    assert not np.allclose(KE1, KE2), "KE should differ for different nu"


# ===================== Unit Tests: DOF Indices =====================


def test_dof_indices_length():
    from framework import get_dof_indices

    edof = get_dof_indices(3, 2, 0, 0)
    assert len(edof) == 8, f"Element has 8 DOFs, got {len(edof)}"


def test_dof_indices_first_element():
    """Element (0,0) with nely=2: nodes TL=0, TR=3, BR=4, BL=1.
    DOFs must follow the element stiffness node order: TL, TR, BR, BL."""
    from framework import get_dof_indices

    edof = np.array(get_dof_indices(3, 2, 0, 0))
    expected = np.array([0, 1, 6, 7, 8, 9, 2, 3])
    np.testing.assert_array_equal(
        edof, expected, err_msg=f"Element (0,0) DOFs: expected {expected}, got {edof}"
    )


def test_dof_indices_interior_element():
    """Element (1,1) with nely=3: nodes TL=5, TR=9, BR=10, BL=6."""
    from framework import get_dof_indices

    edof = np.array(get_dof_indices(4, 3, 1, 1))
    expected = np.array([10, 11, 18, 19, 20, 21, 12, 13])
    np.testing.assert_array_equal(
        edof, expected, err_msg=f"Element (1,1) DOFs: expected {expected}, got {edof}"
    )


# ===================== Unit Tests: Assembly =====================


def test_assembly_dimensions():
    from framework import compute_element_stiffness, assemble_global_stiffness

    KE = compute_element_stiffness(0.3)
    x = np.ones((2, 3))
    K = assemble_global_stiffness(3, 2, x, 3.0, KE, 1.0, 1e-9)
    ndof = 2 * (3 + 1) * (2 + 1)  # 24
    assert K.shape == (ndof, ndof), f"K shape should be ({ndof},{ndof}), got {K.shape}"


def test_assembly_symmetry():
    from framework import compute_element_stiffness, assemble_global_stiffness

    KE = compute_element_stiffness(0.3)
    x = np.ones((2, 3))
    K = assemble_global_stiffness(3, 2, x, 3.0, KE, 1.0, 1e-9)
    K_dense = K.toarray() if hasattr(K, "toarray") else np.array(K)
    assert np.allclose(K_dense, K_dense.T, atol=1e-12), "Global K must be symmetric"


def test_assembly_simp_scaling():
    """Single element: K(x=0.5,p=3) / K(x=1,p=3) approx 0.125."""
    from framework import compute_element_stiffness, assemble_global_stiffness

    KE = compute_element_stiffness(0.3)
    K_full = assemble_global_stiffness(1, 1, np.ones((1, 1)), 3.0, KE, 1.0, 1e-9)
    K_half = assemble_global_stiffness(
        1, 1, np.full((1, 1), 0.5), 3.0, KE, 1.0, 1e-9
    )
    Kf = K_full.toarray()
    Kh = K_half.toarray()
    nonzero = np.abs(Kf) > 1e-15
    assert np.any(nonzero), "Full-density K should have nonzero entries"
    ratios = Kh[nonzero] / Kf[nonzero]
    assert np.allclose(ratios, 0.125, atol=0.002), (
        f"SIMP ratio should be ~0.125, got {ratios[0]:.6f}"
    )


# ===================== Unit Tests: Sensitivities =====================


def test_sensitivity_sign():
    """Compliance sensitivities must be non-positive."""
    from framework import (
        compute_element_stiffness,
        assemble_global_stiffness,
        apply_boundary_conditions_and_solve,
        compute_sensitivities,
    )

    KE = compute_element_stiffness(0.3)
    nelx, nely = 4, 2
    x = np.full((nely, nelx), 0.5)
    K = assemble_global_stiffness(nelx, nely, x, 3.0, KE, 1.0, 1e-9)
    ndof = 2 * (nelx + 1) * (nely + 1)
    F = np.zeros(ndof)
    load_node = nelx * (nely + 1) + nely
    F[2 * load_node + 1] = -1.0
    fixed_dofs = np.arange(2 * (nely + 1))
    U = apply_boundary_conditions_and_solve(K, F, fixed_dofs, ndof)
    dc, dv = compute_sensitivities(nelx, nely, x, U, KE, 3.0, 1.0, 1e-9)
    assert np.all(dc <= 0), "Compliance sensitivities must be non-positive"
    assert np.all(dv > 0), "Volume sensitivities must be positive"


def test_sensitivity_power_law():
    """Sensitivity ratio for two density values must follow the derivative power law.
    If the material interpolation is x^p, then dc/dx involves x^(p-1)."""
    from framework import compute_element_stiffness, compute_sensitivities, get_dof_indices

    KE = compute_element_stiffness(0.3)
    nelx, nely = 1, 1
    ndof = 2 * (nelx + 1) * (nely + 1)

    # Construct a displacement field with nonzero entries at element DOFs
    U = np.zeros(ndof)
    edof = get_dof_indices(nelx, nely, 0, 0)
    U[edof[4]] = 0.5
    U[edof[5]] = -1.0
    U[edof[6]] = 0.2
    U[edof[7]] = -0.3

    penal = 3.0
    x_a = np.array([[0.8]])
    x_b = np.array([[0.4]])

    dc_a, _ = compute_sensitivities(nelx, nely, x_a, U, KE, penal, 1.0, 1e-9)
    dc_b, _ = compute_sensitivities(nelx, nely, x_b, U, KE, penal, 1.0, 1e-9)

    # dc ~ -p * x^(p-1) * const  =>  dc_a / dc_b = (x_a / x_b)^(p-1) = 2^2 = 4.0
    ratio = dc_a[0, 0] / dc_b[0, 0]
    expected_ratio = (0.8 / 0.4) ** (penal - 1)
    assert np.isclose(ratio, expected_ratio, rtol=0.02), (
        f"Sensitivity ratio {ratio:.4f} should be {expected_ratio:.4f}"
    )


# ===================== Unit Tests: OC Update =====================


def test_oc_volume_constraint():
    """After OC update, volume fraction must match the target."""
    from framework import optimality_criteria_update

    nelx, nely = 6, 3
    x = np.full((nely, nelx), 0.5)
    # Deterministic sensitivities (negative, varying magnitude)
    dc = -np.array(
        [
            [0.10, 0.50, 0.30, 0.80, 0.15, 0.60],
            [0.20, 0.90, 0.40, 0.55, 0.25, 0.70],
            [0.35, 0.45, 0.65, 0.75, 0.85, 0.95],
        ]
    )
    dv = np.ones((nely, nelx))
    x_new = optimality_criteria_update(nelx, nely, x, dc, dv, 0.5)
    vol = np.mean(x_new)
    assert abs(vol - 0.5) < 0.02, f"Volume fraction should be ~0.5, got {vol:.4f}"
    assert np.all(x_new >= 0), "Densities must be non-negative"
    assert np.all(x_new <= 1.0 + 1e-10), "Densities must be at most 1"


# ===================== Integration Test: Full Optimization =====================


@pytest.fixture(scope="module")
def optimization_result():
    """Run the full optimization once for all integration tests."""
    result = subprocess.run(
        [sys.executable, "/app/run_optimization.py"],
        capture_output=True,
        text=True,
        timeout=240,
        cwd="/app",
    )
    return result


def test_optimization_completes(optimization_result):
    assert optimization_result.returncode == 0, (
        f"Optimization failed:\nstderr: {optimization_result.stderr[-500:]}\n"
        f"stdout: {optimization_result.stdout[-500:]}"
    )


def test_output_files_exist(optimization_result):
    for fname in [
        "final_stats.json",
        "compliance_history.csv",
        "density_field.csv",
        "ke_matrix.csv",
    ]:
        assert os.path.exists(f"/app/results/{fname}"), f"Missing /app/results/{fname}"


def test_final_volume_fraction(optimization_result):
    if not os.path.exists("/app/results/final_stats.json"):
        pytest.skip("Output files missing")
    with open("/app/results/final_stats.json") as f:
        stats = json.load(f)
    assert abs(stats["final_volume_fraction"] - 0.5) < 0.02, (
        f"Volume fraction {stats['final_volume_fraction']:.4f} not close to 0.5"
    )


def test_compliance_positive(optimization_result):
    if not os.path.exists("/app/results/final_stats.json"):
        pytest.skip("Output files missing")
    with open("/app/results/final_stats.json") as f:
        stats = json.load(f)
    assert stats["final_compliance"] > 0, "Compliance must be positive"


def test_compliance_convergence(optimization_result):
    if not os.path.exists("/app/results/compliance_history.csv"):
        pytest.skip("Output files missing")
    history = np.loadtxt("/app/results/compliance_history.csv", delimiter=",")
    assert len(history) >= 10, f"Need >=10 iterations, got {len(history)}"
    assert history[-1] < history[0], (
        f"Compliance should decrease: initial={history[0]:.4f}, final={history[-1]:.4f}"
    )
    # Check convergence: last 10 values should have small coefficient of variation
    if len(history) > 20:
        last_10 = history[-10:]
        cv = np.std(last_10) / np.mean(last_10)
        assert cv < 0.02, f"Compliance not converged: CV={cv:.4f}"


def test_density_field_properties(optimization_result):
    if not os.path.exists("/app/results/density_field.csv"):
        pytest.skip("Output files missing")
    density = np.loadtxt("/app/results/density_field.csv", delimiter=",")
    assert density.shape == (20, 60), (
        f"Density field shape should be (20,60), got {density.shape}"
    )
    assert np.all(density >= 0), "Densities must be non-negative"
    assert np.all(density <= 1.0 + 1e-6), "Densities must be at most 1"
    # Optimized structure should have distinct solid and void regions
    assert np.any(density > 0.9), "Should have solid regions (density > 0.9)"
    assert np.any(density < 0.1), "Should have void regions (density < 0.1)"


def test_saved_ke_matrix(optimization_result):
    if not os.path.exists("/app/results/ke_matrix.csv"):
        pytest.skip("Output files missing")
    KE = np.loadtxt("/app/results/ke_matrix.csv", delimiter=",")
    assert KE.shape == (8, 8), f"KE shape should be (8,8), got {KE.shape}"
    nu = 0.3
    factor = 1.0 / (1.0 - nu ** 2)
    expected_00 = factor * (0.5 - nu / 6)
    assert np.isclose(KE[0, 0], expected_00, rtol=1e-6), (
        f"Saved KE[0,0]={KE[0,0]:.8f}, expected {expected_00:.8f}"
    )
