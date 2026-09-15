#!/usr/bin/env python3
"""
Coherent Point Drift (CPD) rigid registration with scale.

Reads scan data from SQLite, parses TOML config, writes results to SQLite.

Reference: Myronenko & Song, "Point Set Registration: Coherent Point Drift",
IEEE TPAMI 32(12), 2010.
"""

import sqlite3
import tomllib

import numpy as np
from scipy.linalg import svd


# ── SQLite I/O ────────────────────────────────────────────────────────────


def load_scan_names(conn):
    """Get all scan names from the database."""
    c = conn.cursor()
    c.execute("SELECT name FROM scans ORDER BY id")
    return [row[0] for row in c.fetchall()]


def load_points(conn, scan_name, table):
    """Load point cloud from a SQLite table for a given scan via JOIN."""
    c = conn.cursor()
    c.execute(
        f"SELECT p.x, p.y, p.z FROM {table} p "
        "JOIN scans s ON p.scan_id = s.id "
        "WHERE s.name = ? ORDER BY p.point_idx",
        (scan_name,),
    )
    return np.array(c.fetchall(), dtype=np.float64)


# ── CPD rigid + scale ────────────────────────────────────────────────────


def cpd_rigid(X, Y, w=0.3, max_iter=300, tol=1e-8, estimate_scale=True):
    """
    Align Y (source / GMM centroids) to X (target / data).

    Returns (R, t, s) with  T(Y) = s·R·Y + t  ≈ X.
    """
    N, D = X.shape
    M = Y.shape[0]

    R = np.eye(D)
    t = np.zeros(D)
    s = 1.0

    # Initial noise variance: mean squared inter-set distance
    diff = X[None, :, :] - Y[:, None, :]          # M×N×D
    sigma2 = np.sum(diff ** 2) / (D * M * N)

    prev_ll = -np.inf

    for _ in range(max_iter):
        # ── E-step: compute responsibilities P  (M×N) ──────────────────
        TY = s * (Y @ R.T) + t                     # M×D

        dist2 = np.sum(
            (X[None, :, :] - TY[:, None, :]) ** 2,
            axis=2,
        )                                           # M×N

        log_p = -dist2 / (2.0 * sigma2)
        log_c = (
            (D / 2.0) * np.log(2.0 * np.pi * sigma2)
            + np.log(w / (1.0 - w + 1e-15))
            + np.log(float(M) / N)
        )

        # Log-sum-exp per data point (column)
        col_max = np.maximum(np.max(log_p, axis=0), log_c)     # N
        log_denom = col_max + np.log(
            np.sum(np.exp(log_p - col_max[None, :]), axis=0)
            + np.exp(log_c - col_max)
        )

        P = np.exp(log_p - log_denom[None, :])                 # M×N

        # ── Sufficient statistics ──────────────────────────────────────
        P1 = P.sum(axis=1)          # M   (row sums)
        Pt1 = P.sum(axis=0)         # N   (col sums)
        Np = P1.sum()

        if Np < 1e-10:
            break

        mu_x = (X.T @ Pt1) / Np                                # D
        mu_y = (Y.T @ P1) / Np                                 # D

        # Cross-covariance  A = X^T P^T Y  -  Np·μ_x·μ_y^T    (D×D)
        A = X.T @ (P.T @ Y) - Np * mu_x[:, None] * mu_y[None, :]

        # ── M-step ─────────────────────────────────────────────────────
        U, _, Vt = svd(A)
        C = np.eye(D)
        C[-1, -1] = np.linalg.det(U @ Vt)          # prevent reflection
        R = U @ C @ Vt

        trAR = np.sum(A * R)                        # tr(A^T R)
        trYPY = np.sum(P1 * np.sum(Y ** 2, axis=1))  # tr(Y^T diag(P1) Y)
        denom_s = trYPY - Np * np.dot(mu_y, mu_y)

        if estimate_scale and abs(denom_s) > 1e-12:
            s = trAR / denom_s
        else:
            s = 1.0

        t = mu_x - s * (R @ mu_y)

        trXPtX = np.sum(Pt1 * np.sum(X ** 2, axis=1))
        sigma2_new = (
            trXPtX - Np * np.dot(mu_x, mu_x) - s * trAR
        ) / (Np * D)
        sigma2 = max(sigma2_new, 1e-12)

        # ── Convergence ───────────────────────────────────────────────
        ll = -0.5 * Np * D * np.log(sigma2)
        if abs(ll - prev_ll) < tol:
            break
        prev_ll = ll

    return R, t, s


# ── Main ──────────────────────────────────────────────────────────────────


def main():
    # ── Parse TOML configuration ──────────────────────────────────────
    with open("/app/pipeline.toml", "rb") as f:
        config = tomllib.load(f)

    input_db = config["pipeline"]["input_db"]
    output_db = config["pipeline"]["output_db"]
    reg_cfg = config["registration"]
    max_iter = reg_cfg["max_iterations"]
    tol = reg_cfg["convergence_tol"]
    estimate_scale = reg_cfg["estimate_scale"]
    outlier_weights = config["outlier_weights"]

    # ── Read scan data from SQLite ────────────────────────────────────
    conn_in = sqlite3.connect(input_db)
    scan_names = load_scan_names(conn_in)

    # ── Create output SQLite database ─────────────────────────────────
    conn_out = sqlite3.connect(output_db)
    cout = conn_out.cursor()
    cout.execute(
        "CREATE TABLE IF NOT EXISTS transformations ("
        "scenario TEXT PRIMARY KEY, "
        "r11 REAL NOT NULL, r12 REAL NOT NULL, r13 REAL NOT NULL, "
        "r21 REAL NOT NULL, r22 REAL NOT NULL, r23 REAL NOT NULL, "
        "r31 REAL NOT NULL, r32 REAL NOT NULL, r33 REAL NOT NULL, "
        "tx REAL NOT NULL, ty REAL NOT NULL, tz REAL NOT NULL, "
        "scale REAL NOT NULL)"
    )

    # ── Register each scenario ────────────────────────────────────────
    for name in scan_names:
        source = load_points(conn_in, name, "source_points")
        target = load_points(conn_in, name, "target_points")
        w = outlier_weights.get(name, 0.3)

        # X = data (target), Y = template (source)
        R, t, s = cpd_rigid(
            target, source,
            w=w, max_iter=max_iter, tol=tol,
            estimate_scale=estimate_scale,
        )

        cout.execute(
            "INSERT OR REPLACE INTO transformations "
            "(scenario, r11, r12, r13, r21, r22, r23, "
            "r31, r32, r33, tx, ty, tz, scale) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (name,
             R[0, 0], R[0, 1], R[0, 2],
             R[1, 0], R[1, 1], R[1, 2],
             R[2, 0], R[2, 1], R[2, 2],
             t[0], t[1], t[2], float(s)),
        )

        det_R = np.linalg.det(R)
        print(f"{name}: s={s:.6f}  det(R)={det_R:.6f}  t={t.round(4).tolist()}")

    conn_out.commit()
    conn_out.close()
    conn_in.close()
    print("Registration complete!")


if __name__ == "__main__":
    main()
