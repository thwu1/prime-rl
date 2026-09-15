"""
Tests for the Brusselator PDE solver.

"""

import pytest
import numpy as np
import sys
import os

sys.path.insert(0, "/app")

from problem import N, ALPHA_DX2, A_PARAM, B_PARAM, xyd, initial_conditions, OUTPUT_TIMES


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------
@pytest.fixture(scope="module")
def results():
    """Load the pre-computed results file."""
    return np.load("/app/results.npz")


# -----------------------------------------------------------------------
# 1. Basic result structure
# -----------------------------------------------------------------------
class TestResultsStructure:
    def test_results_file_exists(self):
        assert os.path.isfile("/app/results.npz"), "results.npz not found"

    def test_results_keys(self, results):
        for key in ("times", "U", "V"):
            assert key in results, f"Missing key '{key}' in results.npz"

    def test_solution_shape(self, results):
        n_out = len(OUTPUT_TIMES)
        assert results["times"].shape == (n_out,)
        assert results["U"].shape == (n_out, N, N), (
            f"U shape {results['U'].shape} != expected ({n_out}, {N}, {N})"
        )
        assert results["V"].shape == (n_out, N, N), (
            f"V shape {results['V'].shape} != expected ({n_out}, {N}, {N})"
        )


# -----------------------------------------------------------------------
# 2. Solution quality
# -----------------------------------------------------------------------
class TestSolutionQuality:
    def test_initial_conditions(self, results):
        """Solution at t=0 must reproduce the analytical initial condition."""
        u0 = initial_conditions()
        nn = N * N
        U0_expected = u0[:nn].reshape(N, N)
        V0_expected = u0[nn:].reshape(N, N)
        np.testing.assert_allclose(results["U"][0], U0_expected, rtol=1e-4)
        np.testing.assert_allclose(results["V"][0], V0_expected, rtol=1e-4)

    def test_non_negativity(self, results):
        """Chemical concentrations must remain non-negative."""
        assert np.all(results["U"] >= -0.01), (
            f"U has values below -0.01; min = {results['U'].min()}"
        )
        assert np.all(results["V"] >= -0.01), (
            f"V has values below -0.01; min = {results['V'].min()}"
        )

    def test_boundedness(self, results):
        """Solution must stay bounded (no blow-up)."""
        assert np.all(np.abs(results["U"]) < 50), (
            f"U unbounded; max |U| = {np.abs(results['U']).max()}"
        )
        assert np.all(np.abs(results["V"]) < 50), (
            f"V unbounded; max |V| = {np.abs(results['V']).max()}"
        )

    def test_solution_evolves(self, results):
        """Solution at t=11.5 must differ significantly from t=0."""
        U0 = results["U"][0]
        U_final = results["U"][-1]
        change = np.linalg.norm(U_final - U0) / (np.linalg.norm(U0) + 1e-12)
        assert change > 0.01, (
            f"Solution barely changed: relative change = {change:.6f}"
        )


# -----------------------------------------------------------------------
# 3. Boundary conditions
# -----------------------------------------------------------------------
class TestBoundaryConditions:
    def test_clamped_not_periodic(self):
        """RHS must use clamped (Neumann) BC, not periodic wrap-around."""
        from solver import brusselator_rhs

        nn = N * N
        # All-ones state except U(0,0) = 10
        u = np.ones(2 * nn)
        u[0] = 10.0

        rhs = brusselator_rhs(0.0, u)

        # Clamped: im1=0=i, jm1=0=j  =>  neighbors U(0,0)=10, U(1,0)=1, U(0,0)=10, U(0,1)=1
        #   lap = ALPHA_DX2 * (10 + 1 + 10 + 1 - 40) = ALPHA_DX2 * (-18)
        lap_clamped = ALPHA_DX2 * (-18.0)

        # Periodic: im1=N-1, jm1=N-1  =>  neighbors U(31,0)=1, U(1,0)=1, U(0,31)=1, U(0,1)=1
        #   lap = ALPHA_DX2 * (1 + 1 + 1 + 1 - 40) = ALPHA_DX2 * (-36)
        lap_periodic = ALPHA_DX2 * (-36.0)

        # Reaction at (0,0): B + U^2 V - (A+1) U = 1 + 100 - 44 = 57
        reaction = B_PARAM + 10.0 ** 2 * 1.0 - (A_PARAM + 1.0) * 10.0

        expected_clamped = lap_clamped + reaction
        expected_periodic = lap_periodic + reaction
        actual = rhs[0]

        assert abs(actual - expected_clamped) < 1.0, (
            f"RHS uses wrong BC. Got {actual:.2f}, "
            f"expected {expected_clamped:.2f} (clamped), "
            f"not {expected_periodic:.2f} (periodic)"
        )


# -----------------------------------------------------------------------
# 4. Jacobian sparsity pattern
# -----------------------------------------------------------------------
class TestJacobianSparsity:
    def test_sparsity_nnz(self):
        """Jacobian sparsity must have exactly 12*N^2 - 8*N nonzeros."""
        from solver import build_jacobian_sparsity

        J = build_jacobian_sparsity(N)
        expected_nnz = 12 * N ** 2 - 8 * N
        assert J.shape == (2 * N ** 2, 2 * N ** 2), (
            f"Shape {J.shape} != expected ({2*N**2}, {2*N**2})"
        )
        assert J.nnz == expected_nnz, (
            f"nnz = {J.nnz}, expected {expected_nnz}"
        )

    def test_sparsity_interior_structure(self):
        """Interior point must have correct stencil + cross-species coupling."""
        from solver import build_jacobian_sparsity

        J = build_jacobian_sparsity(N)
        J_dense = J.toarray()
        nn = N * N

        # Pick interior point (5, 5)
        i, j = 5, 5
        row_u = i * N + j  # U equation
        row_v = nn + i * N + j  # V equation

        # U equation should couple to U at self and 4 neighbors
        u_cols = [
            i * N + j,
            (i - 1) * N + j,
            (i + 1) * N + j,
            i * N + (j - 1),
            i * N + (j + 1),
        ]
        for c in u_cols:
            assert J_dense[row_u, c] != 0, (
                f"U eq at ({i},{j}): missing stencil entry at col {c}"
            )
        # U equation should couple to V at self
        assert J_dense[row_u, nn + i * N + j] != 0

        # U equation should NOT couple to V at neighbors
        v_neighbor = nn + (i - 1) * N + j
        assert J_dense[row_u, v_neighbor] == 0

        # V equation should couple to V at self and 4 neighbors
        v_cols = [nn + c for c in u_cols]
        for c in v_cols:
            assert J_dense[row_v, c] != 0, (
                f"V eq at ({i},{j}): missing stencil entry at col {c}"
            )
        # V equation should couple to U at self
        assert J_dense[row_v, i * N + j] != 0

    def test_sparsity_corner_structure(self):
        """Corner point (0,0) must have fewer off-diagonal stencil entries."""
        from solver import build_jacobian_sparsity

        J = build_jacobian_sparsity(N)
        nn = N * N
        row_u = 0  # U(0,0)

        # Row should have exactly 4 nonzeros:
        #   U(0,0) self, U(1,0), U(0,1), V(0,0)
        nnz_row = J[row_u, :].nnz
        assert nnz_row == 4, (
            f"Corner U(0,0) has {nnz_row} nnz in row, expected 4"
        )


# -----------------------------------------------------------------------
# 5. Jacobian values
# -----------------------------------------------------------------------
class TestJacobianValues:
    def test_jacobian_vs_finite_diff(self):
        """Analytical Jacobian must match finite differences at a test point."""
        from solver import compute_jacobian, brusselator_rhs

        u0 = initial_conditions()
        t_test = 0.0

        J_an = compute_jacobian(t_test, u0)

        # Finite-difference Jacobian for a subset of columns
        f0 = brusselator_rhs(t_test, u0)
        eps = 1e-7
        n = len(u0)

        rng = np.random.RandomState(42)
        cols = rng.choice(n, size=30, replace=False)

        max_err = 0.0
        for col in cols:
            u_pert = u0.copy()
            u_pert[col] += eps
            f_pert = brusselator_rhs(t_test, u_pert)
            jac_col_fd = (f_pert - f0) / eps

            jac_col_an = np.asarray(J_an[:, col].todense()).ravel()
            err = np.max(np.abs(jac_col_fd - jac_col_an))
            max_err = max(max_err, err)

        assert max_err < 1.0, (
            f"Jacobian error too large: max abs diff = {max_err:.6f}"
        )

    def test_jacobian_diagonal_reaction_terms(self):
        """Spot-check diagonal Jacobian entries against hand-computed values."""
        from solver import compute_jacobian

        u0 = initial_conditions()
        nn = N * N
        U = u0[:nn].reshape(N, N)
        V = u0[nn:].reshape(N, N)

        J = compute_jacobian(0.0, u0)

        # Interior point (10, 10)
        i, j = 10, 10
        idx_u = i * N + j
        idx_v = nn + i * N + j
        Uij, Vij = U[i, j], V[i, j]

        # dU/dU(i,j) = ALPHA_DX2*(-4) + 2*U*V - (A+1)
        expected_dUdU = ALPHA_DX2 * (-4.0) + 2.0 * Uij * Vij - (A_PARAM + 1.0)
        actual_dUdU = J[idx_u, idx_u]
        assert abs(actual_dUdU - expected_dUdU) < 1e-6, (
            f"dU/dU at ({i},{j}): got {actual_dUdU}, expected {expected_dUdU}"
        )

        # dU/dV(i,j) = U^2
        expected_dUdV = Uij ** 2
        actual_dUdV = J[idx_u, idx_v]
        assert abs(actual_dUdV - expected_dUdV) < 1e-6, (
            f"dU/dV at ({i},{j}): got {actual_dUdV}, expected {expected_dUdV}"
        )

        # dV/dU(i,j) = A - 2*U*V
        expected_dVdU = A_PARAM - 2.0 * Uij * Vij
        actual_dVdU = J[idx_v, idx_u]
        assert abs(actual_dVdU - expected_dVdU) < 1e-6, (
            f"dV/dU at ({i},{j}): got {actual_dVdU}, expected {expected_dVdU}"
        )

        # dV/dV(i,j) = ALPHA_DX2*(-4) - U^2
        expected_dVdV = ALPHA_DX2 * (-4.0) - Uij ** 2
        actual_dVdV = J[idx_v, idx_v]
        assert abs(actual_dVdV - expected_dVdV) < 1e-6, (
            f"dV/dV at ({i},{j}): got {actual_dVdV}, expected {expected_dVdV}"
        )
