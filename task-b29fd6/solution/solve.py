#!/usr/bin/env python3
"""

Numerical Precision Challenge -- reference solution.
Step 1: Explore /app/challenges/ to discover and parse problem specifications.
Step 2: Solve each problem to >= 10 significant digits.
"""

import json
import math
import os
import sys


# ================================================================
# Step 1: Explore the challenge directory
# ================================================================

def discover_challenges():
    """Read the challenge index and inspect each subdirectory."""
    base = "/app/challenges"
    with open(os.path.join(base, "index.json")) as f:
        index = json.load(f)

    challenges = {}
    for entry in index["challenges"]:
        cid = entry["id"]
        cdir = os.path.join(base, entry["path"])
        files = os.listdir(cdir)
        challenges[cid] = {
            "category": entry["category"],
            "dir": cdir,
            "files": files,
        }
        print(f"  Discovered {cid}: category={entry['category']}, files={files}")

    return challenges, index["output"]


# ================================================================
# Solver for C1: Oscillatory Integral
#   Parsed from formulation.tex:
#   I = lim_{eps->0} int_eps^1 x^{-1} cos(x^{-1} ln x) dx
#
#   Substitution t = -ln(x) gives  I = int_0^inf cos(t * exp(t)) dt.
#   quadosc with Lambert W zeros for efficient summation.
# ================================================================

def solve_c1():
    from mpmath import mp, mpf, quadosc, cos, exp, lambertw, inf, pi

    mp.dps = 25

    result = quadosc(lambda t: cos(t * exp(t)),
                     [mpf(0), inf],
                     zeros=lambda n: lambertw((2 * mpf(n) - 1) * pi / 2))

    result = float(result)
    print(f"  C1 = {result:.16e}")
    return result


# ================================================================
# Solver for C2: Global Optimization
#   Parsed from objective.py and task.json:
#   min f(x,y) over R^2 — function read from objective.py
#
#   Dense grid search -> Nelder-Mead -> L-BFGS-B polish.
# ================================================================

def solve_c2():
    import numpy as np
    from scipy.optimize import minimize

    def f_scalar(xy):
        x, y = xy
        return (np.exp(np.sin(50 * x))
                + np.sin(60 * np.exp(y))
                + np.sin(70 * np.sin(x))
                + np.sin(np.sin(80 * y))
                - np.sin(10 * (x + y))
                + (x ** 2 + y ** 2) / 4)

    xs = np.linspace(-5, 5, 2001)
    ys = np.linspace(-5, 5, 2001)
    X, Y = np.meshgrid(xs, ys)
    Z = (np.exp(np.sin(50 * X))
         + np.sin(60 * np.exp(Y))
         + np.sin(70 * np.sin(X))
         + np.sin(np.sin(80 * Y))
         - np.sin(10 * (X + Y))
         + (X ** 2 + Y ** 2) / 4)

    idx = np.unravel_index(np.argmin(Z), Z.shape)
    x0 = [float(X[idx]), float(Y[idx])]

    r1 = minimize(f_scalar, x0, method='Nelder-Mead',
                  options={'xatol': 1e-14, 'fatol': 1e-14, 'maxiter': 200000})

    r2 = minimize(f_scalar, r1.x, method='L-BFGS-B',
                  options={'ftol': 1e-15, 'gtol': 1e-15, 'maxiter': 200000})

    result = float(r2.fun)
    print(f"  C2 = {result:.16e}")
    return result


# ================================================================
# Solver for C3: Sparse Matrix Inverse Entry
#   Parsed from matrix_spec.toml and query.json:
#   A is 20000x20000 with primes on diagonal, 1 at |i-j| = 2^k.
#   Compute (A^{-1})_{1,1} via CG with Jacobi preconditioner.
# ================================================================

def generate_primes(n):
    """Sieve of Eratosthenes returning the first n primes."""
    if n < 1:
        return []
    upper = max(20, int(n * (math.log(n) + math.log(max(2, math.log(n))))) + 1000)
    sieve = bytearray(b'\x01') * (upper + 1)
    sieve[0] = sieve[1] = 0
    for i in range(2, int(upper ** 0.5) + 1):
        if sieve[i]:
            sieve[i * i::i] = bytearray(len(sieve[i * i::i]))
    primes = [i for i, v in enumerate(sieve) if v]
    if len(primes) < n:
        raise RuntimeError(f"Sieve too small: got {len(primes)} primes, need {n}")
    return primes[:n]


def solve_c3():
    import numpy as np
    from scipy.sparse import csc_matrix, diags
    from scipy.sparse.linalg import cg

    N = 20000
    primes = generate_primes(N)

    rows = list(range(N))
    cols = list(range(N))
    data = [float(p) for p in primes]

    for k in range(15):          # offsets 2^0 .. 2^14 = 1 .. 16384
        d = 1 << k
        for i in range(N - d):
            rows.append(i);       cols.append(i + d);  data.append(1.0)
            rows.append(i + d);   cols.append(i);      data.append(1.0)

    A = csc_matrix((data, (rows, cols)), shape=(N, N))

    e1 = np.zeros(N)
    e1[0] = 1.0

    diag_inv = 1.0 / np.array([float(p) for p in primes])
    M = diags(diag_inv)

    x, info = cg(A, e1, M=M, rtol=1e-15, maxiter=10000)
    if info != 0:
        raise RuntimeError(f"CG did not converge, info={info}")

    result = float(x[0])
    print(f"  C3 = {result:.16e}")
    return result


# ================================================================

def main():
    print("Step 1: Exploring /app/challenges/\n")
    challenges, output_spec = discover_challenges()

    print(f"\nOutput format: {output_spec}\n")
    print("Step 2: Solving challenges\n")

    a1 = solve_c1()
    a2 = solve_c2()
    a3 = solve_c3()

    outpath = output_spec["file"]
    with open(outpath, "w") as f:
        f.write(f"{a1:.16e}\n")
        f.write(f"{a2:.16e}\n")
        f.write(f"{a3:.16e}\n")

    print(f"\nAnswers written to {outpath}")


if __name__ == "__main__":
    main()
