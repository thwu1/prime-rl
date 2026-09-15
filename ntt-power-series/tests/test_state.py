"""Tests for the hybrid C/Python formal power series library.

"""
import sys
sys.path.insert(0, '/app')
import os
import ctypes
import pytest

MOD = 998244353


def power_mod(base, exp, mod=MOD):
    result = 1
    base %= mod
    while exp > 0:
        if exp & 1:
            result = result * base % mod
        exp >>= 1
        base = base * base % mod
    return result


def modinv_test(a, mod=MOD):
    return power_mod(a, mod - 2, mod)


def brute_multiply(a, b):
    """O(n^2) polynomial multiplication for verification."""
    if not a or not b:
        return [0]
    n = len(a) + len(b) - 1
    result = [0] * n
    for i in range(len(a)):
        for j in range(len(b)):
            result[i + j] = (result[i + j] + a[i] * b[j]) % MOD
    return result


def poly_trunc(a, n):
    """Truncate/pad polynomial to exactly n terms."""
    return (list(a) + [0] * n)[:n]


# ---------------------------------------------------------------------------
# Build verification
# ---------------------------------------------------------------------------

class TestBuild:
    def test_shared_library_exists(self):
        assert os.path.isfile('/app/libntt.so'), \
            "libntt.so not found at /app/; Makefile must produce it"

    def test_shared_library_loadable(self):
        lib = ctypes.CDLL('/app/libntt.so')
        assert lib.poly_multiply is not None, \
            "poly_multiply symbol not found in libntt.so"
        assert lib.ntt is not None, \
            "ntt symbol not found in libntt.so"
        assert lib.free_poly is not None, \
            "free_poly symbol not found in libntt.so"


# ---------------------------------------------------------------------------
# NTT-based multiplication via ctypes
# ---------------------------------------------------------------------------

class TestMultiply:
    def test_simple_squares(self):
        from ntt_binding import multiply
        result = multiply([1, 1], [1, 1])
        assert result == [1, 2, 1], f"Expected [1, 2, 1], got {result}"

    def test_multiply_known(self):
        from ntt_binding import multiply
        a = [1, 2, 3]
        b = [4, 5]
        result = multiply(a, b)
        expected = brute_multiply(a, b)
        assert result == expected, f"Expected {expected}, got {result}"

    def test_multiply_large_coefficients(self):
        """Exercises the full mod-range to catch ctypes type mismatches."""
        from ntt_binding import multiply
        import random
        rng = random.Random(42)
        for trial in range(8):
            na = rng.randint(5, 50)
            nb = rng.randint(5, 50)
            a = [rng.randint(MOD // 2, MOD - 1) for _ in range(na)]
            b = [rng.randint(MOD // 2, MOD - 1) for _ in range(nb)]
            result = multiply(a, b)
            expected = brute_multiply(a, b)
            assert result == expected, \
                f"Mismatch on trial {trial} for sizes {na}x{nb}"

    def test_multiply_random_brute(self):
        from ntt_binding import multiply
        import random
        rng = random.Random(12345)
        for trial in range(10):
            na = rng.randint(1, 60)
            nb = rng.randint(1, 60)
            a = [rng.randint(0, MOD - 1) for _ in range(na)]
            b = [rng.randint(0, MOD - 1) for _ in range(nb)]
            result = multiply(a, b)
            expected = brute_multiply(a, b)
            assert result == expected, \
                f"Mismatch on trial {trial} for sizes {na}x{nb}"


# ---------------------------------------------------------------------------
# Polynomial modular inverse
# ---------------------------------------------------------------------------

class TestPolyInv:
    def test_inv_geometric_series(self):
        from fps import poly_inv
        n = 16
        f = [1, MOD - 1]  # 1 - x
        inv_f = poly_inv(f, n)
        expected = [1] * n  # 1/(1-x) = 1 + x + x^2 + ...
        assert inv_f == expected, f"Expected all ones, got {inv_f}"

    def test_inv_identity(self):
        from fps import poly_inv
        n = 32
        f = [1, 3, 7, 2, 11, 5]
        inv_f = poly_inv(f, n)
        product = brute_multiply(f, inv_f)
        product = poly_trunc(product, n)
        expected = [1] + [0] * (n - 1)
        assert product == expected, "f * inv(f) != 1 mod x^n"

    def test_inv_constant(self):
        from fps import poly_inv
        n = 8
        f = [5]
        inv_f = poly_inv(f, n)
        expected = [modinv_test(5)] + [0] * (n - 1)
        assert inv_f == expected, f"Expected {expected}, got {inv_f}"


# ---------------------------------------------------------------------------
# Polynomial logarithm
# ---------------------------------------------------------------------------

class TestPolyLn:
    def test_ln_one_plus_x(self):
        from fps import poly_ln
        n = 8
        f = [1, 1]  # 1 + x
        result = poly_ln(f, n)
        # ln(1+x) = x - x^2/2 + x^3/3 - x^4/4 + ...
        expected = [0]
        for k in range(1, n):
            if k % 2 == 1:
                expected.append(modinv_test(k))
            else:
                expected.append((MOD - modinv_test(k)) % MOD)
        assert result == expected, f"Expected {expected}, got {result}"

    def test_ln_product_identity(self):
        """ln(f * g) = ln(f) + ln(g) when f[0]=g[0]=1"""
        from fps import poly_ln
        from ntt_binding import multiply
        n = 16
        f = [1, 2, 3, 4]
        g = [1, 5, 7, 2]
        fg = multiply(f, g)
        fg_padded = poly_trunc(fg, n)
        ln_fg = poly_ln(fg_padded, n)
        ln_f = poly_ln(f, n)
        ln_g = poly_ln(g, n)
        ln_sum = [(ln_f[i] + ln_g[i]) % MOD for i in range(n)]
        assert ln_fg == ln_sum, "ln(f*g) != ln(f) + ln(g)"


# ---------------------------------------------------------------------------
# Polynomial exponentiation (exp)
# ---------------------------------------------------------------------------

class TestPolyExp:
    def test_exp_of_x(self):
        from fps import poly_exp
        n = 10
        f = [0, 1]  # x
        result = poly_exp(f, n)
        # e^x = sum x^k / k!
        factorials = [1]
        for i in range(1, n):
            factorials.append(factorials[-1] * i % MOD)
        expected = [modinv_test(factorials[i]) for i in range(n)]
        assert result == expected, f"Expected {expected}, got {result}"

    def test_exp_ln_roundtrip(self):
        from fps import poly_exp, poly_ln
        n = 32
        f = [1, 5, 3, 9, 7, 2, 4, 8]
        ln_f = poly_ln(f, n)
        recovered = poly_exp(ln_f, n)
        assert recovered == poly_trunc(f, n), "exp(ln(f)) != f"

    def test_exp_zero(self):
        from fps import poly_exp
        n = 8
        f = [0]
        result = poly_exp(f, n)
        expected = [1] + [0] * (n - 1)
        assert result == expected, f"exp(0) should be 1, got {result}"


# ---------------------------------------------------------------------------
# Polynomial square root
# ---------------------------------------------------------------------------

class TestPolySqrt:
    def test_sqrt_square_identity(self):
        from fps import poly_sqrt
        n = 32
        f = [1, 2, 5, 3, 7]
        sq = poly_sqrt(f, n)
        product = brute_multiply(sq, sq)
        product = poly_trunc(product, n)
        assert product == poly_trunc(f, n), "sqrt(f)^2 != f"

    def test_sqrt_perfect_square(self):
        from fps import poly_sqrt
        n = 16
        f = [1, 2, 1]  # (1+x)^2
        sq = poly_sqrt(f, n)
        product = brute_multiply(sq, sq)
        product = poly_trunc(product, n)
        assert product == poly_trunc(f, n), "sqrt((1+x)^2)^2 != (1+x)^2"


# ---------------------------------------------------------------------------
# Polynomial power
# ---------------------------------------------------------------------------

class TestPolyPow:
    def test_pow_cube(self):
        from fps import poly_pow
        n = 16
        f = [1, 1]  # 1 + x
        result = poly_pow(f, 3, n)
        expected = poly_trunc([1, 3, 3, 1], n)
        assert result == expected, f"(1+x)^3 mismatch: {result}"

    def test_pow_against_brute(self):
        from fps import poly_pow
        n = 32
        f = [1, 2, 3]
        k = 5
        result = poly_pow(f, k, n)
        brute = [1]
        for _ in range(k):
            brute = brute_multiply(brute, f)
        expected = poly_trunc(brute, n)
        assert result == expected, f"f^{k} mismatch"

    def test_pow_zero(self):
        from fps import poly_pow
        n = 8
        f = [1, 5, 3]
        result = poly_pow(f, 0, n)
        expected = [1] + [0] * (n - 1)
        assert result == expected, f"f^0 should be 1, got {result}"

    def test_pow_one(self):
        from fps import poly_pow
        n = 16
        f = [1, 7, 2, 9]
        result = poly_pow(f, 1, n)
        expected = poly_trunc(f, n)
        assert result == expected, f"f^1 should be f, got {result}"
