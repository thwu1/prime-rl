#!/usr/bin/env python3
"""QEC analysis pipeline: Steane [[7,1,3]] code with non-Clifford T gates via Tsim.

"""

import json
import math
import os
import re

os.environ["JAX_PLATFORMS"] = "cpu"

import numpy as np
from tsim import Circuit

IDEAL_RATE_T = math.sin(math.pi / 8) ** 2  # sin^2(pi/8) ~ 0.14645
IDEAL_RATE_T2 = 0.5  # sin^2(pi/4) = 0.5
SHOTS = 200_000


def make_steane_circuit(gate="T", noise_rate=None):
    """Construct a [[7,1,3]] Steane code encoding circuit.

    Prepares |+> on qubit 6, applies the specified gate, then H,
    resets qubits 0-5, runs the encoding network (3 rounds of CZ gates
    with SQRT_Y rotations), and measures all 7 qubits in the Z basis.

    Detectors check X-type stabilizer parities:
      D0: qubits {0,1,2,3}
      D1: qubits {1,2,4,5}
      D2: qubits {2,3,4,6}
    Observable L0: logical Z via qubits {0,1,5}

    Args:
        gate: "T" for single T, "T_T" for double T, "R_Z" for R_Z(0.25)
        noise_rate: physical error rate for circuit-level depolarizing noise
    """
    if gate == "T":
        gate_line = "T 6"
    elif gate == "T_T":
        gate_line = "T 6\nT 6"
    elif gate == "R_Z":
        gate_line = "R_Z(0.25) 6"
    else:
        raise ValueError(f"Unknown gate type: {gate}")

    def dep1(qubits):
        return f"DEPOLARIZE1({noise_rate}) {qubits}" if noise_rate else ""

    def dep2(qubits):
        return f"DEPOLARIZE2({noise_rate}) {qubits}" if noise_rate else ""

    text = f"""
RX 6
{gate_line}
H 6
R 0 1 2 3 4 5
TICK
SQRT_Y_DAG 0 1 2 3 4 5
{dep1("0 1")}
TICK
CZ 1 2 3 4 5 6
{dep2("1 2")}
TICK
SQRT_Y 6
{dep1("6")}
TICK
CZ 0 3 2 5 4 6
TICK
SQRT_Y 2 3 4 5 6
{dep1("2 4 6")}
TICK
CZ 0 1 2 3 4 5
TICK
{dep1("0 1 2 3 4 5 6")}
SQRT_Y 1 2 4
X 3
TICK
M 0 1 2 3 4 5 6
DETECTOR rec[-7] rec[-6] rec[-5] rec[-4]
DETECTOR rec[-6] rec[-5] rec[-3] rec[-2]
DETECTOR rec[-5] rec[-4] rec[-3] rec[-1]
OBSERVABLE_INCLUDE(0) rec[-7] rec[-6] rec[-2]
"""
    return Circuit(text)


def parse_dem(dem):
    """Parse a stim DetectorErrorModel into a list of mechanism dicts."""
    mechanisms = []
    for line in str(dem).strip().split("\n"):
        line = line.strip()
        m = re.match(r"error\(([0-9.e+\-]+)\)\s+(.*)", line)
        if not m:
            continue
        prob = float(m.group(1))
        tokens = m.group(2).split()
        det_ids = [int(t[1:]) for t in tokens if t.startswith("D")]
        obs_ids = [int(t[1:]) for t in tokens if t.startswith("L")]
        mechanisms.append(
            {"probability": prob, "detectors": det_ids, "observables": obs_ids}
        )
    return mechanisms


def build_syndrome_decoder(mechanisms, num_detectors):
    """Build a maximum-likelihood syndrome lookup-table decoder.

    For each possible syndrome (tuple of detector values), accumulates
    the total probability of error mechanisms that flip L0 vs. those
    that do not. The decoder flips L0 when the flip-probability exceeds
    the no-flip probability for that syndrome.
    """
    flip_prob = {}
    noflip_prob = {}

    for mech in mechanisms:
        syndrome = tuple(
            1 if i in mech["detectors"] else 0 for i in range(num_detectors)
        )
        flips_l0 = 0 in mech["observables"]

        flip_prob.setdefault(syndrome, 0.0)
        noflip_prob.setdefault(syndrome, 0.0)

        if flips_l0:
            flip_prob[syndrome] += mech["probability"]
        else:
            noflip_prob[syndrome] += mech["probability"]

    table = {}
    all_syndromes = set(list(flip_prob.keys()) + list(noflip_prob.keys()))
    for syn in all_syndromes:
        table[syn] = flip_prob.get(syn, 0.0) > noflip_prob.get(syn, 0.0)

    # No-error syndrome defaults to no flip
    zero_syn = tuple(0 for _ in range(num_detectors))
    table.setdefault(zero_syn, False)

    return table


def apply_decoder(det_samples, obs_samples, table, num_detectors):
    """Apply the lookup-table decoder to sampled data."""
    corrected = obs_samples.copy()
    for i in range(len(det_samples)):
        syndrome = tuple(int(det_samples[i, j]) for j in range(num_detectors))
        if table.get(syndrome, False):
            corrected[i, 0] = not corrected[i, 0]
    return corrected


def main():
    results = {}

    # ===== 1. Circuit structural properties =====
    print("Constructing noiseless Steane code + T gate circuit...")
    c_t = make_steane_circuit("T")
    results["circuit_properties"] = {
        "num_qubits": c_t.num_qubits,
        "num_measurements": c_t.num_measurements,
        "num_detectors": c_t.num_detectors,
        "num_observables": c_t.num_observables,
        "t_count": c_t.tcount(),
        "is_clifford": c_t.is_clifford,
    }
    print(f"  Qubits: {c_t.num_qubits}, Detectors: {c_t.num_detectors}, "
          f"Observables: {c_t.num_observables}, T-count: {c_t.tcount()}")

    # ===== 2. Noiseless T-gate sampling =====
    print("Compiling and sampling noiseless T-gate circuit...")
    sampler_t = c_t.compile_detector_sampler(seed=42)
    det_t, obs_t = sampler_t.sample(shots=SHOTS, separate_observables=True)
    noiseless_obs = float(np.count_nonzero(obs_t)) / len(obs_t)
    noiseless_det = float(np.any(det_t, axis=1).sum()) / len(det_t)

    results["noiseless_analysis"] = {
        "observable_flip_rate": noiseless_obs,
        "detector_firing_rate": noiseless_det,
        "ideal_rate": float(IDEAL_RATE_T),
    }
    print(f"  Observable flip rate: {noiseless_obs:.4f} (ideal: {IDEAL_RATE_T:.4f})")
    print(f"  Detector firing rate: {noiseless_det:.4f}")

    # ===== 3. T vs R_Z(0.25) equivalence =====
    print("Verifying T vs R_Z(0.25) equivalence...")
    c_rz = make_steane_circuit("R_Z")
    sampler_rz = c_rz.compile_detector_sampler(seed=42)
    _, obs_rz = sampler_rz.sample(shots=SHOTS, separate_observables=True)
    rz_obs = float(np.count_nonzero(obs_rz)) / len(obs_rz)

    results["equivalence_check"] = {
        "t_observable_rate": noiseless_obs,
        "rz_observable_rate": rz_obs,
    }
    print(f"  T rate: {noiseless_obs:.4f}, R_Z rate: {rz_obs:.4f}, "
          f"diff: {abs(noiseless_obs - rz_obs):.4f}")

    # ===== 4. Detector error model analysis =====
    print("Extracting detector error model at p=0.001...")
    c_noisy = make_steane_circuit("T", noise_rate=0.001)
    dem = c_noisy.detector_error_model()
    mechanisms = parse_dem(dem)

    total_prob = sum(m["probability"] for m in mechanisms)
    max_weight = (
        max(len(m["detectors"]) + len(m["observables"]) for m in mechanisms)
        if mechanisms
        else 0
    )

    results["dem_analysis"] = {
        "num_error_mechanisms": len(mechanisms),
        "total_error_probability": total_prob,
        "max_mechanism_weight": max_weight,
    }
    print(f"  Error mechanisms: {len(mechanisms)}, total prob: {total_prob:.6f}, "
          f"max weight: {max_weight}")

    # ===== 5. Noisy sampling + syndrome decoding =====
    print("Sampling noisy circuit and applying decoder...")
    noisy_sampler = c_noisy.compile_detector_sampler(seed=123)
    det_noisy, obs_noisy = noisy_sampler.sample(
        shots=SHOTS, separate_observables=True
    )

    raw_obs = float(np.count_nonzero(obs_noisy)) / len(obs_noisy)
    det_rate = float(np.any(det_noisy, axis=1).sum()) / len(det_noisy)

    # Post-selection: keep only shots with no detector events
    no_error_mask = np.all(det_noisy == 0, axis=1)
    if np.any(no_error_mask):
        ps_obs = float(np.count_nonzero(obs_noisy[no_error_mask])) / int(
            no_error_mask.sum()
        )
    else:
        ps_obs = None

    # Build and apply syndrome decoder
    table = build_syndrome_decoder(mechanisms, c_noisy.num_detectors)
    corrected = apply_decoder(det_noisy, obs_noisy, table, c_noisy.num_detectors)
    dec_obs = float(np.count_nonzero(corrected)) / len(corrected)

    raw_dev = abs(raw_obs - IDEAL_RATE_T)
    dec_dev = abs(dec_obs - IDEAL_RATE_T)

    results["noisy_analysis"] = {
        "physical_error_rate": 0.001,
        "raw_observable_flip_rate": raw_obs,
        "detector_firing_rate": det_rate,
        "post_selected_observable_flip_rate": ps_obs,
        "decoded_observable_flip_rate": dec_obs,
        "raw_deviation_from_ideal": raw_dev,
        "decoded_deviation_from_ideal": dec_dev,
        "decoder_provides_improvement": bool(dec_dev < raw_dev),
    }
    print(f"  Raw obs rate: {raw_obs:.4f}, decoded: {dec_obs:.4f}")
    print(f"  Raw deviation: {raw_dev:.4f}, decoded deviation: {dec_dev:.4f}")
    print(f"  Detector firing rate: {det_rate:.4f}")
    if ps_obs is not None:
        print(f"  Post-selected rate: {ps_obs:.4f}")

    # ===== 6. Dual T-gate (T^2) analysis =====
    print("Analyzing dual T-gate (T^2) circuit...")
    c_t2 = make_steane_circuit("T_T")
    sampler_t2 = c_t2.compile_detector_sampler(seed=42)
    _, obs_t2 = sampler_t2.sample(shots=SHOTS, separate_observables=True)
    t2_obs = float(np.count_nonzero(obs_t2)) / len(obs_t2)

    results["dual_t_analysis"] = {
        "noiseless_observable_flip_rate": t2_obs,
        "ideal_rate": float(IDEAL_RATE_T2),
    }
    print(f"  Dual-T obs rate: {t2_obs:.4f} (ideal: {IDEAL_RATE_T2:.4f})")

    # ===== Write results =====
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("\nPipeline complete. Results written to /app/results.json")


if __name__ == "__main__":
    main()
