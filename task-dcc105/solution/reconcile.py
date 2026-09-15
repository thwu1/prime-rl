#!/usr/bin/env python3
"""
VDI 2048 Nonlinear Data Reconciliation Engine.

Parses the Modelica model to extract the enthalpy function coefficients
and constraint structure, then performs iterative constrained WLS
reconciliation with statistical testing.
"""

import csv
import json
import math
import re
import sys

import numpy as np
from scipy.stats import chi2


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_modelica_model(path):
    """Parse the Modelica .mo file to extract enthalpy coefficients."""
    with open(path) as f:
        text = f.read()
    # Extract enthalpy polynomial coefficients from the function definition
    a_match = re.search(r'constant\s+Real\s+a\s*=\s*([\d.]+)', text)
    b_match = re.search(r'constant\s+Real\s+b\s*=\s*([\d.]+)', text)
    if not a_match or not b_match:
        raise ValueError("Could not extract enthalpy coefficients from Modelica model")
    a = float(a_match.group(1))
    b = float(b_match.group(1))
    return a, b


def parse_measurements(path):
    variables, values, hwci = [], [], []
    with open(path) as f:
        reader = csv.reader(f, delimiter=";")
        next(reader)  # header
        for row in reader:
            if not row or row[0].strip().startswith("//"):
                continue
            variables.append(row[0].strip())
            values.append(float(row[1].strip()))
            hwci.append(float(row[2].strip()))
    return variables, np.array(values), np.array(hwci)


def parse_correlations(path, variables):
    n = len(variables)
    R = np.eye(n)
    try:
        with open(path) as f:
            reader = csv.reader(f, delimiter=";")
            header = next(reader)
            col_vars = [h.strip() for h in header[1:]]
            for row in reader:
                if not row:
                    continue
                row_var = row[0].strip()
                if row_var not in variables:
                    continue
                i = variables.index(row_var)
                for k in range(1, len(row)):
                    cell = row[k].strip()
                    if cell and (k - 1) < len(col_vars):
                        col_var = col_vars[k - 1]
                        if col_var in variables:
                            j = variables.index(col_var)
                            try:
                                r_val = float(cell)
                                R[i, j] = r_val
                                R[j, i] = r_val
                            except ValueError:
                                pass
    except FileNotFoundError:
        pass
    return R


# ---------------------------------------------------------------------------
# Enthalpy helpers
# ---------------------------------------------------------------------------

def h(T, a, b):
    """h(T) = a*T + b*T^2"""
    return a * T + b * T * T


# ---------------------------------------------------------------------------
# Constraint system
# ---------------------------------------------------------------------------

def constraints(x, idx, a, b):
    """Evaluate the 9 constraint equations f(x) = 0."""
    m = {k: x[idx[k]] for k in idx}
    return np.array([
        m["m1"] + m["m2"] - m["m3"],
        m["m3"] - m["m4"] - m["m5"] - m["m6"],
        m["m4"] - m["m7"],
        m["m5"] - m["m8"],
        m["m6"] - m["m9"],
        m["m7"] + m["m8"] + m["m9"] + m["m10"] - m["m11"],
        m["m11"] - m["m12"],
        m["m1"] * h(m["T1"], a, b) + m["m2"] * h(m["T2"], a, b)
        - m["m3"] * h(m["T3"], a, b),
        m["m7"] * h(m["T7"], a, b) + m["m8"] * h(m["T8"], a, b)
        + m["m9"] * h(m["T9"], a, b) + m["m10"] * h(m["T10"], a, b)
        - m["m11"] * h(m["T11"], a, b),
    ])


def numerical_jacobian(x, idx, a, b, eps=1e-7):
    """Central-difference Jacobian."""
    f0 = constraints(x, idx, a, b)
    n = len(x)
    r = len(f0)
    F = np.zeros((r, n))
    for j in range(n):
        xp = x.copy()
        xm = x.copy()
        xp[j] += eps
        xm[j] -= eps
        F[:, j] = (constraints(xp, idx, a, b) - constraints(xm, idx, a, b)) / (2.0 * eps)
    return F


# ---------------------------------------------------------------------------
# Data reconciliation
# ---------------------------------------------------------------------------

def reconcile(x_meas, S, idx, a, b, max_iter=100):
    n = len(x_meas)
    x_k = x_meas.copy()

    for iteration in range(1, max_iter + 1):
        f_k = constraints(x_k, idx, a, b)
        F_k = numerical_jacobian(x_k, idx, a, b)

        FSFT = F_k @ S @ F_k.T
        rhs = f_k + F_k @ (x_meas - x_k)
        lam = np.linalg.solve(FSFT, rhs)
        x_new = x_meas - S @ F_k.T @ lam

        change = np.max(np.abs(x_new - x_k))
        x_k = x_new
        if change < 1e-8:
            break

    max_residual = np.max(np.abs(constraints(x_k, idx, a, b)))
    converged = (iteration < max_iter) or (max_residual < 1e-6)

    # Final Jacobian
    F = numerical_jacobian(x_k, idx, a, b)
    FSFT = F @ S @ F.T
    FSFT_inv = np.linalg.inv(FSFT)

    # Objective function
    dx = x_meas - x_k
    J_star = float(dx @ np.linalg.solve(S, dx))

    # Reconciled covariance and correction covariance
    Proj = S @ F.T @ FSFT_inv @ F @ S
    S_rec = S - Proj
    V = Proj

    return x_k, S_rec, V, J_star, iteration, converged


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    a, b = parse_modelica_model("/app/plant_model.mo")
    variables, x_meas, hwci = parse_measurements("/app/measurements.csv")
    R = parse_correlations("/app/correlations.csv", variables)

    idx = {v: i for i, v in enumerate(variables)}
    n = len(variables)

    # Build covariance matrix
    sigma = hwci / 1.96
    S = np.outer(sigma, sigma) * R

    # Reconcile
    x_rec, S_rec, V, J_star, num_iter, converged = reconcile(x_meas, S, idx, a, b)

    # Statistics
    r = 9  # number of constraints
    chi2_crit = float(chi2.ppf(0.95, r))
    global_pass = J_star < chi2_crit

    # Reconciled HWCI
    sigma_rec = np.sqrt(np.maximum(np.diag(S_rec), 0.0))
    hwci_rec = 1.96 * sigma_rec

    # Local tests
    local_vals = []
    local_pass = []
    for i in range(n):
        if V[i, i] > 1e-15:
            d = abs(x_rec[i] - x_meas[i]) / math.sqrt(V[i, i])
        else:
            d = 0.0
        local_vals.append(d)
        local_pass.append(d <= 1.96)

    faulty = [variables[i] for i in range(n) if not local_pass[i]]

    # ---- Write reconciled_values.csv ----
    with open("/app/reconciled_values.csv", "w", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow([
            "Variable Name", "Measured Value", "Reconciled Value",
            "Measured HWCI", "Reconciled HWCI",
            "Local Test Value", "Local Test Result",
        ])
        for i, v in enumerate(variables):
            w.writerow([
                v,
                f"{x_meas[i]:.6f}",
                f"{x_rec[i]:.6f}",
                f"{hwci[i]:.6f}",
                f"{hwci_rec[i]:.6f}",
                f"{local_vals[i]:.6f}",
                "TRUE" if local_pass[i] else "FALSE",
            ])

    # ---- Write test_results.json ----
    result = {
        "global_test": {
            "J_star": J_star,
            "chi_square_critical": chi2_crit,
            "degrees_of_freedom": r,
            "result": "TRUE" if global_pass else "FALSE",
        },
        "faulty_sensors": faulty,
        "num_iterations": num_iter,
        "converged": bool(converged),
    }
    with open("/app/test_results.json", "w") as f:
        json.dump(result, f, indent=2)

    print(f"Reconciliation complete in {num_iter} iterations.")
    print(f"J* = {J_star:.4f}   chi2_crit = {chi2_crit:.4f}")
    print(f"Global test: {'PASS' if global_pass else 'FAIL'}")
    print(f"Faulty sensors: {faulty}")


if __name__ == "__main__":
    main()
