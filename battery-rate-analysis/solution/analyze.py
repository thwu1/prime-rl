#!/usr/bin/env python3
"""
Rate capability analysis with voltage decomposition for a lithium-ion cell.
Uses PyBaMM SPMe model with Chen2020 parameters and lumped thermal model.
"""

import json
import os

import numpy as np
import pybamm


def find_variable(sol, candidates):
    """Try each candidate variable name; return the first that resolves."""
    for name in candidates:
        try:
            _ = sol[name].entries
            return name
        except KeyError:
            continue
    raise KeyError(
        f"None of the candidate variable names found: {candidates}"
    )


def main():
    os.makedirs("/app/results", exist_ok=True)

    # ── Model and parameters ──────────────────────────────────────────
    model = pybamm.lithium_ion.SPMe(options={"thermal": "lumped"})
    param = pybamm.ParameterValues("Chen2020")
    param.update({"Ambient temperature [K]": 298.15})

    nominal_cap = param["Nominal cell capacity [A.h]"]

    c_rates = [0.2, 0.5, 1.0, 1.5, 2.0]
    c_rate_labels = ["0.2C", "0.5C", "1C", "1.5C", "2C"]

    rate_data = {}
    decomp_data = {}
    discharge_times = []
    discharge_currents = []

    # Variable name candidates (cover naming differences across versions)
    temp_candidates = [
        "X-averaged cell temperature [K]",
        "Cell temperature [K]",
        "Volume-averaged cell temperature [K]",
    ]
    rxn_candidates = [
        "X-averaged battery reaction overpotential [V]",
        "Battery reaction overpotential [V]",
    ]
    conc_candidates = [
        "X-averaged battery concentration overpotential [V]",
        "Battery concentration overpotential [V]",
    ]
    elyte_candidates = [
        "X-averaged battery electrolyte ohmic losses [V]",
        "Battery electrolyte ohmic losses [V]",
    ]
    solid_candidates = [
        "X-averaged battery solid phase ohmic losses [V]",
        "Battery solid phase ohmic losses [V]",
    ]

    for c_rate, label in zip(c_rates, c_rate_labels):
        print(f"Simulating {label} discharge...")

        experiment = pybamm.Experiment(
            [f"Discharge at {c_rate}C until 2.5 V"]
        )
        sim = pybamm.Simulation(
            model, parameter_values=param, experiment=experiment
        )
        sol = sim.solve(initial_soc=1.0)

        # ── Basic metrics ─────────────────────────────────────────────
        t = sol["Time [s]"].entries
        V = sol["Terminal voltage [V]"].entries
        I = sol["Current [A]"].entries
        Q_arr = sol["Discharge capacity [A.h]"].entries

        Q = float(Q_arr[-1])
        energy_wh = float(np.trapezoid(V * np.abs(I), t) / 3600.0)
        avg_V = energy_wh / Q if Q > 0 else 0.0

        # Temperature
        temp_var = find_variable(sol, temp_candidates)
        T = sol[temp_var].entries
        max_T = float(np.max(T))

        rate_data[label] = {
            "capacity_ah": Q,
            "energy_wh": energy_wh,
            "avg_voltage_v": avg_V,
            "max_temp_k": max_T,
        }

        discharge_times.append(float(t[-1]))
        discharge_currents.append(c_rate * nominal_cap)

        # ── Voltage decomposition at 50% DOD ─────────────────────────
        dod_frac = Q_arr / Q
        idx_50 = int(np.argmin(np.abs(dod_frac - 0.5)))

        rxn_var = find_variable(sol, rxn_candidates)
        conc_var = find_variable(sol, conc_candidates)
        elyte_var = find_variable(sol, elyte_candidates)
        solid_var = find_variable(sol, solid_candidates)

        rxn = float(abs(sol[rxn_var].entries[idx_50]))
        conc = float(abs(sol[conc_var].entries[idx_50]))
        elyte = float(abs(sol[elyte_var].entries[idx_50]))
        solid = float(abs(sol[solid_var].entries[idx_50]))

        decomp_data[label] = {
            "reaction_overpotential_v": rxn,
            "concentration_overpotential_v": conc,
            "electrolyte_ohmic_v": elyte,
            "solid_phase_ohmic_v": solid,
        }

        print(
            f"  {label}: Q={Q:.4f} Ah, E={energy_wh:.4f} Wh, "
            f"V_avg={avg_V:.4f} V, T_max={max_T:.2f} K"
        )

    # ── Critical C-rate ───────────────────────────────────────────────
    cap_ref = rate_data["0.2C"]["capacity_ah"]
    critical_crate = "0.2C"
    for label in c_rate_labels:
        if rate_data[label]["capacity_ah"] >= 0.8 * cap_ref:
            critical_crate = label

    # ── Peukert exponent ──────────────────────────────────────────────
    # ln(t) = ln(K) - k * ln(I)
    log_I = np.log(np.array(discharge_currents))
    log_t = np.log(np.array(discharge_times))
    coeffs = np.polyfit(log_I, log_t, 1)
    peukert_k = float(-coeffs[0])

    # ── Dominant loss mechanism ───────────────────────────────────────
    dominant_loss = {}
    for label in c_rate_labels:
        losses = {
            "reaction_overpotential": decomp_data[label][
                "reaction_overpotential_v"
            ],
            "concentration_overpotential": decomp_data[label][
                "concentration_overpotential_v"
            ],
            "electrolyte_ohmic": decomp_data[label]["electrolyte_ohmic_v"],
            "solid_phase_ohmic": decomp_data[label]["solid_phase_ohmic_v"],
        }
        dominant_loss[label] = max(losses, key=losses.get)

    analysis = {
        "critical_crate": critical_crate,
        "peukert_exponent": peukert_k,
        "dominant_loss": dominant_loss,
    }

    # ── Write outputs ─────────────────────────────────────────────────
    with open("/app/results/rate_capability.json", "w") as f:
        json.dump(rate_data, f, indent=2)

    with open("/app/results/voltage_decomposition.json", "w") as f:
        json.dump(decomp_data, f, indent=2)

    with open("/app/results/analysis.json", "w") as f:
        json.dump(analysis, f, indent=2)

    print(f"\nCritical C-rate: {critical_crate}")
    print(f"Peukert exponent: {peukert_k:.4f}")
    print(f"Dominant losses: {dominant_loss}")
    print("Results written to /app/results/")


if __name__ == "__main__":
    main()
