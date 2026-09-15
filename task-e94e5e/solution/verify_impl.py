"""Verification framework for cross-validating Sedov and Noh solvers.

Compares quadrature strategies for Sedov alpha, cross-validates both
solvers' density predictions against Rankine-Hugoniot theory, and
writes structured results to results.json.
"""


import json
import sys
import math

sys.path.insert(0, '/app')

import numpy as np
import scipy.integrate as sci_int

from sedov import Sedov
from noh import Noh


def compare_quadrature():
    """Compare quad vs fixed_quad for Sedov alpha (spherical, gamma=1.4)."""
    solver = Sedov(geometry=3, gamma=1.4, omega=0.)
    vmin = solver.v0
    vmax = solver.v2
    j = solver.geometry
    gamm1 = solver.gamm1

    # Method 1: quad (already computed during __init__)
    alpha_quad = solver.alpha

    # Vectorize integrands for fixed_quad (which passes arrays, not scalars)
    efun01_vec = np.vectorize(solver.efun01)
    efun02_vec = np.vectorize(solver.efun02)

    # Method 2: fixed_quad with n=15
    eval1_fq15 = sci_int.fixed_quad(efun01_vec, vmin, vmax, n=15)[0]
    eval2_fq15 = sci_int.fixed_quad(efun02_vec, vmin, vmax, n=15)[0]
    alpha_fq15 = (j - 1) * math.pi * (eval1_fq15 + 2.0 * eval2_fq15 / gamm1)

    # Method 3: fixed_quad with n=40
    eval1_fq40 = sci_int.fixed_quad(efun01_vec, vmin, vmax, n=40)[0]
    eval2_fq40 = sci_int.fixed_quad(efun02_vec, vmin, vmax, n=40)[0]
    alpha_fq40 = (j - 1) * math.pi * (eval1_fq40 + 2.0 * eval2_fq40 / gamm1)

    ref_alpha = 0.851060
    errors = {
        'quad': abs(alpha_quad - ref_alpha),
        'fixed_quad_n15': abs(alpha_fq15 - ref_alpha),
        'fixed_quad_n40': abs(alpha_fq40 - ref_alpha),
    }
    best = min(errors, key=errors.get)

    return {
        'quad_alpha': float(alpha_quad),
        'fixed_quad_n15_alpha': float(alpha_fq15),
        'fixed_quad_n40_alpha': float(alpha_fq40),
        'reference_alpha': ref_alpha,
        'quad_error': float(errors['quad']),
        'fq15_error': float(errors['fixed_quad_n15']),
        'fq40_error': float(errors['fixed_quad_n40']),
        'best_method': best,
    }


def cross_validate():
    """Cross-validate Noh and Sedov density predictions against analytics."""
    results = {}
    for gamma_val, gname in [(1.4, 'gamma_1_4'), (5.0 / 3.0, 'gamma_5_3')]:
        compression = (gamma_val + 1) / (gamma_val - 1)
        for geom, geoname in [(1, 'planar'), (2, 'cylindrical'),
                               (3, 'spherical')]:
            # Noh: evaluate well inside the shock
            noh = Noh(geometry=geom, gamma=gamma_val, u0=-1., rho0=1.)
            r_shock = abs(noh.u0) * 1.0 * (gamma_val - 1) / 2.0
            r_test = np.array([r_shock * 0.5])
            sol_noh = noh(r_test, 1.0)
            noh_density = float(sol_noh.density[0])
            noh_expected = 1.0 * compression ** geom

            # Sedov: read compression ratio from solver attributes
            sedov = Sedov(geometry=geom, gamma=gamma_val, omega=0., eblast=1.0)
            sedov_compression = float(sedov.gpogm)

            key = f'{geoname}_{gname}'
            results[key] = {
                'analytical_ratio': float(compression),
                'sedov_compression': sedov_compression,
                'noh_postshock_density': noh_density,
                'noh_expected_density': noh_expected,
                'noh_density_error': float(
                    abs(noh_density - noh_expected) / noh_expected),
            }
    return results


def verify_rankine_hugoniot():
    """Verify Rankine-Hugoniot conditions at the Sedov shock front."""
    solver = Sedov(geometry=3, gamma=1.4, omega=0., eblast=0.851072)
    r = np.linspace(0.01, 1.2, 1201)
    sol = solver(r, 1.0)

    r2 = solver.r2
    us = solver.us
    gamma = solver.gamma
    rho0 = solver.rho0
    gp1 = gamma + 1.0

    # Exact Rankine-Hugoniot values
    rho2_exact = rho0 * gp1 / (gamma - 1.0)
    u2_exact = 2.0 * us / gp1
    p2_exact = 2.0 * rho0 * us ** 2 / gp1

    ishock = np.argmin(np.abs(r - r2))

    return {
        'shock_position': float(r2),
        'density_at_shock': float(sol.density[ishock]),
        'density_exact': float(rho2_exact),
        'density_rel_error': float(
            abs(sol.density[ishock] - rho2_exact) / rho2_exact),
        'velocity_at_shock': float(sol.velocity[ishock]),
        'velocity_exact': float(u2_exact),
        'velocity_rel_error': float(
            abs(sol.velocity[ishock] - u2_exact) / max(abs(u2_exact), 1e-15)),
        'pressure_at_shock': float(sol.pressure[ishock]),
        'pressure_exact': float(p2_exact),
        'pressure_rel_error': float(
            abs(sol.pressure[ishock] - p2_exact) / p2_exact),
    }


if __name__ == '__main__':
    results = {
        'quadrature_comparison': compare_quadrature(),
        'cross_validation': cross_validate(),
        'rankine_hugoniot': verify_rankine_hugoniot(),
    }
    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)
    print('Verification complete. Results written to /app/results.json')
