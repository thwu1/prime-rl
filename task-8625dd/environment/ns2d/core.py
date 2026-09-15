"""NS2DSolver: 2D incompressible Navier-Stokes on a periodic domain."""

import numpy as np

from .grid import build_grid
from .spectral import solve_poisson, compute_velocity, compute_rhs
from .integrator import ssp_rk3_step
from .diagnostics import compute_energy, compute_enstrophy, compute_energy_spectrum


class NS2DSolver:
    def __init__(self, N, Re, dt, dealias=True):
        self.N = N
        self.Re = Re
        self.nu = 0.0 if Re > 1e14 else 1.0 / Re
        self.dt = dt
        self._grid = build_grid(N, dealias)
        self.X = self._grid['X']
        self.Y = self._grid['Y']

    def initialize_taylor_green(self):
        return 2.0 * np.cos(self.X) * np.cos(self.Y)

    def solve_poisson(self, omega):
        return solve_poisson(omega, self._grid)

    def compute_velocity(self, psi):
        return compute_velocity(psi, self._grid)

    def step(self, omega):
        rhs_fn = lambda w: compute_rhs(w, self._grid, self.nu)
        return ssp_rk3_step(omega, self.dt, rhs_fn)

    def compute_energy(self, omega):
        return compute_energy(
            omega, self._grid,
            lambda w: solve_poisson(w, self._grid),
            lambda p: compute_velocity(p, self._grid),
        )

    def compute_enstrophy(self, omega):
        return compute_enstrophy(omega)

    def compute_energy_spectrum(self, omega):
        return compute_energy_spectrum(omega, self._grid)

    def run(self, omega, T):
        nsteps = int(round(T / self.dt))
        times = [0.0]
        energies = [self.compute_energy(omega)]
        enstrophies = [self.compute_enstrophy(omega)]
        for i in range(nsteps):
            omega = self.step(omega)
            times.append((i + 1) * self.dt)
            energies.append(self.compute_energy(omega))
            enstrophies.append(self.compute_enstrophy(omega))
        return {
            'omega': omega,
            'times': np.array(times),
            'energies': np.array(energies),
            'enstrophies': np.array(enstrophies),
        }
