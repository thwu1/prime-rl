"""Jacobian elliptic function cd(u, k) = cn(u,k)/dn(u,k) via ascending Landen recursion."""

import numpy as np
from landen import landen_sequence
from elliptic_k import complete_elliptic_K


def elliptic_cd(u, k):
    """Evaluate cd(u, k) using ascending Landen recursion.

    At the bottom of the Landen sequence the modulus is near zero,
    so cd approximates cosine. The ascending recursion reconstructs
    cd at the original modulus.

    Parameters
    ----------
    u : complex or float
        Argument (not normalized by K).
    k : float
        Elliptic modulus, 0 < k < 1.

    Returns
    -------
    complex
        cd(u, k).
    """
    u = complex(u)
    k = float(k)

    if k < 1e-15:
        return np.cos(u)

    seq = landen_sequence(k, n=30)
    K = complete_elliptic_K(k)

    x = u / K
    w = np.cos(np.pi * x / 2.0)

    for i in range(len(seq) - 2, -1, -1):
        ki = seq[i + 1]
        w = (1.0 + ki) * w / (1.0 + ki * w)

    return w
