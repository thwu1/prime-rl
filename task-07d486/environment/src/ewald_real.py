
"""Real-space component of the Ewald summation.

Computes the real-space (short-range) contribution to the electrostatic
energy and forces using the complementary error function (erfc) screening.
Uses minimum image convention for the nearest image of each pair.
"""
import numpy as np
from scipy.special import erfc


def compute_real_space(positions, charges, box_length, alpha):
    """
    Compute real-space Ewald energy and forces.

    Parameters
    ----------
    positions : array_like, shape (N, 3)
        Particle positions in Cartesian coordinates.
    charges : array_like, shape (N,)
        Particle charges.
    box_length : float
        Side length of the cubic simulation box.
    alpha : float
        Ewald splitting parameter.

    Returns
    -------
    energy : float
        Real-space contribution to the electrostatic energy.
    forces : ndarray, shape (N, 3)
        Real-space contribution to forces on each particle.
    """
    pos = np.asarray(positions, dtype=np.float64)
    q = np.asarray(charges, dtype=np.float64)
    N = len(q)
    L = float(box_length)
    inv_sqrt_pi = 1.0 / np.sqrt(np.pi)

    energy = 0.0
    forces = np.zeros((N, 3))

    for i in range(N - 1):
        dr = pos[i + 1:] - pos[i]
        # Apply minimum image convention
        dr -= L * np.floor(dr / L)

        r2 = np.sum(dr * dr, axis=1)
        r = np.sqrt(r2)

        ar = alpha * r
        erfc_ar = erfc(ar)
        exp_ar2 = np.exp(-ar * ar)
        qq = q[i] * q[i + 1:]

        energy += np.sum(qq * erfc_ar / r)

        f_mag = qq * (erfc_ar / r2 + 2.0 * alpha * inv_sqrt_pi * exp_ar2 / r) / r
        f_vec = f_mag[:, np.newaxis] * dr
        forces[i] -= np.sum(f_vec, axis=0)
        forces[i + 1:] += f_vec

    return energy, forces
