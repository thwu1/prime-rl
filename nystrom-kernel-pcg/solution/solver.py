#!/usr/bin/env python3
"""
Nystrom-preconditioned conjugate gradient solver for kernel ridge regression.

Algorithm overview:
1. Estimate ridge leverage scores via a pilot Nystrom sketch (uniform subsample).
2. Sample landmark points proportional to estimated leverage scores.
3. Build a Nystrom preconditioner applied via the Woodbury matrix identity.
4. Solve (K + lambda I) alpha = y with preconditioned CG.
"""

import numpy as np
from scipy.linalg import cho_factor, cho_solve
import json
import os


# ---------------------------------------------------------------------------
# Kernel helpers (matrix-free, chunked)
# ---------------------------------------------------------------------------

def kernel_columns(X, col_indices, sigma, chunk_size=1000):
    """Compute K[:, col_indices] without forming the full kernel matrix."""
    n = X.shape[0]
    X_cols = X[col_indices]
    s = len(col_indices)
    result = np.zeros((n, s))
    sq_all = np.sum(X ** 2, axis=1)
    sq_cols = np.sum(X_cols ** 2, axis=1)
    for i in range(0, n, chunk_size):
        end = min(i + chunk_size, n)
        cross = X[i:end] @ X_cols.T
        dists_sq = sq_all[i:end, None] + sq_cols[None, :] - 2.0 * cross
        np.maximum(dists_sq, 0.0, out=dists_sq)
        result[i:end] = np.exp(-dists_sq / (2.0 * sigma ** 2))
    return result


def kernel_matvec(X, v, sigma, lam, chunk_size=1000):
    """Compute (K + lambda I) @ v without forming the full kernel matrix."""
    n = X.shape[0]
    result = lam * v.copy()
    sq_norms = np.sum(X ** 2, axis=1)
    for i in range(0, n, chunk_size):
        end = min(i + chunk_size, n)
        cross = X[i:end] @ X.T
        dists_sq = sq_norms[i:end, None] + sq_norms[None, :] - 2.0 * cross
        np.maximum(dists_sq, 0.0, out=dists_sq)
        K_chunk = np.exp(-dists_sq / (2.0 * sigma ** 2))
        result[i:end] += K_chunk @ v
    return result


# ---------------------------------------------------------------------------
# Leverage score estimation
# ---------------------------------------------------------------------------

def estimate_ridge_leverage_scores(X, sigma, lam, s_pilot=250):
    """Approximate ridge leverage scores via a pilot Nystrom sketch.

    Steps:
      1. Uniformly sample s_pilot landmark columns.
      2. Form C = K[:, S], W = K[S, S].
      3. Eigendecompose W; compute Z = C @ W^{-1/2}.
      4. Ridge leverage scores = diag(Z (Z^T Z + lambda I)^{-1} Z^T).
    """
    n = X.shape[0]
    rng = np.random.RandomState(42)
    pilot_idx = rng.choice(n, s_pilot, replace=False)

    # K[:, pilot] and K[pilot, pilot]
    C = kernel_columns(X, pilot_idx, sigma)          # (n, s_pilot)
    W = C[pilot_idx, :]                               # (s_pilot, s_pilot)

    # Stable W^{-1/2} via eigendecomposition
    eigvals, eigvecs = np.linalg.eigh(W)
    eigvals = np.maximum(eigvals, 1e-10)
    W_inv_sqrt = eigvecs @ np.diag(1.0 / np.sqrt(eigvals)) @ eigvecs.T

    Z = C @ W_inv_sqrt                                # (n, s_pilot)

    # (Z^T Z + lambda I)^{-1}
    ZTZ_reg = Z.T @ Z + lam * np.eye(s_pilot)
    ZTZ_inv = np.linalg.inv(ZTZ_reg)

    # leverage_i = z_i^T (Z^T Z + lambda I)^{-1} z_i
    ZM = Z @ ZTZ_inv                                  # (n, s_pilot)
    leverage_scores = np.sum(ZM * Z, axis=1)           # (n,)

    return leverage_scores


# ---------------------------------------------------------------------------
# Nystrom preconditioner
# ---------------------------------------------------------------------------

def build_nystrom_preconditioner(X, landmarks, sigma, lam):
    """Return a function that applies P^{-1} v using the Woodbury identity.

    P = C W^{-1} C^T + lambda I   (Nystrom + regularisation)
    P^{-1} v = (1/lambda) (v - C M^{-1} C^T v)
    where M = lambda W + C^T C.
    """
    s = len(landmarks)
    C = kernel_columns(X, landmarks, sigma)            # (n, s)
    W = C[landmarks, :]                                 # (s, s)

    # M = lambda * W + C^T C, regularised for Cholesky stability
    W_reg = W + 1e-10 * np.eye(s)
    M = lam * W_reg + C.T @ C
    M += 1e-10 * np.eye(s)

    try:
        L_M = cho_factor(M)
    except np.linalg.LinAlgError:
        L_M = cho_factor(M + 1e-6 * np.eye(s))

    def apply_precond(v):
        Ct_v = C.T @ v                                 # (s,)
        x = cho_solve(L_M, Ct_v)                        # (s,)
        return (v - C @ x) / lam

    return apply_precond


# ---------------------------------------------------------------------------
# Preconditioned conjugate gradient
# ---------------------------------------------------------------------------

def pcg(matvec_fn, b, precond_fn, max_iter, tol):
    """Preconditioned conjugate gradient for symmetric positive-definite A.

    Returns (x, residual_history) where residual_history[k] = ||r_k||/||b||.
    """
    x = np.zeros_like(b)
    r = b.copy()
    z = precond_fn(r)
    p = z.copy()
    rz = np.dot(r, z)

    b_norm = np.linalg.norm(b)
    residuals = [np.linalg.norm(r) / b_norm]

    for k in range(max_iter):
        Ap = matvec_fn(p)
        pAp = np.dot(p, Ap)
        if pAp <= 0:
            break
        alpha_k = rz / pAp
        x = x + alpha_k * p
        r = r - alpha_k * Ap

        rel_res = np.linalg.norm(r) / b_norm
        residuals.append(rel_res)

        if rel_res < tol:
            break

        z = precond_fn(r)
        rz_new = np.dot(r, z)
        beta = rz_new / max(abs(rz), 1e-30)
        p = z + beta * p
        rz = rz_new

    return x, np.array(residuals)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    X = np.load('/app/data/X.npy')
    y = np.load('/app/data/y.npy')
    with open('/app/data/config.json') as f:
        config = json.load(f)

    sigma = config['sigma']
    lam = config['lambda']
    max_iter = config['max_cg_iterations']
    tol = config['residual_tolerance']
    n = config['n']

    # 1. Leverage score estimation
    print("Estimating ridge leverage scores via pilot Nystrom sketch ...")
    lev_scores = estimate_ridge_leverage_scores(X, sigma, lam, s_pilot=250)

    # Normalise to sampling probabilities
    probs = np.maximum(lev_scores, 1e-12)
    probs /= probs.sum()

    # 2. Landmark selection
    s = 400
    rng = np.random.RandomState(99)
    landmarks = rng.choice(n, s, replace=False, p=probs)
    landmarks = np.sort(landmarks)
    print(f"Selected {len(landmarks)} landmarks")

    # 3. Preconditioner
    print("Building Nystrom preconditioner ...")
    precond = build_nystrom_preconditioner(X, landmarks, sigma, lam)

    # 4. PCG solve
    print("Running preconditioned conjugate gradient ...")
    mv = lambda v: kernel_matvec(X, v, sigma, lam)
    alpha, res_hist = pcg(mv, y, precond, max_iter, tol)

    num_iter = len(res_hist) - 1
    print(f"Converged in {num_iter} iterations")
    print(f"Final relative residual: {res_hist[-1]:.2e}")

    # 5. Save outputs
    os.makedirs('/app/output', exist_ok=True)
    np.save('/app/output/alpha.npy', alpha)
    np.save('/app/output/landmarks.npy', landmarks)
    np.save('/app/output/residual_history.npy', res_hist)
    with open('/app/output/num_iterations.txt', 'w') as f:
        f.write(str(num_iter))

    print("Done.")


if __name__ == '__main__':
    main()
