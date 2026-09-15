#!/usr/bin/env python3
"""
Reference solution for the Brusselator PDE numerical analysis pipeline.

Produces all six required output files:
  - solution_bdf.npz (BDF with analytical Jacobian)
  - solution_imex.npz (IMEX operator splitting)
  - jacobian_at_t0.npz (sparse CSC Jacobian)
  - stiffness_analysis.json (eigenvalue analysis)
  - preconditioner_analysis.json (GMRES + ILU comparison)
  - sparsity_analysis.json (structural nonzero count)
"""

import numpy as np
import json
import sys
import time

sys.path.insert(0, '/app')
from brusselator_problem import (N, A_PARAM, B_PARAM, D,
                                  brusselator_rhs, initial_conditions,
                                  T_SPAN, X, Y)

from scipy.integrate import solve_ivp
from scipy.sparse import eye as speye, kron, diags, bmat, save_npz
from scipy.sparse.linalg import splu, eigs, gmres, spilu, LinearOperator

NN = N * N


# ---------------------------------------------------------------------------
# Laplacian and Jacobian construction
# ---------------------------------------------------------------------------

def build_lap1d(n):
    """1D second-difference with Neumann BCs (modified corners)."""
    main = -2.0 * np.ones(n)
    main[0] = main[-1] = -1.0
    return diags([np.ones(n - 1), main, np.ones(n - 1)],
                 [-1, 0, 1], shape=(n, n), format='csc')


def build_lap2d():
    """2D Laplacian via Kronecker product: L = I x T + T x I."""
    T = build_lap1d(N)
    I_N = speye(N, format='csc')
    return kron(T, I_N, format='csc') + kron(I_N, T, format='csc')


L2D = build_lap2d()
DL = D * L2D


def analytical_jac(t, y):
    """Analytical Jacobian with 2x2 block structure."""
    U, V = y[:NN], y[NN:]
    J_UU = DL + diags(2.0 * U * V - (A_PARAM + 1.0), 0,
                       shape=(NN, NN), format='csc')
    J_UV = diags(U ** 2, 0, shape=(NN, NN), format='csc')
    J_VU = diags(A_PARAM - 2.0 * U * V, 0, shape=(NN, NN), format='csc')
    J_VV = DL + diags(-U ** 2, 0, shape=(NN, NN), format='csc')
    return bmat([[J_UU, J_UV], [J_VU, J_VV]], format='csc')


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main():
    y0 = initial_conditions()

    # === 1. BDF Solution ===
    print("1. BDF solve with analytical sparse Jacobian...")
    t0 = time.time()
    sol = solve_ivp(brusselator_rhs, T_SPAN, y0, method='BDF',
                    jac=analytical_jac, rtol=1e-6, atol=1e-9,
                    dense_output=True)
    assert sol.success, f"BDF failed: {sol.message}"
    print(f"   Done in {time.time() - t0:.1f}s ({sol.nfev} fev, {sol.njev} jev)")

    y_mid = sol.sol(5.75)
    y_final = sol.sol(11.5)
    np.savez('/app/solution_bdf.npz',
             u_final=y_final[:NN].reshape(N, N),
             v_final=y_final[NN:].reshape(N, N),
             u_mid=y_mid[:NN].reshape(N, N),
             v_mid=y_mid[NN:].reshape(N, N))

    # === 2. IMEX Solution ===
    # Backward Euler for diffusion (implicit) + Forward Euler for reaction (explicit)
    print("2. IMEX solve (implicit diffusion, explicit reaction)...")
    t0 = time.time()

    N_steps = 4000  # chosen for stability + accuracy
    dt = (T_SPAN[1] - T_SPAN[0]) / N_steps
    mid_step = N_steps // 2  # step 2000 -> t = 5.75

    # Pre-factor the implicit diffusion matrix (constant, reused every step)
    I_nn = speye(NN, format='csc')
    A_impl = (I_nn - dt * DL).tocsc()
    lu_diff = splu(A_impl)

    U = y0[:NN].copy()
    V = y0[NN:].copy()
    u_mid_imex = v_mid_imex = None

    # Pre-compute source mask (time-invariant spatial pattern)
    X_flat = X.ravel()
    Y_flat = Y.ravel()
    source_mask = (X_flat - 0.3) ** 2 + (Y_flat - 0.6) ** 2 <= 0.01

    for n in range(N_steps):
        t_n = T_SPAN[0] + n * dt

        # Explicit reaction terms
        source = np.zeros(NN)
        if t_n >= 1.1:
            source[source_mask] = 5.0

        R_U = B_PARAM + U * U * V - (A_PARAM + 1.0) * U + source
        R_V = A_PARAM * U - U * U * V

        # Implicit diffusion solve: (I - dt*D*L) u_{n+1} = u_n + dt*R(u_n)
        U = lu_diff.solve(U + dt * R_U)
        V = lu_diff.solve(V + dt * R_V)

        if n + 1 == mid_step:
            u_mid_imex = U.copy().reshape(N, N)
            v_mid_imex = V.copy().reshape(N, N)

    print(f"   Done in {time.time() - t0:.1f}s ({N_steps} steps, dt={dt:.6f})")

    np.savez('/app/solution_imex.npz',
             u_final=U.reshape(N, N), v_final=V.reshape(N, N),
             u_mid=u_mid_imex, v_mid=v_mid_imex)

    # === 3. Jacobian at t=0 ===
    J0 = analytical_jac(0.0, y0)
    save_npz('/app/jacobian_at_t0.npz', J0)

    # === 4. Stiffness Analysis ===
    print("4. Eigenvalue analysis...")
    # 5 largest eigenvalues by magnitude
    vals_large, _ = eigs(J0, k=5, which='LM', maxiter=5000)
    vals_large = vals_large[np.argsort(-np.abs(vals_large))]

    # 5 smallest eigenvalues by magnitude (shift-invert near 0)
    vals_small, _ = eigs(J0, k=5, sigma=0, maxiter=5000)
    vals_small = vals_small[np.argsort(np.abs(vals_small))]

    rho = float(np.max(np.abs(vals_large)))
    min_mag = float(np.min(np.abs(vals_small)))

    stiffness = {
        'eigenvalues_largest': [[float(v.real), float(v.imag)] for v in vals_large],
        'eigenvalues_smallest': [[float(v.real), float(v.imag)] for v in vals_small],
        'stiffness_ratio': rho / min_mag,
        'max_explicit_dt': 2.0 / rho,
    }
    with open('/app/stiffness_analysis.json', 'w') as f:
        json.dump(stiffness, f, indent=2)
    print(f"   Spectral radius: {rho:.1f}, stiffness ratio: {rho / min_mag:.0f}")
    print(f"   Max explicit dt: {2.0 / rho:.2e}")

    # === 5. Preconditioner Analysis ===
    print("5. GMRES + ILU preconditioner comparison...")
    b = brusselator_rhs(0.0, y0)

    # GMRES without preconditioning
    iters_no = [0]
    def cb_no(_):
        iters_no[0] += 1
    x_no, info_no = gmres(J0, b, tol=1e-6, atol=0,
                           callback=cb_no, restart=100, maxiter=500)

    # GMRES with ILU preconditioning
    ilu = spilu(J0.tocsc(), drop_tol=1e-5, fill_factor=10)
    M_ilu = LinearOperator(J0.shape, matvec=ilu.solve)

    iters_ilu = [0]
    def cb_ilu(_):
        iters_ilu[0] += 1
    x_ilu, info_ilu = gmres(J0, b, tol=1e-6, atol=0,
                             M=M_ilu, callback=cb_ilu, restart=100, maxiter=500)

    bnorm = np.linalg.norm(b)
    res_no = float(np.linalg.norm(J0 @ x_no - b) / bnorm)
    res_ilu = float(np.linalg.norm(J0 @ x_ilu - b) / bnorm)

    precond = {
        'gmres_iters_no_precond': iters_no[0],
        'gmres_iters_ilu': iters_ilu[0],
        'ilu_fill_ratio': float(ilu.nnz / J0.nnz),
        'gmres_residual_no_precond': res_no,
        'gmres_residual_ilu': res_ilu,
    }
    with open('/app/preconditioner_analysis.json', 'w') as f:
        json.dump(precond, f, indent=2)
    print(f"   GMRES iters: {iters_no[0]} (none) vs {iters_ilu[0]} (ILU)")
    print(f"   Residuals: {res_no:.2e} (none) vs {res_ilu:.2e} (ILU)")

    # === 6. Sparsity Analysis ===
    # Structural sparsity pattern (state-independent)
    I_NN = speye(NN, format='csc')
    DL_pattern = (abs(DL) > 0).astype(float)
    structural = bmat([[DL_pattern, I_NN], [I_NN, DL_pattern]], format='csc')
    total = 2 * NN

    sparsity = {
        'total_unknowns': total,
        'nnz_jacobian': int(structural.nnz),
        'density': float(structural.nnz / total ** 2),
    }
    with open('/app/sparsity_analysis.json', 'w') as f:
        json.dump(sparsity, f, indent=2)
    print(f"6. Sparsity: {structural.nnz} nnz, density {structural.nnz / total**2:.6f}")

    print("\nAll outputs written successfully.")


if __name__ == '__main__':
    main()
