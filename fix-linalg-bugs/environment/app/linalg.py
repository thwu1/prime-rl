"""
Arbitrary-precision numerical linear algebra library.

Provides LU, QR, and Cholesky decomposition with corresponding linear system
solvers for both real and complex matrices, using mpmath for precision arithmetic.
"""

import mpmath


def _to_matrix(data):
    """Convert nested list or vector to mpmath.matrix."""
    if isinstance(data, mpmath.matrix):
        return data.copy()
    if isinstance(data[0], (list, tuple)):
        m = len(data)
        n = len(data[0])
        M = mpmath.matrix(m, n)
        for i in range(m):
            for j in range(n):
                M[i, j] = data[i][j]
        return M
    else:
        m = len(data)
        M = mpmath.matrix(m, 1)
        for i in range(m):
            M[i] = data[i]
        return M


def _is_complex(M):
    """Check if matrix has any complex-valued elements."""
    for i in range(M.rows):
        for j in range(M.cols):
            if isinstance(M[i, j], mpmath.mpc):
                return True
    return False


def lu_decompose(A):
    """
    LU decomposition with partial pivoting.

    Returns (LU, pivots) in compact form: L stored below diagonal,
    U on and above diagonal.
    """
    A = _to_matrix(A).copy()
    n = A.rows
    if n != A.cols:
        raise ValueError("need square matrix")
    tol = mpmath.absmin(mpmath.mnorm(A, 1) * mpmath.eps)
    pivots = [None] * (n - 1)

    for j in range(n - 1):
        best = 0
        for k in range(j, n):
            row_sum = mpmath.fsum(mpmath.absmin(A[k, l]) for l in range(j, n))
            if mpmath.absmin(row_sum) <= tol:
                raise ZeroDivisionError("matrix is numerically singular")
            scaled = mpmath.absmin(A[k, j]) / row_sum
            if scaled > best:
                best = scaled
                pivots[j] = k
        if pivots[j] is None:
            raise ZeroDivisionError("matrix is numerically singular")
        if pivots[j] != j:
            for c in range(n):
                A[j, c], A[pivots[j], c] = A[pivots[j], c], A[j, c]
        if mpmath.absmin(A[j, j]) <= tol:
            raise ZeroDivisionError("matrix is numerically singular")
        for i in range(j + 1, n):
            A[i, j] /= A[j, j]
            for k in range(j + 1, n):
                A[i, k] -= A[i, j] * A[j, k]

    if pivots and mpmath.absmin(A[n - 1, n - 1]) <= tol:
        raise ZeroDivisionError("matrix is numerically singular")
    return A, pivots


def lu_solve(A, b):
    """Solve Ax = b via LU decomposition with partial pivoting."""
    A = _to_matrix(A)
    b = _to_matrix(b).copy()
    n = A.rows
    if n != A.cols:
        raise ValueError("need square matrix")
    LU, pivots = lu_decompose(A)

    for k in range(len(pivots)):
        if pivots[k] is not None and pivots[k] != k:
            b[k], b[pivots[k]] = b[pivots[k]], b[k]

    # Forward substitution (L)
    for i in range(1, n):
        for j in range(i):
            b[i] -= LU[i, j] * b[j]

    # Back substitution (U)
    for i in range(n - 1, -1, -1):
        for j in range(i + 1, n):
            b[i] -= LU[i, j] * b[j]
        b[i] /= LU[i, i]

    return b


def householder_qr_solve(A, b):
    """
    Solve Ax = b via Householder QR decomposition.

    Handles determined (m == n) and overdetermined (m > n) systems.
    For overdetermined systems, computes the least-squares solution.

    Parameters
    ----------
    A : matrix-like (m x n, m >= n)
    b : vector-like (m x 1)

    Returns
    -------
    x : mpmath.matrix (n x 1)
        Solution vector.
    residual : float
        Norm of the residual ||Ax - b||.
    """
    A = _to_matrix(A).copy()
    b = _to_matrix(b).copy()
    m, n = A.rows, A.cols
    if m < n:
        raise ValueError("cannot solve underdetermined system")

    # Build augmented matrix [A | b]
    Aug = mpmath.matrix(m, n + 1)
    for i in range(m):
        for j in range(n):
            Aug[i, j] = A[i, j]
        Aug[i, n] = b[i]

    # Householder triangularization
    p = []
    for j in range(n):
        s = mpmath.fsum(abs(Aug[i, j]) ** 2 for i in range(j, m))
        if not abs(s) > mpmath.eps:
            raise ValueError("matrix is numerically singular")

        # Choose sign for numerical stability
        p.append(-mpmath.sign(mpmath.re(Aug[j, j])) * mpmath.sqrt(s))

        kappa = mpmath.mpf(1) / (s - p[j] * Aug[j, j])
        Aug[j, j] -= p[j]

        # Apply Householder reflection to trailing columns
        for k in range(j + 1, n + 1):
            y = mpmath.fsum(
                mpmath.conj(Aug[i, j]) * Aug[i, k] for i in range(j, m)
            ) * kappa
            for i in range(j, m):
                Aug[i, k] -= Aug[i, j] * y

    # Back-substitution to recover x
    x = mpmath.matrix(n, 1)
    for i in range(n):
        x[i] = Aug[i, n]
    for i in range(n - 1, -1, -1):
        x[i] -= mpmath.fsum(Aug[i, j] * x[j] for j in range(i + 1, n))
        x[i] /= p[i]

    # Compute residual norm
    if m > n:
        r = mpmath.matrix(m - n, 1)
        for i in range(m - n):
            r[i] = Aug[m - 1 - i, n]
        res = float(mpmath.norm(r))
    else:
        res = float(mpmath.norm(A * x - b))

    return x, res


def cholesky_decompose(A):
    """
    Cholesky decomposition of a Hermitian positive-definite matrix.

    Returns lower triangular L such that A = L * L^H.
    For real symmetric A, this reduces to A = L * L^T.
    """
    A = _to_matrix(A)
    n = A.rows
    if n != A.cols:
        raise ValueError("need square matrix")
    L = mpmath.matrix(n)

    for j in range(n):
        diag = mpmath.re(A[j, j]) - mpmath.re(mpmath.fsum(
            L[j, k] * mpmath.conj(L[j, k]) for k in range(j)
        ))
        if diag <= 0:
            raise ValueError("matrix is not positive-definite")
        L[j, j] = mpmath.sqrt(diag)
        for i in range(j + 1, n):
            off = mpmath.fsum(
                L[i, k] * mpmath.conj(L[j, k]) for k in range(j)
            )
            L[i, j] = (A[i, j] - off) / L[j, j]

    return L


def cholesky_solve(A, b):
    """
    Solve Ax = b for Hermitian positive-definite A via Cholesky factorization.

    Decomposes A = L L^H, then solves:
      1. L y = b   (forward substitution)
      2. L^H x = y (back substitution)
    """
    A = _to_matrix(A)
    b = _to_matrix(b).copy()
    n = A.rows
    if n != A.cols:
        raise ValueError("need square matrix")

    L = cholesky_decompose(A)

    # Forward substitution: L y = b
    for i in range(n):
        b[i] -= mpmath.fsum(L[i, j] * b[j] for j in range(i))
        b[i] /= L[i, i]

    # Back substitution: L^H x = y
    x = mpmath.matrix(n, 1)
    for i in range(n):
        x[i] = b[i]
    for i in range(n - 1, -1, -1):
        x[i] -= mpmath.fsum(L[j, i] * x[j] for j in range(i + 1, n))
        x[i] /= L[i, i]

    return x


def qr_factorize(A):
    """
    QR factorization via Householder reflections.

    Computes A = Q R where Q is orthogonal (real) or unitary (complex)
    and R is upper triangular. Handles both real and complex matrices.

    Parameters
    ----------
    A : matrix-like (m x n, m >= n)

    Returns
    -------
    Q : mpmath.matrix (m x m)
    R : mpmath.matrix (m x n)
    """
    A = _to_matrix(A).copy()
    m, n = A.rows, A.cols
    if m < n:
        raise ValueError("need m >= n")

    cmplx = _is_complex(A)
    tau = mpmath.matrix(n, 1)

    if cmplx:
        _factor_complex(A, tau, m, n)
    else:
        _factor_real(A, tau, m, n)

    # Extract R from upper triangular part
    R = A.copy()
    for j in range(n):
        for i in range(j + 1, m):
            R[i, j] = mpmath.mpf(0)

    # Backward accumulation to form Q
    one = mpmath.mpc(1, 0) if cmplx else mpmath.mpf(1)
    zero = mpmath.mpc(0, 0) if cmplx else mpmath.mpf(0)

    A.cols += (m - n)
    for j in range(m):
        A[j, j] = one
        for i in range(j):
            A[i, j] = zero

    for j in range(n - 1, -1, -1):
        t = -tau[j]
        A[j, j] += t
        for k in range(j + 1, m):
            if cmplx:
                y = mpmath.fsum(
                    A[i, j] * mpmath.conj(A[i, k]) for i in range(j + 1, m)
                )
                temp = t * mpmath.conj(y)
            else:
                y = mpmath.fsum(
                    A[i, j] * A[i, k] for i in range(j + 1, m)
                )
                temp = t * y
            A[j, k] = temp
            for i in range(j + 1, m):
                A[i, k] += A[i, j] * temp
        for i in range(j + 1, m):
            A[i, j] *= t

    Q = mpmath.matrix(m, m)
    for i in range(m):
        for j2 in range(m):
            Q[i, j2] = A[i, j2]

    R_full = mpmath.matrix(m, n)
    for i in range(m):
        for j2 in range(n):
            R_full[i, j2] = R[i, j2]

    return Q, R_full


def _factor_complex(A, tau, m, n):
    """Householder factorization for complex matrices (LAPACK-style)."""
    for j in range(n):
        alpha = A[j, j]
        alphr = mpmath.re(alpha)
        alphi = mpmath.im(alpha)

        if (m - j) >= 2:
            xnorm = mpmath.fsum(
                A[i, j] * A[i, j] for i in range(j + 1, m)
            )
            xnorm = mpmath.re(mpmath.sqrt(xnorm))
        else:
            xnorm = mpmath.mpf(0)

        if xnorm == 0 and alphi == 0:
            tau[j] = mpmath.mpc(0, 0)
            continue

        if alphr < 0:
            beta = mpmath.sqrt(alphr ** 2 + alphi ** 2 + xnorm ** 2)
        else:
            beta = -mpmath.sqrt(alphr ** 2 + alphi ** 2 + xnorm ** 2)

        tau[j] = mpmath.mpc((beta - alphr) / beta, -alphi / beta)
        t = -mpmath.conj(tau[j])
        za = mpmath.mpf(1) / (alpha - beta)

        for i in range(j + 1, m):
            A[i, j] *= za

        A[j, j] = mpmath.mpc(1, 0)
        for k in range(j + 1, n):
            y = mpmath.fsum(
                A[i, j] * mpmath.conj(A[i, k]) for i in range(j, m)
            )
            temp = t * mpmath.conj(y)
            for i in range(j, m):
                A[i, k] += A[i, j] * temp

        A[j, j] = mpmath.mpc(mpmath.re(beta), 0)


def _factor_real(A, tau, m, n):
    """Householder factorization for real matrices."""
    for j in range(n):
        alpha = A[j, j]

        if (m - j) > 2:
            xnorm = mpmath.fsum(A[i, j] ** 2 for i in range(j + 1, m))
            xnorm = mpmath.sqrt(xnorm)
        elif (m - j) == 2:
            xnorm = abs(A[m - 1, j])
        else:
            xnorm = mpmath.mpf(0)

        if xnorm == 0:
            tau[j] = mpmath.mpf(0)
            continue

        if alpha < 0:
            beta = mpmath.sqrt(alpha ** 2 + xnorm ** 2)
        else:
            beta = -mpmath.sqrt(alpha ** 2 + xnorm ** 2)

        tau[j] = (beta - alpha) / beta
        t = -tau[j]
        da = mpmath.mpf(1) / (alpha - beta)

        for i in range(j + 1, m):
            A[i, j] *= da

        A[j, j] = mpmath.mpf(1)
        for k in range(j + 1, n):
            y = mpmath.fsum(A[i, j] * A[i, k] for i in range(j, m))
            temp = t * y
            for i in range(j, m):
                A[i, k] += A[i, j] * temp

        A[j, j] = beta


def condition_number(A):
    """Estimate condition number (1-norm) of a square matrix."""
    A = _to_matrix(A)
    return float(mpmath.mnorm(A, 1) * mpmath.mnorm(mpmath.inverse(A), 1))
