#!/usr/bin/env python3

"""Reference solver: produces correct results.json from config.json."""

import json
from fractions import Fraction

import mpmath

mpmath.mp.dps = 60  # 60-digit working precision


def frac_to_mpf(s):
    """Convert a rational-number string like '3/7' or '-5' to mpmath.mpf."""
    f = Fraction(s)
    return mpmath.mpf(f.numerator) / mpmath.mpf(f.denominator)


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def load_config():
    with open("/app/config.json") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Padé evaluation
# ---------------------------------------------------------------------------

def compute_pade_eval(coeffs_mpf, m, n, z):
    """Return the value of the [m/n] Padé approximant at complex z."""
    p, q = mpmath.pade(coeffs_mpf[: m + n + 1], m, n)
    num = sum(c * z ** k for k, c in enumerate(p))
    den = sum(c * z ** k for k, c in enumerate(q))
    return num / den


# ---------------------------------------------------------------------------
# Convergence radius & singularity classification via regression
# ---------------------------------------------------------------------------

def analyse_coefficients(coeffs_mpf):
    """Return (R, singularity_type, nearest_singularity) from Taylor coefficients.

    Fits  log|c_k| = a + b·k + c·log(k)  by least squares on the tail,
    giving  R = exp(-b)  and the singularity exponent c.
    """
    n = len(coeffs_mpf)
    start = max(5, n // 2)

    # Collect data points where c_k != 0
    ks, ys = [], []
    for k in range(start, n):
        if abs(coeffs_mpf[k]) > 0:
            ks.append(k)
            ys.append(mpmath.log(abs(coeffs_mpf[k])))

    m_pts = len(ks)

    # Build normal-equations matrices for y = a + b·k + c·log(k)
    S1 = mpmath.mpf(m_pts)
    Sk = sum(mpmath.mpf(k) for k in ks)
    Slk = sum(mpmath.log(mpmath.mpf(k)) for k in ks)
    Sk2 = sum(mpmath.mpf(k) ** 2 for k in ks)
    Sklk = sum(mpmath.mpf(k) * mpmath.log(mpmath.mpf(k)) for k in ks)
    Slk2 = sum(mpmath.log(mpmath.mpf(k)) ** 2 for k in ks)
    Sy = sum(ys)
    Sky = sum(mpmath.mpf(k) * y for k, y in zip(ks, ys))
    Slky = sum(mpmath.log(mpmath.mpf(k)) * y for k, y in zip(ks, ys))

    # 3×3 normal equations
    A = mpmath.matrix([
        [S1, Sk, Slk],
        [Sk, Sk2, Sklk],
        [Slk, Sklk, Slk2],
    ])
    rhs = mpmath.matrix([Sy, Sky, Slky])
    beta = mpmath.lu_solve(A, rhs)
    a_val, b_val, c_val = beta[0], beta[1], beta[2]

    # Convergence radius
    R_raw = mpmath.exp(-b_val)

    # Snap to nearest simple fraction if close
    for candidate in [mpmath.mpf(v) for v in
                      ("0.1", "0.2", "0.25", "0.5", "1", "2", "3", "4", "5", "10")]:
        if candidate > 0 and abs(R_raw - candidate) / candidate < mpmath.mpf("0.005"):
            R_raw = candidate
            break

    # Classify singularity from exponent c
    c_float = float(c_val)
    if abs(c_float) < 0.5:
        sing_type = "polar"
    elif abs(c_float + 1) < 0.35:
        sing_type = "logarithmic_branch"
    else:
        sing_type = "algebraic_branch"

    # Locate nearest singularity via sign pattern of normalized tail
    normalised = [coeffs_mpf[k] * R_raw ** k for k in range(start, n)]
    signs = [1 if x >= 0 else -1 for x in normalised]
    alternating = all(signs[i] * signs[i + 1] < 0 for i in range(len(signs) - 1))

    if alternating:
        sing_re, sing_im = -R_raw, mpmath.mpf(0)
    else:
        sing_re, sing_im = R_raw, mpmath.mpf(0)

    return R_raw, sing_type, sing_re, sing_im


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    config = load_config()
    results = {}

    for fname in ("f1", "f2", "f3"):
        coeffs_str = config["functions"][fname]["coefficients"]
        coeffs_mpf = [frac_to_mpf(c) for c in coeffs_str]

        R, sing_type, sing_re, sing_im = analyse_coefficients(coeffs_mpf)

        # Padé evaluations
        pade_evals = {}
        for m, n in config["pade_orders"]:
            order_key = f"{m}_{n}"
            evals = {}
            for idx, pt in enumerate(config["evaluation_points"]):
                z = mpmath.mpc(pt["re"], pt["im"])
                val = compute_pade_eval(coeffs_mpf, m, n, z)
                evals[str(idx)] = {
                    "re": mpmath.nstr(val.real, 45),
                    "im": mpmath.nstr(val.imag, 45),
                }
            pade_evals[order_key] = evals

        results[fname] = {
            "convergence_radius": mpmath.nstr(R, 15),
            "singularity_type": sing_type,
            "nearest_singularity": {
                "re": mpmath.nstr(sing_re, 15),
                "im": mpmath.nstr(sing_im, 15),
            },
            "pade_evaluations": pade_evals,
        }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")


if __name__ == "__main__":
    main()
