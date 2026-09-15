#!/usr/bin/env python3
"""Steane [[7,1,3]] code T-gate analysis pipeline using bloqade-tsim.

"""

import json
import math

import numpy as np
import tsim


def make_noiseless_circuit():
    """Build noiseless [[7,1,3]] Steane code with logical T-gate injection.

    Circuit structure:
      - Prepare |+> on qubit 6 via RX, apply T, then H
      - Reset ancilla qubits 0-5
      - Encode via CZ-based encoding (SQRT_Y_DAG, CZ layers, SQRT_Y corrections)
      - Measure all 7 qubits
      - 3 Z-type stabilizer detectors from [7,4,3] Hamming parity check matrix
      - 1 logical Z observable
    """
    return tsim.Circuit("""
        RX 6
        T 6
        H 6
        R 0 1 2 3 4 5
        SQRT_Y_DAG 0 1 2 3 4 5
        CZ 1 2 3 4 5 6
        SQRT_Y 6
        CZ 0 3 2 5 4 6
        SQRT_Y 2 3 4 5 6
        CZ 0 1 2 3 4 5
        SQRT_Y 1 2 4
        X 3
        TICK
        M 0 1 2 3 4 5 6
        DETECTOR rec[-7] rec[-6] rec[-5] rec[-4]
        DETECTOR rec[-6] rec[-5] rec[-3] rec[-2]
        DETECTOR rec[-5] rec[-4] rec[-3] rec[-1]
        OBSERVABLE_INCLUDE(0) rec[-7] rec[-6] rec[-2]
    """)


def make_noisy_circuit(p):
    """Build noisy version with circuit-level depolarizing noise.

    DEPOLARIZE1(p) after each single-qubit gate layer.
    DEPOLARIZE2(p) after each CZ (two-qubit) gate layer.
    DEPOLARIZE1(p) on all data qubits before measurement.
    """
    return tsim.Circuit(f"""
        RX 6
        T 6
        H 6
        R 0 1 2 3 4 5
        TICK
        SQRT_Y_DAG 0 1 2 3 4 5
        DEPOLARIZE1({p}) 0 1 2 3 4 5
        TICK
        CZ 1 2 3 4 5 6
        DEPOLARIZE2({p}) 1 2 3 4 5 6
        TICK
        SQRT_Y 6
        DEPOLARIZE1({p}) 6
        TICK
        CZ 0 3 2 5 4 6
        DEPOLARIZE2({p}) 0 3 2 5 4 6
        TICK
        SQRT_Y 2 3 4 5 6
        DEPOLARIZE1({p}) 2 3 4 5 6
        TICK
        CZ 0 1 2 3 4 5
        DEPOLARIZE2({p}) 0 1 2 3 4 5
        TICK
        DEPOLARIZE1({p}) 0 1 2 3 4 5 6
        SQRT_Y 1 2 4
        X 3
        TICK
        M 0 1 2 3 4 5 6
        DETECTOR rec[-7] rec[-6] rec[-5] rec[-4]
        DETECTOR rec[-6] rec[-5] rec[-3] rec[-2]
        DETECTOR rec[-5] rec[-4] rec[-3] rec[-1]
        OBSERVABLE_INCLUDE(0) rec[-7] rec[-6] rec[-2]
    """)


def count_dem_mechanisms(dem):
    """Count total error mechanisms and those that flip logical observable L0."""
    total = 0
    l0_flipping = 0
    for instr in dem:
        if instr.type == "error":
            total += 1
            targets = instr.targets_copy()
            for t in targets:
                if t.is_logical_observable_id() and t.val == 0:
                    l0_flipping += 1
                    break
    return total, l0_flipping


def main():
    # --- Noiseless circuit analysis ---
    c = make_noiseless_circuit()

    circuit_info = {
        "num_qubits": c.num_qubits,
        "num_measurements": c.num_measurements,
        "num_detectors": c.num_detectors,
        "num_observables": c.num_observables,
        "t_count": c.tcount(),
    }

    sampler = c.compile_detector_sampler(seed=42)
    det_samples, obs_samples = sampler.sample(
        shots=100_000, separate_observables=True
    )
    noiseless_obs_rate = float(np.mean(obs_samples))

    # --- Noisy analysis across multiple error rates ---
    noise_levels = [0.001, 0.005, 0.01, 0.05, 0.1]
    noisy_results = []

    for p in noise_levels:
        nc = make_noisy_circuit(p)

        # Detector error model analysis
        dem = nc.detector_error_model()
        num_mech, num_l0 = count_dem_mechanisms(dem)

        # Sampling
        sampler = nc.compile_detector_sampler(seed=42)
        det_samples, obs_samples = sampler.sample(
            shots=50_000, separate_observables=True
        )

        raw_obs_rate = float(np.mean(obs_samples))
        has_event = np.any(det_samples, axis=1)
        detection_event_rate = float(np.mean(has_event))

        # Post-selection: keep only shots with no detection events
        no_event = ~has_event
        ps_yield = float(np.mean(no_event))
        if np.sum(no_event) > 0:
            ps_obs_rate = float(np.mean(obs_samples[no_event]))
        else:
            ps_obs_rate = None

        noisy_results.append({
            "p": p,
            "num_dem_mechanisms": num_mech,
            "num_l0_flipping_mechanisms": num_l0,
            "raw_obs_rate": raw_obs_rate,
            "detection_event_rate": detection_event_rate,
            "post_selected_obs_rate": ps_obs_rate,
            "post_selection_yield": ps_yield,
        })

    results = {
        "circuit": circuit_info,
        "noiseless": {"observable_rate": noiseless_obs_rate},
        "noisy": noisy_results,
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    expected = math.sin(math.pi / 8) ** 2
    print(f"Noiseless obs rate: {noiseless_obs_rate:.4f} (expected: {expected:.4f})")
    for entry in noisy_results:
        print(
            f"p={entry['p']:.3f}: raw={entry['raw_obs_rate']:.4f} "
            f"ps={entry['post_selected_obs_rate']}"
            f" yield={entry['post_selection_yield']:.4f}"
            f" dem={entry['num_dem_mechanisms']} (L0: {entry['num_l0_flipping_mechanisms']})"
        )
    print("Results written to /app/results.json")


if __name__ == "__main__":
    main()
