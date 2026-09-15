#!/usr/bin/env python3
"""Battery cell discharge characterization pipeline."""

import json
import os

import numpy as np
import pybamm


def main():
    os.makedirs("/app/results", exist_ok=True)

    # Load cell specification
    with open("/app/cell_spec.json") as f:
        spec = json.load(f)

    param = pybamm.ParameterValues(spec["parameter_set"])
    param.update(
        {"Ambient temperature [K]": spec["test_conditions"]["ambient_temperature_k"]}
    )

    model = pybamm.lithium_ion.SPMe(options={"thermal": "isothermal"})

    nominal_cap = param["Nominal cell capacity [A.h]"]

    c_rates = [0.5, 1.0, 2.0]
    c_rate_labels = ["0.5C", "1C", "2C"]

    rate_data = {}
    decomp_data = {}

    for c_rate, label in zip(c_rates, c_rate_labels):
        print(f"Running {label} discharge...")

        experiment = pybamm.Experiment(
            [f"Discharge at {c_rate}C until {spec['voltage_limits']['lower_cutoff_v']} V"]
        )
        sim = pybamm.Simulation(
            model, parameter_values=param, experiment=experiment
        )
        sol = sim.solve(initial_soc=spec["test_conditions"]["initial_soc"])

        t = sol["Time [s]"].entries
        V = sol["Terminal voltage [V]"].entries
        I = sol["Current [A]"].entries
        Q = float(sol["Discharge capacity [A.h]"].entries[-1])

        # Energy
        energy_wh = float(np.trapezoid(V, t / 3600.0))
        avg_V = energy_wh / Q if Q > 0 else 0.0

        # Temperature — isothermal, use ambient
        max_T = float(spec["test_conditions"]["ambient_temperature_k"])

        rate_data[label] = {
            "capacity_ah": Q,
            "energy_wh": energy_wh,
            "avg_voltage_v": avg_V,
            "max_temp_k": max_T,
        }

        # Voltage decomposition
        idx = len(t) - 1

        rxn = float(sol["X-averaged battery reaction overpotential [V]"].entries[idx])
        conc = float(sol["X-averaged battery concentration overpotential [V]"].entries[idx])
        elyte = float(sol["X-averaged battery electrolyte ohmic losses [V]"].entries[idx])
        solid = float(sol["X-averaged battery solid phase ohmic losses [V]"].entries[idx])

        decomp_data[label] = {
            "reaction_overpotential_v": rxn,
            "concentration_overpotential_v": conc,
            "electrolyte_ohmic_v": elyte,
            "solid_phase_ohmic_v": solid,
        }

    # Write results
    with open("/app/results/rate_capability.json", "w") as f:
        json.dump(rate_data, f, indent=2)

    with open("/app/results/voltage_decomposition.json", "w") as f:
        json.dump(decomp_data, f, indent=2)

    print("Analysis complete. Results written to /app/results/")


if __name__ == "__main__":
    main()
