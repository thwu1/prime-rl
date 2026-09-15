#!/usr/bin/env python3
"""SPACE landscape evolution multi-regime analyzer.

Reads scenario configurations from /app/config.json, runs the SPACE
(Stream Power with Alluvium Conservation and Entrainment) model for each
scenario to geomorphic steady state, classifies the erosion regime,
computes analytical steady-state solutions, and writes diagnostic results
to /app/results.json.

Reference:
  Shobe, C.M., Tucker, G.E., Barnhart, K.R. (2017). The SPACE 1.0 model.
  Geoscientific Model Development 10(12), 4577-4604.
"""


import json
import sys

import numpy as np
from landlab import RasterModelGrid
from landlab.components import (
    DepressionFinderAndRouter,
    FlowAccumulator,
    Space,
)


def classify_regime(params):
    """Classify the erosion regime from physical parameters.

    - detachment_limited: F_f ~ 1, negligible soil and settling velocity
    - transport_limited:  F_f ~ 1, thick initial soil, significant v_s
    - bedrock_alluvial:   fractional F_f (0 < F_f < 1)
    """
    F_f = params["F_f"]
    v_s = params["v_s"]
    initial_soil = params["initial_soil_depth"]

    if F_f < 0.99:
        return "bedrock_alluvial"
    # F_f ~ 1
    if initial_soil > 10.0 and v_s > 0.1:
        return "transport_limited"
    return "detachment_limited"


def analytical_slopes(regime, params, drainage_areas):
    """Compute analytical steady-state slopes for the classified regime."""
    U = params["uplift_rate"]
    m = params["m_sp"]
    n = params["n_sp"]
    A = np.array(drainage_areas)

    if regime == "detachment_limited":
        # S = (U / K_br)^(1/n) * A^(-m/n)
        K_br = params["K_br"]
        return np.power(U / K_br, 1.0 / n) * np.power(A, -m / n)

    elif regime == "transport_limited":
        # S = ((U*v_s*(1-phi))/(K_sed*A^m) + (U*(1-phi))/(K_sed*A^m))^(1/n)
        K_sed = params["K_sed"]
        v_s = params["v_s"]
        phi = params["phi"]
        return np.power(
            (U * v_s * (1.0 - phi)) / (K_sed * np.power(A, m))
            + (U * (1.0 - phi)) / (K_sed * np.power(A, m)),
            1.0 / n,
        )

    elif regime == "bedrock_alluvial":
        # S = ((U*v_s*(1-F_f))/(K_sed*A^m) + U/(K_br*A^m))^(1/n)
        K_sed = params["K_sed"]
        K_br = params["K_br"]
        v_s = params["v_s"]
        F_f = params["F_f"]
        return np.power(
            (U * v_s * (1.0 - F_f)) / (K_sed * np.power(A, m))
            + U / (K_br * np.power(A, m)),
            1.0 / n,
        )


def analytical_soil_depth(params):
    """Compute bedrock-alluvial equilibrium soil depth.

    H = -H_star * ln(1 - v_s / (K_sed / (K_br * (1 - F_f)) + v_s))
    """
    H_star = params["H_star"]
    v_s = params["v_s"]
    K_sed = params["K_sed"]
    K_br = params["K_br"]
    F_f = params["F_f"]
    return float(-H_star * np.log(1.0 - (v_s / (K_sed / (K_br * (1.0 - F_f)) + v_s))))


def analytical_sediment_fluxes(params, drainage_areas):
    """Compute transport-limited steady-state sediment flux.

    Qs = U * A * (1 - phi)
    """
    U = params["uplift_rate"]
    phi = params["phi"]
    return (U * np.array(drainage_areas) * (1.0 - phi)).tolist()


def compute_concavity(slopes, drainage_areas):
    """Compute slope-area concavity index via log-log regression.

    S = k_s * A^(-theta) => log(S) = -theta * log(A) + log(k_s)
    """
    log_a = np.log(np.array(drainage_areas))
    log_s = np.log(np.array(slopes))
    coeffs = np.polyfit(log_a, log_s, 1)
    return float(-coeffs[0])


def run_scenario(name, params):
    """Run a single SPACE scenario to steady state."""
    nr = params["grid_rows"]
    nc = params["grid_cols"]
    dx = params["grid_spacing"]
    seed = params["random_seed"]
    topo_scale = params["topo_scale"]
    initial_soil = params["initial_soil_depth"]

    # ---- grid setup ----
    mg = RasterModelGrid((nr, nc), xy_spacing=dx)
    z = mg.add_zeros("topographic__elevation", at="node")
    br = mg.add_zeros("bedrock__elevation", at="node")
    soil = mg.add_zeros("soil__depth", at="node")

    # Initial topography: tilted plane + random noise
    np.random.seed(seed=seed)
    z[:] += (
        mg.node_y / topo_scale
        + mg.node_x / topo_scale
        + np.random.rand(len(mg.node_y)) / 10000.0
    )

    # Boundary conditions: all edges closed, node 0 open
    mg.set_closed_boundaries_at_grid_edges(
        bottom_is_closed=True,
        left_is_closed=True,
        right_is_closed=True,
        top_is_closed=True,
    )
    mg.set_watershed_boundary_condition_outlet_id(
        0, mg.at_node["topographic__elevation"], -9999.0
    )

    # Set soil depth and adjust elevations
    soil[:] = initial_soil
    br[:] = z[:]
    z[:] += soil[:]

    # ---- components ----
    fa = FlowAccumulator(
        mg,
        flow_director="D8",
        depression_finder="DepressionFinderAndRouter",
    )

    sp = Space(
        mg,
        K_sed=params["K_sed"],
        K_br=params["K_br"],
        F_f=params["F_f"],
        phi=params["phi"],
        H_star=params["H_star"],
        v_s=params["v_s"],
        m_sp=params["m_sp"],
        n_sp=params["n_sp"],
        sp_crit_sed=params["sp_crit_sed"],
        sp_crit_br=params["sp_crit_br"],
    )

    # ---- time loop ----
    U = params["uplift_rate"]
    dt = params["dt"]
    max_iter = params["max_iterations"]

    for i in range(max_iter):
        fa.run_one_step()
        sp.run_one_step(dt=dt)
        br[mg.core_nodes] += U * dt
        soil[0] = initial_soil  # maintain outlet boundary
        z[:] = br[:] + soil[:]

    # ---- collect results ----
    core = mg.core_nodes
    slopes = mg.at_node["topographic__steepest_slope"][core].tolist()
    areas = mg.at_node["drainage_area"][core].tolist()
    soil_depths = mg.at_node["soil__depth"][core].tolist()

    # Handle field name differences across landlab versions
    if "sediment__flux" in mg.at_node:
        sed_fluxes = mg.at_node["sediment__flux"][core].tolist()
    elif "sediment__outflux" in mg.at_node:
        sed_fluxes = mg.at_node["sediment__outflux"][core].tolist()
    else:
        sed_fluxes = [0.0] * len(core)

    return slopes, areas, soil_depths, sed_fluxes


def main():
    with open("/app/config.json") as f:
        config = json.load(f)

    results = {}

    for name, params in config["scenarios"].items():
        print(f"Running scenario: {name} ...", flush=True)

        slopes, areas, soil_depths, sed_fluxes = run_scenario(name, params)
        regime = classify_regime(params)
        ana_slopes = analytical_slopes(regime, params, areas)

        # Compute concavity index from numerical slopes
        concavity = compute_concavity(slopes, areas)

        result = {
            "regime": regime,
            "core_node_slopes": slopes,
            "core_node_drainage_areas": areas,
            "core_node_soil_depths": soil_depths,
            "core_node_sediment_fluxes": sed_fluxes,
            "analytical_slopes": ana_slopes.tolist(),
            "analytical_soil_depth": None,
            "analytical_sediment_fluxes": None,
            "slope_area_concavity": concavity,
        }

        if regime == "bedrock_alluvial":
            result["analytical_soil_depth"] = analytical_soil_depth(params)

        if regime == "transport_limited":
            result["analytical_sediment_fluxes"] = analytical_sediment_fluxes(
                params, areas
            )

        results[name] = result

        # Diagnostic output
        rmse = np.sqrt(np.mean((np.array(slopes) - ana_slopes) ** 2))
        print(f"  regime={regime}  slope_rmse={rmse:.2e}  concavity={concavity:.4f}", flush=True)

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")


if __name__ == "__main__":
    main()
