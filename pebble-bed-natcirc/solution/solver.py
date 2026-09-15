#!/usr/bin/env python3
"""
Natural circulation analysis for a pebble-bed HTGR.
Solves for steady-state natural circulation conditions at each
post-shutdown time point.

"""
import tomllib
import numpy as np
import csv
import sys
import os

G = 9.80665  # m/s^2


def load_config(path):
    with open(path, 'rb') as f:
        return tomllib.load(f)


def he_density(T, P, R_sp):
    return P / (R_sp * T)


def he_viscosity(T, coeff, exp):
    return coeff * T ** exp


def he_conductivity(T, coeff, exp):
    return coeff * T ** exp


def graphite_k(T, k_a, k_b):
    return 1.0 / (k_a + k_b * T)


def solve_natural_circulation(Q_decay, T_in, P, cfg, n_nodes):
    """
    Solve for the natural circulation mass flow rate and compute
    the resulting temperature distribution.

    Parameters
    ----------
    Q_decay : float
        Total decay heat power [W]
    T_in : float
        Core inlet temperature [K]
    P : float
        System pressure [Pa]
    cfg : dict
        Parsed reactor configuration
    n_nodes : int
        Number of axial discretization nodes

    Returns
    -------
    dict with keys: mdot, T_out, peak_T_surf, peak_T_center, dp_core
    """
    # Unpack geometry
    H = cfg['core']['height_m']
    R_core = cfg['core']['radius_m']
    dp = cfg['core']['pebble_diameter_m']
    eps = cfg['core']['porosity']
    A_core = np.pi * R_core ** 2

    H_ch = cfg['chimney']['height_m']
    A_ch = cfg['chimney']['flow_area_m2']
    D_ch = cfg['chimney']['hydraulic_diameter_m']
    f_ch = cfg['chimney']['friction_factor']

    # Helium property parameters
    he = cfg['helium']
    cp = he['cp']
    R_sp = he['R_specific']
    mu_c, mu_e = he['mu_coeff'], he['mu_exp']
    k_c, k_e = he['k_coeff'], he['k_exp']

    # Graphite parameters
    gr = cfg['graphite']
    k_a, k_b = gr['k_a'], gr['k_b']

    # Axial mesh
    dz = H / n_nodes
    z = np.linspace(dz / 2, H - dz / 2, n_nodes)

    # Sinusoidal power profile
    # q'''(z) = q_peak * sin(pi*z/H)
    # integral of q_peak * sin(pi*z/H) dz from 0 to H = q_peak * 2*H/pi
    # This must equal Q_decay / A_core
    # So q_peak = Q_decay * pi / (2 * A_core * H)
    q_peak = Q_decay * np.pi / (2.0 * A_core * H)
    q_prof = q_peak * np.sin(np.pi * z / H)

    rho_in = he_density(T_in, P, R_sp)

    def momentum_residual(mdot):
        """
        Returns buoyancy - friction. Positive means buoyancy dominates
        (flow should be higher).
        """
        # Temperature profile
        T_f = T_in + (Q_decay / (2.0 * mdot * cp)) * (1.0 - np.cos(np.pi * z / H))
        T_out = T_in + Q_decay / (mdot * cp)

        if T_out > 5000.0:
            return 1e10  # unphysical, force bisection to increase mdot

        # Densities
        rho_f = he_density(T_f, P, R_sp)
        rho_out = he_density(T_out, P, R_sp)

        # Buoyancy: integral over core + chimney contribution
        buoy_core = G * np.sum((rho_in - rho_f) * dz)
        buoy_chimney = G * H_ch * (rho_in - rho_out)
        total_buoy = buoy_core + buoy_chimney

        # Core friction (Ergun equation)
        v_s = mdot / (rho_f * A_core)
        mu_f = he_viscosity(T_f, mu_c, mu_e)
        ergun_visc = 150.0 * mu_f * v_s * (1.0 - eps) ** 2 / (dp ** 2 * eps ** 3)
        ergun_iner = 1.75 * rho_f * v_s ** 2 * (1.0 - eps) / (dp * eps ** 3)
        dp_core = np.sum((ergun_visc + ergun_iner) * dz)

        # Chimney friction (Darcy-Weisbach)
        v_ch = mdot / (rho_out * A_ch)
        dp_chimney = f_ch * (H_ch / D_ch) * 0.5 * rho_out * v_ch ** 2

        total_friction = dp_core + dp_chimney
        return total_buoy - total_friction

    # Bisection solver
    mdot_lo = 0.001
    mdot_hi = 200.0

    # Verify brackets
    r_lo = momentum_residual(mdot_lo)
    r_hi = momentum_residual(mdot_hi)
    if r_lo < 0 or r_hi > 0:
        # Try wider range
        mdot_lo = 1e-6
        mdot_hi = 500.0

    for _ in range(300):
        mdot_mid = (mdot_lo + mdot_hi) / 2.0
        r_mid = momentum_residual(mdot_mid)
        if r_mid > 0:
            mdot_lo = mdot_mid
        else:
            mdot_hi = mdot_mid
        if (mdot_hi - mdot_lo) / mdot_mid < 1e-12:
            break

    mdot = (mdot_lo + mdot_hi) / 2.0

    # Final computation with converged flow rate
    T_f = T_in + (Q_decay / (2.0 * mdot * cp)) * (1.0 - np.cos(np.pi * z / H))
    T_out = T_in + Q_decay / (mdot * cp)

    # Heat transfer
    rho_f = he_density(T_f, P, R_sp)
    v_s = mdot / (rho_f * A_core)
    mu_f = he_viscosity(T_f, mu_c, mu_e)
    k_f = he_conductivity(T_f, k_c, k_e)
    Pr_f = mu_f * cp / k_f
    Re_f = rho_f * v_s * dp / mu_f

    # Wakao-Kaguei correlation
    Nu = 2.0 + 1.1 * Re_f ** 0.6 * Pr_f ** (1.0 / 3.0)
    h_conv = Nu * k_f / dp
    h_v = 6.0 * (1.0 - eps) * h_conv / dp

    # Pebble surface temperature
    T_surf = T_f + q_prof / h_v
    peak_T_surf = float(np.max(T_surf))

    # Pebble centerline temperature at each axial node
    rp = dp / 2.0
    q_peb = q_prof / (1.0 - eps)  # volumetric heat gen per unit pebble volume
    C_vals = q_peb * rp ** 2 / 6.0  # integral of k dT from T_s to T_c
    T_center = ((k_a + k_b * T_surf) * np.exp(k_b * C_vals) - k_a) / k_b
    peak_T_center = float(np.max(T_center))

    # Core pressure drop
    ergun_visc = 150.0 * mu_f * v_s * (1.0 - eps) ** 2 / (dp ** 2 * eps ** 3)
    ergun_iner = 1.75 * rho_f * v_s ** 2 * (1.0 - eps) / (dp * eps ** 3)
    dp_core_total = float(np.sum((ergun_visc + ergun_iner) * dz))

    return {
        'mdot': float(mdot),
        'T_out': float(T_out),
        'peak_T_surf': peak_T_surf,
        'peak_T_center': peak_T_center,
        'dp_core': dp_core_total,
    }


def main():
    config_path = '/app/reactor.toml'
    output_path = '/app/results.csv'

    cfg = load_config(config_path)

    P = cfg['conditions']['pressure_Pa']
    T_in = cfg['conditions']['inlet_temperature_K']
    Q0 = cfg['conditions']['thermal_power_W']
    n_nodes = cfg['simulation']['n_axial_nodes']
    time_points = cfg['simulation']['time_points_hours']
    decay_coeff = cfg['decay_heat']['coefficient']
    decay_exp = cfg['decay_heat']['exponent']

    fieldnames = [
        'time_hours', 'decay_heat_MW', 'mass_flow_rate_kg_s',
        'outlet_temp_K', 'peak_surface_temp_K', 'peak_centerline_temp_K',
        'core_dp_Pa'
    ]

    results = []
    for t_hr in time_points:
        t_s = t_hr * 3600.0
        Q_decay = Q0 * decay_coeff * t_s ** decay_exp

        res = solve_natural_circulation(Q_decay, T_in, P, cfg, n_nodes)

        row = {
            'time_hours': f'{t_hr:.1f}',
            'decay_heat_MW': f'{Q_decay / 1e6:.6f}',
            'mass_flow_rate_kg_s': f'{res["mdot"]:.6f}',
            'outlet_temp_K': f'{res["T_out"]:.4f}',
            'peak_surface_temp_K': f'{res["peak_T_surf"]:.4f}',
            'peak_centerline_temp_K': f'{res["peak_T_center"]:.4f}',
            'core_dp_Pa': f'{res["dp_core"]:.4f}',
        }
        results.append(row)

    with open(output_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    print(f'Results written to {output_path}')
    for row in results:
        print(row)


if __name__ == '__main__':
    main()
