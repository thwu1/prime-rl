#!/usr/bin/env python3
"""Draft QEC pipeline — produces incorrect results, needs debugging.

"""
import os
os.environ["JAX_PLATFORMS"] = "cpu"

from tsim import Circuit


def make_steane_t_circuit():
    text = """
RX 6
T 6
H 6
R 0 1 2 3 4 5
TICK
SQRT_Y_DAG 0 1 2 3 4 5
TICK
CZ 1 2 3 4 5 6
TICK
SQRT_Y 6
TICK
CZ 0 3 2 5 4 6
TICK
SQRT_Y 2 3 4 5 6
TICK
CZ 0 1 2 3 4 5
TICK
SQRT_Y 1 2 4
TICK
M 0 1 2 3 4 5 6
DETECTOR rec[-7] rec[-6] rec[-4] rec[-3]
DETECTOR rec[-6] rec[-4] rec[-3] rec[-2]
DETECTOR rec[-4] rec[-3] rec[-2] rec[-1]
OBSERVABLE_INCLUDE(0) rec[-7] rec[-5] rec[-1]
"""
    return Circuit(text)


if __name__ == "__main__":
    c = make_steane_t_circuit()
    print(f"Qubits: {c.num_qubits}, Detectors: {c.num_detectors}, "
          f"Observables: {c.num_observables}")

    sampler = c.compile_detector_sampler(seed=42)
    det, obs = sampler.sample(shots=10000, separate_observables=True)

    obs_rate = sum(int(obs[i, 0]) for i in range(len(obs))) / len(obs)
    det_rate = sum(
        1 for i in range(len(det))
        if any(det[i, j] for j in range(det.shape[1]))
    ) / len(det)

    print(f"Observable flip rate: {obs_rate:.4f}")
    print(f"Detector firing rate: {det_rate:.4f}")
    print("NOTE: Expected detector firing rate of 0.0 for a correct "
          "noiseless circuit")
