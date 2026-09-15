#!/usr/bin/env python3
"""Generate /app/config.json with Taylor coefficients and a broken /app/results.json."""
import json
from fractions import Fraction


def _factorial(n):
    r = 1
    for i in range(2, n + 1):
        r *= i
    return r


def f1_coefficients(n):
    """Taylor coefficients of exp(z) / (1 - z/3).

    c_k = sum_{j=0}^{k} (1/3)^{k-j} / j!
    Simple pole at z=3. Convergence radius R=3.
    """
    coeffs = []
    for k in range(n):
        c = Fraction(0)
        for j in range(k + 1):
            c += Fraction(1, _factorial(j)) * Fraction(1, 3) ** (k - j)
        coeffs.append(str(c))
    return coeffs


def f2_coefficients(n):
    """Taylor coefficients of log(1+z).

    c_0 = 0, c_k = (-1)^(k+1)/k for k >= 1.
    Branch point at z=-1. Convergence radius R=1.
    """
    coeffs = ["0"]
    for k in range(1, n):
        c = Fraction((-1) ** (k + 1), k)
        coeffs.append(str(c))
    return coeffs


def f3_coefficients(n):
    """Taylor coefficients of sqrt(1+2z) = sum_k C(1/2,k)*(2z)^k.

    Branch point at z=-1/2. Convergence radius R=1/2.
    """
    coeffs = []
    for k in range(n):
        if k == 0:
            binom = Fraction(1)
        else:
            binom = Fraction(1)
            for j in range(k):
                binom *= (Fraction(1, 2) - j)
            fact = 1
            for j in range(1, k + 1):
                fact *= j
            binom = Fraction(binom, fact)
        c = binom * Fraction(2**k)
        coeffs.append(str(c))
    return coeffs


# ---------------------------------------------------------------------------
# Float-precision Pade for generating broken results
# ---------------------------------------------------------------------------

def _solve_system(A, b):
    """Solve Ax=b via Gaussian elimination with partial pivoting."""
    n = len(b)
    M = [list(A[i]) + [b[i]] for i in range(n)]
    for col in range(n):
        max_row = col
        for r in range(col + 1, n):
            if abs(M[r][col]) > abs(M[max_row][col]):
                max_row = r
        M[col], M[max_row] = M[max_row], M[col]
        pivot = M[col][col]
        if abs(pivot) < 1e-30:
            continue
        for r in range(col + 1, n):
            factor = M[r][col] / pivot
            for j in range(col, n + 1):
                M[r][j] -= factor * M[col][j]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        s = M[i][n]
        for j in range(i + 1, n):
            s -= M[i][j] * x[j]
        if abs(M[i][i]) > 1e-30:
            x[i] = s / M[i][i]
    return x


def _pade_eval_float(coeffs_str, m, n, z):
    """Compute [m/n] Pade approximant at complex z using float precision (~15 digits)."""
    c = [float(Fraction(s)) for s in coeffs_str[:m + n + 1]]

    # Build linear system for denominator coefficients q_1,...,q_n
    A_mat = []
    b_vec = []
    for j in range(n):
        row = []
        for k in range(1, n + 1):
            idx = m + 1 + j - k
            row.append(c[idx] if 0 <= idx < len(c) else 0.0)
        A_mat.append(row)
        rhs_idx = m + 1 + j
        b_vec.append(-c[rhs_idx] if 0 <= rhs_idx < len(c) else 0.0)

    q = _solve_system(A_mat, b_vec)
    q_full = [1.0] + q

    # Numerator coefficients
    p = []
    for j in range(m + 1):
        pj = c[j]
        for k in range(1, min(j, n) + 1):
            pj += c[j - k] * q_full[k]
        p.append(pj)

    # Evaluate P(z)/Q(z)
    pz = sum(p[k] * z**k for k in range(len(p)))
    qz = sum(q_full[k] * z**k for k in range(len(q_full)))
    return pz / qz


def _generate_broken_results(config):
    """Generate plausible-but-incorrect results at float precision."""
    # Deliberately wrong metadata for each function
    wrong_meta = {
        "f1": {"radius": "2.847", "stype": "logarithmic_branch",
               "sing_re": "3.12", "sing_im": "0"},
        "f2": {"radius": "0.983", "stype": "polar",
               "sing_re": "1.0", "sing_im": "0"},
        "f3": {"radius": "0.517", "stype": "logarithmic_branch",
               "sing_re": "-0.48", "sing_im": "0.12"},
    }
    results = {}
    for fname in ("f1", "f2", "f3"):
        coeffs = config["functions"][fname]["coefficients"]
        meta = wrong_meta[fname]
        pade_evals = {}
        for order in config["pade_orders"]:
            m, n = order
            order_key = "{}_{}".format(m, n)
            evals = {}
            for idx, pt in enumerate(config["evaluation_points"]):
                z = complex(float(pt["re"]), float(pt["im"]))
                val = _pade_eval_float(coeffs, m, n, z)
                evals[str(idx)] = {
                    "re": "{:.15e}".format(val.real),
                    "im": "{:.15e}".format(val.imag),
                }
            pade_evals[order_key] = evals
        results[fname] = {
            "convergence_radius": meta["radius"],
            "singularity_type": meta["stype"],
            "nearest_singularity": {"re": meta["sing_re"], "im": meta["sing_im"]},
            "pade_evaluations": pade_evals,
        }
    return results


# ---------------------------------------------------------------------------
# Main: generate config.json and broken results.json
# ---------------------------------------------------------------------------

config = {
    "precision_digits": 40,
    "functions": {
        "f1": {"coefficients": f1_coefficients(30)},
        "f2": {"coefficients": f2_coefficients(30)},
        "f3": {"coefficients": f3_coefficients(30)},
    },
    "pade_orders": [[5, 5], [10, 10], [14, 14]],
    "evaluation_points": [
        {"re": "0.3", "im": "0.0"},
        {"re": "0.7", "im": "0.0"},
        {"re": "1.5", "im": "0.5"},
        {"re": "-0.3", "im": "0.2"},
    ],
}

with open("/app/config.json", "w") as f:
    json.dump(config, f, indent=2)

broken = _generate_broken_results(config)
with open("/app/results.json", "w") as f:
    json.dump(broken, f, indent=2)
