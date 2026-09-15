#!/usr/bin/env python3
"""Porous media CFD V&V analysis.

Parses OpenFOAM case directories, performs grid convergence verification
(Richardson extrapolation + GCI), fits Forchheimer model to pressure-sweep
data, validates against Kozeny-Carman, and generates gnuplot diagnostic plots.

"""
import json
import math
import os
import re
import subprocess

import numpy as np


# ==============================================================
# Parsing utilities
# ==============================================================

def parse_openfoam_dict_value(filepath, key):
    """Extract a scalar value from an OpenFOAM dictionary file.

    Handles both plain values (key  value;) and dimensioned values
    (key  [dims] value;).
    """
    with open(filepath) as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("#"):
                continue
            if key in stripped:
                # Match: key  [dims] value;  OR  key  value;
                m = re.search(
                    r'\b' + re.escape(key) + r'\s+'
                    r'(?:\[[^\]]*\]\s+)?'
                    r'([+-]?\d+\.?\d*(?:[eE][+-]?\d+)?)\s*;',
                    stripped,
                )
                if m:
                    return float(m.group(1))
    return None


def parse_geometry_dat(filepath):
    """Parse the geometry.dat key-value file."""
    params = {}
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                params[parts[0]] = float(parts[1])
    return params


def parse_surface_field_value(filepath):
    """Parse an OpenFOAM surfaceFieldValue .dat file.

    Format: Time  (Ux Uy Uz)_inlet  (Ux Uy Uz)_outlet  p_inlet  p_outlet
    Returns list of record dicts.
    """
    records = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            vectors = re.findall(r"\(([^)]+)\)", line)
            scalar_str = re.sub(r"\([^)]+\)", "", line)
            scalars = scalar_str.split()

            inlet_U = [float(x) for x in vectors[0].split()]
            outlet_U = [float(x) for x in vectors[1].split()]

            records.append({
                "time": float(scalars[0]),
                "inlet_Ux": inlet_U[0],
                "outlet_Ux": outlet_U[0],
                "inlet_p": float(scalars[1]),
                "outlet_p": float(scalars[2]),
            })
    return records


def get_converged_state(case_dir):
    """Extract converged velocity and pressure drop from a case."""
    dat_path = os.path.join(
        case_dir, "postProcessing", "surfaceFieldValue", "0",
        "surfaceFieldValue.dat")
    records = parse_surface_field_value(dat_path)
    last = records[-1]
    U = last["inlet_Ux"]
    dp = last["inlet_p"] - last["outlet_p"]
    return U, dp


# ==============================================================
# Main analysis
# ==============================================================

def main():
    base = "/data/cases"

    # ---- Load physical parameters ----
    # Fluid properties from any case's transportProperties
    tp_path = os.path.join(base, "mesh_100x50", "constant",
                           "transportProperties")
    nu = parse_openfoam_dict_value(tp_path, "nu")
    rho = parse_openfoam_dict_value(tp_path, "rho")
    mu = nu * rho

    # Geometry
    geom = parse_geometry_dat(os.path.join(base, "geometry.dat"))
    L_domain = geom["domain_length"]
    d_p = geom["particle_diameter"]
    porosity = geom["porosity"]

    # ==============================================================
    # VERIFICATION: Grid convergence analysis
    # ==============================================================
    mesh_cases = sorted(
        [d for d in os.listdir(base) if d.startswith("mesh_")],
        key=lambda d: int(d.split("_")[1].split("x")[0]),
    )

    mesh_results = []
    for case_name in mesh_cases:
        m = re.search(r"mesh_(\d+)x(\d+)", case_name)
        nx = int(m.group(1))
        U, dp = get_converged_state(os.path.join(base, case_name))
        k = mu * U * L_domain / dp
        h = L_domain / nx
        mesh_results.append((nx, h, k))

    permeabilities = [r[2] for r in mesh_results]
    grid_spacings = [r[1] for r in mesh_results]

    # Richardson extrapolation
    r_ratio = grid_spacings[0] / grid_spacings[1]
    k1, k2, k3 = permeabilities
    p_obs = math.log((k1 - k2) / (k2 - k3)) / math.log(r_ratio)
    k_ext = k3 + (k3 - k2) / (r_ratio ** p_obs - 1.0)

    # GCI (Roache's method, Fs = 1.25)
    eps_fine = abs((k3 - k2) / k3)
    gci_fine = 1.25 * eps_fine / (r_ratio ** p_obs - 1.0) * 100.0

    eps_coarse = abs((k1 - k2) / k2)
    gci_coarse_val = 1.25 * eps_coarse / (r_ratio ** p_obs - 1.0) * 100.0

    # Asymptotic convergence ratio
    gci_fine_raw = 1.25 * eps_fine / (r_ratio ** p_obs - 1.0)
    gci_coarse_raw = 1.25 * eps_coarse / (r_ratio ** p_obs - 1.0)
    asymptotic_ratio = gci_coarse_raw / (r_ratio ** p_obs * gci_fine_raw)
    in_asymptotic_range = abs(asymptotic_ratio - 1.0) < 0.05

    # ==============================================================
    # VALIDATION: Flow regime characterization
    # ==============================================================
    pres_cases = sorted(
        [d for d in os.listdir(base) if d.startswith("dp_")],
    )

    Us = []
    grad_ps = []
    for case_name in pres_cases:
        U, dp = get_converged_state(os.path.join(base, case_name))
        Us.append(U)
        grad_ps.append(dp / L_domain)

    Us = np.array(Us)
    grad_ps = np.array(grad_ps)

    # Forchheimer: dP/L = (mu/k)*U + beta*rho*U^2
    # Linearized: (dP/L)/U = mu/k + beta*rho*U
    Y = grad_ps / Us
    coeffs = np.polyfit(Us, Y, 1)
    b_fit = coeffs[0]   # beta * rho
    a_fit = coeffs[1]   # mu / k

    k_forch = mu / a_fit
    beta_forch = b_fit / rho

    # Critical Re: inertial = 10% of total
    # b*U^2 / (a*U + b*U^2) = 0.1 => U_crit = a/(9*b)
    U_crit = a_fit / (9.0 * b_fit)
    Re_crit = rho * U_crit * d_p / mu

    # Kozeny-Carman analytical permeability
    k_kc = d_p ** 2 * porosity ** 3 / (180.0 * (1.0 - porosity) ** 2)
    val_error_pct = abs(k_forch - k_kc) / k_kc * 100.0

    # ==============================================================
    # GNUPLOT PLOTS
    # ==============================================================

    # Write convergence data file
    with open("/app/convergence_data.dat", "w") as f:
        f.write("# h [m]    k [m^2]    k_extrap [m^2]\n")
        for h, k in zip(grid_spacings, permeabilities):
            f.write("{:.6e}  {:.6e}  {:.6e}\n".format(h, k, k_ext))

    # Write convergence gnuplot script
    with open("/app/convergence.gp", "w") as f:
        f.write('set terminal pngcairo size 800,600 enhanced\n')
        f.write('set output "/app/convergence.png"\n')
        f.write('set xlabel "Grid spacing h [m]"\n')
        f.write('set ylabel "Permeability k [m^2]"\n')
        f.write('set title "Grid Convergence Study"\n')
        f.write('set logscale x\n')
        f.write('set key top left\n')
        f.write('set grid\n')
        f.write('plot "/app/convergence_data.dat" using 1:2 '
                'with linespoints pt 7 ps 1.5 title "Computed k(h)", \\\n')
        f.write('     "/app/convergence_data.dat" using 1:3 '
                'with lines lt 2 dt 2 title "Extrapolated"\n')

    subprocess.run(["gnuplot", "/app/convergence.gp"], check=True)

    # Write regime data file
    with open("/app/regime_data.dat", "w") as f:
        f.write("# U [m/s]    dP/L [Pa/m]    fit [Pa/m]\n")
        for u, gp in zip(Us, grad_ps):
            fit_val = a_fit * u + b_fit * u ** 2
            f.write("{:.6e}  {:.6e}  {:.6e}\n".format(u, gp, fit_val))

    # Write regime gnuplot script
    with open("/app/regime.gp", "w") as f:
        f.write('set terminal pngcairo size 800,600 enhanced\n')
        f.write('set output "/app/regime.png"\n')
        f.write('set xlabel "Superficial velocity U [m/s]"\n')
        f.write('set ylabel "Pressure gradient dP/L [Pa/m]"\n')
        f.write('set title "Flow Regime Characterization"\n')
        f.write('set logscale x\n')
        f.write('set logscale y\n')
        f.write('set key top left\n')
        f.write('set grid\n')
        f.write('plot "/app/regime_data.dat" using 1:2 '
                'with points pt 7 ps 1.5 title "Simulation", \\\n')
        f.write('     "/app/regime_data.dat" using 1:3 '
                'with lines lt 2 lw 2 title "Forchheimer fit"\n')

    subprocess.run(["gnuplot", "/app/regime.gp"], check=True)

    # ==============================================================
    # OUTPUT
    # ==============================================================
    results = {
        "verification": {
            "permeabilities": permeabilities,
            "convergence_order": p_obs,
            "asymptotic_ratio": asymptotic_ratio,
            "extrapolated_value": k_ext,
            "discretization_uncertainty_pct": gci_fine,
            "in_asymptotic_range": in_asymptotic_range,
        },
        "validation": {
            "intrinsic_permeability": k_forch,
            "inertial_coefficient": beta_forch,
            "transition_reynolds": Re_crit,
            "kozeny_carman_permeability": k_kc,
            "validation_error_pct": val_error_pct,
        },
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
