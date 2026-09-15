
"""Self-energy correction for the Ewald summation.

Removes the spurious self-interaction introduced by the Gaussian screening
charge distribution in both the real-space and reciprocal-space sums.
"""
import numpy as np


def compute_self_energy(charges, alpha):
    """
    Compute the Ewald self-energy correction.

    Parameters
    ----------
    charges : array_like, shape (N,)
        Particle charges.
    alpha : float
        Ewald splitting parameter.

    Returns
    -------
    energy : float
        Self-energy correction (always negative for non-zero charges).
    """
    q = np.asarray(charges, dtype=np.float64)
    return -(alpha / np.sqrt(np.pi)) * np.sum(q * q)
