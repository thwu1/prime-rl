"""
Precision Oracle — computes special function values at challenging evaluation points.

Targets 50-significant-digit accuracy for three categories:
  polylog:      Li_s(z) — the polylogarithm
  hurwitz_zeta: zeta(s,a) — Hurwitz zeta function
  hilbert_det:  det(H_n) — Hilbert matrix determinant

Run this oracle and inspect /app/output/results.json to understand the
computation targets and identify which values are incorrect.
"""
import json
import os
from mpmath import mp, mpf, mpc, nstr, power, fac, matrix, det, bernoulli

OUTPUT_DPS = 50
GUARD = 10


def polylog_series(s, z):
    """
    Li_s(z) via truncated power series: sum_{k=1}^{inf} z^k / k^s.

    Converges for |z| < 1 and conditionally on |z| = 1 if Re(s) > 1.
    """
    mp.dps = OUTPUT_DPS + GUARD
    total = mpf(0)
    for k in range(1, 1000):
        term = z ** k / mpf(k) ** s
        total += term
        if abs(term) < power(10, -(OUTPUT_DPS + GUARD)):
            break
    return total


def hurwitz_euler_maclaurin(s, a, N=200, num_corrections=3):
    """
    Hurwitz zeta via Euler-Maclaurin with N partial-sum terms and
    num_corrections Bernoulli correction terms.

    zeta(s,a) = sum_{k=0}^{N-1} (a+k)^{-s}
              + (a+N)^{1-s}/(s-1) + (a+N)^{-s}/2
              + sum_{m=1}^{p} B_{2m}/(2m)! * s^{(2m-1)} * (a+N)^{-(s+2m-1)}
    """
    mp.dps = OUTPUT_DPS + GUARD
    s = mpf(s)
    a = mpf(a)

    total = mpf(0)
    for k in range(N):
        total += (a + k) ** (-s)

    total += (a + N) ** (1 - s) / (s - 1)
    total += (a + N) ** (-s) / 2

    for m in range(1, num_corrections + 1):
        bern = bernoulli(2 * m)
        coeff = bern / fac(2 * m)
        rising = mpf(1)
        for j in range(2 * m - 1):
            rising *= (s + j)
        total += coeff * rising * (a + N) ** (-(s + 2 * m - 1))

    return total


def hilbert_det_lu(n):
    """det(H_n) via mpmath's LU-based determinant."""
    mp.dps = OUTPUT_DPS + GUARD
    H = matrix(n, n)
    for i in range(n):
        for j in range(n):
            H[i, j] = mpf(1) / (i + j + 1)
    return det(H)


def main():
    os.makedirs("/app/output", exist_ok=True)
    results = {"polylog": {}, "hurwitz_zeta": {}, "hilbert_det": {}}

    mp.dps = OUTPUT_DPS + GUARD

    # Polylogarithm Li_s(z) at four challenging points
    polylog_inputs = {
        "2:0.5":     (2, mpf("0.5")),            # |z|<1, geometric convergence
        "2:-1":      (2, mpf("-1")),              # |z|=1, alternating, slow
        "3:-1":      (3, mpf("-1")),              # |z|=1, alternating, slow
        "2:1-1e-20": (2, 1 - power(10, -20)),     # z -> 1, extreme cancellation
    }
    for key, (s, z) in polylog_inputs.items():
        val = polylog_series(s, z)
        results["polylog"][key] = nstr(val, OUTPUT_DPS, strip_zeros=False)

    # Hurwitz zeta at three points with increasing difficulty
    hurwitz_inputs = {
        "2:0.25":   (2, 0.25),   # Re(s)>1, moderate
        "3:0.75":   (3, 0.75),   # Re(s)>1, moderate
        "0.5:0.25": (0.5, 0.25), # Re(s)<1, series diverges
    }
    for key, (s, a) in hurwitz_inputs.items():
        val = hurwitz_euler_maclaurin(s, a)
        results["hurwitz_zeta"][key] = nstr(val, OUTPUT_DPS, strip_zeros=False)

    # Hilbert determinants at three sizes
    for n in [10, 15, 20]:
        val = hilbert_det_lu(n)
        results["hilbert_det"][str(n)] = nstr(val, OUTPUT_DPS, strip_zeros=False)

    with open("/app/output/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Oracle results written to /app/output/results.json")
    for cat, vals in results.items():
        print(f"\n{cat}:")
        for k, v in vals.items():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
