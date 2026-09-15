"""Condition number estimators for benchmark."""
import numpy as np
import scipy.linalg


def tricond_nopiv(A):
    """Condition estimate from unpivoted QR diagonal ratio."""
    R = np.linalg.qr(A, mode="r")
    d = np.abs(np.diag(R))
    return float(np.max(d) / np.min(d))


def tricond_piv(A):
    """Condition estimate from pivoted QR diagonal ratio."""
    _, R, _ = scipy.linalg.qr(A, pivoting=True)
    d = np.abs(np.diag(R))
    return float(np.max(d) / np.min(d))


def _hager_norm1_inv(A):
    """Estimate ||A^{-1}||_1 iteratively."""
    n = A.shape[0]
    x = np.ones(n) / n
    est = 0.0

    for k in range(6):
        w = np.linalg.solve(A, x)
        est_new = np.linalg.norm(w, 1)

        if k > 0 and est_new <= est:
            break
        est = est_new

        s = np.sign(w)
        s[s == 0] = 1.0

        z = np.linalg.solve(A.T, s)

        if np.max(np.abs(z)) <= np.dot(z, x):
            break

        j = int(np.argmax(np.abs(z)))
        x = np.zeros(n)
        x[j] = 1.0

    return est


def hager_cond1(A):
    """1-norm condition number estimate."""
    norm1_A = float(np.linalg.norm(A, 1))
    norm1_Ainv = _hager_norm1_inv(A)
    return norm1_Ainv


def exact_cond2(A):
    """Exact 2-norm condition number via SVD."""
    s = np.linalg.svd(A, compute_uv=False)
    return float(s[0] / s[-1])
