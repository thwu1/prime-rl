#!/usr/bin/env python3
"""Generate transport_data.h5 for spacecraft radiation shielding task."""
import numpy as np
import h5py
import os

os.makedirs("/app/data", exist_ok=True)

with h5py.File("/app/data/transport_data.h5", "w") as f:
    f.attrs["description"] = "Nuclear interaction data library for spacecraft radiation shielding analysis"
    f.attrs["format_version"] = "1.0"

    # --- Energy group structure ---
    eg = f.create_group("energy_groups")
    eg.attrs["num_groups"] = 8
    ds = eg.create_dataset(
        "boundaries_mev",
        data=np.array(
            [10.0, 30.0, 100.0, 300.0, 1000.0, 3000.0, 10000.0, 30000.0, 100000.0]
        ),
    )
    ds.attrs["units"] = "MeV"
    ds.attrs["ordering"] = "Group 0 = lowest energy (10-30 MeV), Group 7 = highest (30000-100000 MeV)"

    # --- Materials ---
    materials_grp = f.create_group("materials")

    all_materials = {
        "aluminum": {
            "symbol": "Al",
            "Z": 13,
            "A": 27,
            "density": 2.70,
            "removal_xs": [0.120, 0.095, 0.075, 0.062, 0.055, 0.052, 0.050, 0.049],
            "scatter": [
                [0.30, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00],
                [0.15, 0.28, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00],
                [0.05, 0.18, 0.25, 0.00, 0.00, 0.00, 0.00, 0.00],
                [0.02, 0.06, 0.20, 0.22, 0.00, 0.00, 0.00, 0.00],
                [0.01, 0.03, 0.08, 0.22, 0.20, 0.00, 0.00, 0.00],
                [0.005, 0.02, 0.05, 0.10, 0.25, 0.18, 0.00, 0.00],
                [0.003, 0.01, 0.03, 0.07, 0.12, 0.28, 0.15, 0.00],
                [0.002, 0.008, 0.02, 0.05, 0.10, 0.15, 0.30, 0.12],
            ],
        },
        "iron": {
            "symbol": "Fe",
            "Z": 26,
            "A": 56,
            "density": 7.87,
            "removal_xs": [0.085, 0.072, 0.060, 0.052, 0.048, 0.046, 0.045, 0.044],
            "scatter": [
                [0.35, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00],
                [0.18, 0.32, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00],
                [0.08, 0.22, 0.28, 0.00, 0.00, 0.00, 0.00, 0.00],
                [0.04, 0.10, 0.25, 0.24, 0.00, 0.00, 0.00, 0.00],
                [0.03, 0.06, 0.12, 0.28, 0.20, 0.00, 0.00, 0.00],
                [0.02, 0.04, 0.08, 0.15, 0.30, 0.16, 0.00, 0.00],
                [0.015, 0.03, 0.06, 0.12, 0.18, 0.32, 0.12, 0.00],
                [0.01, 0.025, 0.05, 0.10, 0.16, 0.22, 0.34, 0.10],
            ],
        },
        "polyethylene": {
            "symbol": "CH2",
            "Z": -1,
            "A": 14,
            "density": 0.94,
            "removal_xs": [0.178, 0.140, 0.105, 0.082, 0.068, 0.060, 0.056, 0.054],
            "scatter": [
                [0.25, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00],
                [0.35, 0.22, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00],
                [0.06, 0.38, 0.20, 0.00, 0.00, 0.00, 0.00, 0.00],
                [0.02, 0.08, 0.40, 0.18, 0.00, 0.00, 0.00, 0.00],
                [0.01, 0.03, 0.10, 0.42, 0.16, 0.00, 0.00, 0.00],
                [0.005, 0.02, 0.05, 0.12, 0.44, 0.14, 0.00, 0.00],
                [0.003, 0.01, 0.03, 0.08, 0.15, 0.46, 0.12, 0.00],
                [0.002, 0.008, 0.02, 0.06, 0.12, 0.20, 0.48, 0.10],
            ],
        },
        "lead": {
            "symbol": "Pb",
            "Z": 82,
            "A": 207,
            "density": 11.35,
            "removal_xs": [0.065, 0.058, 0.050, 0.045, 0.042, 0.041, 0.040, 0.040],
            "scatter": [
                [0.38, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00],
                [0.20, 0.35, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00],
                [0.12, 0.24, 0.30, 0.00, 0.00, 0.00, 0.00, 0.00],
                [0.06, 0.14, 0.28, 0.26, 0.00, 0.00, 0.00, 0.00],
                [0.04, 0.08, 0.16, 0.30, 0.22, 0.00, 0.00, 0.00],
                [0.03, 0.06, 0.12, 0.20, 0.32, 0.18, 0.00, 0.00],
                [0.025, 0.05, 0.10, 0.16, 0.24, 0.34, 0.14, 0.00],
                [0.02, 0.04, 0.08, 0.14, 0.20, 0.28, 0.36, 0.10],
            ],
        },
        "water": {
            "symbol": "H2O",
            "Z": -1,
            "A": 18,
            "density": 1.00,
            "removal_xs": [0.165, 0.130, 0.098, 0.078, 0.064, 0.057, 0.053, 0.051],
            "scatter": [
                [0.26, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00],
                [0.32, 0.24, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00],
                [0.06, 0.35, 0.21, 0.00, 0.00, 0.00, 0.00, 0.00],
                [0.02, 0.07, 0.37, 0.19, 0.00, 0.00, 0.00, 0.00],
                [0.01, 0.03, 0.09, 0.38, 0.17, 0.00, 0.00, 0.00],
                [0.005, 0.02, 0.05, 0.11, 0.40, 0.15, 0.00, 0.00],
                [0.003, 0.01, 0.03, 0.08, 0.14, 0.42, 0.13, 0.00],
                [0.002, 0.008, 0.02, 0.06, 0.11, 0.18, 0.44, 0.11],
            ],
        },
        "carbon": {
            "symbol": "C",
            "Z": 6,
            "A": 12,
            "density": 1.60,
            "removal_xs": [0.150, 0.118, 0.090, 0.072, 0.062, 0.057, 0.053, 0.051],
            "scatter": [
                [0.28, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00],
                [0.25, 0.26, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00],
                [0.06, 0.28, 0.23, 0.00, 0.00, 0.00, 0.00, 0.00],
                [0.02, 0.07, 0.30, 0.20, 0.00, 0.00, 0.00, 0.00],
                [0.01, 0.03, 0.09, 0.32, 0.18, 0.00, 0.00, 0.00],
                [0.005, 0.02, 0.05, 0.11, 0.35, 0.16, 0.00, 0.00],
                [0.003, 0.01, 0.03, 0.08, 0.14, 0.38, 0.13, 0.00],
                [0.002, 0.008, 0.02, 0.05, 0.11, 0.18, 0.40, 0.11],
            ],
        },
    }

    for name, props in all_materials.items():
        mg = materials_grp.create_group(name)
        mg.attrs["symbol"] = props["symbol"]
        mg.attrs["atomic_number"] = props["Z"]
        mg.attrs["atomic_mass"] = props["A"]
        mg.attrs["density_g_per_cm3"] = props["density"]
        ds_xs = mg.create_dataset(
            "removal_cross_section", data=np.array(props["removal_xs"])
        )
        ds_xs.attrs["units"] = "cm2/g"
        ds_xs.attrs["description"] = (
            "Macroscopic removal cross-section per unit areal density"
        )
        ds_sc = mg.create_dataset(
            "secondary_particle_matrix", data=np.array(props["scatter"])
        )
        ds_sc.attrs["convention"] = (
            "matrix[source_group, product_group]; "
            "source_group >= product_group for non-zero entries (no upscatter); "
            "diagonal = forward scattering; "
            "below diagonal = downscatter from higher to lower energy"
        )
        ds_sc.attrs["description"] = (
            "Fractional yield of secondary/scattered particles per nuclear interaction"
        )

    # --- Source spectra ---
    spectra_grp = f.create_group("source_spectra")

    gcr_envs = {
        "gcr_1au_avg": {
            "type": "continuous",
            "desc": "GCR protons at 1 AU, averaged solar modulation",
            "flux": [3.2, 12.5, 22.0, 24.0, 10.5, 3.0, 0.5, 0.06],
        },
        "gcr_1au_min": {
            "type": "continuous",
            "desc": "GCR protons at 1 AU, solar minimum (maximum GCR intensity)",
            "flux": [4.48, 17.5, 30.8, 33.6, 14.7, 4.2, 0.7, 0.084],
        },
        "gcr_1au_max": {
            "type": "continuous",
            "desc": "GCR protons at 1 AU, solar maximum (minimum GCR intensity)",
            "flux": [1.92, 7.5, 13.2, 14.4, 6.3, 1.8, 0.3, 0.036],
        },
        "gcr_1_5au": {
            "type": "continuous",
            "desc": "GCR protons at 1.5 AU (Mars orbit), averaged solar modulation",
            "flux": [3.68, 14.375, 25.3, 27.6, 12.075, 3.45, 0.575, 0.069],
        },
    }

    for env_name, env_data in gcr_envs.items():
        sg = spectra_grp.create_group(env_name)
        sg.attrs["type"] = env_data["type"]
        sg.attrs["description"] = env_data["desc"]
        ds = sg.create_dataset("flux", data=np.array(env_data["flux"]))
        ds.attrs["units"] = "protons/cm2/s"

    spe = spectra_grp.create_group("spe_event")
    spe.attrs["type"] = "impulse"
    spe.attrs["description"] = (
        "Solar Particle Event total integrated fluence (single impulsive event)"
    )
    ds = spe.create_dataset(
        "fluence",
        data=np.array([5.0e7, 2.0e7, 5.0e6, 1.0e6, 1.0e5, 5.0e3, 1.0e2, 1.0]),
    )
    ds.attrs["units"] = "protons/cm2"

    # --- Dose conversion coefficients ---
    dc = f.create_group("dose_conversion")
    dc.attrs["reference"] = "ICRP Publication 116 - protons"
    dc.attrs["quantity"] = "Ambient dose equivalent H*(10)"
    ds = dc.create_dataset(
        "h_star_10",
        data=np.array([3.0, 8.0, 22.0, 55.0, 110.0, 180.0, 280.0, 420.0]),
    )
    ds.attrs["units"] = "pSv.cm2"
    ds.attrs["description"] = (
        "Fluence-to-dose conversion: multiply particle fluence (particles/cm2) "
        "by coefficient to get dose in pSv"
    )

    # --- Shield configurations ---
    shields_grp = f.create_group("shield_configurations")

    layer_dt = np.dtype(
        [("material", "S20"), ("areal_density_g_per_cm2", np.float64)]
    )

    shield_specs = {
        "bare": {
            "desc": "No shielding (unshielded reference)",
            "layers": [],
        },
        "config_A": {
            "desc": "Single aluminum structural shell",
            "layers": [("aluminum", 2.70)],
        },
        "config_B": {
            "desc": "Aluminum-iron-aluminum sandwich",
            "layers": [("aluminum", 2.70), ("iron", 7.87), ("aluminum", 2.70)],
        },
        "config_C": {
            "desc": "Single polyethylene slab",
            "layers": [("polyethylene", 15.0)],
        },
        "config_D": {
            "desc": "Iron-polyethylene-aluminum graded shield",
            "layers": [("iron", 5.0), ("polyethylene", 10.0), ("aluminum", 3.0)],
        },
        "config_E": {
            "desc": "Lead-iron-polyethylene-carbon four-layer heavy shield",
            "layers": [
                ("lead", 3.0),
                ("iron", 8.0),
                ("polyethylene", 12.0),
                ("carbon", 5.0),
            ],
        },
        "config_F": {
            "desc": "Al-Fe-CH2-Fe-Al five-layer reactor-style shield",
            "layers": [
                ("aluminum", 2.70),
                ("iron", 15.74),
                ("polyethylene", 1.88),
                ("iron", 15.74),
                ("aluminum", 2.70),
            ],
        },
    }

    for cfg_name, cfg_data in shield_specs.items():
        cg = shields_grp.create_group(cfg_name)
        cg.attrs["description"] = cfg_data["desc"]
        raw = cfg_data["layers"]
        if raw:
            arr = np.array(raw, dtype=layer_dt)
        else:
            arr = np.array([], dtype=layer_dt)
        cg.create_dataset("layers", data=arr)

print("Created /app/data/transport_data.h5")
