"""Descending Landen sequence for elliptic moduli reduction."""

import numpy as np


def landen_sequence(k, n=7):
    """Compute descending Landen sequence starting from modulus k.

    Parameters
    ----------
    k : float
        Starting elliptic modulus, 0 < k < 1.
    n : int
        Maximum number of sequence elements (including k itself).

    Returns
    -------
    list of float
        Descending Landen sequence [k_0, k_{-1}, k_{-2}, ...].
    """
    seq = [float(k)]
    ki = float(k)
    for _ in range(n - 1):
        kp = np.sqrt(1.0 - ki * ki)
        ki = (ki / (1.0 + kp)) ** 2
        seq.append(ki)
        if ki < 1e-18:
            break
    return seq
