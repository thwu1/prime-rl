#!/usr/bin/env python3
"""
Reference solution for the Numerical Analysis Precision Challenge.
Reads problem specifications from /app/challenge/ and solves each to high precision.
"""

import json
import os
import re
import numpy as np
import mpmath
from scipy import sparse
from scipy.sparse.linalg import spsolve
from scipy.integrate import quad as scipy_quad
from scipy.optimize import brentq
from fractions import Fraction

os.makedirs("/app/results", exist_ok=True)

# Step 1: Read manifest to understand output structure
with open("/app/challenge/manifest.json") as f:
    manifest = json.load(f)

output_dir = manifest["output"]["dir"]
naming_pattern = manifest["output"]["naming"]
problem_ids = manifest["problems"]

print(f"Found {len(problem_ids)} problems: {problem_ids}")
print(f"Output to: {output_dir}/{naming_pattern}")


def prime_sieve(limit):
    """Sieve of Eratosthenes returning list of primes up to limit."""
    sieve = [True] * (limit + 1)
    sieve[0] = sieve[1] = False
    for i in range(2, int(limit**0.5) + 1):
        if sieve[i]:
            for j in range(i * i, limit + 1, i):
                sieve[j] = False
    return [i for i in range(limit + 1) if sieve[i]]


# ==================== Problem P1 ====================
# Read formulation and parameters from challenge files

def solve_P1():
    with open("/app/challenge/problems/P1/params.json") as f:
        params = json.load(f)
    alpha = params["alpha"]
    print(f"P1: oscillatory integral with alpha={alpha}")

    mpmath.mp.dps = 50

    def integrand(s):
        if s == 0:
            return mpmath.mpf(1) / alpha
        w = mpmath.lambertw(s / alpha)
        return mpmath.cos(s) * w / (s * (1 + w))

    result = mpmath.quadosc(integrand, [0, mpmath.inf], period=2 * mpmath.pi)
    return float(result)


# ==================== Problem P2 ====================
# Read matrix spec and offsets from challenge files

def solve_P2():
    with open("/app/challenge/problems/P2/offsets.txt") as f:
        lines = f.readlines()

    N = None
    target = None
    offsets = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            m = re.search(r"N\s*=\s*(\d+)", line)
            if m:
                N = int(m.group(1))
            m = re.search(r"target_entry\s*=\s*\((\d+),(\d+)\)", line)
            if m:
                target = (int(m.group(1)), int(m.group(2)))
            continue
        offsets.append(int(line))

    print(f"P2: {N}x{N} sparse matrix, offsets={offsets}, target={target}")

    primes = prime_sieve(200000)[:N]
    assert len(primes) == N

    diag_data = [np.array(primes, dtype=np.float64)]
    diag_offsets = [0]
    for d in offsets:
        diag_data.append(np.ones(N - d))
        diag_offsets.append(d)
        diag_data.append(np.ones(N - d))
        diag_offsets.append(-d)

    A = sparse.diags(diag_data, diag_offsets, shape=(N, N), format="csc")

    # target is 1-indexed
    ei = np.zeros(N)
    ei[target[1] - 1] = 1.0
    x = spsolve(A, ei)
    return x[target[0] - 1]


# ==================== Problem P3 ====================
# Read domain from challenge files

def solve_P3():
    with open("/app/challenge/problems/P3/domain.json") as f:
        domain = json.load(f)
    L = domain["length"]
    W = domain["width"]
    print(f"P3: Brownian exit on {L}x{W} rectangle")

    mpmath.mp.dps = 40
    half_L = mpmath.mpf(L) / 2
    result = mpmath.mpf(0)
    for k in range(200):
        n = 2 * k + 1
        sign = mpmath.mpf((-1) ** k)
        term = 4 / (n * mpmath.pi) * sign / mpmath.cosh(half_L * n * mpmath.pi)
        result += term
        if abs(term) < mpmath.power(10, -35):
            break
    return float(result)


# ==================== Problem P4 ====================
# Read constraints from challenge files

def solve_P4():
    with open("/app/challenge/problems/P4/constraints.json") as f:
        constraints = json.load(f)

    target_str = constraints["target"]["value"]
    target_prob = float(Fraction(target_str))
    # P_return = 1 - 1/G => G = 1/(1 - P_return)
    target_G = 1.0 / (1.0 - target_prob)
    print(f"P4: biased walk, target return prob = {target_str} => G = {target_G}")

    def G00(eps):
        def integrand(phi):
            theta2 = phi * phi
            R = 1 - np.cos(theta2) / 2
            S = 2 * eps * np.sin(theta2)
            a = complex(R, -S)
            val = a * a - 0.25
            if abs(val) < 1e-30:
                return 0.0
            w = val ** 0.5
            return (1.0 / w).real * 2 * phi

        result, _ = scipy_quad(integrand, 0, np.sqrt(np.pi), limit=300)
        return result / np.pi

    eps_result = brentq(
        lambda e: G00(e) - target_G, 0.01, 0.24, xtol=1e-14, rtol=1e-14
    )
    return eps_result


# ==================== Main ====================
if __name__ == "__main__":
    solvers = {"P1": solve_P1, "P2": solve_P2, "P3": solve_P3, "P4": solve_P4}

    for pid in problem_ids:
        print(f"\nSolving {pid}...")
        ans = solvers[pid]()
        print(f"  {pid} = {ans:.15e}")

        outfile = os.path.join(output_dir, naming_pattern.replace("{ID}", pid))
        with open(outfile, "w") as f:
            f.write(f"{float(ans):.15e}\n")

    print("\nAll problems solved. Results written to /app/results/")
