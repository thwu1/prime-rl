"""Grid construction for 2D spectral solver on periodic domain."""

import numpy as np
from numpy.fft import fftfreq


def build_grid(N, dealias=True):
    """Build physical and spectral grids for a [0, 2pi)^2 periodic box."""
    x = np.linspace(0, 2.0 * np.pi, N, endpoint=False)
    X, Y = np.meshgrid(x, x, indexing='ij')

    k = fftfreq(N, d=1.0 / N)
    KX, KY = np.meshgrid(k, k, indexing='ij')
    K2 = KX ** 2 + KY ** 2
    K_mag = np.sqrt(K2)

    K2_inv = np.zeros((N, N))
    nz = K2 > 0
    K2_inv[nz] = 1.0 / K2[nz]

    kmax = N // 3
    mask = np.ones((N, N), dtype=float)
    if dealias:
        mask[(np.abs(KX) > kmax) | (np.abs(KY) > kmax)] = 0.0

    return {
        'X': X, 'Y': Y,
        'KX': KX, 'KY': KY,
        'K2': K2, 'K_mag': K_mag,
        'K2_inv': K2_inv,
        'mask': mask,
        'N': N,
    }
