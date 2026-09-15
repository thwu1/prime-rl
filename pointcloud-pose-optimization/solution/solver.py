#!/usr/bin/env python3
"""Multi-scan point cloud alignment solver."""

import numpy as np
from scipy.spatial import KDTree
import h5py
import os


# ---------------------------------------------------------------------------
# SE(3) Lie group utilities
# ---------------------------------------------------------------------------

def skew(v):
    """3-vector -> 3x3 skew-symmetric matrix."""
    return np.array([
        [0.0, -v[2], v[1]],
        [v[2], 0.0, -v[0]],
        [-v[1], v[0], 0.0],
    ])


def se3_exp(twist):
    """Exponential map  se(3) -> SE(3).

    twist = [omega (3), v (3)]
    """
    omega = twist[:3]
    v = twist[3:]
    theta = np.linalg.norm(omega)

    if theta < 1e-10:
        T = np.eye(4)
        T[:3, 3] = v
        return T

    omega_hat = skew(omega)
    omega_hat_sq = omega_hat @ omega_hat
    th2 = theta * theta
    th3 = th2 * theta

    A = np.sin(theta) / theta
    B = (1.0 - np.cos(theta)) / th2
    C = (theta - np.sin(theta)) / th3

    R = np.eye(3) + A * omega_hat + B * omega_hat_sq
    V = np.eye(3) + B * omega_hat + C * omega_hat_sq

    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = V @ v
    return T


def se3_log(T):
    """Logarithmic map  SE(3) -> se(3).

    Returns twist = [omega (3), v (3)].
    """
    R = T[:3, :3]
    t = T[:3, 3]

    cos_theta = np.clip((np.trace(R) - 1.0) / 2.0, -1.0, 1.0)
    theta = np.arccos(cos_theta)

    if theta < 1e-10:
        return np.concatenate([np.zeros(3), t])

    ln_R = theta / (2.0 * np.sin(theta)) * (R - R.T)
    omega = np.array([ln_R[2, 1], ln_R[0, 2], ln_R[1, 0]])

    omega_hat = skew(omega)
    omega_hat_sq = omega_hat @ omega_hat
    th2 = theta * theta
    th3 = th2 * theta
    B = (1.0 - np.cos(theta)) / th2
    C = (theta - np.sin(theta)) / th3
    V = np.eye(3) + B * omega_hat + C * omega_hat_sq
    v = np.linalg.solve(V, t)

    return np.concatenate([omega, v])


# ---------------------------------------------------------------------------
# Normal estimation
# ---------------------------------------------------------------------------

def estimate_normals(points, k=20):
    """Estimate surface normals via local PCA on k nearest neighbours."""
    tree = KDTree(points)
    _, indices = tree.query(points, k=k)
    normals = np.zeros_like(points)
    for i in range(len(points)):
        nbrs = points[indices[i]]
        cov = np.cov(nbrs.T)
        evals, evecs = np.linalg.eigh(cov)
        normals[i] = evecs[:, 0]
    return normals


# ---------------------------------------------------------------------------
# Point-to-plane ICP
# ---------------------------------------------------------------------------

def icp(source, target, target_normals, init_T,
        max_iter=60, tol=1e-7, max_corr_dist=2.0):
    """Point-to-plane ICP registration.

    Finds T such that  target ~ T @ source.
    """
    T = init_T.copy()
    tree = KDTree(target)

    for _ in range(max_iter):
        src_t = (T[:3, :3] @ source.T + T[:3, 3:4]).T

        dists, indices = tree.query(src_t)
        mask = dists < max_corr_dist
        if np.sum(mask) < 30:
            break

        p = src_t[mask]
        q = target[indices[mask]]
        n = target_normals[indices[mask]]

        cross = np.cross(p, n)
        A = np.column_stack([cross, n])
        b = -np.sum((p - q) * n, axis=1)

        x, _, _, _ = np.linalg.lstsq(A, b, rcond=None)
        r = x[:3]
        dt = x[3:]

        theta = np.linalg.norm(r)
        if theta < 1e-10:
            R_delta = np.eye(3)
        else:
            K = skew(r / theta)
            R_delta = (np.eye(3) + np.sin(theta) * K
                       + (1.0 - np.cos(theta)) * (K @ K))

        T_delta = np.eye(4)
        T_delta[:3, :3] = R_delta
        T_delta[:3, 3] = dt
        T = T_delta @ T

        if np.linalg.norm(x) < tol:
            break

    return T


# ---------------------------------------------------------------------------
# Pose graph optimisation (Gauss-Newton on SE(3))
# ---------------------------------------------------------------------------

def pose_graph_optimize(poses, edges, measurements, num_iterations=50):
    """Gauss-Newton optimisation of a pose graph.

    Pose 0 is held fixed (anchor).
    """
    n = len(poses)
    current = [p.copy() for p in poses]

    for _it in range(num_iterations):
        dim = 6 * (n - 1)
        H = np.zeros((dim, dim))
        b = np.zeros(dim)

        for (i, j), Z_ij in zip(edges, measurements):
            T_ij_pred = np.linalg.inv(current[i]) @ current[j]
            e = se3_log(np.linalg.inv(Z_ij) @ T_ij_pred)

            eps = 1e-7
            Ji = np.zeros((6, 6))
            Jj = np.zeros((6, 6))

            for k in range(6):
                delta = np.zeros(6)
                delta[k] = eps

                Ti_p = se3_exp(delta) @ current[i]
                T_ij_p = np.linalg.inv(Ti_p) @ current[j]
                Ji[:, k] = (se3_log(np.linalg.inv(Z_ij) @ T_ij_p) - e) / eps

                Tj_p = se3_exp(delta) @ current[j]
                T_ij_p = np.linalg.inv(current[i]) @ Tj_p
                Jj[:, k] = (se3_log(np.linalg.inv(Z_ij) @ T_ij_p) - e) / eps

            if i > 0:
                ii = (i - 1) * 6
                H[ii:ii + 6, ii:ii + 6] += Ji.T @ Ji
                b[ii:ii + 6] += Ji.T @ e
            if j > 0:
                jj = (j - 1) * 6
                H[jj:jj + 6, jj:jj + 6] += Jj.T @ Jj
                b[jj:jj + 6] += Jj.T @ e
            if i > 0 and j > 0:
                ii = (i - 1) * 6
                jj = (j - 1) * 6
                H[ii:ii + 6, jj:jj + 6] += Ji.T @ Jj
                H[jj:jj + 6, ii:ii + 6] += Jj.T @ Ji

        damping = 1e-6
        H_damped = H + damping * np.eye(dim)
        try:
            dx = np.linalg.solve(H_damped, -b)
        except np.linalg.LinAlgError:
            break

        max_step = 0.0
        for idx in range(1, n):
            off = (idx - 1) * 6
            step = dx[off:off + 6]
            current[idx] = se3_exp(step) @ current[idx]
            max_step = max(max_step, np.linalg.norm(step))

        if max_step < 1e-8:
            break

    return current


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main():
    # Read data from HDF5
    with h5py.File('/app/data/scans.h5', 'r') as f:
        scans = []
        for i in range(8):
            scans.append(f['/scans/scan_{:03d}'.format(i)][:])
        init_poses = f['/initial_poses'][:]
        raw_pairs = f['/overlap_pairs'][:]
        pairs = [(int(p[0]), int(p[1])) for p in raw_pairs]

    # Estimate normals for each scan
    scan_normals = []
    for scan in scans:
        scan_normals.append(estimate_normals(scan, k=20))

    # Pairwise registration
    measurements = []
    for i, j in pairs:
        T_init = np.linalg.inv(init_poses[i]) @ init_poses[j]
        T_ij = icp(scans[j], scans[i], scan_normals[i], T_init,
                    max_iter=80, max_corr_dist=2.0)
        measurements.append(T_ij)

    # Pose graph optimisation
    current_poses = [init_poses[k].copy() for k in range(8)]
    optimised = pose_graph_optimize(current_poses, pairs, measurements,
                                    num_iterations=50)

    # Write output HDF5
    os.makedirs('/app/output', exist_ok=True)
    with h5py.File('/app/output/result.h5', 'w') as f:
        ds = f.create_dataset('poses', data=np.array(optimised),
                              dtype='float64')
        ds.attrs['reference_scan'] = 0


if __name__ == '__main__':
    main()
