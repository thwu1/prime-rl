"""
Outcome-based tests for the Brusselator solver pipeline.

"""

import pytest
import numpy as np
import sys

sys.path.insert(0, '/app')


class TestRHSProperties:
    """Verify fundamental mathematical properties of the RHS function."""

    def test_steady_state_rhs_is_zero(self):
        """At the spatially uniform steady state the RHS must vanish."""
        from solver.system import brusselator_rhs
        N = 20
        A, B = 1.0, 3.0
        y = np.zeros(2 * N)
        y[0::2] = A
        y[1::2] = B / A
        rhs = brusselator_rhs(y, N, A=A, B=B)
        assert np.allclose(rhs, 0.0, atol=1e-8), (
            f"RHS at steady state (u={A}, v={B/A}) is not zero: "
            f"max|rhs| = {np.max(np.abs(rhs)):.2e}"
        )

    def test_rhs_output_shape(self):
        from solver.system import brusselator_rhs
        N = 15
        y = np.ones(2 * N)
        rhs = brusselator_rhs(y, N)
        assert rhs.shape == (2 * N,), f"Expected shape ({2*N},), got {rhs.shape}"


class TestSparsityAndColoring:
    """Verify the sparsity detection and coloring pipeline."""

    def test_coloring_validity_against_sparsity(self):
        """No two columns sharing a nonzero row may have the same color."""
        from solver.system import build_sparsity_pattern
        from solver.sparse_diff import column_connectivity_graph, greedy_coloring
        N = 20
        S = build_sparsity_pattern(N)
        adj = column_connectivity_graph(S)
        colors = greedy_coloring(adj, S.shape[1])

        S_csr = S.tocsr()
        for row in range(S.shape[0]):
            start, end = S_csr.indptr[row], S_csr.indptr[row + 1]
            nz_cols = S_csr.indices[start:end]
            seen_colors = {}
            for col in nz_cols:
                c = colors[col]
                if c in seen_colors:
                    pytest.fail(
                        f"Invalid coloring: columns {seen_colors[c]} and {col} "
                        f"share row {row} but both have color {c}"
                    )
                seen_colors[c] = col

    def test_sparsity_pattern_structure(self):
        """Sparsity pattern must have correct shape and reasonable density."""
        from solver.system import build_sparsity_pattern
        from scipy import sparse
        N = 50
        S = build_sparsity_pattern(N)
        n = 2 * N
        assert S.shape == (n, n)
        assert sparse.issparse(S)
        S_arr = S.toarray()
        for i in range(n):
            assert S_arr[i, i] != 0, f"Diagonal ({i},{i}) is zero"
        assert S.nnz > 2 * n
        assert S.nnz < 10 * n


class TestJacobianAccuracy:
    """Sparse Jacobian must agree with element-wise finite differences."""

    def test_sparse_matches_dense_fd(self):
        from solver.system import brusselator_rhs, build_sparsity_pattern
        from solver.sparse_diff import (column_connectivity_graph,
                                        greedy_coloring,
                                        compressed_jacobian)
        N = 10
        n = 2 * N
        S = build_sparsity_pattern(N)
        adj = column_connectivity_graph(S)
        colors = greedy_coloring(adj, n)

        rng = np.random.RandomState(42)
        x = np.abs(rng.randn(n)) + 0.5

        f = lambda y: brusselator_rhs(y, N)

        eps = 1e-7
        f0 = f(x)
        J_dense = np.zeros((n, n))
        for j in range(n):
            xp = x.copy()
            xp[j] += eps
            J_dense[:, j] = (f(xp) - f0) / eps

        J_sparse = compressed_jacobian(f, x, S, colors).toarray()

        S_arr = S.toarray()
        for i in range(n):
            for j in range(n):
                if S_arr[i, j] != 0:
                    assert abs(J_sparse[i, j] - J_dense[i, j]) < 1e-3, (
                        f"Jacobian mismatch at ({i},{j}): "
                        f"sparse={J_sparse[i,j]:.4e}, dense={J_dense[i,j]:.4e}"
                    )


class TestGMRES:
    """Verify GMRES implementation on known linear systems."""

    def test_gmres_solves_diagonal_system(self):
        """GMRES must solve a trivial diagonal system exactly."""
        from solver.krylov import preconditioned_gmres
        n = 50
        rng = np.random.RandomState(99)
        diag = rng.rand(n) + 0.5
        from scipy import sparse
        A = sparse.diags(diag, format='csc')
        b = np.ones(n)
        x_exact = b / diag

        x, converged, _ = preconditioned_gmres(
            A_matvec=lambda v: A @ v,
            b=b, tol=1e-10, max_iter=100, restart=50
        )
        assert converged, "GMRES did not converge on diagonal system"
        assert np.allclose(x, x_exact, rtol=1e-8), (
            f"Max error: {np.max(np.abs(x - x_exact)):.2e}"
        )

    def test_gmres_solves_banded_system(self):
        """GMRES must solve a diagonally-dominant tridiagonal system."""
        from solver.krylov import preconditioned_gmres
        from scipy import sparse
        n = 100
        rng = np.random.RandomState(42)
        diag_main = rng.rand(n) * 5 + 10
        diag_sub = rng.rand(n - 1) * 0.5
        diag_sup = rng.rand(n - 1) * 0.5
        A = sparse.diags([diag_sub, diag_main, diag_sup],
                         [-1, 0, 1], format='csc')

        x_true = rng.randn(n)
        b = A @ x_true

        x, converged, _ = preconditioned_gmres(
            A_matvec=lambda v: A @ v,
            b=b, tol=1e-10, max_iter=200, restart=50
        )
        assert converged, "GMRES did not converge on tridiagonal system"
        assert np.allclose(x, x_true, rtol=1e-6), (
            f"Max error: {np.max(np.abs(x - x_true)):.2e}"
        )

    def test_gmres_with_ilu_preconditioner(self):
        """GMRES with ILU preconditioning on a Newton-system-like matrix."""
        from solver.krylov import preconditioned_gmres
        from solver.system import brusselator_rhs, build_sparsity_pattern
        from solver.sparse_diff import (column_connectivity_graph,
                                        greedy_coloring,
                                        compressed_jacobian)
        from scipy import sparse
        from scipy.sparse.linalg import splu, spilu

        N = 15
        n = 2 * N
        S = build_sparsity_pattern(N)
        adj = column_connectivity_graph(S)
        coloring = greedy_coloring(adj, n)

        rng = np.random.RandomState(42)
        y0 = np.abs(rng.randn(n)) + 0.5
        f = lambda y: brusselator_rhs(y, N)
        J = compressed_jacobian(f, y0, S, coloring)

        dt = 0.01
        A = sparse.eye(n, format='csc') - dt * J
        b = rng.randn(n)

        ilu = spilu(A)
        x_ref = splu(A).solve(b)

        x, converged, n_iter = preconditioned_gmres(
            A_matvec=lambda v: A @ v,
            b=b,
            M_solve=ilu.solve,
            tol=1e-8,
            max_iter=200,
            restart=40,
        )
        assert converged, f"GMRES+ILU did not converge after {n_iter} iterations"
        assert np.allclose(x, x_ref, rtol=1e-5), (
            f"Max error vs LU: {np.max(np.abs(x - x_ref)):.2e}"
        )


class TestCExtension:
    """Verify the compiled C RHS kernel matches the Python implementation."""

    def test_c_rhs_matches_python(self):
        """C backend must produce results identical to Python RHS."""
        from solver.c_ext.wrapper import c_brusselator_rhs
        from solver.system import brusselator_rhs

        N = 30
        rng = np.random.RandomState(123)
        y = np.abs(rng.randn(2 * N)) + 0.1

        py_result = brusselator_rhs(y, N)
        c_result = c_brusselator_rhs(y, N)

        assert np.allclose(py_result, c_result, rtol=1e-12, atol=1e-14), (
            f"C vs Python max diff: {np.max(np.abs(py_result - c_result)):.2e}"
        )

    def test_c_rhs_at_steady_state(self):
        """C RHS must vanish at the homogeneous steady state."""
        from solver.c_ext.wrapper import c_brusselator_rhs

        N = 20
        A, B = 1.0, 3.0
        y = np.zeros(2 * N)
        y[0::2] = A
        y[1::2] = B / A

        rhs = c_brusselator_rhs(y, N)
        assert np.allclose(rhs, 0.0, atol=1e-10), (
            f"C RHS at steady state: max|rhs| = {np.max(np.abs(rhs)):.2e}"
        )

    def test_c_rhs_different_parameters(self):
        """C backend with non-default diffusion and kinetic parameters."""
        from solver.c_ext.wrapper import c_brusselator_rhs
        from solver.system import brusselator_rhs

        N = 25
        Du, Dv, A, B = 0.05, 0.01, 2.0, 4.5
        rng = np.random.RandomState(77)
        y = np.abs(rng.randn(2 * N)) + 0.1

        py_result = brusselator_rhs(y, N, Du=Du, Dv=Dv, A=A, B=B)
        c_result = c_brusselator_rhs(y, N, Du=Du, Dv=Dv, A=A, B=B)

        assert np.allclose(py_result, c_result, rtol=1e-12, atol=1e-14), (
            f"C vs Python max diff (custom params): "
            f"{np.max(np.abs(py_result - c_result)):.2e}"
        )


class TestSolutionAccuracy:
    """Solver output must match the pre-computed reference."""

    def test_matches_reference_at_final_time(self):
        from solver import solve_brusselator
        ref = np.load('/app/reference/solution_ref.npz')
        y_ref = ref['y_final']

        t, y, stats = solve_brusselator(N=50, t_end=10.0,
                                        rtol=1e-4, atol=1e-6)
        rel_err = np.linalg.norm(y[-1] - y_ref) / np.linalg.norm(y_ref)
        assert rel_err < 0.05, (
            f"Relative error {rel_err:.4e} exceeds 5% threshold "
            f"vs reference solution"
        )

    def test_solution_stays_bounded(self):
        from solver import solve_brusselator
        t, y, stats = solve_brusselator(N=30, t_end=5.0)

        assert np.all(np.isfinite(y)), "Solution contains NaN or Inf"
        u_all = y[:, 0::2]
        v_all = y[:, 1::2]
        assert np.all(u_all > -0.5), f"u went negative: min={u_all.min():.4e}"
        assert np.all(v_all > -0.5), f"v went negative: min={v_all.min():.4e}"
        assert np.all(u_all < 20.0), f"u blew up: max={u_all.max():.4e}"
        assert np.all(v_all < 20.0), f"v blew up: max={v_all.max():.4e}"


class TestSolverEfficiency:
    """Verify that the solver is computationally efficient."""

    def test_jacobian_reuse(self):
        """Fewer Jacobian evaluations than accepted time steps."""
        from solver import solve_brusselator
        t, y, stats = solve_brusselator(N=30, t_end=5.0)
        assert stats['n_steps'] > 10, (
            f"Only {stats['n_steps']} steps taken"
        )
        assert stats['n_jacobian_evals'] < stats['n_steps'], (
            f"Jacobian not reused: {stats['n_jacobian_evals']} evals "
            f"for {stats['n_steps']} steps"
        )

    def test_rejection_rate_bounded(self):
        """Rejection rate must stay low with well-tuned step control."""
        from solver import solve_brusselator
        t, y, stats = solve_brusselator(N=30, t_end=5.0)
        total = stats['n_steps'] + stats['n_rejected_steps']
        rej_rate = stats['n_rejected_steps'] / max(1, total)
        assert rej_rate < 0.15, (
            f"Rejection rate {rej_rate:.1%} > 15%"
        )

    def test_step_sizes_adaptive(self):
        """Step sizes must vary (not fixed)."""
        from solver import solve_brusselator
        t, y, stats = solve_brusselator(N=20, t_end=5.0)
        sizes = np.array(stats['step_sizes'])
        assert len(sizes) > 5
        cv = np.std(sizes) / np.mean(sizes)
        assert cv > 0.01, (
            f"Step size CV={cv:.4f} too small -- stepping not adaptive"
        )


class TestControllerModes:
    """Both PI and P controllers must produce valid solutions."""

    def test_both_controllers_reach_tend(self):
        from solver import solve_brusselator
        N = 15
        t_end = 2.0

        t_pi, y_pi, s_pi = solve_brusselator(N=N, t_end=t_end, controller='PI')
        assert s_pi['n_steps'] > 0
        assert abs(t_pi[-1] - t_end) < 1e-10

        t_p, y_p, s_p = solve_brusselator(N=N, t_end=t_end, controller='P')
        assert s_p['n_steps'] > 0
        assert abs(t_p[-1] - t_end) < 1e-10

    def test_controllers_agree_on_solution(self):
        from solver import solve_brusselator
        N = 15
        t_end = 2.0

        _, y_pi, _ = solve_brusselator(N=N, t_end=t_end,
                                       rtol=1e-4, atol=1e-6,
                                       controller='PI')
        _, y_p, _ = solve_brusselator(N=N, t_end=t_end,
                                      rtol=1e-4, atol=1e-6,
                                      controller='P')

        rel_err = np.linalg.norm(y_pi[-1] - y_p[-1]) / max(
            np.linalg.norm(y_pi[-1]), 1e-10
        )
        assert rel_err < 0.1, (
            f"PI and P controllers disagree: relative error = {rel_err:.4e}"
        )


class TestKrylovIntegration:
    """Full solver using the Krylov (GMRES) linear solver pathway."""

    def test_krylov_solver_matches_reference(self):
        """Krylov-based solver must produce accurate solution."""
        from solver import solve_brusselator
        ref = np.load('/app/reference/solution_ref.npz')
        y_ref = ref['y_final']

        t, y, stats = solve_brusselator(
            N=50, t_end=10.0, rtol=1e-4, atol=1e-6,
            linear_solver='krylov', c_backend=False,
        )
        rel_err = np.linalg.norm(y[-1] - y_ref) / np.linalg.norm(y_ref)
        assert rel_err < 0.05, (
            f"Krylov solver relative error {rel_err:.4e} > 5%"
        )

    def test_krylov_with_c_backend(self):
        """Full pipeline: GMRES linear solver + compiled C RHS backend."""
        from solver import solve_brusselator
        ref = np.load('/app/reference/solution_ref.npz')
        y_ref = ref['y_final']

        t, y, stats = solve_brusselator(
            N=50, t_end=10.0, rtol=1e-4, atol=1e-6,
            linear_solver='krylov', c_backend=True,
        )
        rel_err = np.linalg.norm(y[-1] - y_ref) / np.linalg.norm(y_ref)
        assert rel_err < 0.05, (
            f"Krylov+C solver relative error {rel_err:.4e} > 5%"
        )
        assert stats['n_steps'] > 10, "Too few steps with krylov+C"
