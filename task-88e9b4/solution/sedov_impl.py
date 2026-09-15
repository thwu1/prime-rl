"""Sedov blast wave solver implementing the Kamm & Timmes (2007) formulation.

Computes self-similar Sedov similarity functions, energy normalization integrals,
post-shock Rankine-Hugoniot states, and full radial profiles of hydrodynamic
quantities for the standard (uniform density) case across planar, cylindrical,
and spherical geometries.

Reference: Kamm & Timmes (2007), "On Efficient Generation of Numerically Robust
Sedov Solutions", LA-UR-07-2849.
"""


import numpy as np
import scipy.integrate as sci_int
import scipy.optimize as sci_opt
from scipy.interpolate import interp1d
import math


def compute_sedov_exponents(geometry, gamma, omega=0.0):
    """Compute Sedov similarity exponents (Kamm eqs 42-47) and derived constants.

    Parameters
    ----------
    geometry : int
        1=planar, 2=cylindrical, 3=spherical
    gamma : float
        Specific heat ratio (gamma = cp/cv, must be > 1)
    omega : float
        Initial density power-law exponent (rho = rho0 * r^(-omega))

    Returns
    -------
    dict with keys:
        a0..a5 : Similarity exponents (Kamm eqs 42-47)
        v2 : Shock-jump similarity variable
        v0 : Post-shock origin similarity variable
        vstar : Critical velocity for solution type classification
        gamm1, gamp1, gpogm, xg2, denom2, denom3 : Derived constants
        a_val, b_val, c_val, d_val, e_val : Frequent combinations (Kamm eqs 33-37)
    """
    gamm1 = gamma - 1.0
    gamp1 = gamma + 1.0
    gpogm = gamp1 / gamm1
    xg2 = geometry + 2.0 - omega
    denom2 = 2.0 * gamm1 + geometry - gamma * omega
    denom3 = geometry * (2.0 - gamma) - omega

    # Shock-jump similarity variable (Kamm eq 14)
    v2 = 4.0 / (xg2 * gamp1)
    # Post-shock origin (Kamm eq 16)
    v0 = 2.0 / (xg2 * gamma)
    # Critical velocity for solution type
    vstar = 2.0 / (gamm1 * geometry + 2.0)

    # Exponents: Kamm equations 42-47
    # a0=beta6, a1=beta1, a2=-beta2, a3=beta3, a4=beta4, a5=-beta5
    a0 = 2.0 / xg2
    a2 = -gamm1 / denom2
    a1 = (xg2 * gamma / (2.0 + geometry * gamm1)) * \
         ((2.0 * (geometry * (2.0 - gamma) - omega)) /
          (gamma * xg2 ** 2) - a2)
    a3 = (geometry - omega) / denom2
    a4 = xg2 * (geometry - omega) * a1 / denom3
    a5 = (omega * gamp1 - 2.0 * geometry) / denom3

    # Frequent combinations: Kamm equations 33-37
    a_val = 0.25 * xg2 * gamp1
    b_val = gpogm
    c_val = 0.5 * xg2 * gamma
    d_val = (xg2 * gamp1) / (xg2 * gamp1 -
                              2.0 * (2.0 + geometry * gamm1))
    e_val = 0.5 * (2.0 + geometry * gamm1)

    return {
        'a0': a0, 'a1': a1, 'a2': a2, 'a3': a3, 'a4': a4, 'a5': a5,
        'v2': v2, 'v0': v0, 'vstar': vstar,
        'gamm1': gamm1, 'gamp1': gamp1, 'gpogm': gpogm, 'xg2': xg2,
        'denom2': denom2, 'denom3': denom3,
        'a_val': a_val, 'b_val': b_val, 'c_val': c_val,
        'd_val': d_val, 'e_val': e_val,
    }


def compute_sedov_functions(v, geometry, gamma, omega=0.0, _exps=None):
    """Evaluate Sedov similarity functions at similarity variable v.

    Implements Kamm equations 29-32 (intermediate variables x1-x4)
    and equations 38-41 (Sedov functions) for the standard case.

    Parameters
    ----------
    v : float
        Similarity variable, in range [v0, v2]
    geometry : int
        1=planar, 2=cylindrical, 3=spherical
    gamma : float
        Specific heat ratio
    omega : float
        Initial density power-law exponent
    _exps : dict, optional
        Pre-computed exponents (for efficiency in repeated calls)

    Returns
    -------
    tuple (lam, dlamdv, f, g, h)
        lam : spatial similarity variable (zeta in Kamm's notation)
        dlamdv : derivative d(lambda)/dv
        f : velocity ratio function (V in Kamm)
        g : density ratio function (D in Kamm)
        h : pressure ratio function (P in Kamm)
    """
    if _exps is None:
        _exps = compute_sedov_exponents(geometry, gamma, omega)

    a0 = _exps['a0']
    a1 = _exps['a1']
    a2 = _exps['a2']
    a3 = _exps['a3']
    a4 = _exps['a4']
    a5 = _exps['a5']
    a_val = _exps['a_val']
    b_val = _exps['b_val']
    c_val = _exps['c_val']
    d_val = _exps['d_val']
    e_val = _exps['e_val']
    xg2 = _exps['xg2']

    # Intermediate variables: Kamm equations 29-32
    x1 = a_val * v
    dx1dv = a_val

    cbag = max(1e-30, c_val * v - 1.0)
    x2 = b_val * cbag
    dx2dv = b_val * c_val

    ebag = 1.0 - e_val * v
    x3 = d_val * ebag
    dx3dv = -d_val * e_val

    x4 = b_val * (1.0 - 0.5 * xg2 * v)
    x4 = max(x4, 1e-12)
    dx4dv = -b_val * 0.5 * xg2

    # Sedov functions: Kamm equations 38-41 (standard case)
    lam = x1 ** (-a0) * x2 ** (-a2) * x3 ** (-a1)
    dlamdv = -(a0 * dx1dv / x1 + a2 * dx2dv / x2 +
               a1 * dx3dv / x3) * lam
    f = x1 * lam
    g = (x1 ** (a0 * omega) *
         x2 ** (a3 + a2 * omega) *
         x3 ** (a4 + a1 * omega) *
         x4 ** a5)
    h = (x1 ** (a0 * geometry) *
         x3 ** (a4 + a1 * (omega - 2.0)) *
         x4 ** (1.0 + a5))

    return (lam, dlamdv, f, g, h)


def compute_energy_integrals(geometry, gamma, omega=0.0):
    """Compute Sedov energy integrals and normalization constant alpha.

    Implements Kamm equations 80, 81 (energy integrands) and
    equation 85 (alpha normalization).

    Parameters
    ----------
    geometry : int
        1=planar, 2=cylindrical, 3=spherical
    gamma : float
        Specific heat ratio
    omega : float
        Initial density power-law exponent

    Returns
    -------
    tuple (eval1, eval2, alpha)
        eval1 : First energy integral (kinetic)
        eval2 : Second energy integral (internal)
        alpha : Energy normalization constant
    """
    exps = compute_sedov_exponents(geometry, gamma, omega)
    gpogm = exps['gpogm']
    xg2 = exps['xg2']
    gamm1 = exps['gamm1']
    gamp1 = exps['gamp1']
    v2 = exps['v2']
    v0 = exps['v0']

    def efun01(v):
        """Integrand for first (kinetic) energy integral - Kamm eq 80."""
        lam, dlamdv, f, g, h = compute_sedov_functions(
            v, geometry, gamma, omega, _exps=exps)
        return dlamdv * lam ** (geometry + 1.0) * gpogm * g * v ** 2

    def efun02(v):
        """Integrand for second (internal) energy integral - Kamm eq 81."""
        lam, dlamdv, f, g, h = compute_sedov_functions(
            v, geometry, gamma, omega, _exps=exps)
        z = 8.0 / ((geometry + 2.0 - omega) ** 2 * gamp1)
        return dlamdv * lam ** (geometry - 1.0) * h * z

    eval1 = sci_int.quad(efun01, v0, v2, epsabs=1e-12)[0]
    eval2 = sci_int.quad(efun02, v0, v2, epsabs=1e-12)[0]

    # Alpha normalization: Kamm eq 85
    if geometry == 1:
        alpha = 0.5 * eval1 + eval2 / gamm1
    else:
        alpha = ((geometry - 1.0) * math.pi *
                 (eval1 + 2.0 * eval2 / gamm1))

    return (eval1, eval2, alpha)


def compute_postshock(geometry, gamma, rho0, eblast, alpha, t, omega=0.0):
    """Compute post-shock state from Rankine-Hugoniot jump conditions.

    Parameters
    ----------
    geometry : int
        1=planar, 2=cylindrical, 3=spherical
    gamma : float
        Specific heat ratio
    rho0 : float
        Initial (pre-shock) density
    eblast : float
        Total deposited energy
    alpha : float
        Energy normalization constant from compute_energy_integrals
    t : float
        Time (must be > 0)
    omega : float
        Initial density power-law exponent

    Returns
    -------
    dict with keys: r2, rho2, u2, p2, e2, cs2
        r2 : Shock position
        rho2 : Post-shock density
        u2 : Post-shock velocity
        p2 : Post-shock pressure
        e2 : Post-shock specific internal energy
        cs2 : Post-shock sound speed
    """
    gamm1 = gamma - 1.0
    gamp1 = gamma + 1.0
    gpogm = gamp1 / gamm1
    xg2 = geometry + 2.0 - omega

    # Shock position from energy conservation
    r2 = (eblast / (alpha * rho0)) ** (1.0 / xg2) * t ** (2.0 / xg2)

    # Pre-shock density at shock location
    rho1 = rho0 * r2 ** (-omega)

    # Shock speed
    us = (2.0 / xg2) * r2 / t

    # Post-shock state from Rankine-Hugoniot conditions
    u2 = 2.0 * us / gamp1
    rho2 = gpogm * rho1
    p2 = 2.0 * rho1 * us ** 2 / gamp1
    e2 = p2 / (gamm1 * rho2)
    cs2 = math.sqrt(gamma * p2 / rho2)

    return {
        'r2': r2, 'rho2': rho2, 'u2': u2,
        'p2': p2, 'e2': e2, 'cs2': cs2
    }


def _find_v_for_lambda(lam_want, v0, v2, geometry, gamma, omega, exps):
    """Find similarity variable v corresponding to spatial variable lam_want.

    Uses bounded minimization followed by Nelder-Mead refinement.
    """
    def obj(v):
        lam, _, _, _, _ = compute_sedov_functions(
            v, geometry, gamma, omega, _exps=exps)
        return (lam - lam_want) ** 2

    # Initial search with bounded minimization
    vopt = sci_opt.fminbound(obj, v0, v2, xtol=1e-30, maxfun=1000)
    # Refine with Nelder-Mead
    result = sci_opt.fmin(obj, vopt, xtol=1e-16, ftol=1e-16,
                          disp=False, maxfun=2000)
    vopt = result[0]
    # Clamp to valid range
    vopt = max(v0, min(v2, vopt))
    return vopt


def solve_sedov(r, t, geometry=3, gamma=1.4, rho0=1.0, eblast=0.851072,
                omega=0.0):
    """Compute full Sedov blast wave solution at positions r and time t.

    Parameters
    ----------
    r : array_like
        Radial positions at which to evaluate the solution
    t : float
        Time (must be > 0)
    geometry : int
        1=planar, 2=cylindrical, 3=spherical
    gamma : float
        Specific heat ratio
    rho0 : float
        Initial density
    eblast : float
        Total deposited energy
    omega : float
        Initial density power-law exponent

    Returns
    -------
    dict with keys:
        density, velocity, pressure, specific_internal_energy, sound_speed :
            NumPy arrays of physical quantities at positions r
        r2 : float, shock position
        alpha : float, energy normalization constant
        eval1 : float, first energy integral
        eval2 : float, second energy integral
    """
    r = np.asarray(r, dtype=float)

    exps = compute_sedov_exponents(geometry, gamma, omega)
    v2 = exps['v2']
    v0 = exps['v0']
    gamm1 = exps['gamm1']
    gamp1 = exps['gamp1']
    gpogm = exps['gpogm']
    xg2 = exps['xg2']

    eval1, eval2, alpha = compute_energy_integrals(geometry, gamma, omega)

    # Shock position and post-shock state
    r2 = (eblast / (alpha * rho0)) ** (1.0 / xg2) * t ** (2.0 / xg2)
    rho1 = rho0 * r2 ** (-omega)
    us = (2.0 / xg2) * r2 / t
    u2 = 2.0 * us / gamp1
    rho2 = gpogm * rho1
    p2 = 2.0 * rho1 * us ** 2 / gamp1

    # Evaluate on a dense intermediate grid for interpolation
    # Include shock-adjacent points to capture the sharp density peak
    npts = 3001
    r_max = float(np.max(r))
    if r_max <= 0:
        r_max = r2 * 1.5
    base_grid = np.linspace(0.0, r_max, npts)
    shock_points = np.array([
        r2 * 0.999, r2 * 0.9999, r2 * 0.99999, r2
    ])
    shock_points = shock_points[(shock_points >= 0) & (shock_points <= r_max)]
    r_eval = np.sort(np.unique(np.concatenate([base_grid, shock_points])))[::-1]
    npts = len(r_eval)

    density_eval = np.zeros(npts)
    velocity_eval = np.zeros(npts)
    pressure_eval = np.zeros(npts)

    vwant_prev = None
    vtol = 1e-8
    converged_idx = npts  # index at which v convergence was detected

    for i in range(npts):
        rwant = r_eval[i]

        if rwant > r2:
            # Outside shock: initial conditions
            density_eval[i] = rho0 * rwant ** (-omega) if omega != 0 else rho0
            velocity_eval[i] = 0.0
            pressure_eval[i] = 0.0
        elif rwant <= 0:
            # Origin: compute from v0 limit
            _, _, f0, g0, h0 = compute_sedov_functions(
                v0, geometry, gamma, omega, _exps=exps)
            density_eval[i] = rho2 * g0
            velocity_eval[i] = 0.0
            pressure_eval[i] = p2 * h0
        elif i >= converged_idx:
            # Past convergence: interpolation will handle this
            density_eval[i] = density_eval[converged_idx - 1]
            velocity_eval[i] = 0.0
            pressure_eval[i] = pressure_eval[converged_idx - 1]
        else:
            lam_want = rwant / r2
            vopt = _find_v_for_lambda(
                lam_want, v0, v2, geometry, gamma, omega, exps)

            _, _, f, g, h = compute_sedov_functions(
                vopt, geometry, gamma, omega, _exps=exps)

            density_eval[i] = rho2 * g
            velocity_eval[i] = u2 * f
            pressure_eval[i] = p2 * h

            # Check v convergence (double precision limit)
            if vwant_prev is not None and abs(vopt - vwant_prev) < vtol:
                converged_idx = i + 1
            vwant_prev = vopt

    # Compute origin values and append
    _, _, f0, g0, h0 = compute_sedov_functions(
        v0, geometry, gamma, omega, _exps=exps)
    den_origin = rho2 * g0
    pre_origin = p2 * h0

    # Ensure origin point is correct
    density_eval[-1] = den_origin
    velocity_eval[-1] = 0.0
    pressure_eval[-1] = pre_origin

    # Interpolate from r_eval back to desired r
    density = np.interp(r, r_eval[::-1], density_eval[::-1])
    velocity = np.interp(r, r_eval[::-1], velocity_eval[::-1])
    pressure = np.interp(r, r_eval[::-1], pressure_eval[::-1])

    sie = np.where(density > 0,
                   pressure / (gamm1 * density), 0.0)
    cs = np.where(density > 0,
                  np.sqrt(np.maximum(gamma * pressure / density, 0.0)),
                  0.0)

    return {
        'density': density,
        'velocity': velocity,
        'pressure': pressure,
        'specific_internal_energy': sie,
        'sound_speed': cs,
        'r2': float(r2),
        'alpha': float(alpha),
        'eval1': float(eval1),
        'eval2': float(eval2),
    }
