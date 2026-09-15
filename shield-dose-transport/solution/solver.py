#!/usr/bin/env python3
"""
Solve the spacecraft radiation shielding assessment.

"""

import json
import math
import os
import h5py

DELTA_X = 0.1  # spatial step in g/cm^2
N_GROUPS = 8


def load_hdf5_data(path):
    """Load all data from the HDF5 transport data file."""
    materials = {}
    spectra = {}
    spe_fluence = None
    h_star = None
    shield_configs = {}

    with h5py.File(path, "r") as f:
        # Materials
        for mat_name in f["materials"]:
            mg = f["materials"][mat_name]
            materials[mat_name] = {
                "removal_xs": mg["removal_cross_section"][:].tolist(),
                "scatter": mg["secondary_particle_matrix"][:].tolist(),
            }

        # Source spectra
        for env_name in f["source_spectra"]:
            sg = f["source_spectra"][env_name]
            env_type = sg.attrs["type"]
            if env_type == "continuous":
                spectra[env_name] = sg["flux"][:].tolist()
            elif env_type == "impulse":
                spe_fluence = sg["fluence"][:].tolist()

        # Dose conversion
        h_star = f["dose_conversion"]["h_star_10"][:].tolist()

        # Shield configurations
        for cfg_name in f["shield_configurations"]:
            cg = f["shield_configurations"][cfg_name]
            layers_raw = cg["layers"][:]
            layers = []
            for layer in layers_raw:
                mat = layer["material"]
                if isinstance(mat, bytes):
                    mat = mat.decode("utf-8")
                ad = float(layer["areal_density_g_per_cm2"])
                layers.append({"material": mat, "areal_density": ad})
            shield_configs[cfg_name] = layers

    return materials, spectra, spe_fluence, h_star, shield_configs


def propagate_step(phi_in, sigma_r, S, dx):
    """Single thin-slab transport step."""
    phi_out = [0.0] * N_GROUPS
    for gp in range(N_GROUPS):
        phi_out[gp] = phi_in[gp] * math.exp(-sigma_r[gp] * dx)
        for g in range(gp, N_GROUPS):
            reaction_rate = phi_in[g] * (1.0 - math.exp(-sigma_r[g] * dx))
            phi_out[gp] += reaction_rate * S[g][gp]
    return phi_out


def propagate_layer(phi_in, sigma_r, S, areal_density):
    """Propagate through a single material layer with spatial discretization."""
    phi = list(phi_in)
    n_steps = max(1, int(round(areal_density / DELTA_X)))
    dx = areal_density / n_steps
    for _ in range(n_steps):
        phi = propagate_step(phi, sigma_r, S, dx)
    return phi


def propagate_shield(phi_in, layers, materials):
    """Propagate through a multi-layer shield."""
    phi = list(phi_in)
    for layer in layers:
        mat = materials[layer["material"]]
        sigma_r = mat["removal_xs"]
        S = mat["scatter"]
        x = layer["areal_density"]
        phi = propagate_layer(phi, sigma_r, S, x)
    return phi


def dose_rate_from_flux(phi, h_star):
    """Compute dose rate in uSv/h from continuous flux (particles/cm2/s)."""
    total = sum(phi[g] * h_star[g] for g in range(N_GROUPS))
    return total * 3600.0 / 1e6


def dose_from_fluence(phi, h_star):
    """Compute dose in uSv from impulse fluence (particles/cm2)."""
    total = sum(phi[g] * h_star[g] for g in range(N_GROUPS))
    return total / 1e6


def main():
    materials, spectra, spe_fluence, h_star, shield_configs = load_hdf5_data(
        "/app/data/transport_data.h5"
    )

    with open("/app/data/mission.json") as f:
        mission = json.load(f)

    hours_per_month = mission["time_conversion"]["hours_per_month"]
    career_limit = mission["career_dose_limit_mSv"]

    os.makedirs("/app/results", exist_ok=True)

    # Part 1: Dose rates for all configs x all environments
    dose_rates = {}
    for env_name, flux in spectra.items():
        dose_rates[env_name] = {}
        for cfg_name, layers in shield_configs.items():
            phi_out = propagate_shield(flux, layers, materials)
            rate = dose_rate_from_flux(phi_out, h_star)
            dose_rates[env_name][cfg_name] = round(rate, 4)

    with open("/app/results/config_dose_rates.json", "w") as f:
        json.dump(dose_rates, f, indent=2)

    # Part 2: Mission dose for all configs
    mission_doses = {}
    for cfg_name, layers in shield_configs.items():
        flux_1 = spectra["gcr_1au_avg"]
        rate_1 = dose_rate_from_flux(
            propagate_shield(flux_1, layers, materials), h_star
        )
        leg1_hours = 6 * hours_per_month
        leg1_mSv = rate_1 * leg1_hours / 1000.0

        phi_spe = propagate_shield(spe_fluence, layers, materials)
        spe_uSv = dose_from_fluence(phi_spe, h_star)
        spe_mSv = spe_uSv / 1000.0

        flux_2 = spectra["gcr_1_5au"]
        rate_2 = dose_rate_from_flux(
            propagate_shield(flux_2, layers, materials), h_star
        )
        leg2_hours = 18 * hours_per_month
        leg2_mSv = rate_2 * leg2_hours / 1000.0

        leg3_mSv = leg1_mSv

        total_mSv = leg1_mSv + spe_mSv + leg2_mSv + leg3_mSv

        mission_doses[cfg_name] = {
            "leg1_dose_mSv": round(leg1_mSv, 4),
            "spe_dose_mSv": round(spe_mSv, 6),
            "leg2_dose_mSv": round(leg2_mSv, 4),
            "leg3_dose_mSv": round(leg3_mSv, 4),
            "total_dose_mSv": round(total_mSv, 4),
            "within_limit": total_mSv < career_limit,
        }

    with open("/app/results/mission_doses.json", "w") as f:
        json.dump(mission_doses, f, indent=2)

    print("Results written to /app/results/")


if __name__ == "__main__":
    main()
