#!/usr/bin/env python3
"""
Solution for Multi-Precision Numerical Analysis Challenge.

Reads problem specifications from /app/challenge.json and data files,
solves three numerical problems:
1. Parametric oscillatory integral via Lambert-W zero-finding + quadosc
2. Sparse matrix inverse entry via scipy sparse direct solve
3. Slowly convergent alternating series via mpmath Shanks acceleration

"""

import os
import math
import json


def load_challenge_config():
    with open('/app/challenge.json') as f:
        return json.load(f)


def solve_problem1(params_file):
    """
    Compute I(a) = integral_0^inf cos(a*t*exp(t)) dt for parameter values
    loaded from the data file.

    The integrand oscillates with increasing frequency as t grows.
    The zeros of cos(a*t*e^t) occur when a*t*e^t = (n + 1/2)*pi, i.e.,
    t*e^t = (n + 1/2)*pi/a, giving t = W((n + 1/2)*pi/a) where W is the
    Lambert W function. We pass these zeros to mpmath.quadosc.
    """
    with open(params_file) as f:
        params = json.load(f)
    a_values = params['values']

    from mpmath import mp, mpf, quadosc, cos, exp, pi, lambertw, inf
    mp.dps = 30

    results = []
    for a_val in a_values:
        a = mpf(a_val)
        f = lambda t, _a=a: cos(_a * t * exp(t))
        zeros_fn = lambda n, _a=a: lambertw((n + mpf('0.5')) * pi / _a)
        result = quadosc(f, [0, inf], zeros=zeros_fn)
        results.append(mp.nstr(result, 16))
    return results


def solve_problem2(config_file):
    """
    Compute (M^{-1})_{row,col} for the sparse matrix M defined by the config.
    Generate primes via sieve, construct CSC sparse matrix with Fibonacci-offset
    bands, solve M*x = e_col using scipy's sparse direct solver.
    """
    with open(config_file) as f:
        config = json.load(f)

    N = config['size']
    fibs = config['off_diagonal']['offsets']
    target_row = config['target']['row'] - 1  # Convert to 0-indexed
    target_col = config['target']['col'] - 1

    import numpy as np
    from scipy.sparse import csc_matrix
    from scipy.sparse.linalg import spsolve

    upper = int(N * (math.log(N) + math.log(math.log(N)) + 2))
    sieve = bytearray(b'\x01') * (upper + 1)
    sieve[0] = sieve[1] = 0
    for i in range(2, int(upper**0.5) + 1):
        if sieve[i]:
            for j in range(i * i, upper + 1, i):
                sieve[j] = 0
    primes = [i for i in range(2, upper + 1) if sieve[i]][:N]
    assert len(primes) == N, f"Need {N} primes, only found {len(primes)}"

    rows, cols, vals = [], [], []
    for i in range(N):
        rows.append(i)
        cols.append(i)
        vals.append(float(primes[i]))
        for fv in fibs:
            if i + fv < N:
                rows.append(i)
                cols.append(i + fv)
                vals.append(1.0)
            if i - fv >= 0:
                rows.append(i)
                cols.append(i - fv)
                vals.append(1.0)

    M = csc_matrix((vals, (rows, cols)), shape=(N, N))

    e = np.zeros(N)
    e[target_col] = 1.0
    x = spsolve(M, e)
    return f"{x[target_row]:.15e}"


def solve_problem3(series_file):
    """
    Compute the alternating series defined in the series definition file.
    Uses mpmath.nsum with Shanks transformation for reliable convergence
    of this conditionally convergent series with O(1/(n*ln(n))) decay.
    """
    with open(series_file) as f:
        series_def = json.load(f)

    # Verify the series structure matches expectations
    assert 'H_n' in series_def['term_function']['expression']

    from mpmath import mp, mpf, nsum, harmonic, inf
    mp.dps = 30

    def term(n):
        n_int = int(n)
        sign = mpf(1) if n_int % 2 == 1 else mpf(-1)
        return sign / (n * harmonic(n_int))

    S = nsum(term, [1, inf], method='shanks')
    return mp.nstr(S, 16)


if __name__ == '__main__':
    config = load_challenge_config()

    # Create output directory
    os.makedirs('/app/results', exist_ok=True)

    problems = {p['id']: p for p in config['problems']}

    # Problem 1: Oscillatory Integrals
    p1 = problems['P1']
    print("=== Problem 1: Parametric Oscillatory Integrals ===")
    integrals = solve_problem1(p1['data_files'][0])
    with open(p1['output_file'], 'w') as f:
        for val in integrals:
            f.write(val + '\n')
    for i, v in enumerate(integrals, 1):
        print(f"  I({i}) = {v}")

    # Problem 2: Sparse Matrix
    p2 = problems['P2']
    print("\n=== Problem 2: Sparse Matrix Inverse Entry ===")
    entry = solve_problem2(p2['data_files'][0])
    with open(p2['output_file'], 'w') as f:
        f.write(entry + '\n')
    print(f"  (M^-1)[1,1] = {entry}")

    # Problem 3: Series
    p3 = problems['P3']
    print("\n=== Problem 3: Alternating Series Sum ===")
    series = solve_problem3(p3['data_files'][0])
    with open(p3['output_file'], 'w') as f:
        f.write(series + '\n')
    print(f"  S = {series}")

    print("\nAll problems solved successfully.")
