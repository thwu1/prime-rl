
import json
import math
import os
import functools
import pytest
import numpy as np
from scipy.sparse import csc_matrix
from scipy.sparse.linalg import splu
import mpmath

# DNA: session-specific parameters (must match calibration.json in environment)
SESSION_ID = "c9a7f3e2d5b14806"
ALPHA = 1.7320508075688772
BETA = 0.6180339887498949
MATRIX_N = 2000
BAND_COUNT = 8
TARGET_INDICES_1 = [37, 1000, 2000]
RECT_LENGTH = 9.4
RECT_WIDTH = 1.6


def sieve_primes(n):
    """Return the first n primes using Sieve of Eratosthenes."""
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
    for i in range(2, int(limit**0.5) + 1):
        if is_prime[i]:
            for j in range(i * i, limit + 1, i):
                is_prime[j] = False
    primes = [i for i in range(2, limit + 1) if is_prime[i]]
    while len(primes) < n:
        limit = int(limit * 1.5)
        is_prime = [True] * (limit + 1)
        is_prime[0] = is_prime[1] = False
        for i in range(2, int(limit**0.5) + 1):
            if is_prime[i]:
                for j in range(i * i, limit + 1, i):
                    is_prime[j] = False
        primes = [i for i in range(2, limit + 1) if is_prime[i]]
    return primes[:n]


def load_results():
    """Load the agent's results from /app/results.json."""
    with open("/app/results.json") as f:
        return json.load(f)


@functools.lru_cache(maxsize=1)
def compute_ref_integral():
    """Reference: integral_0^inf cos(alpha*x^2 + beta*x)/cosh(x) dx."""
    mpmath.mp.dps = 30
    alpha = mpmath.mpf("1.7320508075688772")
    beta = mpmath.mpf("0.6180339887498949")
    result = mpmath.quad(
        lambda x: mpmath.cos(alpha * x ** 2 + beta * x) / mpmath.cosh(x),
        [0, 2, 5, 10, 20, 50],
    )
    return float(result)


@functools.lru_cache(maxsize=1)
def compute_ref_matrix_entries():
    """Reference: diagonal entries of A^{-1} for the 2000x2000 sparse matrix."""
    N = MATRIX_N
    primes = sieve_primes(N)
    offsets = [2 ** k for k in range(BAND_COUNT)]

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
    for idx_1 in TARGET_INDICES_1:
        idx_0 = idx_1 - 1
        rhs = np.zeros(N)
        rhs[idx_0] = 1.0
        sol = lu.solve(rhs)
        entries[idx_1] = float(sol[idx_0])

    return entries


@functools.lru_cache(maxsize=1)
def compute_ref_exit_prob():
    """Reference: Brownian exit probability through short ends of 9.4 x 1.6 rectangle.

    Uses harmonic measure series on [-L/2, L/2] x [-W/2, W/2]:
    P = (4/pi) * sum_{n>=0} (-1)^n / ((2n+1) * cosh((2n+1)*pi*L/(2*W)))
    with L = 9.4, W = 1.6.
    """
    mpmath.mp.dps = 30
    L = mpmath.mpf("9.4")
    W = mpmath.mpf("1.6")
    P = mpmath.mpf(0)
    for n in range(300):
        coeff = 2 * n + 1
        arg = coeff * mpmath.pi * L / (2 * W)
        term = mpmath.power(-1, n) / (coeff * mpmath.cosh(arg))
        P += term
        if abs(term) < mpmath.power(10, -28):
            break
    P *= 4 / mpmath.pi
    return float(P)


def relative_error(computed, reference):
    """Compute relative error between computed and reference values."""
    if reference == 0:
        return abs(computed)
    return abs(computed - reference) / abs(reference)


class TestNumericalChallenge:
    """Verify the agent's numerical results against independently computed references."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.results = load_results()

    def test_results_file_exists(self):
        assert os.path.exists("/app/results.json"), "results.json not found at /app/"

    def test_session_id(self):
        assert self.results.get("session_id") == SESSION_ID, (
            f"session_id must match calibration: expected '{SESSION_ID}', "
            f"got '{self.results.get('session_id')}'"
        )

    def test_all_keys_present(self):
        required = ["session_id", "integral", "inv_37", "inv_1000", "inv_2000", "exit_prob"]
        for key in required:
            assert key in self.results, f"Key '{key}' missing from results.json"

    def test_integral(self):
        ref = compute_ref_integral()
        val = float(self.results["integral"])
        err = relative_error(val, ref)
        assert err < 1e-9, (
            f"Integral: got {val}, expected {ref}, relative error {err:.2e}"
        )

    def test_inv_37(self):
        refs = compute_ref_matrix_entries()
        val = float(self.results["inv_37"])
        ref = refs[37]
        err = relative_error(val, ref)
        assert err < 1e-9, (
            f"A^-1[37,37]: got {val}, expected {ref}, relative error {err:.2e}"
        )

    def test_inv_1000(self):
        refs = compute_ref_matrix_entries()
        val = float(self.results["inv_1000"])
        ref = refs[1000]
        err = relative_error(val, ref)
        assert err < 1e-9, (
            f"A^-1[1000,1000]: got {val}, expected {ref}, relative error {err:.2e}"
        )

    def test_inv_2000(self):
        refs = compute_ref_matrix_entries()
        val = float(self.results["inv_2000"])
        ref = refs[2000]
        err = relative_error(val, ref)
        assert err < 1e-9, (
            f"A^-1[2000,2000]: got {val}, expected {ref}, relative error {err:.2e}"
        )

    def test_exit_prob(self):
        ref = compute_ref_exit_prob()
        val = float(self.results["exit_prob"])
        err = relative_error(val, ref)
        assert err < 1e-9, (
            f"Exit prob: got {val}, expected {ref}, relative error {err:.2e}"
        )
