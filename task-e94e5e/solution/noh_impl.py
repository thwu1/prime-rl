"""Noh implosion solver — exact analytical solution.

Implements the Noh converging shock problem for planar, cylindrical,
and spherical geometries with arbitrary specific heat ratio.
"""


import numpy as np

from base import ExactSolver, ExactSolution


class Noh(ExactSolver):
    """Computes the exact solution to the Noh implosion problem.

    A gas with uniform density rho0 and inward radial velocity u0 < 0
    converges toward the origin, producing an outward-propagating shock.
    """

    parameters = {
        'geometry': '1=planar, 2=cylindrical, 3=spherical',
        'gamma': 'specific heat ratio',
        'u0': 'incident velocity (must be negative)',
        'rho0': 'initial density',
    }

    geometry = 3
    gamma = 5.0 / 3.0
    u0 = -1.0
    rho0 = 1.0

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.geometry not in [1, 2, 3]:
            raise ValueError("geometry must be 1, 2, or 3")
        if self.gamma <= 1.0:
            raise ValueError("gamma must be greater than 1")
        if self.u0 >= 0.0:
            raise ValueError("u0 must be negative")
        if self.rho0 <= 0.0:
            raise ValueError("rho0 must be positive")

    def _run(self, r, t):
        if t <= 0:
            nan_arr = np.full(len(r), np.nan)
            return ExactSolution(
                [r, nan_arr, nan_arr, nan_arr, nan_arr, nan_arr],
                names=['position', 'density', 'pressure',
                       'specific_internal_energy', 'velocity', 'sound_speed'],
            )

        j = self.geometry
        gamma = self.gamma
        rho0 = self.rho0
        u0_abs = abs(self.u0)
        gp1 = gamma + 1.0
        gm1 = gamma - 1.0
        G = gp1 / gm1  # compression ratio

        # Shock position
        r_shock = u0_abs * t * gm1 / 2.0

        # Post-shock values (spatially uniform behind the shock)
        rho_post = rho0 * G ** j
        # General pressure formula valid for all gamma
        p_post = rho0 * self.u0 ** 2 * G ** (j - 1) * gp1 / 2.0
        sie_post = self.u0 ** 2 / 2.0

        # Pre-shock density: rho0 * (1 + |u0|*t/r)^(j-1)
        # Guard against r=0 to avoid division by zero
        r_safe = np.maximum(r, 1e-30)
        rho_pre = rho0 * (1.0 + u0_abs * t / r_safe) ** (j - 1)

        # Assemble solution arrays using where
        density = np.where(r < r_shock, rho_post, rho_pre)
        velocity = np.where(r < r_shock, 0.0, self.u0)
        pressure = np.where(r < r_shock, p_post, 0.0)
        sie = np.where(r < r_shock, sie_post, 0.0)

        # Sound speed: sqrt(gamma * p / rho) where p > 0
        sound_speed = np.where(
            (density > 0) & (pressure > 0),
            np.sqrt(gamma * pressure / density),
            0.0,
        )

        return ExactSolution(
            [r, density, pressure, sie, velocity, sound_speed],
            names=['position', 'density', 'pressure',
                   'specific_internal_energy', 'velocity', 'sound_speed'],
        )
