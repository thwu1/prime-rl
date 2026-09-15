#!/usr/bin/env python3

"""
Reference solution for the Numerical Experiments Workspace.

1. Read calibration.json to get session_id and problem parameters.
2. Read experiment configs to understand each computational problem.
3. Implement high-precision numerical methods for each.
4. Write results to /app/results.json matching schema.json.
"""

import json
import math
import numpy as np
from scipy.sparse import csc_matrix
from scipy.sparse.linalg import splu
import mpmath


def sieve_primes(n):
    """Return the first n prime numbers via Sieve of Eratosthenes."""
    if n < 1:
        return []
    if n < 6:
        limit = 15
    else:
        ln_n = math.log(n)
        ln_ln_n = math.log(ln_n)
        limit = int(n * (ln_n + ln_ln_n)) + 100
    is_prime = [True] * (limit + 1)
    is_prime[0] = is_prime[1] = False
    for i in range(2, int(limit ** 0.5) + 1):
        if is_prime[i]:
            for j in range(i * i, limit + 1, i):
                is_prime[j] = False
    primes = [i for i in range(2, limit + 1) if is_prime[i]]
    while len(primes) < n:
        limit = int(limit * 1.5)
        is_prime = [True] * (limit + 1)
        is_prime[0] = is_prime[1] = False
        for i in range(2, int(limit ** 0.5) + 1):
            if is_prime[i]:
                for j in range(i * i, limit + 1, i):
                    is_prime[j] = False
        primes = [i for i in range(2, limit + 1) if is_prime[i]]
    return primes[:n]


def solve_quadrature(alpha, beta):
    """Solve experiment: quadrature.

    Integrand: cos(alpha*x^2 + beta*x) / cosh(x) on [0, +inf).
    Uses mpmath arbitrary-precision adaptive quadrature with interval
    splitting to handle the oscillatory numerator.
    """
    mpmath.mp.dps = 30
    a = mpmath.mpf(str(alpha))
    b = mpmath.mpf(str(beta))
    result = mpmath.quad(
        lambda x: mpmath.cos(a * x ** 2 + b * x) / mpmath.cosh(x),
        [0, 2, 5, 10, 20, 50],
    )
    return float(result)


def solve_sparse_inverse(N, band_count, targets_1indexed):
    """Solve experiment: sparse_inverse.

    N x N matrix with primes on diagonal, 1.0 at off-diagonal positions
    where |i-j| is a power of 2 (up to 2^(band_count-1)).
    Compute diagonal entries of A^{-1} at specified 1-indexed positions.
    """
    primes = sieve_primes(N)
    offsets = [2 ** k for k in range(band_count)]

    rows, cols, vals = [], [], []
    for i in range(N):
        rows.append(i)
        cols.append(i)
        vals.append(float(primes[i]))
        for d in offsets:
            j = i + d
            if j < N:
                rows.extend([i, j])
                cols.extend([j, i])
                vals.extend([1.0, 1.0])

    A = csc_matrix((vals, (rows, cols)), shape=(N, N))
    lu = splu(A)

    entries = {}
    for idx_1 in targets_1indexed:
        idx_0 = idx_1 - 1
        key = f"inv_{idx_1}"
        rhs = np.zeros(N)
        rhs[idx_0] = 1.0
        sol = lu.solve(rhs)
        entries[key] = float(sol[idx_0])

    return entries


def solve_exit_prob(L, W):
    """Solve experiment: stochastic.

    2D Brownian motion in rectangle [-L/2, L/2] x [-W/2, W/2], start at (0,0).
    Compute P(exit through short sides x = +/- L/2).

    Uses harmonic measure series:
    P = (4/pi) * sum_{n>=0} (-1)^n / ((2n+1) * cosh((2n+1)*pi*L/(2*W)))
    """
    mpmath.mp.dps = 30
    Lm = mpmath.mpf(str(L))
    Wm = mpmath.mpf(str(W))

    P = mpmath.mpf(0)
    for n in range(300):
        coeff = 2 * n + 1
        arg = coeff * mpmath.pi * Lm / (2 * Wm)
        term = mpmath.power(-1, n) / (coeff * mpmath.cosh(arg))
        P += term
        if abs(term) < mpmath.power(10, -28):
            break

    P *= 4 / mpmath.pi
    return float(P)


def main():
    print("=== Numerical Experiments Workspace: Reference Solution ===\n")

    # Step 1: Read calibration
    with open("/app/calibration.json") as f:
        cal = json.load(f)
    session_id = cal["session_id"]
    params = cal["parameter_overrides"]
    print(f"Session ID: {session_id}")

    # Step 2: Read experiment configs
    with open("/app/experiments/quadrature/config.json") as f:
        quad_cfg = json.load(f)
    with open("/app/experiments/sparse_inverse/targets.json") as f:
        sparse_targets = json.load(f)
    with open("/app/experiments/stochastic/setup.json") as f:
        stoch_cfg = json.load(f)

    # Step 3: Solve each experiment
    print("[1/3] Solving quadrature experiment...")
    alpha = params["quadrature"]["alpha"]
    beta = params["quadrature"]["beta"]
    integral = solve_quadrature(alpha, beta)
    print(f"      integral = {integral:.15e}")

    print("[2/3] Solving sparse_inverse experiment...")
    N = params["sparse_inverse"]["dimension"]
    band_count = params["sparse_inverse"]["band_count"]
    targets = sparse_targets["target_indices_1indexed"]
    inv_entries = solve_sparse_inverse(N, band_count, targets)
    for key, val in sorted(inv_entries.items()):
        print(f"      {key} = {val:.15e}")

    print("[3/3] Solving stochastic experiment...")
    L = params["stochastic"]["length"]
    W = params["stochastic"]["width"]
    exit_prob = solve_exit_prob(L, W)
    print(f"      exit_prob = {exit_prob:.15e}")

    # Step 4: Write results
    results = {
        "session_id": session_id,
        "integral": integral,
        "exit_prob": exit_prob,
    }
    results.update(inv_entries)

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nResults written to /app/results.json")


if __name__ == "__main__":
    main()
