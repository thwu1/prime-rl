#!/usr/bin/env python3
"""
Stiff ODE solver with sparse Jacobian via graph coloring,
implicit Euler + Newton iteration, quasi-Newton Jacobian reuse,
and PI-controlled adaptive timestepping (step-doubling error estimation).

"""

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import splu


def build_brusselator_sparsity(N):
    """Build binary CSC sparsity pattern for the interleaved Brusselator Jacobian.

    State vector layout: [u1, v1, u2, v2, ..., uN, vN] (size 2N).
    Returns scipy.sparse.csc_matrix with 1s at every possible nonzero position.
    """
    n = 2 * N
    rows, cols = [], []

    for i in range(N):
        ui = 2 * i
        vi = 2 * i + 1

        # Row ui: du_i/dt depends on u_{i-1} (diffusion), u_i, u_{i+1} (diffusion), v_i (reaction)
        if i > 0:
            rows.append(ui); cols.append(2 * (i - 1))      # u_{i-1}
        rows.append(ui); cols.append(ui)                    # u_i
        if i < N - 1:
            rows.append(ui); cols.append(2 * (i + 1))      # u_{i+1}
        rows.append(ui); cols.append(vi)                    # v_i

        # Row vi: dv_i/dt depends on v_{i-1} (diffusion), u_i (reaction), v_i, v_{i+1} (diffusion)
        if i > 0:
            rows.append(vi); cols.append(2 * (i - 1) + 1)  # v_{i-1}
        rows.append(vi); cols.append(ui)                    # u_i
        rows.append(vi); cols.append(vi)                    # v_i
        if i < N - 1:
            rows.append(vi); cols.append(2 * (i + 1) + 1)  # v_{i+1}

    data = np.ones(len(rows), dtype=np.float64)
    return sparse.csc_matrix((data, (rows, cols)), shape=(n, n))


def column_connectivity_graph(S):
    """Build column connectivity graph from a sparsity pattern.

    Two columns i and j are connected (conflict) if there exists a row
    where both have nonzero entries.

    Returns dict: {column_index: set of conflicting column indices}.
    """
    n_cols = S.shape[1]
    adj = {i: set() for i in range(n_cols)}
    S_csr = S.tocsr()

    for row in range(S.shape[0]):
        start, end = S_csr.indptr[row], S_csr.indptr[row + 1]
        nz_cols = S_csr.indices[start:end]
        for ii in range(len(nz_cols)):
            for jj in range(ii + 1, len(nz_cols)):
                ci, cj = int(nz_cols[ii]), int(nz_cols[jj])
                adj[ci].add(cj)
                adj[cj].add(ci)

    return adj


def greedy_distance1_coloring(adj, n_cols):
    """Greedy sequential distance-1 graph coloring.

    Returns np.array of 0-indexed color assignments (length n_cols).
    """
    colors = np.full(n_cols, -1, dtype=int)

    for node in range(n_cols):
        used = set()
        for nb in adj.get(node, set()):
            if colors[nb] >= 0:
                used.add(colors[nb])
        c = 0
        while c in used:
            c += 1
        colors[node] = c

    return colors


def compressed_sparse_jacobian(f, x, sparsity, coloring, eps=1e-7):
    """Compute sparse Jacobian via compressed finite differences.

    Uses the coloring to perturb multiple columns simultaneously, then
    decompresses the result using the known sparsity pattern.

    Returns scipy.sparse.csc_matrix.
    """
    n = len(x)
    n_colors = int(np.max(coloring)) + 1
    f0 = f(x)

    S_csc = sparsity.tocsc()
    jac_rows, jac_cols, jac_data = [], [], []

    for c in range(n_colors):
        # Build seed: 1 at every column with this color
        seed = np.zeros(n)
        col_indices = np.where(coloring == c)[0]
        seed[col_indices] = 1.0

        # Compressed finite difference
        compressed = (f(x + eps * seed) - f0) / eps

        # Decompress: for each column j with this color,
        # extract Jacobian values at its known nonzero rows
        for j in col_indices:
            start, end = S_csc.indptr[j], S_csc.indptr[j + 1]
            for row in S_csc.indices[start:end]:
                jac_rows.append(int(row))
                jac_cols.append(int(j))
                jac_data.append(compressed[int(row)])

    return sparse.csc_matrix((jac_data, (jac_rows, jac_cols)), shape=(n, n))


def brusselator_rhs(y, N, Du=0.02, Dv=0.02, A=1.0, B=3.0):
    """Right-hand side of the 1D Brusselator reaction-diffusion system.

    State: interleaved [u1, v1, u2, v2, ..., uN, vN].
    Dirichlet BCs: u(0)=u(1)=A, v(0)=v(1)=B/A.
    """
    dx = 1.0 / (N + 1)
    dx2 = dx * dx

    u = y[0::2]
    v = y[1::2]

    u_bc = A
    v_bc = B / A

    # Pad with boundary values for diffusion stencil
    u_pad = np.concatenate(([u_bc], u, [u_bc]))
    v_pad = np.concatenate(([v_bc], v, [v_bc]))

    dydt = np.zeros_like(y)
    dydt[0::2] = (Du * (u_pad[:-2] - 2.0 * u_pad[1:-1] + u_pad[2:]) / dx2
                  + A - (B + 1.0) * u + u * u * v)
    dydt[1::2] = (Dv * (v_pad[:-2] - 2.0 * v_pad[1:-1] + v_pad[2:]) / dx2
                  + B * u - u * u * v)

    return dydt


def _newton_solve(f, y_n, dt, lu, atol, rtol, max_iter=50):
    """Newton iteration for implicit Euler: solve x - y_n - dt*f(x) = 0.

    Uses a fixed LU factorization of J = I - dt * df/dy (quasi-Newton).
    Returns (solution, converged, n_fevals).
    """
    x = y_n.copy()
    n_fevals = 0

    for _ in range(max_iter):
        fx = f(x)
        n_fevals += 1
        g = x - y_n - dt * fx
        delta = lu.solve(g)
        x -= delta

        if np.linalg.norm(delta, ord=np.inf) < atol + rtol * np.linalg.norm(x, ord=np.inf):
            return x, True, n_fevals

    return x, False, n_fevals


def solve_brusselator(N=50, t_end=10.0, rtol=1e-4, atol=1e-6, controller='PI'):
    """Solve the Brusselator system with adaptive implicit Euler + step doubling.

    Returns (t_array, y_array, stats_dict).
    """
    n = 2 * N
    dx = 1.0 / (N + 1)
    x_grid = np.linspace(dx, 1.0 - dx, N)

    # Initial conditions
    y0 = np.zeros(n)
    y0[0::2] = 1.0 + np.sin(2.0 * np.pi * x_grid)
    y0[1::2] = 3.0

    # Precompute sparsity and coloring (done once)
    S = build_brusselator_sparsity(N)
    adj = column_connectivity_graph(S)
    coloring = greedy_distance1_coloring(adj, n)
    n_colors = int(np.max(coloring)) + 1

    rhs = lambda y: brusselator_rhs(y, N)

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

    # Jacobian reuse state
    J_ode = None
    need_jac = True
    steps_since_jac = 0
    max_steps_per_jac = 20

    # PI controller state
    q_prev = None

    # Safety and clamping parameters
    safety = 0.9
    fac_min = 0.2
    fac_max = 5.0

    newton_atol = atol * 0.1
    newton_rtol = rtol * 0.1

    for _ in range(500000):
        if t >= t_end - 1e-14:
            break
        dt = min(dt, t_end - t)
        if dt < 1e-14:
            break

        # Compute / recompute ODE Jacobian df/dy if needed
        if need_jac:
            J_ode = compressed_sparse_jacobian(rhs, y, S, coloring)
            stats['n_jacobian_evals'] += 1
            stats['n_function_evals'] += n_colors + 1
            need_jac = False
            steps_since_jac = 0

        # --- Full step (dt) ---
        J_full = sparse.eye(n, format='csc') - dt * J_ode
        try:
            lu_full = splu(J_full)
        except Exception:
            dt *= 0.5
            need_jac = True
            stats['n_rejected_steps'] += 1
            continue
        stats['n_lu_factorizations'] += 1

        y_full, conv_full, nfe = _newton_solve(rhs, y, dt, lu_full,
                                               newton_atol, newton_rtol)
        stats['n_function_evals'] += nfe

        if not conv_full or not np.all(np.isfinite(y_full)):
            dt *= 0.5
            need_jac = True
            stats['n_rejected_steps'] += 1
            q_prev = None
            continue

        # --- Two half steps (dt/2 each) ---
        dt2 = dt / 2.0
        J_half = sparse.eye(n, format='csc') - dt2 * J_ode
        try:
            lu_half = splu(J_half)
        except Exception:
            dt *= 0.5
            need_jac = True
            stats['n_rejected_steps'] += 1
            continue
        stats['n_lu_factorizations'] += 1

        y_mid, conv1, nfe = _newton_solve(rhs, y, dt2, lu_half,
                                          newton_atol, newton_rtol)
        stats['n_function_evals'] += nfe
        if not conv1 or not np.all(np.isfinite(y_mid)):
            dt *= 0.5
            need_jac = True
            stats['n_rejected_steps'] += 1
            q_prev = None
            continue

        y_dbl, conv2, nfe = _newton_solve(rhs, y_mid, dt2, lu_half,
                                          newton_atol, newton_rtol)
        stats['n_function_evals'] += nfe
        if not conv2 or not np.all(np.isfinite(y_dbl)):
            dt *= 0.5
            need_jac = True
            stats['n_rejected_steps'] += 1
            q_prev = None
            continue

        # --- Error estimation ---
        err_vec = y_dbl - y_full
        scale = atol + rtol * np.maximum(np.abs(y), np.abs(y_dbl))
        q = np.sqrt(np.mean((err_vec / scale) ** 2))

        if q > 1.0:
            # Reject step
            stats['n_rejected_steps'] += 1
            factor = max(fac_min, safety * q ** (-0.5))
            dt *= factor
            need_jac = True
            q_prev = None
            continue

        # --- Accept step (Richardson extrapolation for order boost) ---
        y = 2.0 * y_dbl - y_full
        t += dt
        stats['n_steps'] += 1
        stats['step_sizes'].append(dt)
        t_hist.append(t)
        y_hist.append(y.copy())

        # --- Step size control ---
        q_safe = max(q, 1e-10)

        if controller == 'PI' and q_prev is not None:
            # PI controller: dt_new = dt * q^(-alpha) * q_prev^(beta)
            # alpha = 0.7/(p+1), beta = 0.4/(p+1), p=1 for implicit Euler
            alpha = 0.7 / 2.0   # = 0.35
            beta = 0.4 / 2.0    # = 0.2
            factor = q_safe ** (-alpha) * q_prev ** beta
        else:
            # P controller: dt_new = dt * q^(-1/(p+1))
            factor = q_safe ** (-0.5)

        factor = min(fac_max, max(fac_min, safety * factor))
        dt *= factor
        q_prev = q_safe

        # Jacobian reuse heuristic: refresh periodically
        steps_since_jac += 1
        if steps_since_jac >= max_steps_per_jac:
            need_jac = True

    return np.array(t_hist), np.array(y_hist), stats
