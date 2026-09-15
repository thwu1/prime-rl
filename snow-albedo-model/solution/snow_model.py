#!/usr/bin/env python3
"""SUMMA-compatible single-layer snow column model.

Reads SUMMA-format file manager, decisions, and parameter files.
Simulates snow accumulation, albedo evolution, energy balance,
melt, sublimation, and compaction for a single HRU.
Writes output in NetCDF format.
"""

import argparse
import numpy as np
import netCDF4 as nc
import os
import sys

# ──────────────────────────────────────────────────────────────────────
# Physical constants
# ──────────────────────────────────────────────────────────────────────
STEFAN_BOLTZMANN = 5.67e-8       # W m⁻² K⁻⁴
CP_AIR = 1005.0                  # J kg⁻¹ K⁻¹
L_SUBLIMATION = 2.834e6          # J kg⁻¹
L_FUSION = 3.34e5                # J kg⁻¹
RHO_WATER = 1000.0               # kg m⁻³
R_DRY = 287.0                    # J kg⁻¹ K⁻¹  (dry air gas constant)
R_VAPOR = 461.5                  # J kg⁻¹ K⁻¹  (water vapor gas constant)
T_MELT = 273.15                  # K


# ──────────────────────────────────────────────────────────────────────
# Configuration parsers
# ──────────────────────────────────────────────────────────────────────

def parse_file_manager(path):
    """Parse SUMMA-format file manager.

    Each non-comment line: keyword  'value'
    """
    config = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('!'):
                continue
            parts = line.split()
            if len(parts) >= 2:
                key = parts[0]
                # Rejoin remaining parts and strip quotes
                val = ' '.join(parts[1:]).strip("'\"")
                config[key] = val
    return config


def parse_decisions(path):
    """Parse SUMMA-format decisions file.

    Each non-comment line: decision_name  value
    """
    decisions = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('!'):
                continue
            parts = line.split()
            if len(parts) >= 2:
                decisions[parts[0]] = parts[1]
    return decisions


def parse_params(path):
    """Parse pipe-delimited parameter file.

    Each non-comment line: name | value | lower | upper
    """
    params = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('!'):
                continue
            parts = [p.strip() for p in line.split('|')]
            if len(parts) >= 2:
                try:
                    params[parts[0]] = float(parts[1])
                except ValueError:
                    pass
    return params


def parse_forcing_list(path):
    """Read the forcing file name from the forcing file list."""
    with open(path) as f:
        for line in f:
            line = line.strip().strip("'\"")
            if line:
                return line
    raise ValueError(f"No forcing file found in {path}")


# ──────────────────────────────────────────────────────────────────────
# Atmospheric functions
# ──────────────────────────────────────────────────────────────────────

def sat_vapor_pressure(T):
    """Saturation vapor pressure (Pa) over water/ice using Tetens formula."""
    Tc = T - 273.15
    if Tc >= 0:
        return 611.2 * np.exp(17.67 * Tc / (T - 29.65))
    else:
        # Over ice (Murray, 1967)
        return 611.2 * np.exp(21.87 * Tc / (T - 7.66))


def sat_specific_humidity(T, P):
    """Saturation specific humidity (kg kg⁻¹)."""
    e_sat = sat_vapor_pressure(T)
    e_sat = min(e_sat, P * 0.9)  # safety
    return 0.622 * e_sat / (P - 0.378 * e_sat)


def d_esat_dT(T):
    """Derivative of saturation vapor pressure w.r.t. temperature."""
    Tc = T - 273.15
    if Tc >= 0:
        e = 611.2 * np.exp(17.67 * Tc / (T - 29.65))
        return e * 17.67 * (273.15 - 29.65) / (T - 29.65) ** 2
    else:
        e = 611.2 * np.exp(21.87 * Tc / (T - 7.66))
        return e * 21.87 * (273.15 - 7.66) / (T - 7.66) ** 2


def d_qsat_dT(T, P):
    """Derivative of saturation specific humidity w.r.t. temperature."""
    e_sat = sat_vapor_pressure(T)
    e_sat = min(e_sat, P * 0.9)
    de_dT = d_esat_dT(T)
    denom = P - 0.378 * e_sat
    return 0.622 * P * de_dT / (denom ** 2)


# ──────────────────────────────────────────────────────────────────────
# Energy balance
# ──────────────────────────────────────────────────────────────────────

def compute_energy_balance(T_snow, SW, alpha, LW, T_air, u, P, q_air, params):
    """Compute net surface energy flux and component fluxes.

    Returns (Q_net, Q_sens, Q_lat) in W m⁻².
    Positive = toward surface.
    """
    eps = params['snow_emissivity']
    C_H = params['bulk_transfer_coeff']
    C_E = C_H

    rho_air = P / (R_DRY * max(T_air, 200.0))
    q_sat = sat_specific_humidity(T_snow, P)

    Q_sw = SW * (1.0 - alpha)
    Q_lw = LW - eps * STEFAN_BOLTZMANN * T_snow ** 4
    Q_sens = rho_air * CP_AIR * C_H * u * (T_air - T_snow)
    Q_lat = rho_air * L_SUBLIMATION * C_E * u * (q_air - q_sat)

    Q_net = Q_sw + Q_lw + Q_sens + Q_lat
    return Q_net, Q_sens, Q_lat


def compute_energy_deriv(T_snow, SW, alpha, LW, T_air, u, P, q_air, params):
    """Derivative of net energy w.r.t. T_snow for Newton-Raphson."""
    eps = params['snow_emissivity']
    C_H = params['bulk_transfer_coeff']
    C_E = C_H

    rho_air = P / (R_DRY * max(T_air, 200.0))
    dq_dT = d_qsat_dT(T_snow, P)

    dQ_lw = -4.0 * eps * STEFAN_BOLTZMANN * T_snow ** 3
    dQ_sens = -rho_air * CP_AIR * C_H * u
    dQ_lat = -rho_air * L_SUBLIMATION * C_E * u * dq_dT

    return dQ_lw + dQ_sens + dQ_lat


def solve_surface_temperature(T_init, SW, alpha, LW, T_air, u, P, q_air, params,
                              max_iter=50, tol=0.01):
    """Solve for snow surface temperature via Newton-Raphson.

    Returns the equilibrium surface temperature (K).
    """
    T = T_init

    for _ in range(max_iter):
        Q, _, _ = compute_energy_balance(T, SW, alpha, LW, T_air, u, P, q_air, params)
        dQ = compute_energy_deriv(T, SW, alpha, LW, T_air, u, P, q_air, params)

        if abs(dQ) < 1e-12:
            break

        dT = -Q / dQ
        # Damped update for stability
        dT = max(-10.0, min(10.0, dT))
        T = T + dT

        # Physical bounds
        T = max(T, 200.0)
        T = min(T, T_MELT + 10.0)

        if abs(dT) < tol:
            break

    return T


# ──────────────────────────────────────────────────────────────────────
# Main model
# ──────────────────────────────────────────────────────────────────────

def run_model(file_manager_path):
    """Execute the snow column model from configuration."""

    # --- Parse configuration ---
    fm = parse_file_manager(file_manager_path)

    settings_path = fm.get('settingsPath', '/app/config/')
    forcing_path = fm.get('forcingPath', '/app/data/')
    output_path = fm.get('outputPath', '/app/output/')
    out_prefix = fm.get('outFilePrefix', 'output')

    decisions_file = os.path.join(settings_path, fm['decisionsFile'])
    params_file = os.path.join(settings_path, fm['globalHruParamFile'])
    forcing_list_file = os.path.join(settings_path, fm['forcingListFile'])

    decisions = parse_decisions(decisions_file)
    params = parse_params(params_file)
    forcing_filename = parse_forcing_list(forcing_list_file)

    # --- Read forcing data ---
    forcing_file = os.path.join(forcing_path, forcing_filename)
    ds_f = nc.Dataset(forcing_file, 'r')
    pptrate = ds_f.variables['pptrate'][:, 0].astype(np.float64)
    SWRadAtm = ds_f.variables['SWRadAtm'][:, 0].astype(np.float64)
    LWRadAtm = ds_f.variables['LWRadAtm'][:, 0].astype(np.float64)
    airtemp = ds_f.variables['airtemp'][:, 0].astype(np.float64)
    windspd = ds_f.variables['windspd'][:, 0].astype(np.float64)
    airpres = ds_f.variables['airpres'][:, 0].astype(np.float64)
    spechum = ds_f.variables['spechum'][:, 0].astype(np.float64)
    time_vals = ds_f.variables['time'][:].astype(np.float64)
    n_steps = len(time_vals)
    ds_f.close()

    # --- Extract parameters ---
    albedo_max = params['albedo_max']
    albedo_min = params['albedo_min']
    tau_const = params['tau_const']
    c_warm = params['c_warm']
    c_cold = params['c_cold']
    fresh_snow_density = params['fresh_snow_density']
    rain_snow_thresh = params['rain_snow_thresh']
    new_snow_thresh = params['new_snow_thresh']
    compact_c1 = params['compact_c1']
    compact_c2 = params['compact_c2']
    compact_c3 = params['compact_c3']

    alb_method = decisions.get('alb_method', 'conDecay')
    dt = 3600.0  # hourly timestep

    # --- Initialize state ---
    SWE = 0.0               # kg m⁻²
    snow_depth = 0.0        # m
    snow_density = fresh_snow_density  # kg m⁻³
    snow_albedo = albedo_max
    T_snow = T_MELT - 5.0   # K

    # --- Output arrays ---
    out_SWE = np.zeros(n_steps)
    out_depth = np.zeros(n_steps)
    out_albedo = np.zeros(n_steps)
    out_temp = np.zeros(n_steps)
    out_sens = np.zeros(n_steps)
    out_lat = np.zeros(n_steps)
    out_rain_melt = np.zeros(n_steps)
    out_sublim = np.zeros(n_steps)

    # --- Time loop ---
    for t in range(n_steps):
        ppt = pptrate[t]
        SW = SWRadAtm[t]
        LW = LWRadAtm[t]
        T_air = airtemp[t]
        u = max(windspd[t], 0.1)
        P = airpres[t]
        q_air = spechum[t]

        # Partition precipitation
        if T_air < rain_snow_thresh:
            snow_rate = ppt     # kg m⁻² s⁻¹
            rain_rate = 0.0
        else:
            snow_rate = 0.0
            rain_rate = ppt

        # ── Snow accumulation ──
        new_snow_swe = snow_rate * dt   # kg m⁻²
        new_snow_depth = new_snow_swe / fresh_snow_density if new_snow_swe > 0 else 0.0

        if new_snow_swe > 0:
            if SWE > 0 and snow_depth > 0:
                # Mix old and new snow densities
                total_swe = SWE + new_snow_swe
                total_depth = snow_depth + new_snow_depth
                snow_density = total_swe / total_depth
            else:
                snow_density = fresh_snow_density
            SWE += new_snow_swe
            snow_depth += new_snow_depth

        # ── Albedo evolution ──
        if snow_rate > new_snow_thresh:
            snow_albedo = albedo_max
        elif SWE > 0.01:
            if alb_method == 'conDecay':
                snow_albedo = ((snow_albedo - albedo_min) *
                               np.exp(-dt / tau_const) + albedo_min)
            elif alb_method == 'varDecay':
                if T_snow >= T_MELT:
                    snow_albedo = ((snow_albedo - albedo_min) *
                                   np.exp(-c_warm * dt) + albedo_min)
                else:
                    snow_albedo = snow_albedo - c_cold
                    snow_albedo = max(snow_albedo, albedo_min)

        # ── Energy balance & melt (only with snow) ──
        Q_sens = 0.0
        Q_lat = 0.0
        melt_rate = 0.0
        sublim_rate = 0.0

        if SWE > 0.01:
            T_snow = solve_surface_temperature(
                T_snow, SW, snow_albedo, LW, T_air, u, P, q_air, params
            )

            if T_snow > T_MELT:
                T_snow = T_MELT
                Q_net, Q_sens, Q_lat = compute_energy_balance(
                    T_MELT, SW, snow_albedo, LW, T_air, u, P, q_air, params
                )
                if Q_net > 0:
                    melt_rate = Q_net / L_FUSION  # kg m⁻² s⁻¹
            else:
                _, Q_sens, Q_lat = compute_energy_balance(
                    T_snow, SW, snow_albedo, LW, T_air, u, P, q_air, params
                )

            # Sublimation (latent heat leaving the surface)
            if Q_lat < 0:
                sublim_rate = -Q_lat / L_SUBLIMATION  # kg m⁻² s⁻¹

            # Apply melt
            melt_mass = min(melt_rate * dt, SWE)
            SWE -= melt_mass
            melt_rate = melt_mass / dt

            # Apply sublimation
            sublim_mass = min(sublim_rate * dt, SWE)
            SWE -= sublim_mass
            sublim_rate = sublim_mass / dt

            # ── Snow compaction ──
            if SWE > 0.01 and snow_depth > 0:
                T_eff = max(T_snow, 200.0)
                drhod_dt = (snow_density * compact_c1 *
                            np.exp(-compact_c2 * (T_MELT - T_eff)) *
                            np.exp(-compact_c3 * snow_density))
                snow_density += drhod_dt * dt
                snow_density = max(50.0, min(700.0, snow_density))
                snow_depth = SWE / snow_density
            else:
                SWE = max(SWE, 0.0)
                snow_depth = 0.0
        else:
            SWE = max(SWE, 0.0)
            snow_depth = 0.0
            T_snow = T_air  # reset when no snow

        # ── Store output ──
        out_SWE[t] = SWE
        out_depth[t] = snow_depth
        out_albedo[t] = snow_albedo
        out_temp[t] = T_snow if SWE > 0.01 else T_air
        out_sens[t] = Q_sens
        out_lat[t] = Q_lat
        out_rain_melt[t] = rain_rate + melt_rate
        out_sublim[t] = sublim_rate

    # --- Write output NetCDF ---
    os.makedirs(output_path, exist_ok=True)
    out_file = os.path.join(output_path, f"{out_prefix}_output.nc")

    ds_out = nc.Dataset(out_file, 'w', format='NETCDF4')
    ds_out.createDimension('time', n_steps)
    ds_out.createDimension('hru', 1)

    t_var = ds_out.createVariable('time', 'f8', ('time',))
    t_var[:] = time_vals
    t_var.units = 'hours since 2005-10-01 00:00:00'
    t_var.calendar = 'standard'

    var_data = [
        ('scalarSWE', out_SWE, 'kg m-2'),
        ('scalarSnowDepth', out_depth, 'm'),
        ('scalarSnowAlbedo', out_albedo, '-'),
        ('scalarSurfaceTemp', out_temp, 'K'),
        ('scalarSenHeatTotal', out_sens, 'W m-2'),
        ('scalarLatHeatTotal', out_lat, 'W m-2'),
        ('scalarRainPlusMelt', out_rain_melt, 'kg m-2 s-1'),
        ('scalarSnowSublimation', out_sublim, 'kg m-2 s-1'),
    ]

    for name, data, units in var_data:
        v = ds_out.createVariable(name, 'f8', ('time', 'hru'))
        v[:, 0] = data
        v.units = units

    ds_out.close()
    print(f"Output written: {out_file} ({n_steps} timesteps)")


# ──────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='SUMMA-compatible single-layer snow column model'
    )
    parser.add_argument('-m', '--file-manager', required=True,
                        help='Path to SUMMA file manager configuration')
    args = parser.parse_args()

    run_model(args.file_manager)
