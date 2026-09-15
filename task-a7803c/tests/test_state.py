"""
Tests for the Brusselator PDE numerical analysis pipeline.

Independently computes reference solutions and verifies the agent's outputs
for correctness across BDF solution, IMEX solution, Jacobian accuracy,
eigenvalue analysis, preconditioner effectiveness, and sparsity structure.
"""

import numpy as np
import json
import os
import pytest
import sys

sys.path.insert(0, '/app')
from brusselator_problem import (N, A_PARAM, B_PARAM, D,
                                  brusselator_rhs, initial_conditions,
                                  T_SPAN)
from scipy.integrate import solve_ivp
from scipy.sparse import eye as speye, kron, diags, bmat, load_npz
from scipy.sparse.linalg import eigs

NN = N * N


# ---------------------------------------------------------------------------
# Reference Jacobian construction (independent of agent)
# ---------------------------------------------------------------------------

def _build_lap1d(n):
    main = -2.0 * np.ones(n)
    main[0] = main[-1] = -1.0
    return diags([np.ones(n - 1), main, np.ones(n - 1)],
                 [-1, 0, 1], shape=(n, n), format='csc')


def _build_lap2d():
    T = _build_lap1d(N)
    I_N = speye(N, format='csc')
    return kron(T, I_N, format='csc') + kron(I_N, T, format='csc')


_DL = D * _build_lap2d()


def _ref_jac(t, y):
    U, V = y[:NN], y[NN:]
    J_UU = _DL + diags(2.0 * U * V - (A_PARAM + 1.0), 0,
                        shape=(NN, NN), format='csc')
    J_UV = diags(U ** 2, 0, shape=(NN, NN), format='csc')
    J_VU = diags(A_PARAM - 2.0 * U * V, 0, shape=(NN, NN), format='csc')
    J_VV = _DL + diags(-U ** 2, 0, shape=(NN, NN), format='csc')
    return bmat([[J_UU, J_UV], [J_VU, J_VV]], format='csc')


# ---------------------------------------------------------------------------
# Fixtures: reference solutions
# ---------------------------------------------------------------------------

@pytest.fixture(scope='module')
def reference_solution():
    """Compute reference BDF solution with analytical Jacobian."""
    y0 = initial_conditions()
    sol = solve_ivp(brusselator_rhs, T_SPAN, y0, method='BDF',
                    jac=_ref_jac, rtol=1e-6, atol=1e-9,
                    dense_output=True)
    assert sol.success, f"Reference solver failed: {sol.message}"
    y_mid = sol.sol(5.75)
    y_final = sol.sol(11.5)
    return {
        'u_mid': y_mid[:NN].reshape(N, N),
        'v_mid': y_mid[NN:].reshape(N, N),
        'u_final': y_final[:NN].reshape(N, N),
        'v_final': y_final[NN:].reshape(N, N),
    }


@pytest.fixture(scope='module')
def reference_eigenvalues():
    """Compute reference eigenvalues of Jacobian at t=0."""
    y0 = initial_conditions()
    J = _ref_jac(0.0, y0)
    vals_large, _ = eigs(J, k=5, which='LM', maxiter=5000)
    vals_large = vals_large[np.argsort(-np.abs(vals_large))]
    vals_small, _ = eigs(J, k=5, sigma=0, maxiter=5000)
    vals_small = vals_small[np.argsort(np.abs(vals_small))]
    return vals_large, vals_small


# ---------------------------------------------------------------------------
# Fixtures: agent outputs
# ---------------------------------------------------------------------------

@pytest.fixture(scope='module')
def agent_bdf():
    path = '/app/solution_bdf.npz'
    assert os.path.exists(path), f"BDF solution not found at {path}"
    return dict(np.load(path))


@pytest.fixture(scope='module')
def agent_imex():
    path = '/app/solution_imex.npz'
    assert os.path.exists(path), f"IMEX solution not found at {path}"
    return dict(np.load(path))


@pytest.fixture(scope='module')
def agent_jacobian():
    path = '/app/jacobian_at_t0.npz'
    assert os.path.exists(path), f"Jacobian not found at {path}"
    return load_npz(path)


@pytest.fixture(scope='module')
def agent_stiffness():
    path = '/app/stiffness_analysis.json'
    assert os.path.exists(path), f"Stiffness analysis not found at {path}"
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope='module')
def agent_precond():
    path = '/app/preconditioner_analysis.json'
    assert os.path.exists(path), f"Preconditioner analysis not found at {path}"
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope='module')
def agent_sparsity():
    path = '/app/sparsity_analysis.json'
    assert os.path.exists(path), f"Sparsity analysis not found at {path}"
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Tests: output files exist
# ---------------------------------------------------------------------------

class TestOutputsExist:
    def test_bdf_solution(self):
        assert os.path.exists('/app/solution_bdf.npz')

    def test_imex_solution(self):
        assert os.path.exists('/app/solution_imex.npz')

    def test_jacobian(self):
        assert os.path.exists('/app/jacobian_at_t0.npz')

    def test_stiffness(self):
        assert os.path.exists('/app/stiffness_analysis.json')

    def test_preconditioner(self):
        assert os.path.exists('/app/preconditioner_analysis.json')

    def test_sparsity(self):
        assert os.path.exists('/app/sparsity_analysis.json')


# ---------------------------------------------------------------------------
# Tests: BDF solution correctness
# ---------------------------------------------------------------------------

class TestBDFSolution:
    def test_u_final_shape(self, agent_bdf):
        assert 'u_final' in agent_bdf
        assert agent_bdf['u_final'].shape == (N, N)

    def test_v_final_shape(self, agent_bdf):
        assert 'v_final' in agent_bdf
        assert agent_bdf['v_final'].shape == (N, N)

    def test_u_mid_shape(self, agent_bdf):
        assert 'u_mid' in agent_bdf
        assert agent_bdf['u_mid'].shape == (N, N)

    def test_v_mid_shape(self, agent_bdf):
        assert 'v_mid' in agent_bdf
        assert agent_bdf['v_mid'].shape == (N, N)

    def test_u_final_correctness(self, agent_bdf, reference_solution):
        np.testing.assert_allclose(
            agent_bdf['u_final'], reference_solution['u_final'],
            rtol=5e-3, atol=1e-3,
            err_msg="BDF U field at t=11.5 does not match reference")

    def test_v_final_correctness(self, agent_bdf, reference_solution):
        np.testing.assert_allclose(
            agent_bdf['v_final'], reference_solution['v_final'],
            rtol=5e-3, atol=1e-3,
            err_msg="BDF V field at t=11.5 does not match reference")

    def test_u_mid_correctness(self, agent_bdf, reference_solution):
        np.testing.assert_allclose(
            agent_bdf['u_mid'], reference_solution['u_mid'],
            rtol=5e-3, atol=1e-3,
            err_msg="BDF U field at t=5.75 does not match reference")

    def test_v_mid_correctness(self, agent_bdf, reference_solution):
        np.testing.assert_allclose(
            agent_bdf['v_mid'], reference_solution['v_mid'],
            rtol=5e-3, atol=1e-3,
            err_msg="BDF V field at t=5.75 does not match reference")


# ---------------------------------------------------------------------------
# Tests: IMEX solution correctness (looser tolerance)
# ---------------------------------------------------------------------------

class TestIMEXSolution:
    def test_u_final_shape(self, agent_imex):
        assert 'u_final' in agent_imex
        assert agent_imex['u_final'].shape == (N, N)

    def test_v_final_shape(self, agent_imex):
        assert 'v_final' in agent_imex
        assert agent_imex['v_final'].shape == (N, N)

    def test_u_mid_shape(self, agent_imex):
        assert 'u_mid' in agent_imex
        assert agent_imex['u_mid'].shape == (N, N)

    def test_v_mid_shape(self, agent_imex):
        assert 'v_mid' in agent_imex
        assert agent_imex['v_mid'].shape == (N, N)

    def test_u_final_accuracy(self, agent_imex, reference_solution):
        np.testing.assert_allclose(
            agent_imex['u_final'], reference_solution['u_final'],
            rtol=0.1, atol=0.3,
            err_msg="IMEX U at t=11.5 too far from BDF reference")

    def test_v_final_accuracy(self, agent_imex, reference_solution):
        np.testing.assert_allclose(
            agent_imex['v_final'], reference_solution['v_final'],
            rtol=0.1, atol=0.3,
            err_msg="IMEX V at t=11.5 too far from BDF reference")

    def test_u_mid_accuracy(self, agent_imex, reference_solution):
        np.testing.assert_allclose(
            agent_imex['u_mid'], reference_solution['u_mid'],
            rtol=0.1, atol=0.3,
            err_msg="IMEX U at t=5.75 too far from BDF reference")

    def test_v_mid_accuracy(self, agent_imex, reference_solution):
        np.testing.assert_allclose(
            agent_imex['v_mid'], reference_solution['v_mid'],
            rtol=0.1, atol=0.3,
            err_msg="IMEX V at t=5.75 too far from BDF reference")


# ---------------------------------------------------------------------------
# Tests: physical properties (both solvers)
# ---------------------------------------------------------------------------

class TestPhysicalProperties:
    def test_bdf_finite(self, agent_bdf):
        for key in ['u_final', 'v_final', 'u_mid', 'v_mid']:
            assert np.all(np.isfinite(agent_bdf[key])), \
                f"BDF {key} contains non-finite values"

    def test_bdf_bounded(self, agent_bdf):
        for key in ['u_final', 'v_final', 'u_mid', 'v_mid']:
            assert np.max(np.abs(agent_bdf[key])) < 100, \
                f"BDF {key} has unreasonably large values"

    def test_imex_finite(self, agent_imex):
        for key in ['u_final', 'v_final', 'u_mid', 'v_mid']:
            assert np.all(np.isfinite(agent_imex[key])), \
                f"IMEX {key} contains non-finite values"

    def test_imex_bounded(self, agent_imex):
        for key in ['u_final', 'v_final', 'u_mid', 'v_mid']:
            assert np.max(np.abs(agent_imex[key])) < 100, \
                f"IMEX {key} has unreasonably large values"


# ---------------------------------------------------------------------------
# Tests: Jacobian correctness
# ---------------------------------------------------------------------------

class TestJacobianCorrectness:
    def test_jacobian_shape(self, agent_jacobian):
        total = 2 * NN
        assert agent_jacobian.shape == (total, total), \
            f"Expected shape ({total},{total}), got {agent_jacobian.shape}"

    def test_jacobian_is_sparse(self, agent_jacobian):
        assert hasattr(agent_jacobian, 'nnz'), \
            "Jacobian should be a scipy sparse matrix"
        total = 2 * NN
        density = agent_jacobian.nnz / total ** 2
        assert density < 0.01, \
            f"Jacobian density {density:.4f} too high; expected sparse"

    def test_jacobian_matches_finite_diff(self, agent_jacobian):
        """Verify analytical Jacobian against finite differences at t=0."""
        y0 = initial_conditions()
        J_dense = agent_jacobian.toarray()
        eps = 1e-7
        f0 = brusselator_rhs(0.0, y0)
        n = len(y0)

        test_cols = [
            0,                          # corner U (0,0)
            N // 2,                     # edge U (0, N/2)
            N * (N // 2) + N // 2,      # interior U (N/2, N/2)
            NN - 1,                     # corner U (N-1, N-1)
            NN,                         # corner V (0,0)
            NN + N * (N // 2) + N // 2, # interior V
            2 * NN - 1,                 # corner V (N-1, N-1)
        ]
        test_cols = [c for c in test_cols if c < n]

        for j in test_cols:
            y_pert = y0.copy()
            y_pert[j] += eps
            f_pert = brusselator_rhs(0.0, y_pert)
            fd_col = (f_pert - f0) / eps
            np.testing.assert_allclose(
                J_dense[:, j], fd_col, rtol=1e-3, atol=1e-3,
                err_msg=f"Jacobian column {j} does not match finite differences")


# ---------------------------------------------------------------------------
# Tests: stiffness analysis
# ---------------------------------------------------------------------------

class TestStiffnessAnalysis:
    def test_has_required_keys(self, agent_stiffness):
        for key in ['eigenvalues_largest', 'eigenvalues_smallest',
                     'stiffness_ratio', 'max_explicit_dt']:
            assert key in agent_stiffness, f"Missing key: {key}"

    def test_eigenvalue_counts(self, agent_stiffness):
        assert len(agent_stiffness['eigenvalues_largest']) == 5
        assert len(agent_stiffness['eigenvalues_smallest']) == 5

    def test_largest_eigenvalue_magnitudes(self, agent_stiffness, reference_eigenvalues):
        ref_large, _ = reference_eigenvalues
        ref_mags = sorted(np.abs(ref_large), reverse=True)
        agent_mags = sorted(
            [np.sqrt(v[0] ** 2 + v[1] ** 2)
             for v in agent_stiffness['eigenvalues_largest']],
            reverse=True)
        for rm, am in zip(ref_mags, agent_mags):
            np.testing.assert_allclose(am, rm, rtol=0.05,
                err_msg="Largest eigenvalue magnitude mismatch")

    def test_smallest_eigenvalue_magnitudes(self, agent_stiffness, reference_eigenvalues):
        _, ref_small = reference_eigenvalues
        ref_mags = sorted(np.abs(ref_small))
        agent_mags = sorted(
            [np.sqrt(v[0] ** 2 + v[1] ** 2)
             for v in agent_stiffness['eigenvalues_smallest']])
        for rm, am in zip(ref_mags, agent_mags):
            np.testing.assert_allclose(am, rm, rtol=0.15,
                err_msg="Smallest eigenvalue magnitude mismatch")

    def test_stiffness_ratio(self, agent_stiffness, reference_eigenvalues):
        ref_large, ref_small = reference_eigenvalues
        ref_ratio = np.max(np.abs(ref_large)) / np.min(np.abs(ref_small))
        np.testing.assert_allclose(
            agent_stiffness['stiffness_ratio'], ref_ratio, rtol=0.2,
            err_msg="Stiffness ratio mismatch")

    def test_max_explicit_dt(self, agent_stiffness, reference_eigenvalues):
        ref_large, _ = reference_eigenvalues
        ref_dt = 2.0 / np.max(np.abs(ref_large))
        np.testing.assert_allclose(
            agent_stiffness['max_explicit_dt'], ref_dt, rtol=0.05,
            err_msg="Max explicit dt mismatch")

    def test_stiffness_ratio_large(self, agent_stiffness):
        """The Brusselator is severely stiff; ratio should be > 1000."""
        assert agent_stiffness['stiffness_ratio'] > 1000, \
            "Stiffness ratio too small for this problem"

    def test_max_explicit_dt_tiny(self, agent_stiffness):
        """Forward Euler stability limit should be very small (<0.001)."""
        assert agent_stiffness['max_explicit_dt'] < 0.001, \
            "Max explicit dt too large; system is very stiff"


# ---------------------------------------------------------------------------
# Tests: preconditioner analysis
# ---------------------------------------------------------------------------

class TestPreconditionerAnalysis:
    def test_has_required_keys(self, agent_precond):
        for key in ['gmres_iters_no_precond', 'gmres_iters_ilu',
                     'ilu_fill_ratio', 'gmres_residual_no_precond',
                     'gmres_residual_ilu']:
            assert key in agent_precond, f"Missing key: {key}"

    def test_ilu_reduces_iterations(self, agent_precond):
        assert agent_precond['gmres_iters_ilu'] < agent_precond['gmres_iters_no_precond'], \
            "ILU preconditioning should reduce GMRES iteration count"

    def test_ilu_convergence(self, agent_precond):
        assert agent_precond['gmres_residual_ilu'] < 1e-5, \
            f"ILU-preconditioned GMRES residual too large: {agent_precond['gmres_residual_ilu']}"

    def test_fill_ratio_reasonable(self, agent_precond):
        fr = agent_precond['ilu_fill_ratio']
        assert 0.5 < fr < 30.0, \
            f"ILU fill ratio {fr} is unreasonable (expected 0.5-30)"

    def test_unpreconditioned_needs_work(self, agent_precond):
        assert agent_precond['gmres_iters_no_precond'] > 10, \
            "Unpreconditioned GMRES should require significant iterations"

    def test_ilu_iterations_positive(self, agent_precond):
        assert agent_precond['gmres_iters_ilu'] > 0, \
            "ILU GMRES should require at least 1 iteration"


# ---------------------------------------------------------------------------
# Tests: sparsity analysis
# ---------------------------------------------------------------------------

class TestSparsityAnalysis:
    def test_total_unknowns(self, agent_sparsity):
        assert agent_sparsity['total_unknowns'] == 2 * NN, \
            f"Expected {2 * NN}, got {agent_sparsity['total_unknowns']}"

    def test_density_is_sparse(self, agent_sparsity):
        assert agent_sparsity['density'] < 0.01, \
            f"Density {agent_sparsity['density']:.6f} too high"

    def test_nnz_matches_structure(self, agent_sparsity):
        """Structural nnz should match 5-point stencil + reaction coupling."""
        expected_nnz = 2 * (5 * N ** 2 - 4 * N) + 2 * N ** 2
        nnz = agent_sparsity['nnz_jacobian']
        assert abs(nnz - expected_nnz) < 0.25 * expected_nnz, \
            f"Expected ~{expected_nnz} structural nonzeros, got {nnz}"
