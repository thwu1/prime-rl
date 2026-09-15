"""
Sedov-von Neumann-Taylor blast wave similarity solution solver.

Computes exact self-similar solutions to the point-explosion problem
in gas dynamics following the formulation of Kamm & Timmes (2000),
LA-UR-00-6055, Los Alamos National Laboratory.

Handles standard, singular, and vacuum solution types plus special
singularity cases (denom2~0 and denom3~0).

"""

import math
import numpy as np
import scipy.integrate as sci_int
import scipy.optimize as sci_opt
from scipy.interpolate import interp1d


class _SedovParams:
    """Precomputed parameters for the Sedov problem."""

    def __init__(self, gamma, geometry, omega):
        self.gamma = gamma
        self.geometry = geometry
        self.omega = omega

        self.gamm1 = gamma - 1.0
        self.gamp1 = gamma + 1.0
        self.gpogm = self.gamp1 / self.gamm1
        self.xg2 = geometry + 2.0 - omega
        self.denom2 = 2.0 * self.gamm1 + geometry - gamma * omega
        self.denom3 = geometry * (2.0 - gamma) - omega

        # Post-shock similarity variable and critical value
        self.v2 = 4.0 / (self.xg2 * self.gamp1)
        self.vstar = 2.0 / (self.gamm1 * geometry + 2.0)

        # Classify solution type
        osmall = 1.0e-4
        if abs(self.v2 - self.vstar) <= osmall:
            self.solution_type = 'singular'
        elif self.v2 < self.vstar - osmall:
            self.solution_type = 'standard'
        else:
            self.solution_type = 'vacuum'

        # Check for special singularities in exponent denominators
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
        self.a1 = (self.xg2 * gamma / (2.0 + geometry * self.gamm1) *
                   ((2.0 * (geometry * (2.0 - gamma) - omega)) /
                    (gamma * self.xg2 ** 2) - self.a2))
        self.a3 = (geometry - omega) / self.denom2
        self.a4 = self.xg2 * (geometry - omega) * self.a1 / self.denom3
        self.a5 = (omega * self.gamp1 - 2.0 * geometry) / self.denom3

        # Combination constants (Kamm equations 33-37)
        self.a_val = 0.25 * self.xg2 * self.gamp1
        self.b_val = self.gpogm
        self.c_val = 0.5 * self.xg2 * gamma
        self.d_val = (self.xg2 * self.gamp1 /
                      (self.xg2 * self.gamp1 -
                       2.0 * (2.0 + geometry * self.gamm1)))
        self.e_val = 0.5 * (2.0 + geometry * self.gamm1)

        # Integration bounds for non-singular cases
        if self.solution_type != 'singular':
            self.v0 = 2.0 / (self.xg2 * gamma)
            self.vv = 2.0 / self.xg2


def _sedov_funcs_impl(v, p):
    """Compute Sedov functions with derivative of lambda.

    Returns: (lam, dlam_dv, f, g, h)
    """
    # Combination variables from v (Kamm equations 29-32)
    x1 = p.a_val * v
    dx1dv = p.a_val

    cbag = max(1.0e-30, p.c_val * v - 1.0)
    x2 = p.b_val * cbag
    dx2dv = p.b_val * p.c_val

    ebag = 1.0 - p.e_val * v
    x3 = p.d_val * ebag
    dx3dv = -p.d_val * p.e_val

    x4 = p.b_val * (1.0 - 0.5 * p.xg2 * v)
    x4 = max(x4, 1.0e-12)
    dx4dv = -p.b_val * 0.5 * p.xg2

    # --- omega2 special singularity (Kamm equations 20-22) ---
    if p.special_singularity == 'omega2':
        beta0 = 1.0 / (2.0 * p.e_val)
        pp1 = p.gamm1 * beta0
        c6 = 0.5 * p.gamp1
        c2 = c6 / p.gamma
        y = 1.0 / (x1 - c2)
        z = (1.0 - x1) * y
        pp2 = p.gamp1 * beta0 * z
        dpp2dv = -p.gamp1 * beta0 * dx1dv * y * (1.0 + z)
        pp3 = (4.0 - p.geometry - 2.0 * p.gamma) * beta0
        pp4 = -p.geometry * p.gamma * beta0

        lam = x1 ** (-p.a0) * x2 ** pp1 * np.exp(pp2)
        dlam_dv = (-p.a0 * dx1dv / x1 + pp1 * dx2dv / x2 + dpp2dv) * lam
        f = x1 * lam
        g = (x1 ** (p.a0 * p.omega) * x2 ** pp3 *
             x4 ** p.a5 * np.exp(-2.0 * pp2))
        h = (x1 ** (p.a0 * p.geometry) * x2 ** pp4 *
             x4 ** (1.0 + p.a5))

    # --- omega3 special singularity (Kamm equations 23-25) ---
    elif p.special_singularity == 'omega3':
        beta0 = 1.0 / (2.0 * p.e_val)
        pp1 = p.a3 + p.omega * p.a2
        pp2 = 1.0 - 4.0 * beta0
        c6 = 0.5 * p.gamp1
        pp3 = (-p.geometry * p.gamma * p.gamp1 * beta0 *
               (1.0 - x1) / (c6 - x1))
        pp4 = 2.0 * (p.geometry * p.gamm1 - p.gamma) * beta0

        lam = x1 ** (-p.a0) * x2 ** (-p.a2) * x4 ** (-p.a1)
        dlam_dv = -(p.a0 * dx1dv / x1 + p.a2 * dx2dv / x2 +
                    p.a1 * dx4dv / x4) * lam
        f = x1 * lam
        g = (x1 ** (p.a0 * p.omega) * x2 ** pp1 *
             x4 ** pp2 * np.exp(pp3))
        h = (x1 ** (p.a0 * p.geometry) * x4 ** pp4 *
             np.exp(pp3))

    # --- Standard case (Kamm equations 38-41) ---
    else:
        lam = x1 ** (-p.a0) * x2 ** (-p.a2) * x3 ** (-p.a1)
        dlam_dv = -(p.a0 * dx1dv / x1 + p.a2 * dx2dv / x2 +
                    p.a1 * dx3dv / x3) * lam
        f = x1 * lam
        g = (x1 ** (p.a0 * p.omega) *
             x2 ** (p.a3 + p.a2 * p.omega) *
             x3 ** (p.a4 + p.a1 * p.omega) * x4 ** p.a5)
        h = (x1 ** (p.a0 * p.geometry) *
             x3 ** (p.a4 + p.a1 * (p.omega - 2.0)) *
             x4 ** (1.0 + p.a5))

    return lam, dlam_dv, f, g, h


def sedov_funcs(v, gamma, geometry, omega):
    """Compute Sedov functions at similarity variable v.

    Parameters
    ----------
    v : float
        Similarity variable.
    gamma : float
        Specific heat ratio.
    geometry : int
        1=planar, 2=cylindrical, 3=spherical.
    omega : float
        Initial density power-law exponent.

    Returns
    -------
    (lam, f, g, h) : tuple of floats
        lambda (normalized radius), f (velocity function),
        g (density function), h (pressure function).
    """
    p = _SedovParams(gamma, geometry, omega)
    lam, _, f, g, h = _sedov_funcs_impl(v, p)
    return lam, f, g, h


def find_v_for_lambda(lam_want, gamma, geometry, omega):
    """Find similarity variable v corresponding to a given lambda.

    Uses bounded minimization followed by Nelder-Mead refinement.

    Parameters
    ----------
    lam_want : float
        Desired normalized radius (0 to 1).
    gamma : float
        Specific heat ratio.
    geometry : int
        1=planar, 2=cylindrical, 3=spherical.
    omega : float
        Initial density power-law exponent.

    Returns
    -------
    v : float
        Similarity variable that gives lambda(v) ~ lam_want.
    """
    p = _SedovParams(gamma, geometry, omega)

    if p.solution_type == 'singular':
        raise ValueError("find_v_for_lambda not applicable for singular type")

    if p.solution_type == 'standard':
        vmin = p.v0
        vmax = p.v2
    else:  # vacuum
        vmin = p.v2
        vmax = p.vv

    def objective(v):
        lam, _, _, _, _ = _sedov_funcs_impl(v, p)
        return (lam - lam_want) ** 2

    # Two-pass optimization for maximum precision
    v = sci_opt.fminbound(objective, vmin, vmax, xtol=1.0e-30, maxfun=1000)
    v = sci_opt.fmin(objective, v, xtol=1.0e-16, ftol=1.0e-16, disp=False)[0]

    return v


def sedov_alpha(gamma, geometry, omega):
    """Compute energy normalization constant alpha.

    Parameters
    ----------
    gamma : float
        Specific heat ratio.
    geometry : int
        1=planar, 2=cylindrical, 3=spherical.
    omega : float
        Initial density power-law exponent.

    Returns
    -------
    (eval1, eval2, alpha) : tuple of floats
        First energy integral, second energy integral, and
        energy normalization constant.
    """
    p = _SedovParams(gamma, geometry, omega)

    if p.solution_type == 'singular':
        # Analytic expressions (Kamm equations 80, 81, 85)
        eval2 = p.gamp1 / (geometry * (p.gamm1 * geometry + 2.0) ** 2)
        eval1 = 2.0 / p.gamm1 * eval2
        alpha = (p.gpogm * 2 ** geometry /
                 (geometry * (p.gamm1 * geometry + 2.0) ** 2))
        if geometry != 1:
            alpha *= math.pi
    else:
        if p.solution_type == 'standard':
            vmin = p.v0
        else:
            vmin = p.vv

        def efun01(v):
            lam, dlam_dv, _f, g, _h = _sedov_funcs_impl(v, p)
            return dlam_dv * lam ** (geometry + 1.0) * p.gpogm * g * v ** 2

        def efun02(v):
            lam, dlam_dv, _f, _g, h = _sedov_funcs_impl(v, p)
            z = 8.0 / ((geometry + 2.0 - omega) ** 2 * p.gamp1)
            return dlam_dv * lam ** (geometry - 1.0) * h * z

        eval1 = sci_int.quad(efun01, vmin, p.v2, epsabs=1.0e-12)[0]
        eval2 = sci_int.quad(efun02, vmin, p.v2, epsabs=1.0e-12)[0]

        if geometry == 1:
            alpha = 0.5 * eval1 + eval2 / p.gamm1
        else:
            alpha = ((geometry - 1.0) * math.pi *
                     (eval1 + 2.0 * eval2 / p.gamm1))

    return eval1, eval2, alpha


def sedov_solution(r, t, gamma=1.4, geometry=3, rho0=1.0,
                   omega=0.0, eblast=0.851072):
    """Compute the Sedov blast wave solution.

    Parameters
    ----------
    r : array_like
        Radial positions.
    t : float
        Time (must be > 0).
    gamma : float
        Specific heat ratio.
    geometry : int
        1=planar, 2=cylindrical, 3=spherical.
    rho0 : float
        Initial density (at r=1 for omega != 0).
    omega : float
        Initial density power-law exponent.
    eblast : float
        Total blast energy.

    Returns
    -------
    dict with keys 'density', 'velocity', 'pressure',
    'specific_internal_energy', 'sound_speed' (numpy arrays)
    and 'shock_position' (float).
    """
    r = np.asarray(r, dtype=float)
    p = _SedovParams(gamma, geometry, omega)

    # Energy normalization
    _, _, alpha = sedov_alpha(gamma, geometry, omega)

    # Shock position and post-shock jump values
    xg2 = p.xg2
    r2 = (eblast / (alpha * rho0)) ** (1.0 / xg2) * t ** (2.0 / xg2)
    rho1 = rho0 * r2 ** (-omega)
    us = (2.0 / xg2) * r2 / t
    u2 = 2.0 * us / p.gamp1
    rho2 = p.gpogm * rho1
    p2 = 2.0 * rho1 * us ** 2 / p.gamp1

    # Vacuum boundary
    rvv = 0.0
    if p.solution_type == 'vacuum':
        lam_vv, _, _, _, _ = _sedov_funcs_impl(p.vv, p)
        rvv = lam_vv * r2

    # Evaluate on a fine uniform grid, then interpolate to desired r
    npts = 3001
    r_eval = np.linspace(0.0, max(r), npts)[::-1]
    den_eval = np.zeros(npts)
    vel_eval = np.zeros(npts)
    pres_eval = np.zeros(npts)

    if p.solution_type == 'standard':
        vmin_opt = p.v0
        vmax_opt = p.v2
    elif p.solution_type == 'vacuum':
        vmin_opt = p.v2
        vmax_opt = p.vv
    else:
        vmin_opt = 0.0
        vmax_opt = 1.0

    vtol = 1.0e-8
    vconverged = False
    prev_vwant = None
    i = 0

    while not vconverged and i < npts:
        rwant = r_eval[i]

        if rwant <= r2:
            if p.solution_type == 'singular':
                lam = rwant / r2
                f_val = lam
                g_val = lam ** (geometry - 2.0) if lam > 0 else 0.0
                h_val = lam ** geometry if lam > 0 else 0.0

            elif p.solution_type == 'vacuum' and rwant < rvv:
                f_val, g_val, h_val = 0.0, 0.0, 0.0

            else:
                lam_want = rwant / r2

                def obj(v):
                    lam_v, _, _, _, _ = _sedov_funcs_impl(v, p)
                    return (lam_v - lam_want) ** 2

                vwant = sci_opt.fminbound(
                    obj, vmin_opt, vmax_opt,
                    xtol=1.0e-30, maxfun=1000)

                _, _, f_val, g_val, h_val = _sedov_funcs_impl(vwant, p)

                if prev_vwant is not None and abs(vwant - prev_vwant) < vtol:
                    vconverged = True
                prev_vwant = vwant

            den_eval[i] = rho2 * g_val
            vel_eval[i] = u2 * f_val
            pres_eval[i] = p2 * h_val
        else:
            den_eval[i] = rho0 * rwant ** (-omega) if rwant > 0 else rho0
            vel_eval[i] = 0.0
            pres_eval[i] = 0.0

        i += 1

    # Truncate to points actually evaluated (minus last duplicate)
    idx = i - 1
    r_eval = r_eval[:idx]
    den_eval = den_eval[:idx]
    vel_eval = vel_eval[:idx]
    pres_eval = pres_eval[:idx]

    # Add origin point
    if p.solution_type in ('singular', 'vacuum'):
        den0 = 0.0
        pres0 = 0.0
    else:
        def obj0(v):
            lam_v, _, _, _, _ = _sedov_funcs_impl(v, p)
            return lam_v ** 2

        vwant0 = sci_opt.fminbound(
            obj0, vmin_opt, vmax_opt, xtol=1.0e-30, maxfun=1000)
        _, _, _f0, g0, h0 = _sedov_funcs_impl(vwant0, p)
        den0 = rho2 * g0
        pres0 = p2 * h0

    r_eval = np.append(r_eval, 0.0)
    den_eval = np.append(den_eval, den0)
    vel_eval = np.append(vel_eval, 0.0)
    pres_eval = np.append(pres_eval, pres0)

    # Interpolate to desired output positions
    density = interp1d(r_eval, den_eval)(r)
    velocity = interp1d(r_eval, vel_eval)(r)
    pressure = interp1d(r_eval, pres_eval)(r)

    # Derived thermodynamic quantities
    gamm1 = p.gamm1
    sie = np.where(density > 0, pressure / (gamm1 * density), 0.0)
    cs = np.where(density > 0, np.sqrt(gamma * pressure / density), 0.0)

    return {
        'density': density,
        'velocity': velocity,
        'pressure': pressure,
        'specific_internal_energy': sie,
        'sound_speed': cs,
        'shock_position': r2,
    }
