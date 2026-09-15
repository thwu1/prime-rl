"""
Naive implementations of matrix functions using truncated Taylor series.

These demonstrate the expected interface but FAIL on challenging matrices:
- matrix_exp: catastrophic cancellation for ||A|| >> 1
- matrix_sqrt: divergence for matrices far from identity
- matrix_log: divergence when ||A - I|| >= 1

Use as a reference for the function signatures and basic behavior only.
"""
import mpmath


def matrix_exp(A, dps=15):
    """Compute matrix exponential via truncated Taylor series.

    Fails for matrices with large norms due to catastrophic cancellation:
    intermediate terms grow as ||A||^k / k! while the final result may be O(1).
    """
    mpmath.mp.dps = dps + 15
    A = mpmath.matrix(A)
    n = A.rows
    result = mpmath.eye(n)
    term = mpmath.eye(n)
    for k in range(1, 60):
        term = term * A / k
        result = result + term
        if float(mpmath.mnorm(term, 1)) < float(mpmath.power(10, -(dps + 10))):
            break
    return result


def matrix_sqrt(A, dps=15):
    """Compute matrix square root via Newton iteration starting from I.

    X_{k+1} = (X_k + A * X_k^{-1}) / 2

    Fails for matrices far from identity: convergence basin is limited,
    and may converge to a non-principal square root or diverge entirely.
    """
    mpmath.mp.dps = dps + 15
    A = mpmath.matrix(A)
    n = A.rows
    X = mpmath.eye(n)
    for _ in range(100):
        Xinv = mpmath.inverse(X)
        Xnew = (X + A * Xinv) / 2
        diff = float(mpmath.mnorm(Xnew - X, 1))
        X = Xnew
        if diff < float(mpmath.power(10, -(dps + 5))):
            break
    return X


def matrix_log(A, dps=15):
    """Compute matrix logarithm via Taylor series log(I + X).

    log(I + X) = X - X^2/2 + X^3/3 - ...

    Only converges when ||A - I|| < 1. Diverges for matrices with
    eigenvalues far from 1. No preprocessing to reduce to convergent regime.
    """
    mpmath.mp.dps = dps + 15
    A = mpmath.matrix(A)
    n = A.rows
    X = A - mpmath.eye(n)
    result = mpmath.matrix(n, n)
    Xk = mpmath.matrix(X)
    for k in range(1, 100):
        sign = mpmath.mpf(1) if k % 2 == 1 else mpmath.mpf(-1)
        term = Xk * (sign / mpmath.mpf(k))
        result = result + term
        if float(mpmath.mnorm(term, 1)) < float(mpmath.power(10, -(dps + 10))):
            break
        Xk = Xk * X
    return result
