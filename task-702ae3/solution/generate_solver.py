"""Generate the Sedov blast wave solver at /app/sedov_solver.py.

"""

solver_code = r'''"""Sedov-Taylor blast wave solver.

Computes exact self-similar solutions for the Sedov point-explosion problem
in planar (n=1), cylindrical (n=2), and spherical (n=3) geometries.

Based on the mathematical framework of Kamm & Timmes (LA-UR-07-2849).
"""

import math
import numpy as np
import scipy.integrate as sci_int
import scipy.optimize as sci_opt
from scipy.interpolate import interp1d


class SedovSolver:
    """Solver for the Sedov-Taylor blast wave problem."""

    def __init__(self, geometry, gamma, omega=0.0, eblast=0.851072, rho0=1.0):
        """
        Parameters
        ----------
        geometry : int
            1=planar, 2=cylindrical, 3=spherical
        gamma : float
            Specific heat ratio (gamma = cp/cv)
        omega : float
            Initial density power-law exponent (rho = rho0 * r^(-omega))
        eblast : float
            Total deposited energy
        rho0 : float
            Reference density
        """
        self.geometry = geometry
        self.gamma = gamma
        self.omega = omega
        self.eblast = eblast
        self.rho0 = rho0

        n = float(geometry)
        gamm1 = gamma - 1.0
        gamp1 = gamma + 1.0
        gpogm = gamp1 / gamm1
        xg2 = n + 2.0 - omega

        self.gamm1 = gamm1
        self.gamp1 = gamp1
        self.gpogm = gpogm
        self.xg2 = xg2

        # Post-shock similarity variable
        self.v2 = 4.0 / (xg2 * gamp1)

        # Post-shock origin (v where lambda -> 0 for standard case)
        self.v0 = 2.0 / (xg2 * gamma)

        # Denominators for exponent computation
        denom2 = 2.0 * gamm1 + n - gamma * omega
        denom3 = n * (2.0 - gamma) - omega

        # Exponents (Kamm eqs 42-47)
        self.a0 = 2.0 / xg2
        self.a2 = -gamm1 / denom2
        self.a1 = (xg2 * gamma / (2.0 + n * gamm1)) * \
            ((2.0 * (n * (2.0 - gamma) - omega)) / (gamma * xg2**2) - self.a2)
        self.a3 = (n - omega) / denom2
        self.a4 = xg2 * (n - omega) * self.a1 / denom3
        self.a5 = (omega * gamp1 - 2.0 * n) / denom3

        # Auxiliary coefficients (Kamm eqs 33-37)
        self.a_val = 0.25 * xg2 * gamp1
        self.b_val = gpogm
        self.c_val = 0.5 * xg2 * gamma
        self.d_val = (xg2 * gamp1) / (xg2 * gamp1 - 2.0 * (2.0 + n * gamm1))
        self.e_val = 0.5 * (2.0 + n * gamm1)

        # Compute energy integrals
        self.eval1, _ = sci_int.quad(
            self._efun01, self.v0, self.v2, epsabs=1e-12)
        self.eval2, _ = sci_int.quad(
            self._efun02, self.v0, self.v2, epsabs=1e-12)

        # Compute alpha (energy normalization constant)
        if geometry == 1:
            self.alpha = 0.5 * self.eval1 + self.eval2 / gamm1
        else:
            self.alpha = (n - 1.0) * math.pi * \
                (self.eval1 + 2.0 * self.eval2 / gamm1)

    def _sedov_funcs_full(self, v):
        """Compute Sedov functions with derivative. Returns (lam, dlamdv, f, g, h)."""
        x1 = self.a_val * v
        dx1dv = self.a_val

        cbag = max(1e-30, self.c_val * v - 1.0)
        x2 = self.b_val * cbag
        dx2dv = self.b_val * self.c_val

        ebag = 1.0 - self.e_val * v
        x3 = self.d_val * ebag
        dx3dv = -self.d_val * self.e_val

        x4 = self.b_val * (1.0 - 0.5 * self.xg2 * v)
        x4 = max(x4, 1e-12)

        n = float(self.geometry)
        omega = self.omega

        # Sedov functions (Kamm eqs 38-41)
        lam = x1**(-self.a0) * x2**(-self.a2) * x3**(-self.a1)
        dlamdv = -(self.a0 * dx1dv / x1 + self.a2 * dx2dv / x2 +
                   self.a1 * dx3dv / x3) * lam
        f = x1 * lam
        g = (x1**(self.a0 * omega) *
             x2**(self.a3 + self.a2 * omega) *
             x3**(self.a4 + self.a1 * omega) *
             x4**self.a5)
        h = (x1**(self.a0 * n) *
             x3**(self.a4 + self.a1 * (omega - 2.0)) *
             x4**(1.0 + self.a5))

        return lam, dlamdv, f, g, h

    def sedov_functions(self, v):
        """Compute Sedov similarity functions at similarity variable v.

        Returns
        -------
        lam : float
            Dimensionless radius (zeta = r/r_s)
        f : float
            Velocity function (V = u/u2)
        g : float
            Density function (D = rho/rho2)
        h : float
            Pressure function (P = p/p2)
        """
        lam, dlamdv, f, g, h = self._sedov_funcs_full(v)
        return lam, f, g, h

    def _efun01(self, v):
        """First energy integral integrand (kinetic energy)."""
        lam, dlamdv, f, g, h = self._sedov_funcs_full(v)
        return dlamdv * lam**(self.geometry + 1.0) * self.gpogm * g * v**2

    def _efun02(self, v):
        """Second energy integral integrand (internal energy)."""
        lam, dlamdv, f, g, h = self._sedov_funcs_full(v)
        z = 8.0 / (self.xg2**2 * self.gamp1)
        return dlamdv * lam**(self.geometry - 1.0) * h * z

    def compute_profiles(self, r, t):
        """Compute physical blast wave profiles at positions r and time t.

        Parameters
        ----------
        r : array_like
            Radial positions
        t : float
            Time (must be > 0)

        Returns
        -------
        dict with keys:
            'position', 'density', 'velocity', 'pressure',
            'specific_internal_energy', 'sound_speed', 'shock_position'
        """
        r = np.asarray(r, dtype=float)

        # Shock position
        r_s = (self.eblast / (self.alpha * self.rho0))**(1.0 / self.xg2) * \
            t**(2.0 / self.xg2)

        # Shock velocity
        u_s = (2.0 / self.xg2) * r_s / t

        # Post-shock conditions (Rankine-Hugoniot)
        rho1 = self.rho0 * r_s**(-self.omega)
        rho2 = self.gpogm * rho1
        u2 = 2.0 * u_s / self.gamp1
        p2 = 2.0 * rho1 * u_s**2 / self.gamp1

        # Build lookup table of Sedov functions on a fine v grid
        nv = 5000
        v_arr = np.linspace(self.v0, self.v2, nv)
        lam_arr = np.zeros(nv)
        f_arr = np.zeros(nv)
        g_arr = np.zeros(nv)
        h_arr = np.zeros(nv)

        for i in range(nv):
            lam_arr[i], f_arr[i], g_arr[i], h_arr[i] = \
                self.sedov_functions(v_arr[i])

        # Build interpolation functions from lambda to Sedov functions
        f_interp = interp1d(lam_arr, f_arr, kind='linear',
                           bounds_error=False, fill_value=(f_arr[0], f_arr[-1]))
        g_interp = interp1d(lam_arr, g_arr, kind='linear',
                           bounds_error=False, fill_value=(g_arr[0], g_arr[-1]))
        h_interp = interp1d(lam_arr, h_arr, kind='linear',
                           bounds_error=False, fill_value=(h_arr[0], h_arr[-1]))

        # Compute profiles
        density = np.zeros_like(r, dtype=float)
        velocity = np.zeros_like(r, dtype=float)
        pressure = np.zeros_like(r, dtype=float)

        inside = r <= r_s
        outside = r > r_s

        if np.any(inside):
            lam_want = r[inside] / r_s
            lam_want = np.clip(lam_want, lam_arr[0], lam_arr[-1])
            density[inside] = rho2 * g_interp(lam_want)
            velocity[inside] = u2 * f_interp(lam_want)
            pressure[inside] = p2 * h_interp(lam_want)

        if np.any(outside):
            density[outside] = self.rho0 * r[outside]**(-self.omega)
            velocity[outside] = 0.0
            pressure[outside] = 0.0

        # Derived quantities
        sie = np.where(density > 0,
                       pressure / (self.gamm1 * density), 0.0)
        sound = np.where(density > 0,
                         np.sqrt(np.maximum(0, self.gamma * pressure / density)),
                         0.0)

        return {
            'position': r,
            'density': density,
            'velocity': velocity,
            'pressure': pressure,
            'specific_internal_energy': sie,
            'sound_speed': sound,
            'shock_position': r_s,
        }
'''

with open('/app/sedov_solver.py', 'w') as f:
    f.write(solver_code)

print("Sedov solver written to /app/sedov_solver.py")
