#!/usr/bin/env python3
"""
Laser-Plasma Acceleration Pre-Flight Analyzer.

Reads /app/lab_config.json and computes fundamental plasma/laser parameters,
grid resolution metrics, and numerical dispersion properties of the Yee FDTD
scheme. Outputs results to /app/analysis_results.json.

"""

import json
import numpy as np
from scipy import constants


def main():
    # ---------------------------------------------------------------
    # Read configuration
    # ---------------------------------------------------------------
    with open("/app/lab_config.json") as f:
        cfg = json.load(f)

    # Input parameters
    lam = cfg["laser"]["wavelength_m"]             # laser wavelength [m]
    E0 = cfg["laser"]["e_max_Vm"]                  # peak electric field [V/m]
    w0 = cfg["laser"]["waist_m"]                    # laser waist [m]
    tau = cfg["laser"]["duration_fwhm_s"]           # FWHM duration [s]

    n_e = cfg["plasma"]["electron_density_m3"]      # electron density [m^-3]
    L_plat = cfg["plasma"]["plateau_length_m"]      # plateau length [m]
    L_up = cfg["plasma"]["up_ramp_length_m"]        # up-ramp length [m]
    L_down = cfg["plasma"]["down_ramp_length_m"]    # down-ramp length [m]
    L_total = L_plat + L_up + L_down                # total plasma length [m]

    nx, ny, nz = cfg["grid"]["n_cells"]
    xlo, ylo, zlo = cfg["grid"]["domain_lo_m"]
    xhi, yhi, zhi = cfg["grid"]["domain_hi_m"]

    cfl_factor = cfg["numerics"]["cfl_factor"]

    # ---------------------------------------------------------------
    # Physical constants (SI, 2018 CODATA)
    # ---------------------------------------------------------------
    c = constants.c              # speed of light [m/s]
    e = constants.e              # elementary charge [C]
    m_e = constants.m_e          # electron mass [kg]
    eps0 = constants.epsilon_0   # vacuum permittivity [F/m]

    # ---------------------------------------------------------------
    # Laser parameters
    # ---------------------------------------------------------------
    omega_0 = 2.0 * np.pi * c / lam        # angular frequency [rad/s]
    k_0 = 2.0 * np.pi / lam                # wavenumber [1/m]
    a_0 = e * E0 / (m_e * c * omega_0)     # normalized vector potential
    I_peak = c * eps0 * E0**2 / 2.0        # peak intensity [W/m^2]
    I_peak_Wcm2 = I_peak * 1.0e-4          # convert to W/cm^2
    z_R = np.pi * w0**2 / lam              # Rayleigh length [m]

    # ---------------------------------------------------------------
    # Plasma parameters
    # ---------------------------------------------------------------
    omega_p = np.sqrt(n_e * e**2 / (eps0 * m_e))  # plasma frequency [rad/s]
    k_p = omega_p / c                               # plasma wavenumber [1/m]
    lambda_p = 2.0 * np.pi * c / omega_p            # plasma wavelength [m]
    skin_depth = c / omega_p                         # skin depth [m]
    n_c = eps0 * m_e * omega_0**2 / e**2            # critical density [m^-3]
    density_ratio = n_e / n_c                        # n_e / n_c
    E_wb = m_e * c * omega_p / e                     # cold wave-breaking field [V/m]

    # ---------------------------------------------------------------
    # Grid analysis
    # ---------------------------------------------------------------
    dx = (xhi - xlo) / nx
    dy = (yhi - ylo) / ny
    dz = (zhi - zlo) / nz

    # 3D Yee FDTD CFL condition:
    #   c * dt * sqrt(1/dx^2 + 1/dy^2 + 1/dz^2) <= 1
    # With CFL factor < 1 for stability margin:
    dt = cfl_factor / (c * np.sqrt(1.0 / dx**2 + 1.0 / dy**2 + 1.0 / dz**2))

    cells_per_laser_wl = lam / dz
    cells_per_skin_depth = skin_depth / min(dx, dy)
    cells_per_plasma_wl = lambda_p / dz

    total_cells = int(nx * ny * nz)
    total_time_steps = int(np.ceil(L_total / (c * dt)))

    # ---------------------------------------------------------------
    # Numerical dispersion of the Yee FDTD scheme
    #
    # For a plane wave propagating along z (kx = ky = 0):
    #
    #   [sin(omega * dt/2) / (c * dt/2)]^2 = [sin(kz * dz/2) / (dz/2)]^2
    #
    # Solving for omega_num at kz = k_0:
    #   sin(omega_num * dt/2) = (c * dt / dz) * sin(k_0 * dz / 2)
    #   omega_num = (2/dt) * arcsin[(c*dt/dz) * sin(k_0*dz/2)]
    #
    # Group velocity from differentiating the dispersion relation:
    #   v_g = d_omega/dk = c * cos(k*dz/2) / cos(omega_num*dt/2)
    # ---------------------------------------------------------------
    S = (c * dt / dz) * np.sin(k_0 * dz / 2.0)

    if abs(S) >= 1.0:
        raise ValueError(
            f"CFL condition violated for laser wavenumber: S = {S:.6f}. "
            "The time step is too large for this grid spacing and frequency."
        )

    omega_num = (2.0 / dt) * np.arcsin(S)

    # Numerical phase velocity
    v_phi_num = omega_num / k_0

    # Numerical group velocity (analytic derivative of dispersion relation)
    v_g_num = c * np.cos(k_0 * dz / 2.0) / np.cos(omega_num * dt / 2.0)

    # Errors relative to the speed of light
    phase_vel_error_pct = (v_phi_num / c - 1.0) * 100.0
    group_vel_error_pct = (v_g_num / c - 1.0) * 100.0

    # ---------------------------------------------------------------
    # Build output
    # ---------------------------------------------------------------
    results = {
        "plasma": {
            "omega_p": float(omega_p),
            "lambda_p_m": float(lambda_p),
            "skin_depth_m": float(skin_depth),
            "critical_density_m3": float(n_c),
            "density_ratio": float(density_ratio),
        },
        "laser": {
            "omega_0": float(omega_0),
            "k_0": float(k_0),
            "a_0": float(a_0),
            "rayleigh_length_m": float(z_R),
            "peak_intensity_Wcm2": float(I_peak_Wcm2),
            "wave_breaking_field_Vm": float(E_wb),
        },
        "grid": {
            "dx_m": float(dx),
            "dy_m": float(dy),
            "dz_m": float(dz),
            "dt_s": float(dt),
            "cells_per_laser_wavelength": float(cells_per_laser_wl),
            "cells_per_skin_depth": float(cells_per_skin_depth),
            "cells_per_plasma_wavelength": float(cells_per_plasma_wl),
            "total_cells": total_cells,
            "total_time_steps": total_time_steps,
        },
        "numerical_dispersion": {
            "numerical_omega_at_k0": float(omega_num),
            "numerical_phase_velocity_c": float(v_phi_num / c),
            "numerical_group_velocity_c": float(v_g_num / c),
            "phase_velocity_error_percent": float(phase_vel_error_pct),
            "group_velocity_error_percent": float(group_vel_error_pct),
        },
    }

    with open("/app/analysis_results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Analysis complete. Results written to /app/analysis_results.json")


if __name__ == "__main__":
    main()
