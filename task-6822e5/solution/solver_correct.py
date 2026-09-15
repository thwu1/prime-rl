"""
Correct, optimized solver for the 2D Brusselator reaction-diffusion PDE.

"""

import numpy as np
from scipy.integrate import solve_ivp
from scipy.sparse import lil_matrix
import sys

sys.path.insert(0, "/app")
from problem import (
    N,
    dx,
    A_PARAM,
    B_PARAM,
    ALPHA,
    ALPHA_DX2,
    xyd,
    TSPAN,
    OUTPUT_TIMES,
    initial_conditions,
)

# ---------------------------------------------------------------------------
# Pre-computed forcing mask (avoids recomputation every RHS call)
# ---------------------------------------------------------------------------
_X, _Y = np.meshgrid(xyd, xyd, indexing="ij")
_forcing_mask = ((_X - 0.3) ** 2 + (_Y - 0.6) ** 2) <= 0.01
_f_active = 5.0 * _forcing_mask.astype(np.float64)


# ---------------------------------------------------------------------------
# Vectorized RHS with correct clamped (Neumann) boundary conditions
# ---------------------------------------------------------------------------
def brusselator_rhs(t, u):
    """
    Right-hand side for the Brusselator PDE.

    Uses np.pad(mode='edge') to implement zero-flux (clamped) boundary
    conditions, and fully vectorized numpy operations for performance.
    """
    nn = N * N
    U = u[:nn].reshape(N, N)
    V = u[nn:].reshape(N, N)

    # Pad with edge values => clamped / zero-flux Neumann BC
    U_pad = np.pad(U, 1, mode="edge")
    V_pad = np.pad(V, 1, mode="edge")

    # 5-point Laplacian stencil
    lap_U = ALPHA_DX2 * (
        U_pad[:-2, 1:-1]
        + U_pad[2:, 1:-1]
        + U_pad[1:-1, :-2]
        + U_pad[1:-1, 2:]
        - 4.0 * U
    )
    lap_V = ALPHA_DX2 * (
        V_pad[:-2, 1:-1]
        + V_pad[2:, 1:-1]
        + V_pad[1:-1, :-2]
        + V_pad[1:-1, 2:]
        - 4.0 * V
    )

    # Forcing (pre-computed mask)
    f_val = _f_active if t >= 1.1 else 0.0

    # Reaction-diffusion equations
    dU = lap_U + B_PARAM + U * U * V - (A_PARAM + 1.0) * U + f_val
    dV = lap_V + A_PARAM * U - U * U * V

    return np.concatenate([dU.ravel(), dV.ravel()])


# ---------------------------------------------------------------------------
# Jacobian sparsity pattern
# ---------------------------------------------------------------------------
def build_jacobian_sparsity(n):
    """
    Construct the sparsity pattern of the Jacobian for an n x n grid
    with 2 coupled species and clamped boundary conditions.

    State layout:  u = [U.ravel(), V.ravel()]
    Total size:    2 * n * n

    Each U equation at (i,j) depends on:
        - U at self and up to 4 distinct Laplacian neighbors
        - V at self (reaction coupling U^2 V)

    Each V equation at (i,j) depends on:
        - V at self and up to 4 distinct Laplacian neighbors
        - U at self (reaction coupling A U - U^2 V)

    At boundaries, clamped neighbors coincide with self, so fewer
    off-diagonal entries exist (the coefficient folds into the diagonal).

    Total nnz = 12 n^2 - 8 n.
    """
    nn = n * n
    size = 2 * nn
    J = lil_matrix((size, size), dtype=np.float64)

    for i in range(n):
        for j in range(n):
            idx_u = i * n + j
            idx_v = nn + i * n + j

            # -- U equation row --
            J[idx_u, idx_u] = 1.0  # self (Laplacian diag + reaction)
            J[idx_u, idx_v] = 1.0  # V coupling (U^2)
            if i > 0:
                J[idx_u, (i - 1) * n + j] = 1.0
            if i < n - 1:
                J[idx_u, (i + 1) * n + j] = 1.0
            if j > 0:
                J[idx_u, i * n + (j - 1)] = 1.0
            if j < n - 1:
                J[idx_u, i * n + (j + 1)] = 1.0

            # -- V equation row --
            J[idx_v, idx_v] = 1.0  # self (Laplacian diag + reaction)
            J[idx_v, idx_u] = 1.0  # U coupling (A - 2UV)
            if i > 0:
                J[idx_v, nn + (i - 1) * n + j] = 1.0
            if i < n - 1:
                J[idx_v, nn + (i + 1) * n + j] = 1.0
            if j > 0:
                J[idx_v, nn + i * n + (j - 1)] = 1.0
            if j < n - 1:
                J[idx_v, nn + i * n + (j + 1)] = 1.0

    return J.tocsc()


# ---------------------------------------------------------------------------
# Analytical Jacobian
# ---------------------------------------------------------------------------
def compute_jacobian(t, u):
    """
    Compute the exact sparse Jacobian of the Brusselator RHS at (t, u).

    The Jacobian has a 2x2 block structure:

        J = [ J_UU   J_UV ]
            [ J_VU   J_VV ]

    where:
        J_UU, J_VV : 5-point Laplacian stencil + diagonal reaction terms
        J_UV, J_VU : diagonal (cross-species coupling at same grid point)

    Boundary correction: at clamped boundaries, neighbor = self, so the
    off-diagonal Laplacian entry vanishes and its coefficient (+alpha/dx^2)
    is added to the diagonal instead of the default -4*alpha/dx^2.
    """
    nn = N * N
    U = u[:nn].reshape(N, N)
    V = u[nn:].reshape(N, N)
    size = 2 * nn
    J = lil_matrix((size, size), dtype=np.float64)

    for i in range(N):
        for j in range(N):
            idx_u = i * N + j
            idx_v = nn + i * N + j

            Uij = U[i, j]
            Vij = V[i, j]

            # Number of clamped boundaries at this point
            bc = int(i == 0) + int(i == N - 1) + int(j == 0) + int(j == N - 1)

            # --- U equation ---
            # d(dU/dt) / dU(i,j):  Laplacian diagonal + reaction
            J[idx_u, idx_u] = (
                ALPHA_DX2 * (-4.0 + bc) + 2.0 * Uij * Vij - (A_PARAM + 1.0)
            )
            # d(dU/dt) / dV(i,j):  U^2
            J[idx_u, idx_v] = Uij * Uij
            # d(dU/dt) / dU(neighbors):  alpha/dx^2  (only distinct neighbors)
            if i > 0:
                J[idx_u, (i - 1) * N + j] = ALPHA_DX2
            if i < N - 1:
                J[idx_u, (i + 1) * N + j] = ALPHA_DX2
            if j > 0:
                J[idx_u, i * N + (j - 1)] = ALPHA_DX2
            if j < N - 1:
                J[idx_u, i * N + (j + 1)] = ALPHA_DX2

            # --- V equation ---
            # d(dV/dt) / dV(i,j):  Laplacian diagonal + reaction
            J[idx_v, idx_v] = ALPHA_DX2 * (-4.0 + bc) - Uij * Uij
            # d(dV/dt) / dU(i,j):  A - 2UV
            J[idx_v, idx_u] = A_PARAM - 2.0 * Uij * Vij
            # d(dV/dt) / dV(neighbors)
            if i > 0:
                J[idx_v, nn + (i - 1) * N + j] = ALPHA_DX2
            if i < N - 1:
                J[idx_v, nn + (i + 1) * N + j] = ALPHA_DX2
            if j > 0:
                J[idx_v, nn + i * N + (j - 1)] = ALPHA_DX2
            if j < N - 1:
                J[idx_v, nn + i * N + (j + 1)] = ALPHA_DX2

    return J.tocsc()


# ---------------------------------------------------------------------------
# Solver
# ---------------------------------------------------------------------------
def solve_brusselator():
    """
    Solve the Brusselator PDE system and save to /app/results.npz.

    Uses scipy's BDF method (implicit multi-step, appropriate for stiff
    systems) with the pre-computed Jacobian sparsity pattern for efficient
    colored finite-difference Jacobian approximation.
    """
    u0 = initial_conditions()
    jac_sp = build_jacobian_sparsity(N)

    sol = solve_ivp(
        brusselator_rhs,
        TSPAN,
        u0,
        method="BDF",
        t_eval=OUTPUT_TIMES,
        jac_sparsity=jac_sp,
        rtol=1e-6,
        atol=1e-8,
        max_step=1.0,
    )

    if not sol.success:
        raise RuntimeError(f"Solver failed: {sol.message}")

    nn = N * N
    n_times = len(OUTPUT_TIMES)
    U_out = sol.y[:nn, :].reshape(N, N, n_times).transpose(2, 0, 1)
    V_out = sol.y[nn:, :].reshape(N, N, n_times).transpose(2, 0, 1)

    np.savez("/app/results.npz", times=np.array(OUTPUT_TIMES), U=U_out, V=V_out)


if __name__ == "__main__":
    solve_brusselator()
