#!/usr/bin/env python3
"""EKF-based probabilistic ODE solver for the Lotka-Volterra system.

Implements the algorithm from /app/spec.md:
  - IWP(q) transition matrix and process noise covariance
  - EKF prediction/update with TS1 linearization
  - Dynamic MLE output scale calibration
"""


import json
import os
import sys
from math import factorial

import numpy as np

# Import the ODE problem definition
sys.path.insert(0, "/app")
from ode_problem import vector_field, jacobian, Y0, T0, T1


# ---------------------------------------------------------------------------
# IWP matrices
# ---------------------------------------------------------------------------

def iwp_transition(h, q):
    """Scalar (q+1)x(q+1) IWP transition matrix (upper triangular Pascal)."""
    n = q + 1
    A = np.zeros((n, n))
    for i in range(n):
        for j in range(i, n):
            A[i, j] = h ** (j - i) / factorial(j - i)
    return A


def iwp_process_noise(h, q):
    """Scalar (q+1)x(q+1) IWP process noise covariance (unit diffusion)."""
    n = q + 1
    Q = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            Q[i, j] = h ** (2 * q - i - j + 1) / (
                factorial(q - i) * factorial(q - j) * (2 * q - i - j + 1)
            )
    return Q


# ---------------------------------------------------------------------------
# Vector field / Jacobian wrappers (list -> numpy)
# ---------------------------------------------------------------------------

def vf_np(y):
    return np.asarray(vector_field(y), dtype=float)


def jac_np(y):
    J = jacobian(y)
    return np.array([[J[0][0], J[0][1]],
                     [J[1][0], J[1][1]]], dtype=float)


# ---------------------------------------------------------------------------
# EKF ODE Filter
# ---------------------------------------------------------------------------

def solve_probabilistic(y0, t0, t1, h, q, d):
    """Run the fixed-step EKF ODE filter with IWP(q) prior and TS1."""
    n = q + 1          # derivatives per component
    N = n * d          # total state dimension

    # --- Scalar IWP matrices ---
    A_scalar = iwp_transition(h, q)
    Q_scalar = iwp_process_noise(h, q)

    # --- Full-dimensional via Kronecker products ---
    A_full = np.kron(A_scalar, np.eye(d))
    Q_raw = np.kron(Q_scalar, np.eye(d))

    # --- Extraction matrices ---
    E0 = np.zeros((d, N))          # y   (derivative 0)
    E1 = np.zeros((d, N))          # y'  (derivative 1)
    for i in range(d):
        E0[i, i] = 1.0
        E1[i, d + i] = 1.0

    # --- Initialise state ---
    y0_np = np.asarray(y0, dtype=float)
    x = np.zeros(N)
    x[:d] = y0_np                  # y_0 known
    x[d:2 * d] = vf_np(y0_np)     # y'_0 = f(y_0) known
    # higher derivatives left at zero

    # --- Initialise covariance ---
    P = np.eye(N)
    P[:d, :d] *= 1e-10             # y_0 known tightly
    P[d:2 * d, d:2 * d] *= 1e-10  # y'_0 known tightly
    # remaining diagonal stays at 1.0 (unknown higher derivatives)

    # --- Dynamic output scale ---
    sigma_sq = 1.0

    # --- Storage ---
    chi_sq_values = []
    num_steps = int(round((t1 - t0) / h))

    I_N = np.eye(N)

    for k in range(num_steps):
        # ---- Predict ----
        x_pred = A_full @ x
        P_pred = A_full @ P @ A_full.T + sigma_sq * Q_raw

        # ---- Extract predicted values ----
        y_pred = E0 @ x_pred
        yp_pred = E1 @ x_pred

        # ---- Innovation (TS1) ----
        f_y = vf_np(y_pred)
        nu = f_y - yp_pred

        J_f = jac_np(y_pred)
        H = E1 - J_f @ E0           # d x N measurement Jacobian

        # ---- Innovation covariance ----
        S = H @ P_pred @ H.T
        S = 0.5 * (S + S.T)         # symmetrise
        S += np.eye(d) * 1e-15      # tiny regularisation

        # ---- Kalman gain ----
        K = P_pred @ H.T @ np.linalg.solve(S, np.eye(d)).T
        # equivalent to P_pred @ H.T @ inv(S), but via solve for stability

        # ---- Normalised innovation (chi-squared statistic) ----
        S_inv_nu = np.linalg.solve(S, nu)
        chi_sq = float(nu @ S_inv_nu)
        chi_sq_values.append(chi_sq)

        # ---- Update output scale (dynamic MLE) ----
        sigma_sq = (k * sigma_sq + chi_sq / d) / (k + 1)

        # ---- State update ----
        x = x_pred + K @ nu

        # ---- Covariance update (Joseph form) ----
        IKH = I_N - K @ H
        P = IKH @ P_pred @ IKH.T
        P = 0.5 * (P + P.T)         # symmetrise

    return {
        "terminal_mean": x[:d],
        "chi_sq_mean": float(np.mean(chi_sq_values)),
        "output_scale": float(sigma_sq),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Read config
    with open("/app/config.json") as f:
        cfg = json.load(f)

    q = cfg["q"]
    h = cfg["h"]
    t0 = cfg["t0"]
    t1 = cfg["t1"]
    d = cfg["d"]

    # Solve
    result = solve_probabilistic(Y0, t0, t1, h, q, d)

    # Ensure output directory
    os.makedirs("/app/results", exist_ok=True)

    # Terminal values
    terminal = {
        "y1": float(result["terminal_mean"][0]),
        "y2": float(result["terminal_mean"][1]),
    }
    with open("/app/results/terminal_values.json", "w") as f:
        json.dump(terminal, f, indent=2)

    # Calibration
    calibration = {
        "chi_sq_mean": result["chi_sq_mean"],
        "output_scale": result["output_scale"],
    }
    with open("/app/results/calibration.json", "w") as f:
        json.dump(calibration, f, indent=2)

    # IWP matrix check entries
    A_check = iwp_transition(h, q)
    Q_check = iwp_process_noise(h, q)
    iwp = {
        "A_01": float(A_check[0, 1]),
        "A_02": float(A_check[0, 2]),
        "A_03": float(A_check[0, 3]),
        "Q_00": float(Q_check[0, 0]),
        "Q_33": float(Q_check[3, 3]),
    }
    with open("/app/results/iwp_check.json", "w") as f:
        json.dump(iwp, f, indent=2)

    print(f"Terminal: y1={terminal['y1']:.8f}, y2={terminal['y2']:.8f}")
    print(f"Calibration: chi_sq_mean={calibration['chi_sq_mean']:.6f}, "
          f"output_scale={calibration['output_scale']:.8f}")
    print(f"IWP check: {iwp}")


if __name__ == "__main__":
    main()
