"""
Tests for high-precision matrix functions: exp, sqrt, log.

Verifies correctness via mathematical identities and known closed-form values,
all checked to 40 decimal digits of precision.

"""

import sys
sys.path.insert(0, '/app')

import pytest
import mpmath

from matrix_functions import matrix_exp, matrix_log, matrix_sqrt

DPS = 40
TOL = mpmath.mpf(10) ** (-DPS)


def _diag(vals):
    """Create diagonal matrix from list of values."""
    n = len(vals)
    M = mpmath.matrix(n, n)
    for i in range(n):
        M[i, i] = vals[i]
    return M


def assert_mat_close(A, B, msg=""):
    """Assert two mpmath matrices are element-wise close within TOL."""
    assert A.rows == B.rows and A.cols == B.cols, \
        f"{msg} shape mismatch: ({A.rows},{A.cols}) vs ({B.rows},{B.cols})"
    for i in range(A.rows):
        for j in range(A.cols):
            d = abs(A[i, j] - B[i, j])
            assert d < TOL, \
                f"{msg} element [{i},{j}]: diff={float(d):.3e}, tol={float(TOL):.3e}"


class TestMatrixExpKnownValues:
    """Matrix exponential: tests with known closed-form results."""

    def test_zero_matrix(self):
        """exp(0) = I."""
        mpmath.mp.dps = DPS + 20
        Z = mpmath.matrix(3, 3)
        result = matrix_exp(Z, DPS)
        assert_mat_close(result, mpmath.eye(3), "exp(0)!=I")

    def test_diagonal(self):
        """exp(diag(a,b,c)) = diag(exp(a),exp(b),exp(c))."""
        mpmath.mp.dps = DPS + 20
        vals = [mpmath.mpf('1'), mpmath.mpf('2'), mpmath.mpf('-3')]
        A = _diag(vals)
        result = matrix_exp(A, DPS)
        expected = _diag([mpmath.exp(v) for v in vals])
        assert_mat_close(result, expected, "exp(diag)")

    def test_rotation_2x2(self):
        """exp([[0,-t],[t,0]]) = rotation matrix by angle t."""
        mpmath.mp.dps = DPS + 20
        t = mpmath.mpf('1') / mpmath.mpf('3')
        A = mpmath.matrix([[0, -t], [t, 0]])
        result = matrix_exp(A, DPS)
        expected = mpmath.matrix([
            [mpmath.cos(t), -mpmath.sin(t)],
            [mpmath.sin(t), mpmath.cos(t)]
        ])
        assert_mat_close(result, expected, "exp(rotation)")

    def test_nilpotent_3x3(self):
        """exp of nilpotent (A^3=0): exp(A) = I + A + A^2/2."""
        mpmath.mp.dps = DPS + 20
        A = mpmath.matrix([
            [0, 1, 0],
            [0, 0, 1],
            [0, 0, 0]
        ])
        result = matrix_exp(A, DPS)
        expected = mpmath.matrix([
            [1, 1, mpmath.mpf('0.5')],
            [0, 1, 1],
            [0, 0, 1]
        ])
        assert_mat_close(result, expected, "exp(nilpotent)")


class TestMatrixExpIdentity:
    """Matrix exponential: identity-based tests on hard matrices."""

    def test_ward_matrix(self):
        """exp(A)*exp(-A) = I for Ward's 3x3 test matrix (norm ~30)."""
        mpmath.mp.dps = DPS + 20
        A = mpmath.matrix([
            [21, 17, 6],
            [-5, -1, -6],
            [4, 4, 16]
        ])
        eA = matrix_exp(A, DPS)
        emA = matrix_exp(-A, DPS)
        assert_mat_close(eA * emA, mpmath.eye(3), "Ward: exp(A)*exp(-A)!=I")

    def test_large_norm_3x3(self):
        """exp(A)*exp(-A) = I for matrix with ||A||_1 > 100."""
        mpmath.mp.dps = DPS + 20
        A = mpmath.matrix([
            [mpmath.mpf('80'), mpmath.mpf('-40'), mpmath.mpf('10')],
            [mpmath.mpf('20'), mpmath.mpf('-60'), mpmath.mpf('30')],
            [mpmath.mpf('-10'), mpmath.mpf('50'), mpmath.mpf('70')]
        ])
        eA = matrix_exp(A, DPS)
        emA = matrix_exp(-A, DPS)
        assert_mat_close(eA * emA, mpmath.eye(3), "large norm: exp(A)*exp(-A)!=I")


class TestMatrixSqrt:
    """Matrix square root tests."""

    def test_identity(self):
        """sqrt(I) = I."""
        mpmath.mp.dps = DPS + 20
        I3 = mpmath.eye(3)
        result = matrix_sqrt(I3, DPS)
        assert_mat_close(result, I3, "sqrt(I)!=I")

    def test_diagonal(self):
        """sqrt(diag(a,b,c)) = diag(sqrt(a),sqrt(b),sqrt(c))."""
        mpmath.mp.dps = DPS + 20
        vals = [mpmath.mpf('4'), mpmath.mpf('9'), mpmath.mpf('16')]
        A = _diag(vals)
        result = matrix_sqrt(A, DPS)
        expected = _diag([mpmath.sqrt(v) for v in vals])
        assert_mat_close(result, expected, "sqrt(diag)")

    def test_spd_3x3(self):
        """sqrt(A)^2 = A for 3x3 symmetric positive-definite matrix."""
        mpmath.mp.dps = DPS + 20
        A = mpmath.matrix([
            [mpmath.mpf('5'), mpmath.mpf('2'), mpmath.mpf('1')],
            [mpmath.mpf('2'), mpmath.mpf('6'), mpmath.mpf('2')],
            [mpmath.mpf('1'), mpmath.mpf('2'), mpmath.mpf('7')]
        ])
        S = matrix_sqrt(A, DPS)
        assert_mat_close(S * S, A, "sqrt(A)^2!=A for 3x3 SPD")

    def test_spd_4x4(self):
        """sqrt(A)^2 = A for 4x4 symmetric positive-definite matrix."""
        mpmath.mp.dps = DPS + 20
        A = mpmath.matrix([
            [10, 3, 1, 0],
            [3, 10, 3, 1],
            [1, 3, 10, 3],
            [0, 1, 3, 10]
        ])
        S = matrix_sqrt(A, DPS)
        assert_mat_close(S * S, A, "sqrt(A)^2!=A for 4x4 SPD")

    def test_nonsymmetric_repeated_eigenvalue(self):
        """sqrt(A)^2 = A for non-diagonalizable matrix (eigenvalue 2, multiplicity 2)."""
        mpmath.mp.dps = DPS + 20
        A = mpmath.matrix([
            [mpmath.mpf('2'), mpmath.mpf('1')],
            [mpmath.mpf('0'), mpmath.mpf('2')]
        ])
        S = matrix_sqrt(A, DPS)
        assert_mat_close(S * S, A, "sqrt(A)^2!=A for non-symmetric")


class TestMatrixLog:
    """Matrix logarithm tests."""

    def test_identity(self):
        """log(I) = 0."""
        mpmath.mp.dps = DPS + 20
        I3 = mpmath.eye(3)
        result = matrix_log(I3, DPS)
        Z = mpmath.matrix(3, 3)
        assert_mat_close(result, Z, "log(I)!=0")

    def test_diagonal(self):
        """log(diag(a,b,c)) = diag(log(a),log(b),log(c))."""
        mpmath.mp.dps = DPS + 20
        vals = [mpmath.mpf('2'), mpmath.mpf('5'), mpmath.mpf('7')]
        A = _diag(vals)
        result = matrix_log(A, DPS)
        expected = _diag([mpmath.log(v) for v in vals])
        assert_mat_close(result, expected, "log(diag)")

    def test_exp_log_roundtrip(self):
        """exp(log(A)) = A for symmetric positive-definite A."""
        mpmath.mp.dps = DPS + 20
        A = mpmath.matrix([
            [mpmath.mpf('4'), mpmath.mpf('1'), mpmath.mpf('0')],
            [mpmath.mpf('1'), mpmath.mpf('5'), mpmath.mpf('1')],
            [mpmath.mpf('0'), mpmath.mpf('1'), mpmath.mpf('3')]
        ])
        logA = matrix_log(A, DPS)
        result = matrix_exp(logA, DPS)
        assert_mat_close(result, A, "exp(log(A))!=A")

    def test_log_exp_roundtrip(self):
        """log(exp(A)) = A for small-eigenvalue matrix."""
        mpmath.mp.dps = DPS + 20
        A = mpmath.matrix([
            [mpmath.mpf('0.5'), mpmath.mpf('0.1')],
            [mpmath.mpf('-0.1'), mpmath.mpf('0.3')]
        ])
        eA = matrix_exp(A, DPS)
        result = matrix_log(eA, DPS)
        assert_mat_close(result, A, "log(exp(A))!=A")


class TestCrossValidation:
    """Cross-validation: consistency between all three functions."""

    def test_sqrt_equals_exp_half_log(self):
        """sqrt(A) = exp(log(A)/2) for symmetric positive-definite A."""
        mpmath.mp.dps = DPS + 20
        A = mpmath.matrix([
            [mpmath.mpf('3'), mpmath.mpf('1')],
            [mpmath.mpf('1'), mpmath.mpf('4')]
        ])
        sqrtA = matrix_sqrt(A, DPS)
        logA = matrix_log(A, DPS)
        half_log = logA / 2
        exp_half = matrix_exp(half_log, DPS)
        assert_mat_close(sqrtA, exp_half, "sqrt(A)!=exp(log(A)/2)")

    def test_exp_doubling(self):
        """exp(2A) = exp(A)^2."""
        mpmath.mp.dps = DPS + 20
        A = mpmath.matrix([
            [mpmath.mpf('1'), mpmath.mpf('0.5')],
            [mpmath.mpf('-0.3'), mpmath.mpf('0.8')]
        ])
        exp2A = matrix_exp(2 * A, DPS)
        expA = matrix_exp(A, DPS)
        assert_mat_close(exp2A, expA * expA, "exp(2A)!=exp(A)^2")
