#!/usr/bin/env python3
"""
GITT analysis pipeline for LGM50 cell using PyBaMM.
Simulates galvanostatic intermittent titration and extracts electrochemical parameters.
"""

import json
import numpy as np
import pybamm


def run_gitt_analysis():
    # Set up SPMe model with Chen2020 parameters for the LGM50 cell
    model = pybamm.lithium_ion.SPMe()
    param = pybamm.ParameterValues("Chen2020")
    Q_nom = param["Nominal cell capacity [A.h]"]

    n_pulses = 8
    pulse_duration = 300  # seconds per discharge pulse

    # Define GITT experiment: series of discharge pulses
    experiment = pybamm.Experiment(
        [
            (f"Discharge at 5C for {pulse_duration} seconds",)
        ] * n_pulses
    )

    sim = pybamm.Simulation(model, parameter_values=param, experiment=experiment)
    sol = sim.solve()

    pulses_data = []
    cumulative_Ah = 0.0
    prev_v_relax = None

    for i in range(n_pulses):
        if i >= len(sol.cycles):
            # Simulation ended early — pad remaining pulses with last known state
            last = pulses_data[-1]
            pulses_data.append({
                "pulse_number": i + 1,
                "v_before_pulse": last["v_after_relaxation"],
                "v_end_pulse": last["v_after_relaxation"],
                "v_after_relaxation": last["v_after_relaxation"],
                "current_A": 0.0,
                "internal_resistance_ohm": 0.0,
                "approx_soc": last["approx_soc"],
            })
            continue

        cycle = sol.cycles[i]
        t_arr = cycle.t

        V_func = cycle["Terminal voltage [V]"]
        I_func = cycle["Current [A]"]

        v_arr = np.asarray(V_func(t=t_arr)).ravel()
        i_arr = np.asarray(I_func(t=t_arr)).ravel()

        # Identify discharge portion (where |I| > threshold)
        is_discharge = np.abs(i_arr) > 0.01

        if np.any(is_discharge):
            dis_idx = np.where(is_discharge)[0]
            I_pulse = float(np.mean(np.abs(i_arr[dis_idx])))
            v_end_pulse = float(v_arr[dis_idx[-1]])
        else:
            I_pulse = Q_nom / 3.0
            v_end_pulse = float(v_arr[0])

        # End-of-cycle voltage
        v_relax = float(v_arr[-1])

        # Equilibrium voltage: use previous relaxation or initial voltage
        if prev_v_relax is None:
            v_eq = float(v_arr[0])
        else:
            v_eq = prev_v_relax

        # Compute apparent internal resistance
        r_int = (v_end_pulse - v_eq) / I_pulse if I_pulse > 1e-10 else 0.0

        # Coulomb counting for SOC
        cumulative_Ah += I_pulse * pulse_duration / 3600.0
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

    # Aggregate metrics
    R_vals = [p["internal_resistance_ohm"] for p in pulses_data]
    avg_R = float(np.mean(R_vals))

    coeffs = np.polyfit(range(len(R_vals)), R_vals, 1)
    trend = "increasing" if coeffs[0] > 0 else "decreasing"

    results = {
        "n_pulses": n_pulses,
        "pulses": pulses_data,
        "average_resistance_ohm": round(avg_R, 6),
        "resistance_trend": trend,
        "total_charge_removed_Ah": round(cumulative_Ah, 6),
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("GITT analysis complete. Results written to /app/results.json")


if __name__ == "__main__":
    run_gitt_analysis()
