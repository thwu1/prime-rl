"""Spectral spatial operators for the vorticity-streamfunction solver."""

import numpy as np
from numpy.fft import fft2, ifft2


def _poisson_invert(omega_hat, grid):
    """Spectral Poisson inversion."""
    return -omega_hat * grid['K2_inv']


def solve_poisson(omega, grid):
    """Solve for streamfunction from vorticity field."""
    return np.real(ifft2(_poisson_invert(fft2(omega), grid)))


def _velocity_from_psi_hat(psi_hat, grid):
    """Velocity components from streamfunction spectrum."""
    u = np.real(ifft2(1j * grid['KX'] * psi_hat))
    v = np.real(ifft2(-1j * grid['KY'] * psi_hat))
    return u, v


def compute_velocity(psi, grid):
    """Compute velocity field (u, v) from streamfunction."""
    return _velocity_from_psi_hat(fft2(psi), grid)


def compute_rhs(omega, grid, nu):
    """Evaluate the right-hand side of the vorticity equation."""
    omega_hat = fft2(omega)
    wh = omega_hat * grid['mask']

    psi_hat = _poisson_invert(wh, grid)
    u, v = _velocity_from_psi_hat(psi_hat, grid)

    dwdx = np.real(ifft2(1j * grid['KX'] * wh))
    dwdy = np.real(ifft2(1j * grid['KY'] * wh))

    nl_hat = fft2(u * dwdx + v * dwdy) * grid['mask']
    diff_hat = -nu * grid['K2'] * omega_hat

    return np.real(ifft2(-nl_hat + diff_hat))
