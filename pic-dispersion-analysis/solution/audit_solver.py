#!/usr/bin/env python3
"""
WarpX Simulation Configuration Audit Solver.

Parses WarpX native ParmParse input files, resolves my_constants references,
computes numerical stability and resolution metrics, and produces
/app/audit_report.json.

"""

import json
import os

import numpy as np
from scipy import constants


def parse_warpx_input(filepath):
    """Parse a WarpX ParmParse-format input file.

    Returns (params, my_constants) where params is a dict of key->raw_string
    and my_constants is a dict of const_name->float.
    """
    params = {}
    my_consts = {}

    with open(filepath) as f:
        for line in f:
            # Strip comments
            line = line.split("#")[0].strip()
            if not line or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()

            if key.startswith("my_constants."):
                const_name = key[len("my_constants."):]
                try:
                    my_consts[const_name] = float(value)
                except ValueError:
                    my_consts[const_name] = value
            else:
                params[key] = value

    return params, my_consts


def resolve_float(value_str, my_consts):
    """Resolve a single-valued parameter: try float, then my_constants lookup."""
    value_str = value_str.strip().strip('"')
    try:
        return float(value_str)
    except ValueError:
        pass
    if value_str in my_consts:
        return float(my_consts[value_str])
    raise ValueError(f"Cannot resolve value: {value_str!r}")


def parse_multi_float(value_str):
    """Parse space-separated floats."""
    return [float(x) for x in value_str.split()]


def parse_multi_int(value_str):
    """Parse space-separated integers."""
    return [int(x) for x in value_str.split()]


def find_electron_density(params, my_consts):
    """Find the electron species density from the input parameters."""
    species_names = params.get("particles.species_names", "").split()
    for sp in species_names:
        charge_key = f"{sp}.charge"
        density_key = f"{sp}.density"
        if charge_key in params and density_key in params:
            charge_str = params[charge_key].strip()
            if "-q_e" in charge_str:
                return resolve_float(params[density_key], my_consts)
    # Fallback: try "electrons.density"
    if "electrons.density" in params:
        return resolve_float(params["electrons.density"], my_consts)
    raise ValueError("Could not find electron density in input file")


def analyze_simulation(filepath):
    """Analyze a single WarpX simulation configuration."""
    params, my_consts = parse_warpx_input(filepath)

    # Physical constants
    c = constants.c
    e = constants.e
    m_e = constants.m_e
    eps0 = constants.epsilon_0

    # ---- Grid ----
    n_cell = parse_multi_int(params["amr.n_cell"])
    prob_lo = parse_multi_float(params["geometry.prob_lo"])
    prob_hi = parse_multi_float(params["geometry.prob_hi"])
    cfl_factor = float(params["warpx.cfl"])

    nx, ny, nz = n_cell
    dx = (prob_hi[0] - prob_lo[0]) / nx
    dy = (prob_hi[1] - prob_lo[1]) / ny
    dz = (prob_hi[2] - prob_lo[2]) / nz
    total_cells = int(nx * ny * nz)

    # ---- Timestep (3D Yee FDTD CFL) ----
    dt = cfl_factor / (c * np.sqrt(1.0 / dx**2 + 1.0 / dy**2 + 1.0 / dz**2))

    # ---- Laser ----
    laser_wl = resolve_float(params["laser1.wavelength"], my_consts)
    e_max = resolve_float(params["laser1.e_max"], my_consts)
    waist = resolve_float(params["laser1.profile_waist"], my_consts)

    omega_0 = 2.0 * np.pi * c / laser_wl
    k_0 = 2.0 * np.pi / laser_wl
    a_0 = e * e_max / (m_e * c * omega_0)
    I_peak_Wcm2 = c * eps0 * e_max**2 / 2.0 * 1.0e-4
    z_R = np.pi * waist**2 / laser_wl

    # ---- Plasma ----
    n_e = find_electron_density(params, my_consts)
    omega_p = np.sqrt(n_e * e**2 / (eps0 * m_e))
    lambda_p = 2.0 * np.pi * c / omega_p
    skin_depth = c / omega_p
    n_c = eps0 * m_e * omega_0**2 / e**2
    density_ratio = n_e / n_c
    E_wb = m_e * c * omega_p / e

    # ---- Resolution ----
    cells_per_laser_wl = laser_wl / dz
    cells_per_skin_depth = skin_depth / min(dx, dy)
    cells_per_plasma_wl = lambda_p / dz

    # ---- Numerical dispersion (Yee FDTD, wave along z, kx=ky=0) ----
    # Dispersion relation: sin(omega*dt/2)/(c*dt/2) = sin(k*dz/2)/(dz/2)
    # For kz = k_0:
    S = (c * dt / dz) * np.sin(k_0 * dz / 2.0)
    assert abs(S) < 1.0, f"CFL violated for laser wavenumber: S={S}"
    omega_num = (2.0 / dt) * np.arcsin(S)
    v_phi = omega_num / k_0
    # Group velocity: d_omega/dk = c * cos(k*dz/2) / cos(omega_num*dt/2)
    v_g = c * np.cos(k_0 * dz / 2.0) / np.cos(omega_num * dt / 2.0)
    phase_err = (v_phi / c - 1.0) * 100.0
    group_err = (v_g / c - 1.0) * 100.0

    # ---- Verdict ----
    cfl_stable = bool(cfl_factor <= 1.0)
    well_resolved = bool(
        cells_per_laser_wl >= 8.0 and cells_per_skin_depth >= 1.0
    )

    return {
        "grid": {
            "dx_m": float(dx),
            "dy_m": float(dy),
            "dz_m": float(dz),
            "total_cells": total_cells,
        },
        "timestep": {
            "dt_s": float(dt),
            "cfl_factor": float(cfl_factor),
        },
        "laser": {
            "wavelength_m": float(laser_wl),
            "frequency_rad_s": float(omega_0),
            "wavenumber_1m": float(k_0),
            "peak_field_Vm": float(e_max),
            "normalized_amplitude": float(a_0),
            "peak_intensity_Wcm2": float(I_peak_Wcm2),
            "rayleigh_length_m": float(z_R),
        },
        "plasma": {
            "density_m3": float(n_e),
            "frequency_rad_s": float(omega_p),
            "wavelength_m": float(lambda_p),
            "skin_depth_m": float(skin_depth),
            "critical_density_m3": float(n_c),
            "density_ratio": float(density_ratio),
            "wavebreaking_field_Vm": float(E_wb),
        },
        "resolution": {
            "cells_per_laser_wavelength": float(cells_per_laser_wl),
            "cells_per_skin_depth": float(cells_per_skin_depth),
            "cells_per_plasma_wavelength": float(cells_per_plasma_wl),
        },
        "numerical_dispersion": {
            "phase_error_pct": float(phase_err),
            "group_error_pct": float(group_err),
        },
        "verdict": {
            "cfl_stable": cfl_stable,
            "well_resolved": well_resolved,
        },
    }


def main():
    sim_dir = "/app/simulations"
    results = {}

    for fname in sorted(os.listdir(sim_dir)):
        if fname.startswith("inputs_"):
            sim_name = fname[len("inputs_"):]
            filepath = os.path.join(sim_dir, fname)
            results[sim_name] = analyze_simulation(filepath)
            print(f"Analyzed: {sim_name}")

    with open("/app/audit_report.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"Audit report written to /app/audit_report.json ({len(results)} simulations)")


if __name__ == "__main__":
    main()
