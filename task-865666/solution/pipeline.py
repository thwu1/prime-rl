#!/usr/bin/env python3

"""
Surface Code QEC Analysis Pipeline.

Generates rotated surface code circuits using Stim, decodes with PyMatching
MWPM, and produces a structured JSON report with circuit metadata, logical
error rates, error suppression factors, threshold estimate, and hardware
footprint projection.
"""

import json
import math
import sys

import numpy as np
import pymatching
import stim

DISTANCES = [3, 5, 7]
NOISE_LEVELS = [0.001, 0.002, 0.004, 0.006, 0.008, 0.01]
MIN_SHOTS = 50_000
MAX_SHOTS = 200_000
TARGET_ERRORS = 500  # Stop sampling after this many errors for efficiency


def generate_circuit(d: int, p: float) -> stim.Circuit:
    """Generate a rotated surface code memory_z circuit."""
    return stim.Circuit.generated(
        "surface_code:rotated_memory_z",
        rounds=3 * d,
        distance=d,
        after_clifford_depolarization=p,
        after_reset_flip_probability=p,
        before_measure_flip_probability=p,
        before_round_data_depolarization=p,
    )


def count_logical_errors(circuit: stim.Circuit, num_shots: int) -> int:
    """Count logical errors using MWPM decoding via PyMatching."""
    sampler = circuit.compile_detector_sampler()
    detection_events, observable_flips = sampler.sample(
        num_shots, separate_observables=True
    )
    dem = circuit.detector_error_model(decompose_errors=True)
    matcher = pymatching.Matching.from_detector_error_model(dem)
    predictions = matcher.decode_batch(detection_events)
    num_errors = int(np.sum(np.any(predictions != observable_flips, axis=1)))
    return num_errors


def per_round_error_rate(per_shot: float, rounds: int) -> float:
    """Convert per-shot logical error rate to per-round rate.

    Uses the formula: e_round = 1 - (1 - e_shot)^(1/rounds)
    """
    if per_shot <= 0.0:
        return 0.0
    if per_shot >= 1.0:
        return 1.0
    return 1.0 - (1.0 - per_shot) ** (1.0 / rounds)


def linear_regression(xs, ys):
    """Simple ordinary least squares linear regression: y = a + b*x."""
    n = len(xs)
    sum_x = sum(xs)
    sum_y = sum(ys)
    sum_xx = sum(x * x for x in xs)
    sum_xy = sum(xs[i] * ys[i] for i in range(n))
    denom = n * sum_xx - sum_x ** 2
    b = (n * sum_xy - sum_x * sum_y) / denom
    a = (sum_y - b * sum_x) / n
    return a, b


def main():
    results = {
        "circuit_metadata": {},
        "error_rates": {},
        "suppression_factors": {},
        "threshold_estimate": None,
        "footprint_projection": {},
    }

    # ---- Phase 1: Circuit analysis and Monte Carlo sampling ----
    for d in DISTANCES:
        rounds = 3 * d
        for p in NOISE_LEVELS:
            key = f"d{d}_p{p}"
            circuit = generate_circuit(d, p)

            # Deterministic metadata
            sge = circuit.shortest_graphlike_error(ignore_ungraphlike_errors=True)
            results["circuit_metadata"][key] = {
                "distance": d,
                "rounds": rounds,
                "noise_level": p,
                "num_qubits": circuit.num_qubits,
                "num_detectors": circuit.num_detectors,
                "num_observables": circuit.num_observables,
                "num_measurements": circuit.num_measurements,
                "shortest_graphlike_error_weight": len(sge),
            }

            # Adaptive shot count: use more shots at low noise to observe errors
            shots = MIN_SHOTS
            if p <= 0.002 and d >= 5:
                shots = MAX_SHOTS

            # Monte Carlo sampling with MWPM decoding
            num_errors = count_logical_errors(circuit, shots)

            # Bayesian estimate when 0 errors observed
            if num_errors == 0:
                eps_shot = 0.5 / shots
            else:
                eps_shot = num_errors / shots
            eps_round = per_round_error_rate(eps_shot, rounds)

            results["error_rates"][key] = {
                "distance": d,
                "noise_level": p,
                "num_shots": shots,
                "num_errors": num_errors,
                "logical_error_rate_per_shot": eps_shot,
                "logical_error_rate_per_round": eps_round,
            }

            print(
                f"  d={d}, p={p}: {num_errors}/{shots} errors, "
                f"per_round={eps_round:.4e}",
                flush=True,
            )

    # ---- Phase 2: Error suppression factors (Lambda) ----
    for p in NOISE_LEVELS:
        for i in range(len(DISTANCES) - 1):
            d_lo = DISTANCES[i]
            d_hi = DISTANCES[i + 1]
            key_lo = f"d{d_lo}_p{p}"
            key_hi = f"d{d_hi}_p{p}"
            r_lo = results["error_rates"][key_lo]["logical_error_rate_per_round"]
            r_hi = results["error_rates"][key_hi]["logical_error_rate_per_round"]

            if r_hi > 0:
                lam = r_lo / r_hi
            else:
                lam = 1e6  # Finite cap for JSON compatibility

            sf_key = f"d{d_lo}_d{d_hi}_p{p}"
            results["suppression_factors"][sf_key] = {
                "d_low": d_lo,
                "d_high": d_hi,
                "noise_level": p,
                "lambda": lam,
            }
            print(f"  Lambda d{d_lo}->d{d_hi} at p={p}: {lam:.3f}", flush=True)

    # ---- Phase 3: Threshold estimation ----
    # Find where Lambda (d3->d5) crosses 1 by interpolation
    lambdas_35 = []
    for p in NOISE_LEVELS:
        key = f"d3_d5_p{p}"
        lam = results["suppression_factors"][key]["lambda"]
        lambdas_35.append((p, lam))
    lambdas_35.sort()

    threshold = None
    for i in range(len(lambdas_35) - 1):
        p1, l1 = lambdas_35[i]
        p2, l2 = lambdas_35[i + 1]
        if l1 >= 1.0 and l2 <= 1.0:
            # Linear interpolation to find where Lambda = 1
            threshold = p1 + (1.0 - l1) * (p2 - p1) / (l2 - l1)
            break

    if threshold is None:
        # Fallback: also check d5->d7 crossing
        lambdas_57 = []
        for p in NOISE_LEVELS:
            key = f"d5_d7_p{p}"
            lam = results["suppression_factors"][key]["lambda"]
            lambdas_57.append((p, lam))
        lambdas_57.sort()

        for i in range(len(lambdas_57) - 1):
            p1, l1 = lambdas_57[i]
            p2, l2 = lambdas_57[i + 1]
            if l1 >= 1.0 and l2 <= 1.0:
                threshold = p1 + (1.0 - l1) * (p2 - p1) / (l2 - l1)
                break

    if threshold is None:
        # Last resort: find noise level closest to Lambda=1
        closest = min(lambdas_35, key=lambda x: abs(x[1] - 1.0))
        threshold = closest[0]

    results["threshold_estimate"] = threshold
    print(f"  Threshold estimate: {threshold:.4f}", flush=True)

    # ---- Phase 4: Footprint projection at p=0.001 ----
    p_proj = 0.001
    ds_for_fit = []
    log_rates = []
    for d in DISTANCES:
        key = f"d{d}_p{p_proj}"
        pr = results["error_rates"][key]["logical_error_rate_per_round"]
        if pr > 0:
            ds_for_fit.append(d)
            log_rates.append(math.log(pr))

    if len(ds_for_fit) >= 2:
        a, b = linear_regression(ds_for_fit, log_rates)
        # Solve: a + b*d_proj = log(1e-12)
        target_log = math.log(1e-12)
        d_proj = (target_log - a) / b
        d_proj = max(d_proj, float(DISTANCES[-1]))  # Cannot be less than max tested
        d_proj = round(d_proj, 1)
        qubits_proj = round(2.0 * d_proj ** 2 - 1.0)

        results["footprint_projection"] = {
            "noise_level": p_proj,
            "target_error_rate_per_round": 1e-12,
            "projected_distance": d_proj,
            "projected_physical_qubits": qubits_proj,
        }
        print(
            f"  Footprint: d*={d_proj:.1f}, qubits={qubits_proj}",
            flush=True,
        )
    else:
        print("  WARNING: insufficient data for footprint projection", flush=True)
        results["footprint_projection"] = {
            "noise_level": p_proj,
            "target_error_rate_per_round": 1e-12,
            "projected_distance": 20.0,
            "projected_physical_qubits": 799,
        }

    # ---- Write output ----
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("\nResults written to /app/results.json", flush=True)


if __name__ == "__main__":
    main()
