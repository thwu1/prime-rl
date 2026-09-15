#!/usr/bin/env python3
"""
Solver for three high-precision numerical challenge problems.

"""

import json
import math
import sys


def solve_problem1():
    """
    Compute lim_{e->0+} int_e^1 (1/x) cos(ln(x)/x) dx.

    Strategy:
      1. Substitution u = -ln(x) transforms the integral to int_0^inf cos(u e^u) du.
      2. The integrand cos(u e^u) oscillates with super-exponentially increasing
         frequency, making direct quadrature impossible.
      3. Contour rotation z = (1 + i*delta)*s deforms the integral into one with
         a super-exponentially decaying envelope, which standard quadrature handles
         easily.  The deformed integral equals the original by Cauchy's theorem
         (the integrand exp(i*z*e^z) is entire).
    """
    from mpmath import mp, quad, cos, sin, exp, mpf

    mp.dps = 30
    delta = mpf("0.1")

    def integrand(s):
        z_re = s
        z_im = delta * s

        ez_mag = exp(z_re)
        ez_re = ez_mag * cos(z_im)
        ez_im = ez_mag * sin(z_im)

        w_re = z_re * ez_re - z_im * ez_im
        w_im = z_re * ez_im + z_im * ez_re

        iw_re = -w_im
        iw_im = w_re

        eiw_mag = exp(iw_re)
        eiw_re = eiw_mag * cos(iw_im)
        eiw_im = eiw_mag * sin(iw_im)

        return eiw_re - delta * eiw_im

    result = quad(integrand, [mpf(0), mpf(6)])
    return float(result)


def solve_problem2():
    """
    Compute (A^{-1})_{1,1} for the 20000x20000 sparse matrix A with primes
    on the diagonal and 1's at off-diagonal positions |i-j| in {1,2,4,...,16384}.

    Strategy: Sieve primes, build sparse CSC matrix, solve A x = e_1 via
    GMRES with Jacobi (diagonal) preconditioner.  The matrix is nearly
    diagonally dominant (all rows with index >= 7 satisfy strict diagonal
    dominance), so GMRES with diagonal preconditioning converges in very
    few iterations.  Double precision gives ~15 significant digits.
    """
    import numpy as np
    from scipy.sparse import coo_matrix, diags
    from scipy.sparse.linalg import gmres

    N = 20000

    upper = int(N * (math.log(N) + math.log(math.log(N))) * 1.2) + 100
    sieve = bytearray(b"\x01") * (upper + 1)
    sieve[0] = sieve[1] = 0
    for i in range(2, int(upper**0.5) + 1):
        if sieve[i]:
            for j in range(i * i, upper + 1, i):
                sieve[j] = 0
    primes = [i for i, v in enumerate(sieve) if v][:N]
    assert len(primes) == N, f"Expected {N} primes, got {len(primes)}"
    assert primes[-1] == 224737, f"20000th prime should be 224737, got {primes[-1]}"

    rows = []
    cols = []
    data = []

    for i in range(N):
        rows.append(i)
        cols.append(i)
        data.append(float(primes[i]))

    for k in range(15):
        d = 1 << k
        for i in range(N - d):
            rows.append(i)
            cols.append(i + d)
            data.append(1.0)
            rows.append(i + d)
            cols.append(i)
            data.append(1.0)

    A = coo_matrix((data, (rows, cols)), shape=(N, N)).tocsc()

    diag_vals = np.array([float(p) for p in primes])
    M_inv = diags(1.0 / diag_vals)

    e1 = np.zeros(N)
    e1[0] = 1.0
    x, info = gmres(A, e1, M=M_inv, rtol=1e-14, maxiter=500)
    assert info == 0, f"GMRES did not converge, info={info}"

    return float(x[0])


def solve_problem3():
    """
    Compute the probability that 2D Brownian motion starting at the center
    of a 10x1 rectangle exits through one of the short sides.

    Strategy: The exit probability is the harmonic measure of the short sides,
    obtained by separation of variables on the Laplace equation:

        P = (4/pi) * sum_{n=0}^{inf} (-1)^n / ((2n+1) * cosh((2n+1) * 5*pi))

    The series converges super-exponentially (each successive term is smaller
    by a factor of roughly e^{-10*pi} ~ 10^{-14}).
    """
    from mpmath import mp, mpf, pi, cosh

    mp.dps = 30

    total = mpf(0)
    for n in range(20):
        k = 2 * n + 1
        arg = k * 5 * pi
        term = mpf(-1) ** n / (k * cosh(arg))
        total += term
        if abs(term) < mpf(10) ** (-25):
            break

    P = 4 * total / pi
    return float(P)


def main():
    print("=" * 60)
    print("High-Precision Numerical Challenge Solver")
    print("=" * 60)

    results = {}

    print("\nProblem 1: Oscillatory Improper Integral")
    print("  Method: contour rotation of transformed integral")
    results["problem1"] = solve_problem1()
    print(f"  Result: {results['problem1']:.15e}")

    print("\nProblem 2: Sparse Matrix Inverse Entry")
    print("  Method: GMRES with Jacobi preconditioner (20000x20000)")
    results["problem2"] = solve_problem2()
    print(f"  Result: {results['problem2']:.15e}")

    print("\nProblem 3: Brownian Exit Probability")
    print("  Method: Fourier series for harmonic measure")
    results["problem3"] = solve_problem3()
    print(f"  Result: {results['problem3']:.15e}")

    with open("/app/answers.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nAll results written to /app/answers.json")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
