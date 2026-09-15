#!/usr/bin/env python3
"""Generate rotated surface code circuits for the decoder task."""
import stim
import os

os.makedirs("/app/circuits", exist_ok=True)

configs = [
    ("d3_p005", 3, 3, 0.005),
    ("d5_p005", 5, 5, 0.005),
]

for name, d, r, p in configs:
    circuit = stim.Circuit.generated(
        "surface_code:rotated_memory_z",
        distance=d,
        rounds=r,
        after_clifford_depolarization=p,
        before_measure_flip_probability=p,
        after_reset_flip_probability=p,
    )
    path = f"/app/circuits/{name}.stim"
    with open(path, "w") as f:
        f.write(str(circuit))
    dem = circuit.detector_error_model(decompose_errors=True)
    print(f"Generated {path}: {dem.num_detectors} detectors, "
          f"{dem.num_observables} observables, {circuit.num_qubits} qubits")
