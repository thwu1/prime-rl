#!/usr/bin/env python3
"""
GICP (Generalized Iterative Closest Point) registration with degeneracy analysis.

Implements the full pipeline from scratch using only numpy and scipy:
  1. Voxel-grid downsampling
  2. KD-tree nearest-neighbor search (scipy.spatial.cKDTree)
  3. Per-point covariance estimation from k-NN
  4. Gauss-Newton optimisation on SE(3)  (left perturbation model)
  5. Hessian eigenvalue analysis for degeneracy detection
"""

import json
import os
import sys

import numpy as np
from scipy.spatial import cKDTree

# ── Lie-group helpers ────────────────────────────────────────────────────────


def skew(v):
    """3×3 skew-symmetric matrix of a 3-vector."""
    return np.array([[0, -v[2], v[1]],
                     [v[2], 0, -v[0]],
                     [-v[1], v[0], 0]], dtype=np.float64)


def exp_se3(xi):
    """Exponential map  se(3) → SE(3).

    xi = [omega_x, omega_y, omega_z, v_x, v_y, v_z]
    Uses Rodrigues + the closed-form V matrix for the translation part.
    """
    omega = xi[:3]
    v = xi[3:]
    theta = np.linalg.norm(omega)

    T = np.eye(4)
    if theta < 1e-10:
        T[:3, 3] = v
        return T

    a = omega / theta
    K = skew(a)
    K2 = K @ K

    sin_t = np.sin(theta)
    cos_t = np.cos(theta)

    R = np.eye(3) + sin_t * K + (1 - cos_t) * K2
    V = np.eye(3) + ((1 - cos_t) / theta) * K + (1 - sin_t / theta) * K2
    T[:3, :3] = R
    T[:3, 3] = V @ v
    return T


# ── Pre-processing ───────────────────────────────────────────────────────────


def voxel_downsample(pts, res):
    """Average points falling in the same voxel cell."""
    keys = np.floor(pts / res).astype(np.int64)
    voxels = {}
    for i in range(len(keys)):
        k = (keys[i, 0], keys[i, 1], keys[i, 2])
        if k in voxels:
            voxels[k].append(i)
        else:
            voxels[k] = [i]
    return np.array([pts[idx].mean(axis=0) for idx in voxels.values()])


def estimate_covariances(pts, tree, k=20):
    """Estimate per-point 3×3 covariance from k nearest neighbours."""
    _, indices = tree.query(pts, k=k)
    n = len(pts)
    covs = np.empty((n, 3, 3))
    for i in range(n):
        nbrs = pts[indices[i]]
        c = nbrs - nbrs.mean(0)
        cov = (c.T @ c) / k
        # Regularise: floor eigenvalues at 1e-4 × max eigenvalue
        w, vecs = np.linalg.eigh(cov)
        w = np.maximum(w, max(1e-4 * w.max(), 1e-12))
        covs[i] = vecs @ np.diag(w) @ vecs.T
    return covs


# ── GICP core ────────────────────────────────────────────────────────────────


def _gicp_inner(tgt, src, tgt_tree, tgt_covs, src_covs,
                T_init, max_iter, max_corr_dist, convergence_eps):
    """Single-resolution GICP optimisation loop."""
    T = T_init.copy()
    H_last = np.zeros((6, 6))

    for it in range(max_iter):
        R = T[:3, :3]
        t = T[:3, 3]

        # Transform source points with current T
        src_t = src @ R.T + t

        # Nearest-neighbour correspondences
        dists, corr_idx = tgt_tree.query(src_t)
        mask = dists < max_corr_dist
        n_corr = mask.sum()
        if n_corr < 10:
            break

        # Build Gauss-Newton system
        H = np.zeros((6, 6))
        g = np.zeros(6)

        active = np.where(mask)[0]
        for i in active:
            j = corr_idx[i]
            q = src_t[i]        # transformed source point
            p = tgt[j]          # corresponding target point
            r = p - q           # residual

            # Combined covariance and information matrix
            C = tgt_covs[j] + R @ src_covs[i] @ R.T
            try:
                Omega = np.linalg.inv(C)
            except np.linalg.LinAlgError:
                continue

            # Jacobian  de/d(xi)  where xi = [omega(3), v(3)]
            #   de/d(omega) =  [q]_×      (3×3)
            #   de/d(v)     = −I           (3×3)
            J = np.empty((3, 6))
            J[:, :3] = skew(q)
            J[:, 3:] = -np.eye(3)

            JtO = J.T @ Omega          # 6×3
            H += JtO @ J               # 6×6
            g += JtO @ r               # 6

        # Gauss-Newton update:  H δ = −g
        try:
            delta = np.linalg.solve(H, -g)
        except np.linalg.LinAlgError:
            delta = np.linalg.lstsq(H, -g, rcond=None)[0]

        T = exp_se3(delta) @ T
        H_last = H

        if np.linalg.norm(delta) < convergence_eps:
            break

    return T, H_last


def gicp_register(target, source, *,
                  max_iter=64,
                  max_corr_dist=2.0,
                  ds_res=0.25,
                  k_nn=20,
                  convergence_eps=1e-6):
    """Run GICP registration with coarse-to-fine, return (T, Hessian_6x6)."""

    # ── Coarse pass (2× resolution) to get a good initial guess ──
    ds_coarse = ds_res * 2.0
    tgt_c = voxel_downsample(target, ds_coarse)
    src_c = voxel_downsample(source, ds_coarse)
    tgt_tree_c = cKDTree(tgt_c)
    src_tree_c = cKDTree(src_c)
    tgt_covs_c = estimate_covariances(tgt_c, tgt_tree_c, k=min(k_nn, len(tgt_c) - 1))
    src_covs_c = estimate_covariances(src_c, src_tree_c, k=min(k_nn, len(src_c) - 1))

    T_coarse, _ = _gicp_inner(tgt_c, src_c, tgt_tree_c, tgt_covs_c, src_covs_c,
                              np.eye(4), max_iter=30,
                              max_corr_dist=max_corr_dist * 1.5,
                              convergence_eps=convergence_eps * 10)

    # ── Fine pass ──
    tgt = voxel_downsample(target, ds_res)
    src = voxel_downsample(source, ds_res)
    tgt_tree = cKDTree(tgt)
    src_tree = cKDTree(src)
    tgt_covs = estimate_covariances(tgt, tgt_tree, k=min(k_nn, len(tgt) - 1))
    src_covs = estimate_covariances(src, src_tree, k=min(k_nn, len(src) - 1))

    T, H = _gicp_inner(tgt, src, tgt_tree, tgt_covs, src_covs,
                       T_coarse, max_iter=max_iter,
                       max_corr_dist=max_corr_dist,
                       convergence_eps=convergence_eps)

    return T, H


def analyse_degeneracy(H, threshold=0.01):
    """Return (sorted_eigenvalues, is_degenerate)."""
    eigvals = np.linalg.eigvalsh(H)
    eigvals_sorted = np.sort(eigvals)
    if eigvals_sorted[-1] > 0:
        ratio = eigvals_sorted[0] / eigvals_sorted[-1]
    else:
        ratio = 0.0
    return eigvals_sorted, ratio < threshold


# ── Main ─────────────────────────────────────────────────────────────────────


def process_scenario(sc_dir, res_dir):
    target = np.loadtxt(os.path.join(sc_dir, "target.txt"))
    source = np.loadtxt(os.path.join(sc_dir, "source.txt"))

    with open(os.path.join(sc_dir, "info.json")) as f:
        info = json.load(f)

    has_outliers = info.get("has_outliers", False)
    md = 1.5 if has_outliers else 2.0
    dsr = 0.3 if has_outliers else 0.25

    T_est, H = gicp_register(target, source,
                              max_corr_dist=md, ds_res=dsr)

    eigvals, is_deg = analyse_degeneracy(H)

    os.makedirs(res_dir, exist_ok=True)
    np.savetxt(os.path.join(res_dir, "transform.txt"), T_est, fmt="%.10f")
    np.savetxt(os.path.join(res_dir, "hessian_eigenvalues.txt"), eigvals, fmt="%.10f")
    with open(os.path.join(res_dir, "is_degenerate.txt"), "w") as f:
        f.write("true" if is_deg else "false")

    print(f"  {info['name']:25s}  deg={str(is_deg):5s}  "
          f"eigval=[{eigvals[0]:.4e} .. {eigvals[-1]:.4e}]  "
          f"ratio={eigvals[0]/max(eigvals[-1],1e-10):.4e}")


def main():
    data_dir = "/app/data"
    results_dir = "/app/results"

    with open(os.path.join(data_dir, "scenarios.json")) as f:
        scenarios = json.load(f)["scenarios"]

    print("GICP registration — processing scenarios")
    for sc in scenarios:
        process_scenario(os.path.join(data_dir, sc),
                         os.path.join(results_dir, sc))
    print("Done.")


if __name__ == "__main__":
    main()
