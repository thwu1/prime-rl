
"""Reciprocal-space component of the Ewald summation.

Computes the long-range (Fourier space) contribution to the electrostatic
energy and forces via structure factors and the Gaussian screening function.
"""
import numpy as np


def compute_reciprocal(positions, charges, box_length, alpha, k_max):
    """
    Compute reciprocal-space Ewald energy and forces.

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
    k_max : int
        Maximum k-vector index in each dimension.

    Returns
    -------
    energy : float
        Reciprocal-space contribution to the electrostatic energy.
    forces : ndarray, shape (N, 3)
        Reciprocal-space contribution to forces on each particle.
    """
    pos = np.asarray(positions, dtype=np.float64)
    q = np.asarray(charges, dtype=np.float64)
    N = len(q)
    L = float(box_length)
    V = L ** 3

    energy = 0.0
    forces = np.zeros((N, 3))

    two_pi_over_L = 2.0 * np.pi / L
    inv_4alpha2 = 1.0 / (4.0 * alpha ** 2)
    # Prefactor for the reciprocal-space sum
    pref_const = 2.0 * np.pi / V

    for nx in range(-k_max, k_max + 1):
        for ny in range(-k_max, k_max + 1):
            for nz in range(-k_max, k_max + 1):
                if nx == 0 and ny == 0 and nz == 0:
                    continue

                k_vec = np.array([nx, ny, nz], dtype=np.float64) * two_pi_over_L
                k2 = np.dot(k_vec, k_vec)

                pref = (pref_const / k2) * np.exp(-k2 * inv_4alpha2)

                k_dot_r = pos @ k_vec
                cos_kr = np.cos(k_dot_r)
                sin_kr = np.sin(k_dot_r)

                S_cos = np.dot(q, cos_kr)
                S_sin = np.dot(q, sin_kr)

                energy += 0.5 * pref * (S_cos ** 2 + S_sin ** 2)

                f_scalar = pref * q * (S_sin * cos_kr - S_cos * sin_kr)
                forces -= np.outer(f_scalar, k_vec)

    return energy, forces
