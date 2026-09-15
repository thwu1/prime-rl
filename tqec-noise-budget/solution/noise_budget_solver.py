#!/usr/bin/env python3

"""Surface code noise mechanism decomposition.

Reads provided Stim circuits, decomposes uniform depolarizing noise into four
isolated mechanisms (gate_noise, idle_noise, prep_noise, meas_noise), extracts
detector error model statistics for each, and computes error budget fractions.
"""

import json
import stim


def extract_dem_stats(circuit: stim.Circuit) -> tuple:
    """Extract error count and total probability weight from a circuit's DEM.

    Returns:
        (error_count, total_weight): Number of error entries and sum of their
        probabilities in the detector error model.
    """
    dem = circuit.detector_error_model()
    total_weight = 0.0
    error_count = 0
    for instruction in dem.flattened():
        if instruction.type == "error":
            prob = instruction.args_copy()[0]
            total_weight += prob
            error_count += 1
    return error_count, total_weight


def main():
    # Load circuit parameters
    with open("/data/circuit_params.json") as f:
        params = json.load(f)

    p = params["noise_level"]
    code_task = params["code_task"]
    rounds = params["rounds"]
    d3 = params["distances"][0]
    d5 = params["distances"][1]

    # Load provided full circuits
    with open("/data/circuit_d{}.stim".format(d3)) as f:
        full_d3 = stim.Circuit(f.read())
    with open("/data/circuit_d{}.stim".format(d5)) as f:
        full_d5 = stim.Circuit(f.read())

    # Extract full circuit DEM statistics
    full_d3_errors, full_d3_weight = extract_dem_stats(full_d3)
    full_d5_errors, full_d5_weight = extract_dem_stats(full_d5)

    print("Full d={}: {} qubits, {} detectors, {} observables, "
          "DEM: {} errors, weight={:.8f}".format(
              d3, full_d3.num_qubits, full_d3.num_detectors,
              full_d3.num_observables, full_d3_errors, full_d3_weight))
    print("Full d={}: {} qubits, {} detectors, {} observables, "
          "DEM: {} errors, weight={:.8f}".format(
              d5, full_d5.num_qubits, full_d5.num_detectors,
              full_d5.num_observables, full_d5_errors, full_d5_weight))

    # Define zero-noise base and per-mechanism overrides
    zero_noise = dict(
        after_clifford_depolarization=0,
        before_round_data_depolarization=0,
        after_reset_flip_probability=0,
        before_measure_flip_probability=0,
    )

    mechanism_params = {
        "gate_noise": {"after_clifford_depolarization": p},
        "idle_noise": {"before_round_data_depolarization": p},
        "prep_noise": {"after_reset_flip_probability": p},
        "meas_noise": {"before_measure_flip_probability": p},
    }

    # Generate isolated-noise circuits and compute budget fractions
    print("\nDecomposing noise mechanisms at d=3...")
    mech_results = {}
    for mech_name, active_noise in mechanism_params.items():
        noise = {**zero_noise, **active_noise}
        iso_circuit = stim.Circuit.generated(
            code_task, rounds=rounds, distance=d3, **noise
        )
        error_count, total_weight = extract_dem_stats(iso_circuit)
        fraction = total_weight / full_d3_weight if full_d3_weight > 0 else 0.0
        mech_results[mech_name] = {
            "dem_error_count": error_count,
            "total_error_weight": total_weight,
            "budget_fraction": fraction,
        }
        print("  {}: {} DEM errors, weight={:.8f}, fraction={:.4f}".format(
            mech_name, error_count, total_weight, fraction))

    # Assemble output
    result = {
        "mechanisms": mech_results,
        "full_circuit": {
            "num_qubits_d3": full_d3.num_qubits,
            "num_qubits_d5": full_d5.num_qubits,
            "num_detectors_d3": full_d3.num_detectors,
            "num_detectors_d5": full_d5.num_detectors,
            "num_observables_d3": full_d3.num_observables,
            "num_observables_d5": full_d5.num_observables,
            "total_dem_weight_d3": full_d3_weight,
            "total_dem_weight_d5": full_d5_weight,
        },
    }

    with open("/app/error_budget.json", "w") as f:
        json.dump(result, f, indent=2)

    total_fraction = sum(m["budget_fraction"] for m in mech_results.values())
    print("\nBudget fraction sum: {:.4f}".format(total_fraction))
    print("Error budget written to /app/error_budget.json")


if __name__ == "__main__":
    main()
