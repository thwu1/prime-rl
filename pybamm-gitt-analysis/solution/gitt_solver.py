#!/usr/bin/env python3

"""
Solution: Evaluate and redesign a GITT pipeline.

Compares SPM and SPMe models for GITT analysis on an LGM50 cell (Chen2020).
Selects the model producing more physically consistent resistance estimates.

Key corrections to the prototype pipeline at /app/gitt_pipeline.py:
1. C-rate: 5C -> C/3 (GITT requires small perturbation currents to maintain
   quasi-equilibrium; 5C depletes a 5 Ah cell in ~2 pulses)
2. Resistance formula: (V_end - V_eq)/I -> (V_eq - V_end)/I (during discharge
   V_eq > V_end, so the original formula yields negative resistance)
3. Protocol: added rest periods between discharge pulses and an initial rest
   to establish OCV (the "Intermittent" in GITT)
4. Model selection: SPMe captures electrolyte concentration effects that are
   important for accurate resistance extraction in commercial cells
"""

import json
import numpy as np
import pybamm


def run_gitt(model, param, n_pulses=8, pulse_s=300, rest_s=1200, init_rest_s=60):
    """Run a GITT experiment and extract per-pulse electrochemical data."""
    Q_nom = param["Nominal cell capacity [A.h]"]

    experiment = pybamm.Experiment(
        [(f"Rest for {init_rest_s} seconds",)]
        + [
            (
                f"Discharge at C/3 for {pulse_s} seconds",
                f"Rest for {rest_s} seconds",
            )
        ]
        * n_pulses
    )

    sim = pybamm.Simulation(model, parameter_values=param, experiment=experiment)
    sol = sim.solve()

    # Initial OCV from rest cycle (cycle 0)
    init_cycle = sol.cycles[0]
    v_ocv = float(init_cycle["Terminal voltage [V]"](t=init_cycle.t[-1]))

    pulses_data = []
    cumulative_Ah = 0.0
    prev_v_relax = v_ocv

    for i in range(n_pulses):
        cycle = sol.cycles[i + 1]
        t_arr = cycle.t
        V_func = cycle["Terminal voltage [V]"]
        I_func = cycle["Current [A]"]

        i_arr = np.asarray(I_func(t=t_arr)).ravel()
        v_arr = np.asarray(V_func(t=t_arr)).ravel()

        is_discharge = np.abs(i_arr) > 0.01
        if np.any(is_discharge):
            dis_idx = np.where(is_discharge)[0]
            I_pulse = float(np.mean(np.abs(i_arr[dis_idx])))
            v_end_pulse = float(v_arr[dis_idx[-1]])
        else:
            I_pulse = Q_nom / 3.0
            v_end_pulse = float(v_arr[0])

        v_relax = float(v_arr[-1])
        v_eq = prev_v_relax

        # Corrected resistance: V_eq > V_end during discharge
        r_int = abs(v_eq - v_end_pulse) / I_pulse if I_pulse > 1e-10 else 0.0

        cumulative_Ah += I_pulse * pulse_s / 3600.0
        soc = max(0.0, 1.0 - cumulative_Ah / Q_nom)

        pulses_data.append({
            "pulse_number": i + 1,
            "v_before_pulse": round(v_eq, 6),
            "v_end_pulse": round(v_end_pulse, 6),
            "v_after_relaxation": round(v_relax, 6),
            "current_A": round(I_pulse, 6),
            "internal_resistance_ohm": round(r_int, 6),
            "approx_soc": round(soc, 4),
        })
        prev_v_relax = v_relax

    return pulses_data, cumulative_Ah


def consistency_score(pulses_data):
    """Rate the physical consistency of GITT results.

    Higher score = more physically consistent.
    Checks voltage ordering, recovery magnitude, resistance range,
    and voltage monotonicity.
    """
    score = 0
    for p in pulses_data:
        if p["v_before_pulse"] > p["v_end_pulse"]:
            score += 1
        if p["v_after_relaxation"] > p["v_end_pulse"]:
            score += 1
        if (p["v_after_relaxation"] - p["v_end_pulse"]) > 0.02:
            score += 1
        if 0.001 < p["internal_resistance_ohm"] < 0.5:
            score += 1
    v_relax = [p["v_after_relaxation"] for p in pulses_data]
    score += sum(1 for i in range(1, len(v_relax)) if v_relax[i] < v_relax[i - 1])
    return score


def main():
    param = pybamm.ParameterValues("Chen2020")

    # Run GITT with SPM (no electrolyte dynamics)
    print("Running GITT with SPM...")
    pulses_spm, charge_spm = run_gitt(pybamm.lithium_ion.SPM(), param)
    score_spm = consistency_score(pulses_spm)
    print(f"  SPM consistency score: {score_spm}")

    # Run GITT with SPMe (includes electrolyte concentration effects)
    print("Running GITT with SPMe...")
    pulses_spme, charge_spme = run_gitt(pybamm.lithium_ion.SPMe(), param)
    score_spme = consistency_score(pulses_spme)
    print(f"  SPMe consistency score: {score_spme}")

    # SPMe captures electrolyte concentration dynamics critical for accurate
    # GITT resistance estimation; prefer it when scores are equal or higher
    if score_spme >= score_spm:
        selected_name = "SPMe"
        pulses_data = pulses_spme
        cumulative_Ah = charge_spme
    else:
        selected_name = "SPM"
        pulses_data = pulses_spm
        cumulative_Ah = charge_spm

    print(f"Selected model: {selected_name}")

    # Aggregate metrics
    R_vals = [p["internal_resistance_ohm"] for p in pulses_data]
    avg_R = float(np.mean(R_vals))
    coeffs = np.polyfit(range(len(R_vals)), R_vals, 1)
    trend = "increasing" if coeffs[0] > 0 else "decreasing"

    results = {
        "n_pulses": 8,
        "model_used": selected_name,
        "pulses": pulses_data,
        "average_resistance_ohm": round(avg_R, 6),
        "resistance_trend": trend,
        "total_charge_removed_Ah": round(cumulative_Ah, 6),
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")
    print(f"  Model: {selected_name}")
    print(f"  Average resistance: {avg_R * 1000:.2f} mOhm")
    print(f"  Resistance trend: {trend}")
    print(f"  Total charge removed: {cumulative_Ah:.4f} A.h")


if __name__ == "__main__":
    main()
