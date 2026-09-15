#!/usr/bin/env python3
"""Corrected cell characterization: SPM vs DFN fidelity study.

Fixes applied to the original cell_analysis.py:
1. Use C-rate notation (e.g. "1C") instead of absolute current ("1 A")
2. Use "lumped" thermal model to capture Joule heating at high C-rates
3. Remove incorrect active material volume fraction override
4. Use time-aligned interpolation for voltage RMSE computation
5. Extract electrolyte concentration at final timestep, not t=0

"""

import json
import numpy as np
import pybamm


def run_discharge(model_class, c_rate, param):
    """Run constant-current discharge simulation with lumped thermal model."""
    model = model_class(options={"thermal": "lumped"})
    exp = pybamm.Experiment([f"Discharge at {c_rate}C until 2.5 V"])
    sim = pybamm.Simulation(model, parameter_values=param, experiment=exp)
    sol = sim.solve()
    return sol


def compute_voltage_rmse(sol_a, sol_b, n_points=100):
    """Compute RMSE between voltage traces using time-aligned interpolation."""
    t_end = min(float(sol_a.t[-1]), float(sol_b.t[-1]))
    t_eval = np.linspace(0, t_end, n_points)
    v_a = np.asarray(sol_a["Terminal voltage [V]"](t_eval)).flatten()
    v_b = np.asarray(sol_b["Terminal voltage [V]"](t_eval)).flatten()
    return float(np.sqrt(np.mean((v_a - v_b) ** 2)))


def main():
    c_rates = [0.5, 1.0, 2.0, 3.0]
    param = pybamm.ParameterValues("Chen2020")

    caps_spm = {}
    caps_dfn = {}
    sols_spm = {}
    sols_dfn = {}

    for cr in c_rates:
        print(f"Running SPM at {cr}C ...")
        sol_s = run_discharge(pybamm.lithium_ion.SPM, cr, param)
        caps_spm[str(cr)] = round(float(
            sol_s["Discharge capacity [A.h]"].entries[-1]), 4)
        sols_spm[cr] = sol_s

        print(f"Running DFN at {cr}C ...")
        sol_d = run_discharge(pybamm.lithium_ion.DFN, cr, param)
        caps_dfn[str(cr)] = round(float(
            sol_d["Discharge capacity [A.h]"].entries[-1]), 4)
        sols_dfn[cr] = sol_d

    # Relative capacity errors
    rel_errs = {}
    for cr in c_rates:
        s = caps_spm[str(cr)]
        d = caps_dfn[str(cr)]
        rel_errs[str(cr)] = round(abs(s - d) / d * 100, 4)

    # Voltage RMSE at selected C-rates
    v_rmse = {}
    for cr in [1.0, 3.0]:
        v_rmse[str(cr)] = round(
            compute_voltage_rmse(sols_spm[cr], sols_dfn[cr]), 6)

    # Temperature rise at 3C
    T = sols_dfn[3.0]["Cell temperature [K]"].entries
    temp_rise = float(np.max(T)) - 273.15 - 25.0

    # Electrolyte concentration range at end of 3C DFN discharge
    ce = sols_dfn[3.0]["Electrolyte concentration [mol.m-3]"]
    ce_snapshot = ce.entries[:, -1]
    conc_range = float(np.max(ce_snapshot) - np.min(ce_snapshot))

    results = {
        "capacities_spm": caps_spm,
        "capacities_dfn": caps_dfn,
        "relative_errors_pct": rel_errs,
        "voltage_rmse": v_rmse,
        "max_temperature_rise_3C": round(temp_rise, 2),
        "electrolyte_conc_range_3C": round(conc_range, 2),
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")


if __name__ == "__main__":
    main()
