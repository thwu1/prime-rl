#!/usr/bin/env python3
"""Preliminary QEC performance analysis for rotated surface code circuits."""

import json
import math

import numpy as np
import stim
import pymatching
from scipy.stats import linregress

DISTANCES = [3, 5, 7]
NUM_SHOTS = 100_000


def run_analysis():
    results = {
        "noise_model": {
            "after_clifford_depolarization": 0.001,
            "before_measure_flip_probability": 0.002,
            "after_reset_flip_probability": 0.001,
            "before_round_data_depolarization": 0.001,
        },
        "distances": {},
    }

    ds = []
    per_round_rates = []

    for d in DISTANCES:
        circuit = stim.Circuit.from_file(f'/app/circuits/d{d}.stim')
        rounds = 3 * d

        sampler = circuit.compile_detector_sampler()
        detection_events, observable_flips = sampler.sample(
            NUM_SHOTS, separate_observables=True
        )

        dem = circuit.detector_error_model()
        matcher = pymatching.Matching.from_detector_error_model(dem)
        predictions = matcher.decode_batch(detection_events)

        num_errors = int(np.sum(np.any(predictions != observable_flips, axis=1)))
        per_shot = num_errors / NUM_SHOTS if num_errors > 0 else 0.5 / NUM_SHOTS

        per_round = per_shot / rounds

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
        per_round_rates.append(per_round)

    fit = linregress(ds, per_round_rates)
    lam = math.exp(fit.slope)

    results['exponential_fit'] = {
        'slope': fit.slope,
        'intercept': fit.intercept,
        'r_squared': fit.rvalue ** 2,
    }
    results['lambda_suppression_factor'] = lam

    target = 1e-12
    if fit.slope != 0:
        proj_d = (target - fit.intercept) / fit.slope
    else:
        proj_d = 99
    proj_d = max(3, int(math.ceil(abs(proj_d))))
    if proj_d % 2 == 0:
        proj_d += 1

    results['projected_distance_for_1e12'] = proj_d
    results['projected_physical_qubits'] = proj_d ** 2

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Analysis complete. Results written to /app/results.json")


if __name__ == '__main__':
    run_analysis()
