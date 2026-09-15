#!/usr/bin/env python3
"""
Create /app/matrix_functions.py with high-precision implementations
of matrix exponential, square root, and logarithm.

Algorithms:
- matrix_exp: Scaling-and-squaring with diagonal Pade approximation
- matrix_sqrt: Denman-Beavers coupled iteration
- matrix_log: Inverse scaling-and-squaring (repeated sqrt + Taylor log)

"""

IMPLEMENTATION = '''"""
High-precision matrix functions using mpmath arbitrary-precision arithmetic.

Provides:
  matrix_exp(A, dps) - Matrix exponential via scaling-and-squaring + Pade
  matrix_sqrt(A, dps) - Matrix square root via Denman-Beavers iteration
  matrix_log(A, dps) - Matrix logarithm via inverse scaling-and-squaring
"""
import mpmath


def matrix_exp(A, dps=15):
    """
    Compute the matrix exponential exp(A) to dps decimal digits.

    Algorithm: scaling-and-squaring with diagonal Pade approximation.
    1. Scale: B = A / 2^s so that ||B||_1 is small
    2. Approximate exp(B) via [p/p] Pade approximant
    3. Square s times: exp(A) = exp(B)^{2^s}
    """
    orig = mpmath.mp.dps
    mpmath.mp.dps = dps + 100
    try:
        A = mpmath.matrix(A)
        n = A.rows
        In = mpmath.eye(n)

        norm_A = float(mpmath.mnorm(A, 1))
        if norm_A < float(mpmath.power(10, -(dps + 80))):
            return mpmath.eye(n)

        # Choose scaling parameter s so ||A/2^s||_1 is well below 1
        s = max(0, int(mpmath.ceil(mpmath.log(2 * norm_A + 1, 2)))) + 4
        B = A / mpmath.power(2, s)

        # Pade order: scale with precision for guaranteed convergence
        p = max(13, dps // 2 + 5)

        # Pade [p/p] coefficients: c_k = (2p-k)! * p! / ((2p)! * k! * (p-k)!)
        coeffs = []
        for k in range(p + 1):
            c = mpmath.fac(2 * p - k) * mpmath.fac(p) / (
                mpmath.fac(2 * p) * mpmath.fac(k) * mpmath.fac(p - k)
            )
            coeffs.append(c)

        # Evaluate numerator N(B) and denominator D(B) by power accumulation
        Bk = mpmath.eye(n)
        N = coeffs[0] * In
        D = coeffs[0] * In
        for k in range(1, p + 1):
            Bk = Bk * B
            N = N + coeffs[k] * Bk
            sign = mpmath.mpf(-1) if k % 2 else mpmath.mpf(1)
            D = D + (sign * coeffs[k]) * Bk

        # R = D^{-1} * N via column-wise LU solve
        R = mpmath.matrix(n, n)
        for col in range(n):
            rhs = mpmath.matrix(n, 1)
            for row in range(n):
                rhs[row] = N[row, col]
            x = mpmath.lu_solve(D, rhs)
            for row in range(n):
                R[row, col] = x[row]

        # Squaring phase: R <- R^{2^s}
        for _ in range(s):
            R = R * R

        return R
    finally:
        mpmath.mp.dps = orig


def matrix_sqrt(A, dps=15):
    """
    Compute the principal matrix square root sqrt(A) to dps decimal digits.

    Algorithm: Denman-Beavers coupled iteration.
      Y_{k+1} = (Y_k + Z_k^{-1}) / 2
      Z_{k+1} = (Z_k + Y_k^{-1}) / 2
    Converges quadratically: Y -> sqrt(A), Z -> sqrt(A)^{-1}.
    Requires all eigenvalues of A to have positive real parts.
    """
    orig = mpmath.mp.dps
    mpmath.mp.dps = dps + 80
    try:
        A = mpmath.matrix(A)
        n = A.rows
        In = mpmath.eye(n)
        tol = mpmath.power(10, -(dps + 40))

        Y = mpmath.matrix(A)
        Z = mpmath.eye(n)

        for _ in range(300):
            # Compute inverses via LU solve
            Zinv = _lu_inverse(Z, n)
            Yinv = _lu_inverse(Y, n)

            Ynew = (Y + Zinv) / 2
            Znew = (Z + Yinv) / 2

            diff = float(mpmath.mnorm(Ynew - Y, 1))
            Y = Ynew
            Z = Znew
            if diff < float(tol):
                break

        return Y
    finally:
        mpmath.mp.dps = orig


def matrix_log(A, dps=15):
    """
    Compute the principal matrix logarithm log(A) to dps decimal digits.

    Algorithm: inverse scaling-and-squaring.
    1. Take s square roots to bring A^{1/2^s} close to I
    2. Compute log(A^{1/2^s}) via Taylor series of log(I + X)
    3. Scale: log(A) = 2^s * log(A^{1/2^s})
    """
    orig = mpmath.mp.dps
    mpmath.mp.dps = dps + 100
    try:
        A = mpmath.matrix(A)
        n = A.rows
        In = mpmath.eye(n)

        # Repeated square roots until ||B - I||_1 < 0.2
        B = mpmath.matrix(A)
        s = 0
        while float(mpmath.mnorm(B - In, 1)) > 0.2:
            B = matrix_sqrt(B, dps + 60)
            s += 1
            if s > 64:
                raise ValueError("matrix_log: failed to reduce to near-identity")

        # Taylor series: log(I + X) = X - X^2/2 + X^3/3 - ...
        X = B - In
        tol = mpmath.power(10, -(dps + 60))
        result = mpmath.matrix(n, n)
        Xk = mpmath.matrix(X)
        for k in range(1, 800):
            sign = mpmath.mpf(1) if k % 2 == 1 else mpmath.mpf(-1)
            term = Xk * (sign / mpmath.mpf(k))
            result = result + term
            if float(mpmath.mnorm(term, 1)) < float(tol):
                break
            Xk = Xk * X

        # Scale back: log(A) = 2^s * log(A^{1/2^s})
        result = result * mpmath.power(2, s)
        return result
    finally:
        mpmath.mp.dps = orig


def _lu_inverse(M, n):
    """Compute matrix inverse via column-wise LU solve."""
    In = mpmath.eye(n)
    result = mpmath.matrix(n, n)
    for col in range(n):
        rhs = mpmath.matrix(n, 1)
        for row in range(n):
            rhs[row] = In[row, col]
        x = mpmath.lu_solve(M, rhs)
        for row in range(n):
            result[row, col] = x[row]
    return result
'''

with open('/app/matrix_functions.py', 'w') as f:
    f.write(IMPLEMENTATION)

print("Created /app/matrix_functions.py successfully.")
