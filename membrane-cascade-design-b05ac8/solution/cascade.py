
"""Two-stage membrane cascade design with recycle and fugacity-corrected driving forces."""

import json
from .eos import pr_fugacity_mixture, load_gas_properties

BARRER_TO_SI = 3.348e-16  # mol*m / (m^2 * s * Pa)


def _load_polymer_database():
    with open("/app/data/polymer_database.json") as f:
        return json.load(f)


def _solve_permeate_composition(Q_CO2, Q_CH4, f_CO2_h, f_CH4_h, p_l_Pa):
    """Solve for permeate CO2 mole fraction in perfect-mixing model.

    In perfect mixing, the permeate composition is uniform and satisfies:
        y_P = J_CO2 / (J_CO2 + J_CH4)
    where J_i = Q_i * (f_i_high - y_i * p_low)

    Solved via fixed-point iteration.
    """
    y = 0.5
    for _ in range(500):
        flux_CO2 = Q_CO2 * (f_CO2_h - y * p_l_Pa)
        flux_CH4 = Q_CH4 * (f_CH4_h - (1 - y) * p_l_Pa)
        total_flux = flux_CO2 + flux_CH4
        if total_flux <= 0:
            break
        y_new = flux_CO2 / total_flux
        if abs(y_new - y) < 1e-14:
            break
        y = y_new
    return y


def _solve_stage(F_in, x_F, x_R_target, p_h_bar, p_l_bar, T, Q_CO2, Q_CH4, gas_props):
    """Solve a single membrane stage with perfect mixing.

    Given the target retentate CO2 fraction, compute the required membrane area,
    permeate composition, and flow split.

    Parameters
    ----------
    F_in : float, feed flow (mol/s)
    x_F : float, feed CO2 mole fraction
    x_R_target : float, target retentate CO2 mole fraction
    p_h_bar, p_l_bar : float, high/low pressures (bar)
    T : float, temperature (K)
    Q_CO2, Q_CH4 : float, permeances (mol/(m^2*s*Pa))
    gas_props : dict

    Returns
    -------
    (area_m2, stage_dict)
    """
    x_R = x_R_target
    p_h_Pa = p_h_bar * 1e5
    p_l_Pa = p_l_bar * 1e5

    # Fugacity coefficients on the high-pressure (retentate) side
    mix_result = pr_fugacity_mixture(
        ["CO2", "CH4"], [x_R, 1 - x_R], T, p_h_bar, gas_props
    )
    phi_CO2 = mix_result["phi"]["CO2"]
    phi_CH4 = mix_result["phi"]["CH4"]

    # Fugacities on high-pressure side
    f_CO2_h = phi_CO2 * x_R * p_h_Pa
    f_CH4_h = phi_CH4 * (1 - x_R) * p_h_Pa

    # Solve for permeate composition
    y_P = _solve_permeate_composition(Q_CO2, Q_CH4, f_CO2_h, f_CH4_h, p_l_Pa)

    # Mass balance: F_in * x_F = R_out * x_R + P_out * y_P
    # where R_out = F_in - P_out
    # => P_out = F_in * (x_F - x_R) / (y_P - x_R)
    denom = y_P - x_R
    if abs(denom) < 1e-15:
        raise ValueError("Cannot separate: permeate and retentate compositions equal")

    P_out = F_in * (x_F - x_R) / denom
    R_out = F_in - P_out

    # Required membrane area from CO2 flux
    J_CO2_total = P_out * y_P  # mol/s of CO2 permeating
    driving_force = f_CO2_h - y_P * p_l_Pa  # Pa
    if driving_force <= 0:
        raise ValueError("Non-positive CO2 driving force")

    A = J_CO2_total / (Q_CO2 * driving_force)  # m^2

    stage_cut = P_out / F_in

    return A, {
        "area_m2": A,
        "stage_cut": stage_cut,
        "retentate": {"CO2": x_R, "CH4": 1 - x_R},
        "permeate": {"CO2": y_P, "CH4": 1 - y_P},
        "retentate_flow": R_out,
        "permeate_flow": P_out,
    }


def design_cascade(config_path):
    """Design a two-stage membrane cascade with interstage recycle.

    Topology:
        Stage 1 feed = raw feed + recycle
        Stage 1 retentate = product
        Stage 1 permeate -> recompressed -> Stage 2 feed
        Stage 2 retentate = recycle
        Stage 2 permeate = reject

    Each stage is sized so its retentate meets the target CO2 mole fraction.
    The recycle is iterated until convergence.
    """
    with open(config_path) as f:
        config = json.load(f)

    gas_props = load_gas_properties()
    polymer_db = _load_polymer_database()

    # Extract parameters
    F0 = config["feed"]["total_flow_mol_per_s"]
    z_CO2 = config["feed"]["composition"]["CO2"]
    p_h = config["feed"]["pressure_bar"]
    p_l = config["permeate_pressure_bar"]
    T = config["feed"]["temperature_K"]

    polymer_abbrev = config["membrane"]["polymer"]
    polymer = next(
        p for p in polymer_db["polymers"] if p["abbreviation"] == polymer_abbrev
    )
    P_CO2_barrer = polymer["permeabilities_barrer"]["CO2"]
    P_CH4_barrer = polymer["permeabilities_barrer"]["CH4"]
    l_m = config["membrane"]["thickness_um"] * 1e-6  # m

    # Permeances in mol/(m^2*s*Pa)
    Q_CO2 = P_CO2_barrer * BARRER_TO_SI / l_m
    Q_CH4 = P_CH4_barrer * BARRER_TO_SI / l_m

    x_R1_target = config["targets"]["stage1_retentate_CO2_mol_frac"]
    x_R2_target = config["targets"]["stage2_retentate_CO2_mol_frac"]

    # Iterative solution with direct substitution
    recycle_flow = 0.0
    recycle_CO2 = z_CO2
    converged = False
    max_iter = 500

    for iteration in range(max_iter):
        # Stage 1 feed = raw feed + recycle
        F1 = F0 + recycle_flow
        if F1 > 0:
            x_F1 = (F0 * z_CO2 + recycle_flow * recycle_CO2) / F1
        else:
            x_F1 = z_CO2

        # Solve Stage 1
        A1, s1 = _solve_stage(
            F1, x_F1, x_R1_target, p_h, p_l, T, Q_CO2, Q_CH4, gas_props
        )

        # Stage 1 permeate -> Stage 2 (recompressed to p_h)
        F2 = s1["permeate_flow"]
        x_F2 = s1["permeate"]["CO2"]

        # Solve Stage 2
        A2, s2 = _solve_stage(
            F2, x_F2, x_R2_target, p_h, p_l, T, Q_CO2, Q_CH4, gas_props
        )

        new_recycle_flow = s2["retentate_flow"]
        new_recycle_CO2 = s2["retentate"]["CO2"]

        # Check convergence (skip first iteration)
        if iteration > 0 and recycle_flow > 1e-10:
            rel_flow = abs(new_recycle_flow - recycle_flow) / recycle_flow
            rel_comp = abs(new_recycle_CO2 - recycle_CO2) / max(
                abs(recycle_CO2), 1e-15
            )
            if rel_flow < 1e-6 and rel_comp < 1e-6:
                recycle_flow = new_recycle_flow
                recycle_CO2 = new_recycle_CO2
                converged = True
                break

        recycle_flow = new_recycle_flow
        recycle_CO2 = new_recycle_CO2

    # Build final output
    product_flow = s1["retentate_flow"]
    product_CO2 = x_R1_target
    reject_flow = s2["permeate_flow"]
    reject_CO2 = s2["permeate"]["CO2"]

    methane_recovery = product_flow * (1 - product_CO2) / (F0 * (1 - z_CO2))

    return {
        "stage1": {
            "area_m2": round(A1, 4),
            "stage_cut": round(s1["stage_cut"], 8),
            "retentate": {
                "CO2": round(s1["retentate"]["CO2"], 8),
                "CH4": round(s1["retentate"]["CH4"], 8),
            },
            "permeate": {
                "CO2": round(s1["permeate"]["CO2"], 8),
                "CH4": round(s1["permeate"]["CH4"], 8),
            },
        },
        "stage2": {
            "area_m2": round(A2, 4),
            "stage_cut": round(s2["stage_cut"], 8),
            "retentate": {
                "CO2": round(s2["retentate"]["CO2"], 8),
                "CH4": round(s2["retentate"]["CH4"], 8),
            },
            "permeate": {
                "CO2": round(s2["permeate"]["CO2"], 8),
                "CH4": round(s2["permeate"]["CH4"], 8),
            },
        },
        "product": {
            "flow_mol_per_s": round(product_flow, 6),
            "CO2_mol_frac": round(product_CO2, 8),
        },
        "reject": {
            "flow_mol_per_s": round(reject_flow, 6),
            "CO2_mol_frac": round(reject_CO2, 8),
        },
        "recycle": {
            "flow_mol_per_s": round(recycle_flow, 6),
            "CO2_mol_frac": round(recycle_CO2, 8),
        },
        "methane_recovery": round(methane_recovery, 8),
        "converged": converged,
        "iterations": iteration + 1,
    }
