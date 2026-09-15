"""Benchmark the surface code decoder using Stim circuits.

"""

import stim
import numpy as np
import json
import sys
import os

sys.path.insert(0, "/app")
from decoder import StimDecoder


def benchmark_circuit(circuit_path, num_shots, seed):
    with open(circuit_path) as f:
        circuit = stim.Circuit(f.read())
    dem = circuit.detector_error_model(decompose_errors=True)
    decoder = StimDecoder(dem)

    sampler = circuit.compile_detector_sampler(seed=seed)
    all_data = sampler.sample(shots=num_shots, append_observables=True)

    n_det = dem.num_detectors
    dets = all_data[:, :n_det].astype(bool)
    obs_actual = all_data[:, n_det:].astype(bool)

    obs_predicted = decoder.decode_batch(dets)
    errors = np.any(obs_predicted != obs_actual, axis=1)
    return float(errors.sum()) / num_shots


def main():
    with open("/app/config.json") as f:
        config = json.load(f)

    results = {}
    for bench in config["benchmarks"]:
        circuit_path = os.path.join("/app", bench["path"])
        ler = benchmark_circuit(circuit_path, config["num_shots"], config["seed"])
        key = f"d{bench['distance']}_p{str(bench['noise']).replace('.', '')}"
        results[key] = {
            "distance": bench["distance"],
            "noise": bench["noise"],
            "logical_error_rate": ler,
            "num_shots": config["num_shots"],
            "threshold": bench["threshold"],
            "passed": ler < bench["threshold"]
        }
        print(f"d={bench['distance']}, p={bench['noise']}: LER={ler:.6f} "
              f"(threshold={bench['threshold']}, "
              f"{'PASS' if ler < bench['threshold'] else 'FAIL'})")

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    all_passed = all(r["passed"] for r in results.values())
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
