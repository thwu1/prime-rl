"""Experiment: Sparse Matrix Inverse

Constructs a structured sparse matrix A of dimension N x N.
The task is to compute specific diagonal entries of A^{-1}.
See targets.json for which entries are needed and the output key format.

Matrix dimension and band count are session-specific (see /app/calibration.json).
"""


def matrix_dimension():
    """The matrix is N x N. Session-specific from calibration."""
    return 2000


def _is_prime(n):
    if n < 2:
        return False
    if n < 4:
        return True
    if n % 2 == 0 or n % 3 == 0:
        return False
    k = 5
    while k * k <= n:
        if n % k == 0 or n % (k + 2) == 0:
            return False
        k += 6
    return True


def diagonal_entry(i):
    """Return A[i,i] for 1-indexed row i.

    The i-th diagonal element equals the i-th prime number.
    This trial-division implementation works for small i;
    for the full matrix an efficient sieve is recommended.
    """
    count = 0
    candidate = 1
    while count < i:
        candidate += 1
        if _is_prime(candidate):
            count += 1
    return candidate


def offdiagonal_distances():
    """A[i,j] = 1 whenever |i-j| belongs to this set (1-indexed i,j).
    All other off-diagonal entries are zero.
    Band count is session-specific from calibration.
    """
    return [2 ** k for k in range(8)]  # {1, 2, 4, 8, 16, 32, 64, 128}


OFFDIAG_VALUE = 1.0
