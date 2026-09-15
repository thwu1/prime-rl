
import pytest
import os
import numpy as np
from scipy import sparse
from scipy.sparse.linalg import spsolve
from scipy.integrate import quad as scipy_quad
from scipy.optimize import brentq


def read_answer(path):
    """Read a single float from a file."""
    assert os.path.exists(path), f"Answer file {path} not found"
    with open(path, "r") as f:
        text = f.read().strip()
    assert len(text) > 0, f"Answer file {path} is empty"
    return float(text)


def relative_error(computed, reference):
    """Compute relative error."""
    if reference == 0:
        return abs(computed)
    return abs(computed - reference) / abs(reference)


def prime_sieve(limit):
    """Sieve of Eratosthenes returning list of primes up to limit."""
    sieve = [True] * (limit + 1)
    sieve[0] = sieve[1] = False
    for i in range(2, int(limit**0.5) + 1):
        if sieve[i]:
            for j in range(i * i, limit + 1, i):
                sieve[j] = False
    return [i for i in range(limit + 1) if sieve[i]]


TOLERANCE = 5e-10  # 10 significant digits


class TestProblemP1:
    """Oscillatory integral: integral_0^1 x^{-1} cos(3 x^{-1} ln x) dx"""

    def test_answer_file_exists(self):
        assert os.path.exists("/app/results/problem_P1.txt")

    def test_answer_accuracy(self):
        import mpmath

        mpmath.mp.dps = 30

        def integrand(s):
            if s == 0:
                return mpmath.mpf(1) / 3
            w = mpmath.lambertw(s / 3)
            return mpmath.cos(s) * w / (s * (1 + w))

        reference = float(
            mpmath.quadosc(integrand, [0, mpmath.inf], period=2 * mpmath.pi)
        )

        computed = read_answer("/app/results/problem_P1.txt")
        err = relative_error(computed, reference)
        assert err < TOLERANCE, (
            f"Problem P1: relative error {err:.2e} exceeds {TOLERANCE:.0e} "
            f"(computed={computed:.15e}, reference={reference:.15e})"
        )


class TestProblemP2:
    """Sparse matrix inverse: A^{-1}[1,1] for 10000x10000 prime-diagonal matrix"""

    def test_answer_file_exists(self):
        assert os.path.exists("/app/results/problem_P2.txt")

    def test_answer_accuracy(self):
        N = 10000
        primes = prime_sieve(200000)[:N]
        assert len(primes) == N

        offsets_list = [2**k for k in range(13)]  # 1, 2, 4, ..., 4096

        diag_data = [np.array(primes, dtype=np.float64)]
        diag_offsets = [0]
        for d in offsets_list:
            diag_data.append(np.ones(N - d))
            diag_offsets.append(d)
            diag_data.append(np.ones(N - d))
            diag_offsets.append(-d)

        A = sparse.diags(diag_data, diag_offsets, shape=(N, N), format="csc")

        e1 = np.zeros(N)
        e1[0] = 1.0
        x = spsolve(A, e1)
        reference = x[0]

        computed = read_answer("/app/results/problem_P2.txt")
        err = relative_error(computed, reference)
        assert err < TOLERANCE, (
            f"Problem P2: relative error {err:.2e} exceeds {TOLERANCE:.0e} "
            f"(computed={computed:.15e}, reference={reference:.15e})"
        )


class TestProblemP3:
    """Brownian exit probability for 12x1 rectangle"""

    def test_answer_file_exists(self):
        assert os.path.exists("/app/results/problem_P3.txt")

    def test_answer_accuracy(self):
        import mpmath

        mpmath.mp.dps = 40

        L = 12
        half_L = mpmath.mpf(L) / 2  # 6
        result = mpmath.mpf(0)
        for k in range(200):
            n = 2 * k + 1
            sign = mpmath.mpf((-1) ** k)
            term = (
                4 / (n * mpmath.pi) * sign / mpmath.cosh(half_L * n * mpmath.pi)
            )
            result += term
            if abs(term) < mpmath.power(10, -35):
                break

        reference = float(result)

        computed = read_answer("/app/results/problem_P3.txt")
        err = relative_error(computed, reference)
        assert err < TOLERANCE, (
            f"Problem P3: relative error {err:.2e} exceeds {TOLERANCE:.0e} "
            f"(computed={computed:.15e}, reference={reference:.15e})"
        )


class TestProblemP4:
    """Biased random walk: find epsilon for P_return = 1/3"""

    def test_answer_file_exists(self):
        assert os.path.exists("/app/results/problem_P4.txt")

    def test_answer_accuracy(self):
        def G00_fast(eps):
            """Compute lattice Green's function G(0,0;eps) using scipy.

            Uses substitution phi = sqrt(theta) to remove the 1/sqrt(theta)
            endpoint singularity, yielding a smooth integrand for scipy.quad.
            """
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

        # Root-find: G(0,0; eps) = 3/2  <=>  P_return = 1 - 1/G = 1/3
        reference = brentq(
            lambda e: G00_fast(e) - 1.5, 0.01, 0.24, xtol=1e-14, rtol=1e-14
        )

        computed = read_answer("/app/results/problem_P4.txt")
        err = relative_error(computed, reference)
        assert err < TOLERANCE, (
            f"Problem P4: relative error {err:.2e} exceeds {TOLERANCE:.0e} "
            f"(computed={computed:.15e}, reference={reference:.15e})"
        )
