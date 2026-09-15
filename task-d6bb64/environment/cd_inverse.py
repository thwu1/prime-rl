"""Inverse Jacobian elliptic function cd^{-1}(w, k) via Newton-Raphson."""

import numpy as np
from elliptic_k import complete_elliptic_K
from jacobi_cd import elliptic_cd


def elliptic_cd_inv(w, k):
    """Compute u such that cd(u, k) = w.

    Uses Newton-Raphson iteration with a suitable initial guess
    based on the relationship between cd and cosine.

    Parameters
    ----------
    w : complex or float
        Target value.
    k : float
        Elliptic modulus, 0 < k < 1.

    Returns
    -------
    complex
        u in the principal domain such that cd(u, k) = w.
    """
    w = complex(w)
    k = float(k)

    if k < 1e-15:
        return np.arccos(w)

    K = complete_elliptic_K(k)
    kp = np.sqrt(1.0 - k * k)
    Kp = complete_elliptic_K(kp)

    w_r = np.real(w)
    w_i = np.imag(w)

    if abs(w_i) < 1e-12 and -1.0 <= w_r <= 1.0:
        u = np.arccos(w_r) * (2 * K / np.pi)
    elif abs(w_i) < 1e-12 and w_r > 1.0:
        val = min(w_r, 1.0 / k - 1e-10)
        u = np.arccosh(val) * (Kp / (np.pi / 2.0))
    elif abs(w_i) < 1e-12 and w_r < -1.0:
        val = min(-w_r, 1.0 / k - 1e-10)
        u = 2 * K + np.arccosh(val) * (Kp / (np.pi / 2.0))
    else:
        u = np.arccos(w) * (2 * K / np.pi)

    delta = K * 1e-8
    for iteration in range(150):
        f_val = elliptic_cd(u, k) - w
        if abs(f_val) < 1e-14:
            break
        df = (elliptic_cd(u + delta, k) - elliptic_cd(u - delta, k)) / (2 * delta)
        if abs(df) < 1e-30:
            delta *= 10
            continue
        step = f_val / df
        u = u - step

    return u
