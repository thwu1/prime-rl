"""Sedov blast wave solver — self-similar point-explosion solution.

Implements the Sedov-Taylor similarity solution for planar, cylindrical,
and spherical geometries, following Kamm & Timmes (2007).
"""


import math
import numpy as np
import scipy.integrate as sci_int
import scipy.optimize as sci_opt
from scipy.interpolate import interp1d

from base import ExactSolver, ExactSolution


class Sedov(ExactSolver):
    """Computes the solution to the Sedov blast wave problem."""

    parameters = {
        'geometry': '1=planar, 2=cylindrical, 3=spherical',
        'gamma': 'specific heat ratio',
        'rho0': 'initial density',
        'omega': 'initial density power-law exponent',
        'eblast': 'total deposited energy',
    }

    geometry = 3
    gamma = 7.0 / 5.0
    rho0 = 1.0
    omega = 0.0
    eblast = 0.851072

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        if self.geometry not in [1, 2, 3]:
            raise ValueError("geometry must be 1, 2, or 3")
        if self.gamma <= 1:
            raise ValueError("gamma must be greater than 1")
        if self.rho0 < 0:
            raise ValueError("density must be greater than 0")
        if self.eblast < 0:
            raise ValueError("eblast must be greater than 0")
        if self.omega < 0 or self.omega >= self.geometry:
            raise ValueError("omega must be between 0 and geometry")

        # Frequently used constants
        self.gamm1 = self.gamma - 1.0
        self.gamp1 = self.gamma + 1.0
        self.gpogm = self.gamp1 / self.gamm1
        self.xg2 = self.geometry + 2.0 - self.omega
        self.denom2 = 2.0 * self.gamm1 + self.geometry - self.gamma * self.omega
        self.denom3 = self.geometry * (2.0 - self.gamma) - self.omega

        # Key velocity ratios
        self.v2 = 4.0 / (self.xg2 * self.gamp1)
        self.vstar = 2.0 / (self.gamm1 * self.geometry + 2.0)

        # Classify solution type
        osmall = 1.0e-4
        if abs(self.v2 - self.vstar) <= osmall:
            self.solution_type = 'singular'
        elif self.v2 < self.vstar - osmall:
            self.solution_type = 'standard'
        elif self.v2 > self.vstar + osmall:
            self.solution_type = 'vacuum'

        # Detect special singularities
        if abs(self.denom2) <= osmall:
            self.special_singularity = 'omega2'
            self.denom2 = 1.0e-8
        elif abs(self.denom3) <= osmall:
            self.special_singularity = 'omega3'
            self.denom3 = 1.0e-8
        else:
            self.special_singularity = 'none'

        # Exponents (Kamm equations 42-47)
        self.a0 = 2.0 / self.xg2
        self.a2 = -self.gamm1 / self.denom2
        self.a1 = (
            self.xg2 * self.gamma / (2.0 + self.geometry * self.gamm1)
        ) * (
            (2.0 * (self.geometry * (2.0 - self.gamma) - self.omega))
            / (self.gamma * self.xg2 ** 2)
            - self.a2
        )
        self.a3 = (self.geometry - self.omega) / self.denom2
        self.a4 = (
            self.xg2 * (self.geometry - self.omega) * self.a1 / self.denom3
        )
        self.a5 = (
            self.omega * self.gamp1 - 2.0 * self.geometry
        ) / self.denom3

        # Intermediate constants (Kamm equations 33-37)
        self.a_val = 0.25 * self.xg2 * self.gamp1
        self.b_val = self.gpogm
        self.c_val = 0.5 * self.xg2 * self.gamma
        self.d_val = (self.xg2 * self.gamp1) / (
            self.xg2 * self.gamp1
            - 2.0 * (2.0 + self.geometry * self.gamm1)
        )
        self.e_val = 0.5 * (2.0 + self.geometry * self.gamm1)

        # Compute energy integrals and alpha
        if self.solution_type == 'singular':
            self.eval2 = self.gamp1 / (
                self.geometry * (self.gamm1 * self.geometry + 2.0) ** 2
            )
            self.eval1 = 2.0 / self.gamm1 * self.eval2
            self.alpha = (
                self.gpogm
                * 2 ** self.geometry
                / (self.geometry * (self.gamm1 * self.geometry + 2.0) ** 2)
            )
            if self.geometry != 1:
                self.alpha *= math.pi
        else:
            self.v0 = 2.0 / (self.xg2 * self.gamma)
            self.vv = 2.0 / self.xg2
            self.rvv = 0.0

            if self.solution_type == 'standard':
                self.vmin = self.v0
            elif self.solution_type == 'vacuum':
                self.vmin = self.vv

            self.eval1 = sci_int.quad(
                self.efun01, self.vmin, self.v2, epsabs=1e-12
            )[0]
            self.eval2 = sci_int.quad(
                self.efun02, self.vmin, self.v2, epsabs=1e-12
            )[0]

            if self.geometry == 1:
                self.alpha = 0.5 * self.eval1 + self.eval2 / self.gamm1
            else:
                self.alpha = (self.geometry - 1.0) * math.pi * (
                    self.eval1 + 2.0 * self.eval2 / self.gamm1
                )

    def _run(self, r, t, npts=3001, vtol=1.0e-8):
        # No valid solution at t <= 0
        if t <= 0:
            nan_array = np.full(len(r), np.nan)
            return ExactSolution(
                [r, nan_array, nan_array, nan_array, nan_array, nan_array],
                names=[
                    'position', 'density', 'pressure',
                    'specific_internal_energy', 'velocity', 'sound_speed',
                ],
            )

        r_eval = np.linspace(0.0, max(r), npts)[::-1]

        density = np.zeros(npts)
        velocity = np.zeros(npts)
        pressure = np.zeros(npts)
        vwant = np.zeros(npts)

        # Shock position and jump conditions
        self.r2 = (
            (self.eblast / (self.alpha * self.rho0)) ** (1.0 / self.xg2)
            * t ** (2.0 / self.xg2)
        )
        self.rho1 = self.rho0 * self.r2 ** (-self.omega)
        self.us = (2.0 / self.xg2) * self.r2 / t
        self.u2 = 2.0 * self.us / self.gamp1
        self.rho2 = self.gpogm * self.rho1
        self.p2 = 2.0 * self.rho1 * self.us ** 2 / self.gamp1

        jumps = [self.r2]

        if self.solution_type == 'vacuum':
            l_rvv = self.sedov_funcs_standard(self.vv)[0]
            self.rvv = l_rvv * self.r2
            jumps.append(self.rvv)

        vconverged = False
        i = 0

        while not vconverged and i < npts:
            rwant = r_eval[i]

            if rwant <= self.r2:
                if self.solution_type == 'singular':
                    l_f, dl, f_f, g_f, h_f = self._sedov_funcs_singular(rwant)
                elif self.solution_type == 'vacuum' and rwant < self.rvv:
                    l_f, dl, f_f, g_f, h_f = 0.0, 0.0, 0.0, 0.0, 0.0
                else:
                    self.lam_want = rwant / self.r2

                    if self.solution_type == 'standard':
                        vmin = self.v0
                        vmax = self.v2
                    elif self.solution_type == 'vacuum':
                        vmin = self.v2
                        vmax = self.vv

                    vwant[i] = sci_opt.fminbound(
                        self._sed_lam_min, vmin, vmax,
                        xtol=1.0e-30, maxfun=1000, disp=False,
                    )

                    l_f, dl, f_f, g_f, h_f = self.sedov_funcs_standard(
                        vwant[i]
                    )

                    if i > 0 and abs(vwant[i] - vwant[i - 1]) < vtol:
                        vconverged = True

                density[i], velocity[i], pressure[i], _, _ = self._physical(
                    f_f, g_f, h_f
                )
            else:
                density[i] = self.rho0 * rwant ** (-self.omega)
                velocity[i] = 0.0
                pressure[i] = 0.0

            i += 1

        # Truncate to computed range
        r_eval = r_eval[: i - 1]
        density = density[: i - 1]
        velocity = velocity[: i - 1]
        pressure = pressure[: i - 1]

        # Add explicit origin point
        if self.solution_type == 'singular':
            _, _, f0, g0, h0 = self._sedov_funcs_singular(0.0)
        elif self.solution_type == 'vacuum':
            f0, g0, h0 = 0.0, 0.0, 0.0
        else:
            self.lam_want = 0.0
            vwant_o = sci_opt.fminbound(
                self._sed_lam_min, vmin, vmax,
                xtol=1.0e-30, maxfun=1000, disp=False,
            )
            _, _, f0, g0, h0 = self.sedov_funcs_standard(vwant_o)

        den0, vel0, pres0, _, _ = self._physical(f0, g0, h0)

        r_eval = np.append(r_eval, 0.0)
        density = np.append(density, den0)
        velocity = np.append(velocity, 0.0)
        pressure = np.append(pressure, pres0)

        # Interpolate from internal grid to requested r
        density = interp1d(r_eval, density)(r)
        velocity = interp1d(r_eval, velocity)(r)
        pressure = interp1d(r_eval, pressure)(r)

        specific_internal_energy = pressure / self.gamm1 / density
        sound_speed = np.sqrt(self.gamma * pressure / density)

        return ExactSolution(
            [r, density, pressure, specific_internal_energy,
             velocity, sound_speed],
            names=[
                'position', 'density', 'pressure',
                'specific_internal_energy', 'velocity', 'sound_speed',
            ],
            jumps=jumps,
        )

    def sedov_funcs_standard(self, v):
        """Compute Sedov functions at similarity variable v.

        Returns (lambda, dlambda_dv, f, g, h).
        """
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
        dx4dv = -self.b_val * 0.5 * self.xg2

        if self.special_singularity == 'omega2':
            beta0 = 1.0 / (2.0 * self.e_val)
            pp1 = self.gamm1 * beta0
            c6 = 0.5 * self.gamp1
            c2 = c6 / self.gamma
            y = 1.0 / (x1 - c2)
            z = (1.0 - x1) * y
            pp2 = self.gamp1 * beta0 * z
            dpp2dv = -self.gamp1 * beta0 * dx1dv * y * (1.0 + z)
            pp3 = (4.0 - self.geometry - 2.0 * self.gamma) * beta0
            pp4 = -self.geometry * self.gamma * beta0

            l_fun = x1 ** (-self.a0) * x2 ** pp1 * np.exp(pp2)
            dlamdv = (
                -self.a0 * dx1dv / x1 + pp1 * dx2dv / x2 + dpp2dv
            ) * l_fun
            f_fun = x1 * l_fun
            g_fun = (
                x1 ** (self.a0 * self.omega)
                * x2 ** pp3
                * x4 ** self.a5
                * np.exp(-2.0 * pp2)
            )
            h_fun = (
                x1 ** (self.a0 * self.geometry)
                * x2 ** pp4
                * x4 ** (1.0 + self.a5)
            )

        elif self.special_singularity == 'omega3':
            beta0 = 1.0 / (2.0 * self.e_val)
            pp1 = self.a3 + self.omega * self.a2
            pp2 = 1.0 - 4.0 * beta0
            c6 = 0.5 * self.gamp1
            pp3 = (
                -self.geometry * self.gamma * self.gamp1 * beta0
                * (1.0 - x1) / (c6 - x1)
            )
            pp4 = 2.0 * (self.geometry * self.gamm1 - self.gamma) * beta0

            l_fun = (
                x1 ** (-self.a0) * x2 ** (-self.a2) * x4 ** (-self.a1)
            )
            dlamdv = -(
                self.a0 * dx1dv / x1
                + self.a2 * dx2dv / x2
                + self.a1 * dx4dv / x4
            ) * l_fun
            f_fun = x1 * l_fun
            g_fun = (
                x1 ** (self.a0 * self.omega)
                * x2 ** pp1
                * x4 ** pp2
                * np.exp(pp3)
            )
            h_fun = (
                x1 ** (self.a0 * self.geometry)
                * x4 ** pp4
                * np.exp(pp3)
            )

        else:
            l_fun = (
                x1 ** (-self.a0) * x2 ** (-self.a2) * x3 ** (-self.a1)
            )
            dlamdv = -(
                self.a0 * dx1dv / x1
                + self.a2 * dx2dv / x2
                + self.a1 * dx3dv / x3
            ) * l_fun
            f_fun = x1 * l_fun
            g_fun = (
                x1 ** (self.a0 * self.omega)
                * x2 ** (self.a3 + self.a2 * self.omega)
                * x3 ** (self.a4 + self.a1 * self.omega)
                * x4 ** self.a5
            )
            h_fun = (
                x1 ** (self.a0 * self.geometry)
                * x3 ** (self.a4 + self.a1 * (self.omega - 2.0))
                * x4 ** (1.0 + self.a5)
            )

        return l_fun, dlamdv, f_fun, g_fun, h_fun

    def efun01(self, v):
        """Integrand for first Sedov energy integral."""
        l_fun, dlamdv, f_fun, g_fun, h_fun = self.sedov_funcs_standard(v)
        return dlamdv * l_fun ** (self.geometry + 1.0) * self.gpogm * g_fun * v ** 2

    def efun02(self, v):
        """Integrand for second Sedov energy integral."""
        l_fun, dlamdv, f_fun, g_fun, h_fun = self.sedov_funcs_standard(v)
        z = 8.0 / ((self.geometry + 2.0 - self.omega) ** 2 * self.gamp1)
        return dlamdv * l_fun ** (self.geometry - 1.0) * h_fun * z

    def _sed_lam_min(self, v):
        """Objective: (λ(v) - λ_want)²."""
        l_fun = self.sedov_funcs_standard(v)[0]
        return (l_fun - self.lam_want) ** 2

    def _physical(self, f_fun, g_fun, h_fun):
        """Convert Sedov functions to physical variables."""
        density = self.rho2 * g_fun
        velocity = self.u2 * f_fun
        pressure = self.p2 * h_fun
        sie = 0.0
        ss = 0.0
        if density > 0.0:
            sie = pressure / (self.gamm1 * density)
            ss = math.sqrt(self.gamma * pressure / density)
        return density, velocity, pressure, sie, ss

    def _sedov_funcs_singular(self, rwant):
        """Sedov functions for the singular solution type."""
        l_fun = rwant / self.r2
        f_fun = l_fun
        g_fun = l_fun ** (self.geometry - 2.0)
        h_fun = l_fun ** self.geometry
        return l_fun, 0.0, f_fun, g_fun, h_fun
