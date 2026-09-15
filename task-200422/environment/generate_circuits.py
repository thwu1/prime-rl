#!/usr/bin/env python3
"""Generate rotated surface code Stim circuit files for QEC analysis task."""
import os
import stim

NOISE_PARAMS = {
    'after_clifford_depolarization': 1e-3,
    'before_measure_flip_probability': 2e-3,
    'after_reset_flip_probability': 1e-3,
    'before_round_data_depolarization': 1e-3,
}

os.makedirs('/app/circuits', exist_ok=True)

for d in [3, 5, 7]:
    circuit = stim.Circuit.generated(
        "surface_code:rotated_memory_z",
        distance=d,
        rounds=3 * d,
        **NOISE_PARAMS,
    )
    with open(f'/app/circuits/d{d}.stim', 'w') as f:
        f.write(str(circuit))
    print(f"Generated d={d} circuit: {circuit.num_qubits} qubits, "
          f"{circuit.num_detectors} detectors")
