"""Complete elliptic integral of the first kind K(k) via Landen transformation."""

import numpy as np
from landen import landen_sequence


def complete_elliptic_K(k):
    """Compute K(k) using the product formula from Landen transformations.

    Parameters
    ----------
    k : float
        Elliptic modulus, 0 <= k < 1.

    Returns
    -------
    float
        K(k), the complete elliptic integral of the first kind.
    """
    k = float(k)
    if k < 1e-15:
        return np.pi / 2.0
    if k > 1.0 - 1e-15:
        return 1e15

    seq = landen_sequence(k, n=30)
    K = np.pi / 2.0
    for i in range(len(seq)):
        K *= (1.0 + seq[i])
    return K
