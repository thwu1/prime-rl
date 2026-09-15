#!/usr/bin/env python3
"""Corrected QEC performance analysis for rotated surface code.

Fixes applied to draft_analysis.py:
1. Per-round rate: use 1-(1-p_shot)^(1/rounds) instead of p_shot/rounds
2. Fit in log space: regress log(per_round_rate) vs distance
3. Lambda: exp(-slope), not exp(slope)
4. Qubit count: 2*d^2 - 1 for rotated surface code
5. DEM: pass decompose_errors=True for proper MWPM decoding
"""

import json
import math

import numpy as np
import scipy.stats
import stim
import pymatching

DISTANCES = [3, 5, 7]
NUM_SHOTS = 100_000


def main():
    results = {
        'noise_model': {
            'after_clifford_depolarization': 1e-3,
            'before_measure_flip_probability': 2e-3,
            'after_reset_flip_probability': 1e-3,
            'before_round_data_depolarization': 1e-3,
        },
        'distances': {},
    }

    ds = []
    log_per_round = []

    for d in DISTANCES:
        rounds = 3 * d

        # Load pre-generated circuit
        circuit = stim.Circuit.from_file(f'/app/circuits/d{d}.stim')

        # Sample detection events and observable flips
        sampler = circuit.compile_detector_sampler()
        detection_events, observable_flips = sampler.sample(
            NUM_SHOTS, separate_observables=True
        )

        # Build decoder from DECOMPOSED detector error model
        dem = circuit.detector_error_model(decompose_errors=True)
        matcher = pymatching.Matching.from_detector_error_model(dem)

        # Decode and count logical errors
        predictions = matcher.decode_batch(detection_events)
        num_errors = int(np.sum(np.any(predictions != observable_flips, axis=1)))

        per_shot = num_errors / NUM_SHOTS
        if num_errors == 0:
            per_shot = 0.5 / NUM_SHOTS

        # Correct per-round conversion
        per_round = 1.0 - (1.0 - per_shot) ** (1.0 / rounds)

        results['distances'][str(d)] = {
            'rounds': rounds,
            'num_qubits': circuit.num_qubits,
            'num_detectors': circuit.num_detectors,
            'num_observables': circuit.num_observables,
            'shots': NUM_SHOTS,
            'logical_errors': num_errors,
            'per_shot_error_rate': per_shot,
            'per_round_error_rate': per_round,
        }

        ds.append(d)
        log_per_round.append(math.log(per_round))

    # Fit in LOG space: log(per_round_rate) = slope * d + intercept
    fit = scipy.stats.linregress(ds, log_per_round)

    # Lambda = exp(-slope) where slope < 0
    lambda_factor = math.exp(-fit.slope)

    results['exponential_fit'] = {
        'slope': fit.slope,
        'intercept': fit.intercept,
        'r_squared': fit.rvalue ** 2,
    }
    results['lambda_suppression_factor'] = lambda_factor

    # Project minimum distance for per-round rate < 1e-12
    target_log = math.log(1e-12)
    projected_d_raw = (target_log - fit.intercept) / fit.slope
    projected_d = int(math.ceil(projected_d_raw))

    # Surface code distance must be odd
    if projected_d % 2 == 0:
        projected_d += 1
    if projected_d < 3:
        projected_d = 3

    # Rotated surface code: 2*d^2 - 1 physical qubits
    results['projected_distance_for_1e12'] = projected_d
    results['projected_physical_qubits'] = 2 * projected_d ** 2 - 1

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")


if __name__ == '__main__':
    main()
