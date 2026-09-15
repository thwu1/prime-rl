#!/usr/bin/env python3
"""2D Pose-Graph SLAM optimizer with Graduated Non-Convexity (GNC).


Reads a G2O pose graph, optimizes using iterative nonlinear least squares
on the SE(2) manifold with Cauchy robust kernel and graduated non-convexity
schedule to handle outlier loop closure edges.
"""
import math
import os

try:
    import numpy as np
    from scipy.sparse import lil_matrix, csc_matrix
    from scipy.sparse.linalg import spsolve
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False


def normalize_angle(a):
    """Normalize angle to [-pi, pi)."""
    return (a + math.pi) % (2 * math.pi) - math.pi


def read_g2o(filename):
    """Parse a G2O file into vertices, edges, and fixed vertex set."""
    vertices = {}
    edges = []
    fixed = set()
    with open(filename, 'r') as f:
        for line in f:
            parts = line.strip().split()
            if not parts or parts[0].startswith('#'):
                continue
            if parts[0] == 'VERTEX_SE2':
                vid = int(parts[1])
                vertices[vid] = [float(parts[2]), float(parts[3]), float(parts[4])]
            elif parts[0] == 'EDGE_SE2':
                i, j = int(parts[1]), int(parts[2])
                meas = [float(parts[3]), float(parts[4]), float(parts[5])]
                iv = [float(x) for x in parts[6:12]]
                info = np.array([[iv[0], iv[1], iv[2]],
                                 [iv[1], iv[3], iv[4]],
                                 [iv[2], iv[4], iv[5]]]) if HAS_SCIPY else \
                       [[iv[0], iv[1], iv[2]],
                        [iv[1], iv[3], iv[4]],
                        [iv[2], iv[4], iv[5]]]
                edges.append((i, j, meas, info))
            elif parts[0] == 'FIX':
                fixed.add(int(parts[1]))
    return vertices, edges, fixed


def compute_error(xi, xj, measurement):
    """Compute SE(2) error between predicted and measured relative transform."""
    c = math.cos(xi[2])
    s = math.sin(xi[2])
    dx_w = xj[0] - xi[0]
    dy_w = xj[1] - xi[1]
    return [
        c * dx_w + s * dy_w - measurement[0],
        -s * dx_w + c * dy_w - measurement[1],
        normalize_angle(xj[2] - xi[2] - measurement[2])
    ]


def compute_jacobians(xi, xj):
    """Compute Jacobians of the SE(2) error w.r.t. xi and xj.

    Returns (A, B) where A = de/dxi (3x3) and B = de/dxj (3x3).
    """
    c = math.cos(xi[2])
    s = math.sin(xi[2])
    dx = xj[0] - xi[0]
    dy = xj[1] - xi[1]

    A = [[-c, -s, -s * dx + c * dy],
         [s, -c, -c * dx - s * dy],
         [0, 0, -1]]

    B = [[c, s, 0],
         [-s, c, 0],
         [0, 0, 1]]

    return A, B


# ---------- Pure Python linear algebra helpers ----------

def _mm3(A, B):
    return [[sum(A[i][k] * B[k][j] for k in range(3))
             for j in range(3)] for i in range(3)]

def _mT3(A):
    return [[A[j][i] for j in range(3)] for i in range(3)]

def _mv3(M, v):
    return [sum(M[i][j] * v[j] for j in range(3)) for i in range(3)]

def _d3(a, b):
    return sum(a[i] * b[i] for i in range(3))

def _gauss_solve(dim, H, b):
    """Solve Hx = -b via Gaussian elimination with partial pivoting."""
    aug = [H[i][:] + [-b[i]] for i in range(dim)]
    for col in range(dim):
        max_val, max_row = abs(aug[col][col]), col
        for row in range(col + 1, dim):
            if abs(aug[row][col]) > max_val:
                max_val = abs(aug[row][col])
                max_row = row
        if max_row != col:
            aug[col], aug[max_row] = aug[max_row], aug[col]
        pivot = aug[col][col]
        if abs(pivot) < 1e-15:
            continue
        for row in range(col + 1, dim):
            factor = aug[row][col] / pivot
            for j in range(col, dim + 1):
                aug[row][j] -= factor * aug[col][j]
    dx = [0.0] * dim
    for i in range(dim - 1, -1, -1):
        if abs(aug[i][i]) < 1e-15:
            continue
        s = aug[i][dim]
        for j in range(i + 1, dim):
            s -= aug[i][j] * dx[j]
        dx[i] = s / aug[i][i]
    return dx


# ---------- Scipy-based solver (preferred) ----------

def _optimize_scipy(vertices, edges, fixed, schedule):
    n = len(vertices)
    ids = sorted(vertices.keys())
    id_to_idx = {vid: i for i, vid in enumerate(ids)}
    dim = 3 * n

    x = np.zeros(dim)
    for vid in ids:
        i = id_to_idx[vid]
        x[3 * i:3 * i + 3] = vertices[vid]

    for cauchy_c, lam in schedule:
        H = lil_matrix((dim, dim))
        b = np.zeros(dim)
        chi2 = 0.0

        for (ei, ej, meas, info) in edges:
            ii, ij = id_to_idx[ei], id_to_idx[ej]
            xi = x[3 * ii:3 * ii + 3]
            xj = x[3 * ij:3 * ij + 3]

            e = np.array(compute_error(xi.tolist(), xj.tolist(), meas))
            A_list, B_list = compute_jacobians(xi.tolist(), xj.tolist())
            A = np.array(A_list)
            B = np.array(B_list)

            info_e = info @ e
            edge_chi2 = float(e @ info_e)
            chi2 += edge_chi2

            w = 1.0 / (1.0 + edge_chi2 / (cauchy_c ** 2)) if cauchy_c else 1.0
            w_info = w * info

            H_ii = A.T @ w_info @ A
            H_ij = A.T @ w_info @ B
            H_jj = B.T @ w_info @ B
            w_info_e = w_info @ e
            bi = A.T @ w_info_e
            bj = B.T @ w_info_e

            si, sj = 3 * ii, 3 * ij
            for r in range(3):
                for c in range(3):
                    H[si + r, si + c] += H_ii[r, c]
                    H[si + r, sj + c] += H_ij[r, c]
                    H[sj + r, si + c] += H_ij[c, r]
                    H[sj + r, sj + c] += H_jj[r, c]
                b[si + r] += bi[r]
                b[sj + r] += bj[r]

        for fid in fixed:
            idx = id_to_idx[fid]
            for k in range(3):
                H[3 * idx + k, 3 * idx + k] += 1e10

        for k in range(dim):
            H[k, k] += lam

        dx = spsolve(csc_matrix(H), -b)
        x += dx
        for vid in ids:
            i = id_to_idx[vid]
            x[3 * i + 2] = normalize_angle(x[3 * i + 2])

    result = {}
    for vid in ids:
        i = id_to_idx[vid]
        result[vid] = [float(x[3 * i]), float(x[3 * i + 1]), float(x[3 * i + 2])]
    return result


# ---------- Pure Python solver (fallback) ----------

def _optimize_pure(vertices, edges, fixed, schedule):
    n = len(vertices)
    ids = sorted(vertices.keys())
    id_to_idx = {vid: i for i, vid in enumerate(ids)}
    dim = 3 * n

    x = [0.0] * dim
    for vid in ids:
        i = id_to_idx[vid]
        x[3 * i], x[3 * i + 1], x[3 * i + 2] = vertices[vid]

    for cauchy_c, lam in schedule:
        H = [[0.0] * dim for _ in range(dim)]
        b = [0.0] * dim
        chi2 = 0.0

        for (ei, ej, meas, info) in edges:
            ii, ij = id_to_idx[ei], id_to_idx[ej]
            xi = [x[3 * ii], x[3 * ii + 1], x[3 * ii + 2]]
            xj = [x[3 * ij], x[3 * ij + 1], x[3 * ij + 2]]

            e = compute_error(xi, xj, meas)
            A, B = compute_jacobians(xi, xj)
            ie = _mv3(info, e)
            ec2 = _d3(e, ie)
            chi2 += ec2

            w = 1.0 / (1.0 + ec2 / (cauchy_c ** 2)) if cauchy_c else 1.0
            wi = [[w * info[r][c] for c in range(3)] for r in range(3)]
            AT, BT = _mT3(A), _mT3(B)
            Hii = _mm3(AT, _mm3(wi, A))
            Hij = _mm3(AT, _mm3(wi, B))
            Hjj = _mm3(BT, _mm3(wi, B))
            wie = _mv3(wi, e)
            bi, bj = _mv3(AT, wie), _mv3(BT, wie)

            si, sj = 3 * ii, 3 * ij
            for r in range(3):
                for c in range(3):
                    H[si + r][si + c] += Hii[r][c]
                    H[si + r][sj + c] += Hij[r][c]
                    H[sj + r][si + c] += Hij[c][r]
                    H[sj + r][sj + c] += Hjj[r][c]
                b[si + r] += bi[r]
                b[sj + r] += bj[r]

        for fid in fixed:
            idx = id_to_idx[fid]
            for k in range(3):
                H[3 * idx + k][3 * idx + k] += 1e10
        for k in range(dim):
            H[k][k] += lam

        dx = _gauss_solve(dim, H, b)
        for k in range(dim):
            x[k] += dx[k]
        for vid in ids:
            i = id_to_idx[vid]
            x[3 * i + 2] = normalize_angle(x[3 * i + 2])

    result = {}
    for vid in ids:
        i = id_to_idx[vid]
        result[vid] = [x[3 * i], x[3 * i + 1], x[3 * i + 2]]
    return result


def optimize_gnc(vertices, edges, fixed):
    """Optimize using Graduated Non-Convexity with Cauchy kernel."""
    # GNC schedule: (cauchy_c, lm_damping)
    # None means no robust kernel; start unweighted then tighten
    schedule = (
        [(None, 1.0)] * 5 +
        [(200, 0.1)] * 5 +
        [(100, 0.1)] * 5 +
        [(50, 0.1)] * 5 +
        [(20, 0.1)] * 10 +
        [(10, 0.1)] * 20 +
        [(5, 0.1)] * 20 +
        [(3, 0.1)] * 30
    )

    if HAS_SCIPY:
        return _optimize_scipy(vertices, edges, fixed, schedule)
    else:
        return _optimize_pure(vertices, edges, fixed, schedule)


def compute_chi2(xi, xj, meas, info):
    """Compute chi-squared for a single edge."""
    e = compute_error(xi, xj, meas)
    if HAS_SCIPY:
        e_np = np.array(e)
        return float(e_np @ info @ e_np)
    else:
        ie = _mv3(info, e)
        return _d3(e, ie)


def main():
    vertices, edges, fixed = read_g2o('/app/data/simulation.g2o')

    # Compute initial chi-squared
    init_chi2 = 0.0
    for (ei, ej, meas, info) in edges:
        init_chi2 += compute_chi2(vertices[ei], vertices[ej], meas, info)

    # Optimize
    optimized = optimize_gnc(vertices, edges, fixed)

    # Compute final per-edge residuals
    edge_residuals = []
    final_chi2 = 0.0
    for (ei, ej, meas, info) in edges:
        chi2 = compute_chi2(optimized[ei], optimized[ej], meas, info)
        edge_residuals.append((ei, ej, chi2))
        final_chi2 += chi2

    outlier_threshold = 1000.0
    outlier_edges = [(i, j, c) for i, j, c in edge_residuals if c > outlier_threshold]

    # Write outputs
    os.makedirs('/app/output', exist_ok=True)

    with open('/app/output/optimized_poses.txt', 'w') as f:
        for vid in sorted(optimized.keys()):
            p = optimized[vid]
            f.write(f"{vid} {p[0]:.6f} {p[1]:.6f} {p[2]:.6f}\n")

    with open('/app/output/edge_residuals.txt', 'w') as f:
        for (i, j, chi2) in edge_residuals:
            f.write(f"{i} {j} {chi2:.6f}\n")

    with open('/app/output/summary.txt', 'w') as f:
        f.write(f"initial_chi2: {init_chi2:.6f}\n")
        f.write(f"final_chi2: {final_chi2:.6f}\n")
        f.write(f"num_outliers: {len(outlier_edges)}\n")
        for i, j, c in outlier_edges:
            f.write(f"outlier: {i} {j} {c:.6f}\n")


if __name__ == '__main__':
    main()
