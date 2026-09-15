"""Kuramoto-Sivashinsky equation with Fourier spectral discretization.

The KS equation: u_t + u*u_x + u_xx + u_xxxx = 0
on [0, L] with periodic boundary conditions.

In Fourier space: u_hat_t = Lk * u_hat + N(u_hat)
where Lk = k^2 - k^4 and N(u_hat) = -j*k/2 * FFT(IFFT(u_hat)^2)
"""

import numpy as np


def setup(L=32 * np.pi, N=128):
    """Initialize KS equation discretization.

    Parameters:
        L: domain length [0, L) with periodic BC
        N: number of Fourier modes (spatial grid points)

    Returns:
        dict with keys: x, k, Lk, u0_hat, L, N
    """
    x = L * np.arange(N) / N
    k = 2 * np.pi * np.fft.fftfreq(N, d=L / N)
    Lk = k ** 2 - k ** 4
    u0 = np.cos(x / 16) * (1 + np.sin(x / 16))
    u0_hat = np.fft.fft(u0)
    return {"x": x, "k": k, "Lk": Lk, "u0_hat": u0_hat, "L": L, "N": N}


def nonlinear(u_hat, k):
    """Compute the nonlinear term N(u_hat) = -j*k/2 * FFT(u^2).

    Parameters:
        u_hat: Fourier coefficients of u
        k: wavenumber array

    Returns:
        Nonlinear term in Fourier space
    """
    u = np.fft.ifft(u_hat).real
    return -0.5j * k * np.fft.fft(u ** 2)
