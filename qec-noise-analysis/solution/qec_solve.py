#!/usr/bin/env python3
"""Solution: QEC noise threshold analysis using bloqade-tsim."""

import json
import os

os.environ["JAX_PLATFORMS"] = "cpu"

import numpy as np
from tsim import Circuit


def make_steane_circuit(p):
    """Construct the noisy [[7,1,3]] Steane code encoding circuit.

    Encodes the logical state H T |+> with depolarizing noise at rate p.
    Uses the standard Steane code stabilizer preparation subcircuit:
      - SQRT_Y_DAG on qubits 0-5 (prepare Y-basis)
      - Three rounds of CZ entangling gates
      - SQRT_Y / X corrections to complete encoding
    Detectors check Z-stabilizer parities; observable is the logical X.
    """
    return Circuit(
        f"""
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
    """
    )


def make_physical_circuit(p):
    """Construct the unencoded single-qubit reference circuit."""
    return Circuit(
        f"""
        RX 0
        T 0
        H 0
        DEPOLARIZE1({p}) 0
        M 0
    """
    )


def sample_steane(p, shots):
    """Sample from the Steane code circuit and compute post-selection stats."""
    c = make_steane_circuit(p)
    sampler = c.compile_detector_sampler()
    det_samples, obs_samples = sampler.sample(
        shots=shots, separate_observables=True
    )

    any_det = np.any(det_samples, axis=1)
    det_rate = float(any_det.mean())
    raw_obs_rate = float(obs_samples.mean())

    no_det = ~any_det
    n_postsel = int(no_det.sum())
    if n_postsel > 0:
        postsel_obs_rate = float(obs_samples[no_det].mean())
    else:
        postsel_obs_rate = float("nan")

    yield_rate = n_postsel / shots
    return det_rate, raw_obs_rate, postsel_obs_rate, yield_rate


def sample_physical(p, shots):
    """Sample from the physical qubit circuit and return obs rate."""
    c = make_physical_circuit(p)
    sampler = c.compile_sampler()
    samples = sampler.sample(shots=shots)
    return float(samples.mean())


def parse_dem(dem):
    """Extract error probabilities from a detector error model."""
    dem_str = str(dem)
    probs = []
    for line in dem_str.strip().split("\n"):
        line = line.strip()
        if line.startswith("error("):
            p_str = line.split("(")[1].split(")")[0]
            probs.append(float(p_str))
    return probs


def main():
    results = {}

    # 1. Structural analysis at p=0.01
    c = make_steane_circuit(0.01)
    results["num_qubits"] = c.num_qubits
    results["num_detectors"] = c.num_detectors
    results["num_observables"] = c.num_observables
    results["tcount"] = c.tcount()

    # 2. Detector error model at p=0.01
    dem = c.detector_error_model(approximate_disjoint_errors=True)
    error_probs = parse_dem(dem)
    results["num_dem_errors"] = len(error_probs)
    results["dem_error_probs"] = error_probs

    # 3. Noiseless sampling (p=0)
    det_r, obs_r, _, _ = sample_steane(0.0, 200_000)
    results["noiseless_obs_rate"] = obs_r
    results["noiseless_det_rate"] = det_r

    # 4. Noisy sampling (p=0.01)
    det_r, raw_obs, postsel_obs, _ = sample_steane(0.01, 200_000)
    results["noisy_det_rate"] = det_r
    results["noisy_raw_obs_rate"] = raw_obs
    results["noisy_postselected_obs_rate"] = postsel_obs

    # 5. Noise sweep with physical comparison
    sweep_results = []
    for p in [0.001, 0.005, 0.01, 0.05, 0.1]:
        det_r, _, postsel_obs, yield_r = sample_steane(p, 200_000)
        phys_obs = sample_physical(p, 200_000)
        sweep_results.append(
            {
                "p": p,
                "postselected_obs_rate": postsel_obs,
                "detection_rate": det_r,
                "yield": yield_r,
                "physical_obs_rate": phys_obs,
            }
        )
    results["sweep_results"] = sweep_results

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Done. Results written to /app/results.json")


if __name__ == "__main__":
    main()
