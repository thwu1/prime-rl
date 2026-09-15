#!/usr/bin/env python3
"""
E5 extremely stiff chemical kinetics ODE solver.


The E5 system models atmospheric chemistry with 4 species
and rate constants spanning 19 orders of magnitude.
"""

import numpy as np
from scipy.integrate import solve_ivp
import csv
import json
import sys

# E5 rate constants
K1 = 7.89e-10
K2 = 1.1e7
K3 = 1.13e9
K4 = 1.13e3

# Initial conditions
Y0 = np.array([1.76e-3, 0.0, 0.0, 0.0])

# Standard output times (logarithmically spaced)
OUTPUT_TIMES = [10.0, 1e3, 1e5, 1e7, 1e9, 1e11, 1e13]


def e5_rhs(t, y):
    """Right-hand side of the E5 system: dy/dt = f(y)."""
    prod1 = K1 * y[0]
    prod2 = K2 * y[0] * y[2]
    prod3 = K3 * y[1] * y[2]
    prod4 = K4 * y[3]
    f = np.empty(4)
    f[0] = -prod1 - prod2
    f[1] = prod1 - prod3
    f[3] = prod2 - prod4
    f[2] = f[1] - f[3]
    return f


def e5_jac(t, y):
    """Analytical Jacobian of the E5 system (4x4 matrix).

    Computed from the partial derivatives of e5_rhs with respect to y.
    Using rate constants: k1=7.89e-10, k2=1.1e7, k3=1.13e9, k4=1.13e3.
    """
    J = np.zeros((4, 4))
    J[0, 0] = -K1 - K2 * y[2]
    J[0, 2] = -K2 * y[0]
    J[1, 0] = K1
    J[1, 1] = -K3 * y[2]
    J[1, 2] = -K3 * y[1]
    J[2, 0] = K1 - K2 * y[2]
    J[2, 1] = -K3 * y[2]
    J[2, 2] = -K2 * y[0] - K3 * y[1]
    J[2, 3] = K4
    J[3, 0] = K2 * y[2]
    J[3, 2] = K2 * y[0]
    J[3, 3] = -K4
    return J


def solve_e5(method, rtol):
    """Solve the E5 problem with specified method and tolerance.

    Args:
        method: str, scipy solver method ('Radau' or 'BDF')
        rtol: float, relative tolerance

    Returns:
        dict mapping output time (float) to solution [y1, y2, y3, y4] (list)
    """
    # Absolute tolerance must be extremely small because solution components
    # reach O(1e-13) and smaller. Without this, the solver loses these
    # components entirely, producing garbage.
    atol = 1.7e-24

    results = {}
    t_start = 0.0
    y_current = Y0.copy()

    for t_end in OUTPUT_TIMES:
        sol = solve_ivp(
            e5_rhs, [t_start, t_end], y_current,
            method=method, rtol=rtol, atol=atol,
            jac=e5_jac, dense_output=False,
            first_step=min(1e-6, (t_end - t_start) * 1e-10)
        )
        if not sol.success:
            print(f"Warning: {method} failed at t={t_end}: {sol.message}",
                  file=sys.stderr)
        y_current = sol.y[:, -1]
        results[t_end] = y_current.tolist()
        t_start = t_end

    return results


def compute_eigenvalues(y):
    """Compute eigenvalues of the E5 Jacobian at state y."""
    J = e5_jac(0, y)
    return np.linalg.eigvals(J)


def stiffness_ratio(eigenvalues):
    """Compute stiffness ratio: max|lambda|/min|lambda| for nonzero lambda."""
    mags = np.abs(eigenvalues)
    nonzero = mags[mags > 1e-30]
    if len(nonzero) < 2:
        return float('inf')
    return float(np.max(nonzero) / np.min(nonzero))


def main():
    # --- 1. Solve with both methods at multiple tolerances ---
    rows = []
    for method in ['Radau', 'BDF']:
        for rtol in [1e-4, 1e-6, 1e-8, 1e-10]:
            print(f"Solving E5: method={method}, rtol={rtol:.0e}...",
                  file=sys.stderr)
            try:
                results = solve_e5(method, rtol)
                for t in OUTPUT_TIMES:
                    y = results[t]
                    rows.append({
                        'method': method,
                        'rtol': rtol,
                        't': t,
                        'y1': y[0], 'y2': y[1], 'y3': y[2], 'y4': y[3]
                    })
            except Exception as e:
                print(f"Error: {method} rtol={rtol}: {e}", file=sys.stderr)

    with open('/app/python_results.csv', 'w', newline='') as f:
        writer = csv.DictWriter(
            f, fieldnames=['method', 'rtol', 't', 'y1', 'y2', 'y3', 'y4'])
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to /app/python_results.csv",
          file=sys.stderr)

    # --- 2. Eigenvalue analysis ---
    eigs_t0 = compute_eigenvalues(Y0)

    # Get y(t=10) from highest-accuracy run
    try:
        ref_results = solve_e5('Radau', 1e-10)
        y_t10 = np.array(ref_results[10.0])
    except Exception as e:
        print(f"Warning: high-accuracy solve failed ({e}), using rtol=1e-8",
              file=sys.stderr)
        ref_results = solve_e5('Radau', 1e-8)
        y_t10 = np.array(ref_results[10.0])
    eigs_t10 = compute_eigenvalues(y_t10)

    def format_eigs(eigs):
        out = []
        for e in eigs:
            if abs(e.imag) < 1e-10 * (abs(e.real) + 1e-30):
                out.append(float(e.real))
            else:
                out.append(str(complex(e)))
        return out

    eig_data = {
        'eigenvalues_t0': format_eigs(eigs_t0),
        'eigenvalues_t10': format_eigs(eigs_t10),
        'stiffness_ratio_t0': stiffness_ratio(eigs_t0),
        'stiffness_ratio_t10': stiffness_ratio(eigs_t10),
    }

    with open('/app/eigenvalues.json', 'w') as f:
        json.dump(eig_data, f, indent=2)
    print("Wrote /app/eigenvalues.json", file=sys.stderr)


if __name__ == '__main__':
    main()
