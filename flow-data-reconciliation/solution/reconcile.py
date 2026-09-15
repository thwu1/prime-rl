#!/usr/bin/env python3
"""
VDI 2048 Data Reconciliation with Serial Gross Error Elimination.

Reads measurement data, correlation matrix, and constraint equations,
then performs constrained WLS reconciliation with iterative fault detection.
"""

import numpy as np
import json
import csv
import os
import re
from scipy import stats
from scipy.linalg import qr


def parse_measurements(filepath):
    """Parse VDI 2048 semicolon-delimited measurement CSV."""
    variables = []
    values = []
    hwcis = []
    with open(filepath) as f:
        reader = csv.reader(f, delimiter=';')
        next(reader)  # skip header
        for row in reader:
            if not row or not row[0].strip() or row[0].strip().startswith('//'):
                continue
            if len(row) < 3:
                continue
            variables.append(row[0].strip())
            values.append(float(row[1].strip()))
            hwcis.append(float(row[2].strip()))
    return variables, np.array(values), np.array(hwcis)


def parse_correlation(filepath, variables):
    """Parse lower-triangular correlation matrix CSV."""
    n = len(variables)
    R = np.zeros((n, n))

    if not os.path.exists(filepath):
        return R

    with open(filepath) as f:
        reader = csv.reader(f, delimiter=';')
        header = next(reader)
        col_vars = [h.strip() for h in header[1:] if h.strip()]

        for row in reader:
            if not row or not row[0].strip():
                continue
            row_var = row[0].strip()
            if row_var not in variables:
                continue
            i = variables.index(row_var)
            for k in range(1, len(row)):
                val_str = row[k].strip() if k < len(row) else ''
                if val_str and (k - 1) < len(col_vars):
                    col_var = col_vars[k - 1]
                    if col_var in variables:
                        j = variables.index(col_var)
                        r_val = float(val_str)
                        R[i, j] = r_val
                        R[j, i] = r_val
    return R


def parse_constraints(filepath, variables):
    """Parse constraint equations from JSON and build the F matrix."""
    with open(filepath) as f:
        data = json.load(f)

    n = len(variables)
    constraints = data['constraints']
    num_c = len(constraints)
    F = np.zeros((num_c, n))

    for c_idx, constraint in enumerate(constraints):
        eq_str = constraint['equation']
        lhs = eq_str.split('=')[0].strip()
        tokens = re.findall(r'([+-]?\s*(?:\d+\.?\d*\s*\*\s*)?[a-zA-Z]\w*)', lhs)

        for token in tokens:
            token = token.replace(' ', '')
            if '*' in token:
                parts = token.split('*')
                coeff = float(parts[0])
                var_name = parts[1]
            else:
                match = re.match(r'^([+-]?)([a-zA-Z]\w*)$', token)
                if not match:
                    continue
                sign = match.group(1)
                var_name = match.group(2)
                coeff = -1.0 if sign == '-' else 1.0

            if var_name in variables:
                j = variables.index(var_name)
                F[c_idx, j] += coeff

    return F


def build_covariance(hwcis, R):
    """Build covariance matrix from half-width confidence intervals and correlations."""
    n = len(hwcis)
    sigmas = hwcis / 1.96
    Sx = np.zeros((n, n))
    for i in range(n):
        Sx[i, i] = sigmas[i] ** 2
        for j in range(i):
            Sx[i, j] = R[i, j] * sigmas[i] * sigmas[j]
            Sx[j, i] = Sx[i, j]
    return Sx, sigmas


def find_independent_constraints(F):
    """Find maximal linearly independent subset of constraint rows via QR with pivoting."""
    m, n = F.shape
    Q, R_mat, perm = qr(F.T, pivoting=True)
    diag = np.abs(np.diag(R_mat[:min(m, n), :]))
    if len(diag) == 0:
        return F[:0, :], 0
    tol = max(F.shape) * diag[0] * np.finfo(float).eps * 100
    rank = int(np.sum(diag > tol))
    independent_rows = sorted(perm[:rank])
    F_indep = F[independent_rows, :]
    return F_indep, rank


def reconcile(x_meas, Sx, F_indep):
    """Constrained WLS reconciliation via Lagrange multipliers."""
    FSF = F_indep @ Sx @ F_indep.T
    residual = F_indep @ x_meas
    lam = np.linalg.solve(FSF, residual)
    correction = Sx @ F_indep.T @ lam
    x_hat = x_meas - correction
    FSF_inv_F_Sx = np.linalg.solve(FSF, F_indep @ Sx)
    Sx_hat = Sx - Sx @ F_indep.T @ FSF_inv_F_Sx
    J_star = float(correction @ np.linalg.solve(Sx, correction))
    return x_hat, Sx_hat, J_star, correction


def compute_local_tests(correction, Sx, Sx_hat):
    """Compute local test statistics for each variable."""
    n = len(correction)
    local_tests = np.zeros(n)
    for i in range(n):
        var_improvement = Sx[i, i] - Sx_hat[i, i]
        if var_improvement > 1e-12:
            local_tests[i] = abs(correction[i]) / np.sqrt(var_improvement)
    return local_tests


def run():
    variables, x_meas, hwcis = parse_measurements('/app/measurements.csv')
    R = parse_correlation('/app/correlation.csv', variables)
    F_full = parse_constraints('/app/constraints.json', variables)

    n = len(variables)
    Sx_original, sigmas = build_covariance(hwcis, R)
    F_indep, rank = find_independent_constraints(F_full)
    chi2_crit = float(stats.chi2.ppf(0.95, rank))
    Sx_work = Sx_original.copy()

    gross_errors = []
    large_var = 1e10

    for iteration in range(10):
        x_hat, Sx_hat, J_star, correction = reconcile(x_meas, Sx_work, F_indep)

        if J_star <= chi2_crit:
            break

        local_tests = compute_local_tests(correction, Sx_work, Sx_hat)

        for ge in gross_errors:
            idx = variables.index(ge)
            local_tests[idx] = 0.0

        worst_idx = int(np.argmax(local_tests))
        worst_val = local_tests[worst_idx]

        if worst_val <= 1.96:
            break

        worst_var = variables[worst_idx]
        gross_errors.append(worst_var)

        Sx_work[worst_idx, worst_idx] = large_var
        for j in range(n):
            if j != worst_idx:
                Sx_work[worst_idx, j] = 0.0
                Sx_work[j, worst_idx] = 0.0

    x_hat, Sx_hat, J_star, correction = reconcile(x_meas, Sx_work, F_indep)

    reconciled_hwcis = np.array([
        1.96 * np.sqrt(max(Sx_hat[i, i], 0.0)) for i in range(n)
    ])

    os.makedirs('/app/results', exist_ok=True)

    with open('/app/results/reconciled_values.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['variable_name', 'measured_value', 'reconciled_value',
                         'measured_hwci', 'reconciled_hwci'])
        for i in range(n):
            writer.writerow([
                variables[i],
                f'{x_meas[i]:.6f}',
                f'{x_hat[i]:.6f}',
                f'{hwcis[i]:.6f}',
                f'{reconciled_hwcis[i]:.6f}'
            ])

    with open('/app/results/gross_errors.json', 'w') as f:
        json.dump(gross_errors, f)

    analysis = {
        'global_test_statistic': float(J_star),
        'chi_square_critical': float(chi2_crit),
        'global_test_passed': bool(J_star <= chi2_crit),
        'num_independent_constraints': int(rank),
        'detected_gross_errors': gross_errors
    }
    with open('/app/results/analysis.json', 'w') as f:
        json.dump(analysis, f, indent=2)


if __name__ == '__main__':
    run()
