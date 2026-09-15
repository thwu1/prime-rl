"""
Main integration driver: adaptive implicit Euler with step-doubling
error estimation, sparse Jacobian reuse, and configurable linear solver
backend (direct LU or iterative GMRES with ILU preconditioning).
"""
import numpy as np
from scipy import sparse
from scipy.sparse.linalg import splu, spilu

from .system import brusselator_rhs, build_sparsity_pattern, make_initial_condition
from .sparse_diff import column_connectivity_graph, greedy_coloring, compressed_jacobian
from .stepping import newton_solve, compute_step_factor


def _make_rhs(N, c_backend=False):
    """Create the RHS callable, optionally using the compiled C backend."""
    if c_backend:
        from .c_ext.wrapper import c_brusselator_rhs
        return lambda y: c_brusselator_rhs(y, N)
    else:
        return lambda y: brusselator_rhs(y, N)


def _make_linear_solver(J_sys, method='direct'):
    """Build a linear-solve callable for the Newton iteration.

    Parameters
    ----------
    J_sys : sparse matrix
        The Newton system matrix  I - dt * J_ode.
    method : str
        'direct' for SuperLU factorisation, 'krylov' for
        preconditioned GMRES with ILU(0).

    Returns
    -------
    solve : callable
        solve(b) returns the solution x of  J_sys @ x = b.
    """
    if method == 'direct':
        lu = splu(J_sys)
        return lu.solve
    elif method == 'krylov':
        from .krylov import preconditioned_gmres
        ilu = spilu(J_sys, drop_tol=1e-4)

        def solve(b):
            x, converged, _ = preconditioned_gmres(
                A_matvec=lambda v: J_sys @ v,
                b=b,
                M_solve=ilu.solve,
                tol=1e-8,
                max_iter=200,
                restart=40,
            )
            return x
        return solve
    else:
        raise ValueError(f"Unknown linear solver method: {method}")


def solve_brusselator(N=50, t_end=10.0, rtol=1e-4, atol=1e-6,
                      controller='PI', max_steps_per_jac=20,
                      linear_solver='direct', c_backend=False):
    """Solve the Brusselator reaction-diffusion system.

    Returns (t_array, y_array, stats_dict).
    """
    n = 2 * N
    y0 = make_initial_condition(N)

    # Build sparsity structure and coloring (once)
    S = build_sparsity_pattern(N)
    adj = column_connectivity_graph(S)
    coloring = greedy_coloring(adj, n)
    n_colors = int(np.max(coloring)) + 1

    rhs = _make_rhs(N, c_backend)

    stats = {
        'n_steps': 0,
        'n_jacobian_evals': 0,
        'n_lu_factorizations': 0,
        'n_function_evals': 0,
        'n_rejected_steps': 0,
        'step_sizes': [],
    }

    t = 0.0
    y = y0.copy()
    dt = min(1e-3, t_end * 1e-4)

    t_hist = [t]
    y_hist = [y.copy()]

    J_ode = None
    need_jac = True
    steps_since_jac = 0
    q_prev = None

    newton_atol = atol * 0.1
    newton_rtol = rtol * 0.1

    for _ in range(500000):
        if t >= t_end - 1e-14:
            break
        dt = min(dt, t_end - t)
        if dt < 1e-14:
            break

        # Recompute ODE Jacobian if needed
        if need_jac:
            J_ode = compressed_jacobian(rhs, y, S, coloring)
            stats['n_jacobian_evals'] += 1
            stats['n_function_evals'] += n_colors + 1
            need_jac = False
            steps_since_jac = 0

        # ---------- full step (dt) ----------
        J_full = sparse.eye(n, format='csc') - dt * J_ode
        try:
            solve_full = _make_linear_solver(J_full, linear_solver)
        except Exception:
            dt *= 0.5
            need_jac = True
            stats['n_rejected_steps'] += 1
            continue
        stats['n_lu_factorizations'] += 1

        y_full, conv_full, nfe = newton_solve(rhs, y, dt, solve_full,
                                              newton_atol, newton_rtol)
        stats['n_function_evals'] += nfe

        if not conv_full or not np.all(np.isfinite(y_full)):
            dt *= 0.5
            need_jac = True
            stats['n_rejected_steps'] += 1
            q_prev = None
            continue

        # ---------- two half steps (dt/2 each) ----------
        dt2 = dt / 2.0
        J_half = sparse.eye(n, format='csc') - dt2 * J_ode
        try:
            solve_half = _make_linear_solver(J_half, linear_solver)
        except Exception:
            dt *= 0.5
            need_jac = True
            stats['n_rejected_steps'] += 1
            continue
        stats['n_lu_factorizations'] += 1

        y_mid, conv1, nfe = newton_solve(rhs, y, dt2, solve_half,
                                         newton_atol, newton_rtol)
        stats['n_function_evals'] += nfe
        if not conv1 or not np.all(np.isfinite(y_mid)):
            dt *= 0.5
            need_jac = True
            stats['n_rejected_steps'] += 1
            q_prev = None
            continue

        y_dbl, conv2, nfe = newton_solve(rhs, y_mid, dt2, solve_half,
                                         newton_atol, newton_rtol)
        stats['n_function_evals'] += nfe
        if not conv2 or not np.all(np.isfinite(y_dbl)):
            dt *= 0.5
            need_jac = True
            stats['n_rejected_steps'] += 1
            q_prev = None
            continue

        # ---------- error estimation ----------
        err_vec = y_dbl - y_full
        scale = atol + rtol * np.maximum(np.abs(y), np.abs(y_dbl))
        q = np.sqrt(np.mean((err_vec / scale) ** 2))

        if q > 1.0:
            stats['n_rejected_steps'] += 1
            factor = max(0.2, 0.9 * q ** (-0.5))
            dt *= factor
            need_jac = True
            q_prev = None
            continue

        # ---------- accept step (Richardson extrapolation) ----------
        y = 2.0 * y_dbl - y_full
        t += dt
        stats['n_steps'] += 1
        stats['step_sizes'].append(dt)
        t_hist.append(t)
        y_hist.append(y.copy())

        # ---------- step-size control ----------
        factor = compute_step_factor(q, q_prev, controller)
        dt *= factor
        q_prev = max(q, 1e-10)

        steps_since_jac += 1
        if steps_since_jac >= max_steps_per_jac:
            need_jac = True

    return np.array(t_hist), np.array(y_hist), stats
