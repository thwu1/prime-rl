#!/usr/bin/env python3
"""Point cloud registration pipeline.

Aligns multiple scans to a common reference frame using
Gaussian mixture model fitting.

Previous engineer's attempt -- runs without errors but
produces geometrically incorrect transforms.

"""
import json
import os

import h5py
import numpy as np
from scipy.spatial.distance import cdist


def gmm_register(source, target, max_iter=30, tol=1e-5):
    """Register source points to target using GMM-based alignment.

    Returns rotation R, translation t, and scale s such that
    s * R @ source + t approximates target.
    """
    M, D = source.shape
    N = target.shape[0]

    R = np.eye(D)
    t = np.zeros(D)
    s = 1.0
    sigma2 = np.sum(cdist(source, target, "sqeuclidean")) / (D * M * N)

    for iteration in range(max_iter):
        old_sigma2 = sigma2

        # Transform source with current parameters
        transformed = s * (source @ R.T) + t

        # Compute squared distances between all pairs
        dist2 = cdist(transformed, target, "sqeuclidean")

        # Posterior probabilities (E-step)
        P = np.exp(-dist2 / (2.0 * sigma2))
        denominator = P.sum(axis=0, keepdims=True) + 1e-10
        P = P / denominator

        # Sufficient statistics
        P1 = P.sum(axis=1)
        Pt1 = P.sum(axis=0)
        Np = P1.sum()

        mu_x = (target.T @ Pt1) / Np
        mu_y = (source.T @ P1) / Np

        A = (P @ target).T @ source - Np * np.outer(mu_x, mu_y)

        # SVD for rotation (M-step)
        U, _, Vt = np.linalg.svd(A)
        C = np.eye(D)
        C[-1, -1] = np.linalg.det(U @ Vt)
        R = U @ C @ Vt

        # Scale and translation update
        Y_centered = source - mu_y
        s = np.trace(A.T @ R) / np.sum(P1[:, None] * Y_centered ** 2)
        t = mu_x - s * (R @ mu_y)

        # Variance update
        X_centered = target - mu_x
        sigma2 = (np.sum(Pt1[:, None] * X_centered ** 2)
                  - s * np.trace(A.T @ R)) / (Np * D)
        sigma2 = max(sigma2, 1e-12)

        if abs(sigma2 - old_sigma2) / max(abs(old_sigma2), 1e-12) < tol:
            break

    return R, t, s


def main():
    os.makedirs("/app/output", exist_ok=True)

    with h5py.File("/app/data/scans.h5", "r") as f:
        scans = []
        for i in range(int(f.attrs['num_scans'])):
            pts = f[f"scan_{i}/points"][:]
            scans.append(pts)

    reference = scans[0]
    results = {}

    for i in range(1, len(scans)):
        print(f"Registering scan_{i} -> scan_0 ...")
        R, t, s = gmm_register(scans[i], reference)

        T = np.eye(4)
        T[:3, :3] = R
        T[:3, 3] = t
        results[f"T_{i}"] = T.tolist()
        print(f"  scale={s:.5f}")

    with open("/app/output/transforms.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Registration complete. Output: /app/output/transforms.json")


if __name__ == "__main__":
    main()
