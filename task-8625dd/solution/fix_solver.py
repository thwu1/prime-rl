"""Fix all bugs in the ns2d solver and write bug report."""

import json
import os

# ============================================================
# Fix Bug 1 (Poisson sign) and Bug 2 (velocity wavenumbers)
# in spectral.py
# ============================================================
spectral_fixed = '''\
"""Spectral spatial operators for the vorticity-streamfunction solver."""

import numpy as np
from numpy.fft import fft2, ifft2


def _poisson_invert(omega_hat, grid):
    """Spectral Poisson inversion."""
    return omega_hat * grid['K2_inv']


def solve_poisson(omega, grid):
    """Solve for streamfunction from vorticity field."""
    return np.real(ifft2(_poisson_invert(fft2(omega), grid)))


def _velocity_from_psi_hat(psi_hat, grid):
    """Velocity components from streamfunction spectrum."""
    u = np.real(ifft2(1j * grid['KY'] * psi_hat))
    v = np.real(ifft2(-1j * grid['KX'] * psi_hat))
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
'''

with open('/app/ns2d/spectral.py', 'w') as f:
    f.write(spectral_fixed)

# ============================================================
# Fix Bug 3 (RK3 stage-3 coefficients) in integrator.py
# ============================================================
integrator_fixed = '''\
"""Time integration for the Navier-Stokes solver."""


def ssp_rk3_step(omega, dt, rhs_fn):
    """SSP-RK3 time integration step."""
    L1 = rhs_fn(omega)
    w1 = omega + dt * L1

    L2 = rhs_fn(w1)
    w2 = 0.75 * omega + 0.25 * (w1 + dt * L2)

    L3 = rhs_fn(w2)
    return (1.0 / 3.0) * omega + (2.0 / 3.0) * (w2 + dt * L3)
'''

with open('/app/ns2d/integrator.py', 'w') as f:
    f.write(integrator_fixed)

# ============================================================
# Fix Bug 4 (enstrophy sum->mean) and Bug 5 (spectrum /K^2)
# in diagnostics.py
# ============================================================
diagnostics_fixed = '''\
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
    return 0.5 * np.mean(omega ** 2)


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
            spectrum[ki] = 0.5 / N ** 4 * np.sum(power[shell] / grid['K2'][shell])
    return spectrum
'''

with open('/app/ns2d/diagnostics.py', 'w') as f:
    f.write(diagnostics_fixed)

# ============================================================
# Bug report
# ============================================================
os.makedirs('/app/results', exist_ok=True)

bug_report = [
    {
        "module": "spectral.py",
        "description": "Poisson inversion has a spurious negative sign: computes -omega_hat*K2_inv instead of omega_hat*K2_inv, inverting the streamfunction",
        "fix": "Removed the minus sign in _poisson_invert so psi_hat = omega_hat * K2_inv"
    },
    {
        "module": "spectral.py",
        "description": "Velocity computation uses wrong wavenumber arrays: u is computed with KX (partial derivative in x) instead of KY (partial derivative in y), and v uses KY instead of KX",
        "fix": "Swapped wavenumber arrays so u = ifft2(1j*KY*psi_hat) and v = ifft2(-1j*KX*psi_hat)"
    },
    {
        "module": "integrator.py",
        "description": "SSP-RK3 stage 3 uses coefficients (0.5, 0.5) instead of the correct Shu-Osher coefficients (1/3, 2/3), reducing temporal accuracy to second order",
        "fix": "Changed stage 3 to (1/3)*omega + (2/3)*(w2 + dt*L3)"
    },
    {
        "module": "diagnostics.py",
        "description": "compute_enstrophy uses np.sum(omega**2) instead of np.mean(omega**2), giving enstrophy values scaled by N^2 instead of domain-averaged",
        "fix": "Changed np.sum to np.mean for correct domain averaging"
    },
    {
        "module": "diagnostics.py",
        "description": "compute_energy_spectrum omits division by K^2 in the shell summation, computing the power spectrum of vorticity instead of the kinetic energy spectrum",
        "fix": "Added division by grid['K2'][shell] in the shell summation"
    }
]

with open('/app/results/bug_report.json', 'w') as f:
    json.dump(bug_report, f, indent=2)

print("All bugs fixed and bug report written.")
