#!/usr/bin/env python3
"""
Corrected rigid Coherent Point Drift (CPD) registration pipeline.

Fixes three deficiencies in /app/pipeline/attempt.py:
  1. Adds uniform outlier distribution component to the E-step, making
     the algorithm robust to outlier points in the scans.
  2. Increases maximum iterations from 30 to 300 with tighter convergence
     tolerance, ensuring the EM algorithm fully converges.
  3. Includes the scale factor s in the final 4x4 transform composition
     (T[:3,:3] = s*R instead of T[:3,:3] = R).

Based on: Myronenko & Song (2010) "Point Set Registration: Coherent Point Drift"

"""

import json
import os

import h5py
import numpy as np
from scipy.spatial.distance import cdist


def cpd_rigid(Y, X, w=0.1, max_iter=300, tol=1e-7):
    """Rigid CPD: find (s, R, t) such that  s * R @ Y + t  approx  X.

    Parameters
    ----------
    Y : (M, D) source points (GMM centroids, to be transformed)
    X : (N, D) target points (data, held fixed)
    w : outlier weight in [0, 1)
    max_iter : maximum EM iterations
    tol : convergence tolerance on relative change of sigma squared

    Returns
    -------
    R : (D, D) rotation matrix
    t : (D,)   translation vector
    s : float  scale factor
    """
    M, D = Y.shape
    N = X.shape[0]

    R = np.eye(D)
    t = np.zeros(D)
    s = 1.0

    sigma2 = np.sum(cdist(Y, X, "sqeuclidean")) / (D * M * N)

    for it in range(max_iter):
        sigma2_old = sigma2

        # E-step: posterior responsibilities P(m | x_n)
        TY = s * (Y @ R.T) + t
        dist2 = cdist(TY, X, "sqeuclidean")

        # Outlier component: key fix for robustness
        c = ((2.0 * np.pi * sigma2) ** (D / 2.0)
             * w / (1.0 - w) * float(M) / float(N))

        P = np.exp(-dist2 / (2.0 * sigma2))
        denom = P.sum(axis=0, keepdims=True) + c
        P /= denom

        # Sufficient statistics
        P1 = P.sum(axis=1)
        Pt1 = P.sum(axis=0)
        Np = P1.sum()

        mu_x = (X.T @ Pt1) / Np
        mu_y = (Y.T @ P1) / Np

        PX = P @ X
        A = PX.T @ Y - Np * np.outer(mu_x, mu_y)

        # M-step: rotation via SVD
        U, _, Vt = np.linalg.svd(A)
        C = np.eye(D)
        C[-1, -1] = np.linalg.det(U @ Vt)
        R = U @ C @ Vt

        Y_c = Y - mu_y
        s = np.trace(A.T @ R) / np.sum(P1[:, None] * Y_c ** 2)

        t = mu_x - s * (R @ mu_y)

        X_c = X - mu_x
        sigma2 = (np.sum(Pt1[:, None] * X_c ** 2)
                  - s * np.trace(A.T @ R)) / (Np * D)
        sigma2 = max(sigma2, 1e-12)

        if abs(sigma2 - sigma2_old) / max(abs(sigma2_old), 1e-12) < tol:
            break

    return R, t, s


def main():
    os.makedirs("/app/output", exist_ok=True)

    with h5py.File("/app/data/scans.h5", "r") as f:
        scans = []
        for i in range(5):
            pts = f[f"scan_{i}/points"][:]
            scans.append(pts)

    reference = scans[0]
    results = {}

    for i in range(1, 5):
        R, t, s = cpd_rigid(scans[i], reference,
                            w=0.1, max_iter=300, tol=1e-8)

        T = np.eye(4)
        T[:3, :3] = s * R   # Include scale factor
        T[:3, 3] = t
        results[f"T_{i}"] = T.tolist()

    with open("/app/output/transforms.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Registration complete.")


if __name__ == "__main__":
    main()
