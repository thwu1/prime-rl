"""Diagnostic quantities for the 2D Navier-Stokes solver."""

import numpy as np
from numpy.fft import fft2


def compute_energy(omega, grid, poisson_fn, velocity_fn):
    """Domain-averaged kinetic energy."""
    psi = poisson_fn(omega)
    u, v = velocity_fn(psi)
    return 0.5 * np.mean(u ** 2 + v ** 2)


def compute_enstrophy(omega):
    """Domain-averaged enstrophy."""
    return 0.5 * np.sum(omega ** 2)


def compute_energy_spectrum(omega, grid):
    """Shell-summed 1D energy spectrum."""
    omega_hat = fft2(omega)
    N = grid['N']
    power = np.abs(omega_hat) ** 2
    kmax_shell = int(np.sqrt(2) * N / 2) + 1
    spectrum = np.zeros(kmax_shell)
    for ki in range(1, kmax_shell):
        shell = (grid['K_mag'] >= ki) & (grid['K_mag'] < ki + 1)
        if np.any(shell):
            spectrum[ki] = 0.5 / N ** 4 * np.sum(power[shell])
    return spectrum
