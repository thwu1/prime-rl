"""ZNE benchmark pipeline: run zero-noise extrapolation on all circuits.

"""
import json
import os
import sys

sys.path.insert(0, "/app")

from simulator import simulate, load_circuit
from noise_scaling import fold_circuit_global
from extrapolation import (
    richardson_extrapolate,
    poly_extrapolate,
    exponential_extrapolate,
)

NOISE_LEVEL = 0.01
SCALE_FACTORS = [1, 3, 5]
CIRCUITS_DIR = "/app/circuits"
OUTPUT_PATH = "/app/results/benchmark.json"


def run_benchmark():
    results = {}

    for fname in sorted(os.listdir(CIRCUITS_DIR)):
        if not fname.endswith(".json"):
            continue

        circuit = load_circuit(os.path.join(CIRCUITS_DIR, fname))
        circuit_id = circuit.get("id", fname.replace(".json", ""))

        # Compute ideal (noiseless) and unmitigated (base noise) values
        ideal = simulate(circuit, noise_level=0.0)
        unmitigated = simulate(circuit, noise_level=NOISE_LEVEL)

        # Generate noise-amplified measurements via global circuit folding
        noisy_values = []
        for sf in SCALE_FACTORS:
            folded = fold_circuit_global(circuit, sf)
            val = simulate(folded, noise_level=NOISE_LEVEL)
            noisy_values.append(val)

        # Apply extrapolation methods
        richardson = richardson_extrapolate(SCALE_FACTORS, noisy_values)
        polynomial_2 = poly_extrapolate(SCALE_FACTORS, noisy_values, 2)
        exponential = exponential_extrapolate(SCALE_FACTORS, noisy_values)

        # Determine best method
        methods = {
            "richardson": richardson,
            "polynomial_2": polynomial_2,
            "exponential": exponential,
        }
        best_method = min(methods, key=lambda m: abs(methods[m] - ideal))

        results[circuit_id] = {
            "ideal": ideal,
            "unmitigated": unmitigated,
            "scale_factors": SCALE_FACTORS,
            "noisy_values": noisy_values,
            "richardson": richardson,
            "polynomial_2": polynomial_2,
            "exponential": exponential,
            "best_method": best_method,
        }

        print(
            f"{circuit_id}: ideal={ideal:.6f}, unmit={unmitigated:.6f}, "
            f"rich={richardson:.6f}, poly2={polynomial_2:.6f}, "
            f"exp={exponential:.6f}, best={best_method}"
        )

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nResults written to {OUTPUT_PATH}")


if __name__ == "__main__":
    run_benchmark()
