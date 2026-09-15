#!/usr/bin/env python3

"""
Battery State-of-Health Analysis Pipeline

Computes formation-adjusted parameters for an LG M50 cell (Chen2020),
compares pristine and degraded discharge characteristics, tracks degradation
trajectory over two stages of cycling with SEI growth, and performs a
sensitivity sweep over SEI kinetic rate constants.
"""

import json

import numpy as np
import pybamm


def compute_formation_loss(param, delta_q_ah):
    """
    Compute degraded cell parameters after formation/storage capacity loss.

    Parameters
    ----------
    param : pybamm.ParameterValues
        The pristine Chen2020 parameter set.
    delta_q_ah : float
        Capacity lost during formation/storage [A.h].

    Returns
    -------
    dict with computed values and degraded parameters.
    """
    F = 96485.3  # Faraday constant [C/mol]

    # Cell geometry and material parameters
    z_sei = param["Ratio of lithium moles to SEI moles"]
    V_bar_sei = param["SEI partial molar volume [m3.mol-1]"]
    L_n = param["Negative electrode thickness [m]"]
    L_y = param["Electrode width [m]"]
    L_z = param["Electrode height [m]"]
    V_n = L_n * L_y * L_z  # negative electrode total volume [m^3]

    R_n = param["Negative particle radius [m]"]
    eps_act_n = param["Negative electrode active material volume fraction"]
    a_n = 3.0 * eps_act_n / R_n  # specific surface area [m^-1]

    eps_neg = param["Negative electrode porosity"]
    c_max_n = param["Maximum concentration in negative electrode [mol.m-3]"]
    c_init_n = param["Initial concentration in negative electrode [mol.m-3]"]

    # Convert capacity loss to SEI concentration [mol/m^3]
    c_sei = delta_q_ah * 3600.0 / (F * z_sei * V_n)

    # Lithium lost from negative electrode particles [mol/m^3]
    delta_c_n = c_sei * z_sei / eps_act_n
    c_init_degraded = c_init_n - delta_c_n

    # SEI film thickness from partial molar volume [m]
    L_sei = c_sei * V_bar_sei / a_n

    # Porosity reduction due to SEI occupying pore space
    eps_neg_degraded = eps_neg - L_sei * a_n

    initial_sto = c_init_n / c_max_n
    degraded_sto = c_init_degraded / c_max_n

    return {
        "capacity_loss_ah": delta_q_ah,
        "initial_stoichiometry": float(initial_sto),
        "degraded_stoichiometry": float(degraded_sto),
        "sei_thickness_nm": float(L_sei * 1e9),
        "degraded_porosity": float(eps_neg_degraded),
        # Internal values for downstream use
        "_c_init_degraded": c_init_degraded,
        "_L_sei": L_sei,
        "_eps_neg_degraded": eps_neg_degraded,
    }


def run_discharge(param, label=""):
    """Run a 1C discharge to 2.5V and return capacity and energy."""
    model = pybamm.lithium_ion.SPM({"SEI": "constant"})
    exp = pybamm.Experiment(["Discharge at 1C until 2.5 V"])
    sim = pybamm.Simulation(model, parameter_values=param, experiment=exp)
    sol = sim.solve(calc_esoh=False)

    t = sol["Time [s]"].entries
    V = sol["Voltage [V]"].entries
    I = sol["Current [A]"].entries
    capacity = float(sol["Discharge capacity [A.h]"].entries[-1])
    energy = float(np.trapz(V * np.abs(I), t) / 3600.0)

    print(f"  {label}: capacity={capacity:.4f} Ah, energy={energy:.4f} Wh")
    return capacity, energy


def run_single_stage_cycling_rpt(param_degraded, k_value):
    """
    Run 10 CCCV ageing cycles with SEI growth at a given kinetic rate
    constant, followed by a 1C reference discharge to 2.5V.

    Returns (rpt_capacity, final_sei_thickness_nm).
    """
    param_k = param_degraded.copy()
    param_k.update({"SEI kinetic rate constant [m.s-1]": k_value})

    model = pybamm.lithium_ion.SPM({"SEI": "ec reaction limited"})

    # 10 CCCV ageing cycles
    cccv_exp = pybamm.Experiment(
        [
            (
                "Discharge at 1C until 3 V",
                "Rest for 1 hour",
                "Charge at 1C until 4.2 V",
                "Hold at 4.2 V until C/50",
            )
        ]
        * 10
    )

    print(f"  Running 10 CCCV cycles at k={k_value:.0e}...")
    sim_cycling = pybamm.Simulation(
        model, experiment=cccv_exp, parameter_values=param_k
    )
    sol_cycling = sim_cycling.solve(calc_esoh=False)

    # RPT: 1C discharge to 2.5V from the fully charged state
    rpt_exp = pybamm.Experiment(["Discharge at 1C until 2.5 V"])
    sim_rpt = pybamm.Simulation(
        model, experiment=rpt_exp, parameter_values=param_k
    )
    sol_rpt = sim_rpt.solve(starting_solution=sol_cycling, calc_esoh=False)

    # Extract RPT capacity
    rpt_cycle = sol_rpt.cycles[-1]
    rpt_entries = rpt_cycle["Discharge capacity [A.h]"].entries
    rpt_capacity = float(rpt_entries[-1] - rpt_entries[0])

    # Extract final SEI thickness
    final_sei_nm = float(
        sol_rpt["X-averaged negative SEI thickness [m]"].entries[-1] * 1e9
    )

    print(f"    RPT capacity={rpt_capacity:.4f} Ah, SEI={final_sei_nm:.2f} nm")
    return rpt_capacity, final_sei_nm


def run_two_stage_cycling_rpt(param_degraded, k_value):
    """
    Run two stages of 10 CCCV ageing cycles each with SEI growth.
    After each stage: charge to full (if needed) + 1C RPT discharge to 2.5V.
    Between stages: charge the cell back to 4.2V before continuing.

    Returns (stage1_rpt, stage2_rpt, stage1_sei_nm, stage2_sei_nm).
    """
    param_k = param_degraded.copy()
    param_k.update({"SEI kinetic rate constant [m.s-1]": k_value})

    model = pybamm.lithium_ion.SPM({"SEI": "ec reaction limited"})

    cccv_exp = pybamm.Experiment(
        [
            (
                "Discharge at 1C until 3 V",
                "Rest for 1 hour",
                "Charge at 1C until 4.2 V",
                "Hold at 4.2 V until C/50",
            )
        ]
        * 10
    )

    rpt_exp = pybamm.Experiment(["Discharge at 1C until 2.5 V"])

    charge_exp = pybamm.Experiment(
        [("Charge at 1C until 4.2 V", "Hold at 4.2 V until C/50")]
    )

    # ── Stage 1: 10 CCCV cycles ──
    print(f"  Stage 1: 10 CCCV cycles at k={k_value:.0e}...")
    sim1 = pybamm.Simulation(
        model, experiment=cccv_exp, parameter_values=param_k
    )
    sol_cycling1 = sim1.solve(calc_esoh=False)

    # RPT 1: cell is charged after last CV hold at 4.2V
    sim_rpt1 = pybamm.Simulation(
        model, experiment=rpt_exp, parameter_values=param_k
    )
    sol_rpt1 = sim_rpt1.solve(starting_solution=sol_cycling1, calc_esoh=False)

    # Extract Stage 1 results
    rpt1_cycle = sol_rpt1.cycles[-1]
    rpt1_entries = rpt1_cycle["Discharge capacity [A.h]"].entries
    stage1_rpt = float(rpt1_entries[-1] - rpt1_entries[0])
    stage1_sei_nm = float(
        sol_rpt1["X-averaged negative SEI thickness [m]"].entries[-1] * 1e9
    )

    print(f"    Stage 1 RPT: {stage1_rpt:.4f} Ah, SEI: {stage1_sei_nm:.2f} nm")

    # ── Charge between stages ──
    # Cell is at ~2.5V after RPT. Must charge back to 4.2V before
    # starting Stage 2 CCCV (which begins with discharge to 3V).
    print("  Charging between stages...")
    sim_charge = pybamm.Simulation(
        model, experiment=charge_exp, parameter_values=param_k
    )
    sol_charge = sim_charge.solve(starting_solution=sol_rpt1, calc_esoh=False)

    # ── Stage 2: 10 more CCCV cycles ──
    print(f"  Stage 2: 10 CCCV cycles at k={k_value:.0e}...")
    sim2 = pybamm.Simulation(
        model, experiment=cccv_exp, parameter_values=param_k
    )
    sol_cycling2 = sim2.solve(starting_solution=sol_charge, calc_esoh=False)

    # RPT 2: cell is charged after last CV hold
    sim_rpt2 = pybamm.Simulation(
        model, experiment=rpt_exp, parameter_values=param_k
    )
    sol_rpt2 = sim_rpt2.solve(starting_solution=sol_cycling2, calc_esoh=False)

    # Extract Stage 2 results
    rpt2_cycle = sol_rpt2.cycles[-1]
    rpt2_entries = rpt2_cycle["Discharge capacity [A.h]"].entries
    stage2_rpt = float(rpt2_entries[-1] - rpt2_entries[0])
    stage2_sei_nm = float(
        sol_rpt2["X-averaged negative SEI thickness [m]"].entries[-1] * 1e9
    )

    print(f"    Stage 2 RPT: {stage2_rpt:.4f} Ah, SEI: {stage2_sei_nm:.2f} nm")

    return stage1_rpt, stage2_rpt, stage1_sei_nm, stage2_sei_nm


def main():
    print("=== Battery State-of-Health Analysis ===\n")

    # Load Chen2020 parameter set
    param = pybamm.ParameterValues("Chen2020")

    # ── Part 1: Formation Loss ──
    print("Part 1: Formation Loss Calculation")
    delta_q = 0.135  # A.h
    formation = compute_formation_loss(param, delta_q)
    print(f"  Initial stoichiometry: {formation['initial_stoichiometry']:.4f}")
    print(f"  Degraded stoichiometry: {formation['degraded_stoichiometry']:.4f}")
    print(f"  SEI thickness: {formation['sei_thickness_nm']:.2f} nm")
    print(f"  Degraded porosity: {formation['degraded_porosity']:.4f}")

    # ── Part 2: Discharge Comparison ──
    print("\nPart 2: Discharge Comparison")

    # Pristine cell
    cap_pristine, energy_pristine = run_discharge(param, label="Pristine")

    # Degraded cell
    param_degraded = param.copy()
    param_degraded.update(
        {
            "Initial concentration in negative electrode [mol.m-3]": formation[
                "_c_init_degraded"
            ],
            "Initial SEI thickness [m]": formation["_L_sei"],
            "Negative electrode porosity": formation["_eps_neg_degraded"],
        }
    )
    cap_degraded, energy_degraded = run_discharge(param_degraded, label="Degraded")

    discharge = {
        "pristine_capacity_ah": cap_pristine,
        "degraded_capacity_ah": cap_degraded,
        "capacity_difference_ah": float(cap_pristine - cap_degraded),
        "pristine_energy_wh": energy_pristine,
        "degraded_energy_wh": energy_degraded,
    }

    # ── Part 3: Degradation Trajectory (two-stage at k=1e-13) ──
    print("\nPart 3: Degradation Trajectory (two-stage, k=1e-13)")
    stage1_rpt, stage2_rpt, stage1_sei, stage2_sei = run_two_stage_cycling_rpt(
        param_degraded, 1e-13
    )

    stage1_retention = float(stage1_rpt / cap_degraded * 100)
    stage2_retention = float(stage2_rpt / cap_degraded * 100)
    fade_per_stage = float(
        (stage1_rpt - stage2_rpt) / stage1_rpt * 100
    )

    degradation_trajectory = {
        "stage1_rpt_ah": stage1_rpt,
        "stage2_rpt_ah": stage2_rpt,
        "stage1_retention_pct": stage1_retention,
        "stage2_retention_pct": stage2_retention,
        "stage1_sei_nm": stage1_sei,
        "stage2_sei_nm": stage2_sei,
        "capacity_fade_per_stage_pct": fade_per_stage,
    }

    print(f"\n  Trajectory summary:")
    print(f"    Stage 1: {stage1_rpt:.4f} Ah ({stage1_retention:.2f}%)")
    print(f"    Stage 2: {stage2_rpt:.4f} Ah ({stage2_retention:.2f}%)")
    print(f"    Fade per stage: {fade_per_stage:.4f}%")

    # ── Part 4: Sensitivity Sweep (single-stage) ──
    print("\nPart 4: Sensitivity Sweep (single-stage)")
    formation_sei_nm = formation["sei_thickness_nm"]

    # Run single-stage for k=1e-14 and k=1e-12
    rpt_14, sei_14 = run_single_stage_cycling_rpt(param_degraded, 1e-14)
    rpt_12, sei_12 = run_single_stage_cycling_rpt(param_degraded, 1e-12)

    # Reuse Stage 1 result for k=1e-13 (same protocol: 10 cycles + RPT)
    sensitivity = {
        "retention_1e-14": float(rpt_14 / cap_degraded * 100),
        "retention_1e-13": stage1_retention,
        "retention_1e-12": float(rpt_12 / cap_degraded * 100),
        "sei_growth_nm_1e-14": float(sei_14 - formation_sei_nm),
        "sei_growth_nm_1e-13": float(stage1_sei - formation_sei_nm),
        "sei_growth_nm_1e-12": float(sei_12 - formation_sei_nm),
    }

    print(f"\n  Sensitivity sweep:")
    for k_str in ["1e-14", "1e-13", "1e-12"]:
        print(
            f"    k={k_str}: retention={sensitivity[f'retention_{k_str}']:.2f}%, "
            f"SEI growth={sensitivity[f'sei_growth_nm_{k_str}']:.2f} nm"
        )

    # ── Output ──
    formation_output = {
        k: v for k, v in formation.items() if not k.startswith("_")
    }

    results = {
        "formation": formation_output,
        "discharge": discharge,
        "degradation_trajectory": degradation_trajectory,
        "sensitivity": sensitivity,
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("\nResults written to /app/results.json")


if __name__ == "__main__":
    main()
