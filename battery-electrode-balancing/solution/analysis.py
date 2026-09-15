#!/usr/bin/env python3
"""
Cell electrode balancing analysis using PyBaMM.

Analyzes how varying the negative electrode thickness affects
lithium-ion cell discharge performance and lithium plating safety.
"""

import json
import sys

import numpy as np
import pybamm


def safe_scalar(val):
    """Convert a potentially multi-dimensional array/value to a Python float.

    For x-averaged quantities that unexpectedly carry an extra particle or
    spatial dimension, np.mean collapses everything to a scalar.
    """
    a = np.asarray(val, dtype=float)
    if a.ndim == 0:
        return float(a)
    if a.size == 1:
        return float(a.flat[0])
    return float(np.mean(a))


def eval_var_at_time(sol, var_name, t_val):
    """Evaluate a solution variable at a specific time, returning a scalar."""
    # Prefer the __call__ interface which handles interpolation
    try:
        val = sol[var_name](t=t_val)
        return safe_scalar(val)
    except (KeyError, TypeError, AttributeError, ValueError):
        pass
    # Fallback: index into .entries at closest time index
    entries = np.asarray(sol[var_name].entries, dtype=float)
    t_arr = np.asarray(sol.t, dtype=float).flatten()
    idx = int(np.argmin(np.abs(t_arr - t_val)))
    if entries.ndim == 1:
        return float(entries[idx])
    # entries may be (n_time, ...) — take mean across non-time dims
    return float(np.mean(entries[idx]))


def eval_var_last(sol, var_name):
    """Get the last time-step value of a variable as a scalar."""
    return eval_var_at_time(sol, var_name, float(sol.t[-1]))


_STOICH_NAMES = {
    "negative": [
        "X-averaged negative particle stoichiometry",
        "Negative electrode stoichiometry",
        "Average negative particle stoichiometry",
    ],
    "positive": [
        "X-averaged positive particle stoichiometry",
        "Positive electrode stoichiometry",
        "Average positive particle stoichiometry",
    ],
}

_CONC_VARS = {
    "negative": (
        "X-averaged negative particle concentration [mol.m-3]",
        "Maximum concentration in negative electrode [mol.m-3]",
    ),
    "positive": (
        "X-averaged positive particle concentration [mol.m-3]",
        "Maximum concentration in positive electrode [mol.m-3]",
    ),
}


def get_stoich(sol, electrode, t_val, param):
    """Get electrode stoichiometry at a specific time as a scalar float."""
    for name in _STOICH_NAMES[electrode]:
        try:
            return eval_var_at_time(sol, name, t_val)
        except (KeyError, TypeError, AttributeError, ValueError, IndexError):
            continue

    # Fallback: concentration / c_max
    conc_var, cmax_key = _CONC_VARS[electrode]
    try:
        conc = eval_var_at_time(sol, conc_var, t_val)
        c_max = float(param[cmax_key])
        return conc / c_max
    except (KeyError, TypeError, AttributeError, ValueError):
        pass

    raise KeyError(f"Could not find stoichiometry variable for {electrode} electrode")


def get_discharge_energy(sol):
    """Extract discharge energy in Wh, with manual integration fallback."""
    try:
        return eval_var_last(sol, "Discharge energy [W.h]")
    except (KeyError, TypeError, AttributeError):
        pass

    # Manual integration: E = integral(V * I) dt, converted to Wh
    t = np.asarray(sol["Time [s]"].entries, dtype=float).flatten()
    V = np.asarray(sol["Voltage [V]"].entries, dtype=float).flatten()
    I = np.asarray(sol["Current [A]"].entries, dtype=float).flatten()
    return float(np.trapz(V * I, t) / 3600.0)


def run_analysis():
    with open("/app/cell_config.json") as f:
        config = json.load(f)

    # Build model
    model_options = {"thermal": "lumped"}
    if config.get("include_thermal") is False:
        model_options.pop("thermal", None)

    # Try enabling built-in energy tracking
    model_options["calculate discharge energy"] = "true"

    model = pybamm.lithium_ion.SPMe(options=model_options)

    # Base parameters
    base_param = pybamm.ParameterValues(config["base_parameter_set"])
    base_neg_thickness = float(base_param["Negative electrode thickness [m]"])
    pos_thickness = float(base_param["Positive electrode thickness [m]"])
    nominal_capacity = float(base_param["Nominal cell capacity [A.h]"])

    results = {
        "base_parameters": {
            "negative_electrode_thickness_m": base_neg_thickness,
            "positive_electrode_thickness_m": pos_thickness,
            "nominal_cell_capacity_Ah": nominal_capacity,
        },
        "analyses": [],
        "optimal_multiplier": None,
        "max_safe_discharge_capacity_Ah": 0.0,
    }

    multipliers = config["negative_electrode_thickness_multipliers"]
    c_rate = config["discharge_c_rate"]
    v_min, v_max = config["voltage_limits_V"]
    t_amb = config["ambient_temperature_K"]
    margin = config["plating_stoichiometry_safety_margin"]
    threshold = 1.0 - margin

    for mult in multipliers:
        print(f"Running multiplier={mult:.2f} ...")

        param = pybamm.ParameterValues(config["base_parameter_set"])
        param["Negative electrode thickness [m]"] = base_neg_thickness * mult
        param["Lower voltage cut-off [V]"] = v_min
        param["Upper voltage cut-off [V]"] = v_max
        param["Ambient temperature [K]"] = t_amb
        param["Initial temperature [K]"] = t_amb

        sim = pybamm.Simulation(model, parameter_values=param)

        try:
            t_max = 3600.0 / c_rate * 1.5
            sol = sim.solve([0, t_max], initial_soc=1.0)
        except Exception as exc:
            print(f"  FAILED: {exc}", file=sys.stderr)
            results["analyses"].append(
                {"thickness_multiplier": mult, "error": str(exc)}
            )
            continue

        # Extract metrics using robust scalar-safe accessors
        discharge_capacity = eval_var_last(sol, "Discharge capacity [A.h]")
        discharge_energy = get_discharge_energy(sol)
        avg_voltage = (
            discharge_energy / discharge_capacity if discharge_capacity > 0 else 0.0
        )

        # Stoichiometries at start (SOC=100%) and end (SOC=0%) of discharge
        t_start = float(sol.t[0])
        t_end = float(sol.t[-1])

        neg_soc100 = get_stoich(sol, "negative", t_start, param)
        neg_soc0 = get_stoich(sol, "negative", t_end, param)
        pos_soc100 = get_stoich(sol, "positive", t_start, param)
        pos_soc0 = get_stoich(sol, "positive", t_end, param)

        # Plating risk: negative electrode too lithiated at SOC=100%
        plating_risk = bool(neg_soc100 > threshold)

        # Limiting electrode: which stoichiometry is nearer its extreme at EOD
        neg_margin_from_zero = neg_soc0           # neg approaches 0
        pos_margin_from_one = 1.0 - pos_soc0      # pos approaches 1
        limiting = (
            "negative" if neg_margin_from_zero < pos_margin_from_one else "positive"
        )

        analysis = {
            "thickness_multiplier": mult,
            "discharge_capacity_Ah": round(discharge_capacity, 6),
            "discharge_energy_Wh": round(discharge_energy, 6),
            "average_voltage_V": round(avg_voltage, 6),
            "neg_stoich_at_soc100": round(neg_soc100, 6),
            "neg_stoich_at_soc0": round(neg_soc0, 6),
            "pos_stoich_at_soc100": round(pos_soc100, 6),
            "pos_stoich_at_soc0": round(pos_soc0, 6),
            "plating_risk": plating_risk,
            "limiting_electrode": limiting,
        }
        results["analyses"].append(analysis)
        print(
            f"  cap={discharge_capacity:.3f} Ah, "
            f"x100={neg_soc100:.4f}, plating={plating_risk}, "
            f"limiting={limiting}"
        )

        # Track optimal (highest capacity among safe configs)
        if not plating_risk and discharge_capacity > results["max_safe_discharge_capacity_Ah"]:
            results["optimal_multiplier"] = mult
            results["max_safe_discharge_capacity_Ah"] = round(discharge_capacity, 6)

    # Write results
    out_path = "/app/results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults written to {out_path}")


if __name__ == "__main__":
    run_analysis()
