"""
Coherent Point Drift (CPD) rigid registration with scale and outlier handling.
Reads point clouds from HDF5 files using h5py.

Implements the EM algorithm from:
  Myronenko & Song, "Point Set Registration: Coherent Point Drift",
  IEEE TPAMI, 2010.

Convention: T(y) = s * R @ y + t  maps source centroids Y toward target data X.
"""
import json

import h5py
import numpy as np
from scipy.spatial.distance import cdist


def cpd_rigid(X, Y, w=0.3, max_iter=200, tol=1e-8):
    """
    CPD rigid+scale registration.

    Parameters
    ----------
    X : ndarray, shape (N, D)
        Target / observed data points.
    Y : ndarray, shape (M, D)
        Source / GMM centroids (to be transformed).
    w : float
        Prior weight of the uniform outlier component (0 < w < 1).
    max_iter : int
        Maximum EM iterations.
    tol : float
        Relative log-likelihood convergence threshold.

    Returns
    -------
    R : ndarray (D, D) — rotation matrix
    t : ndarray (D,)   — translation vector
    s : float          — uniform scale factor
    """
    N, D = X.shape
    M = Y.shape[0]

    # Initialise transformation parameters
    R = np.eye(D)
    t = np.zeros(D)
    s = 1.0

    # Initialise sigma^2 as the mean pairwise squared distance / D
    sigma2 = np.sum(cdist(X, Y, "sqeuclidean")) / (D * N * M)

    q_prev = -np.inf

    for _it in range(max_iter):
        # --- E-step -----------------------------------------------------------
        TY = s * (Y @ R.T) + t                          # M x D
        dist2 = cdist(TY, X, "sqeuclidean")              # M x N

        P = np.exp(-dist2 / (2.0 * sigma2))              # M x N
        c = ((2.0 * np.pi * sigma2) ** (D / 2.0)
             * w / (1.0 - w) * M / N)
        denom = P.sum(axis=0, keepdims=True) + c          # 1 x N
        P /= denom                                        # M x N

        # Sufficient statistics
        P1 = P.sum(axis=1)         # M — row sums
        Pt1 = P.sum(axis=0)        # N — col sums
        Np = P1.sum()              # scalar

        # --- M-step -----------------------------------------------------------
        mu_x = (X.T @ Pt1) / Np                           # D
        mu_y = (Y.T @ P1) / Np                            # D

        # Cross-covariance  D x D
        A = X.T @ P.T @ Y - Np * np.outer(mu_x, mu_y)

        # Optimal rotation via SVD
        U, _S, Vt = np.linalg.svd(A)
        C = np.eye(D)
        C[-1, -1] = np.linalg.det(U @ Vt)
        R = U @ C @ Vt

        # Optimal scale
        trAR = np.trace(A.T @ R)
        Y_c = Y - mu_y
        trYPY = np.sum(P1 * np.sum(Y_c ** 2, axis=1))
        s = trAR / trYPY

        # Optimal translation
        t = mu_x - s * R @ mu_y

        # Optimal variance
        X_c = X - mu_x
        trXPX = np.sum(Pt1 * np.sum(X_c ** 2, axis=1))
        sigma2 = (trXPX - s * trAR) / (Np * D)
        sigma2 = max(sigma2, 1e-12)

        # Convergence
        q = -(trXPX - s * trAR) / (2.0 * sigma2) - Np * D / 2.0 * np.log(sigma2)
        if abs(q - q_prev) < tol * abs(q) and _it > 5:
            break
        q_prev = q

    return R, t, s


def main():
    # Read point clouds from HDF5 files
    with h5py.File("/app/data/source.h5", "r") as f:
        source = f["/pointcloud/xyz"][:]
    with h5py.File("/app/data/target.h5", "r") as f:
        target = f["/pointcloud/xyz"][:]

    # Y = source (GMM centroids), X = target (observations)
    R, t, s = cpd_rigid(target, source, w=0.3, max_iter=200, tol=1e-8)

    result = {
        "rotation_matrix": R.tolist(),
        "translation": t.tolist(),
        "scale": float(s),
    }

    with open("/app/result.json", "w") as f:
        json.dump(result, f, indent=2)


if __name__ == "__main__":
    main()
