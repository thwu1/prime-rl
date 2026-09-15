#!/usr/bin/env python3
"""Run SBI inference for all observations and save results."""
import sys
sys.path.insert(0, '/app')

import csv
import json
import os

import numpy as np

from smc_abc import smc_abc
from metrics import c2st


def load_observation(obs_num):
    """Load observation from CSV file."""
    with open(f'/app/data/observation_{obs_num}.csv') as f:
        reader = csv.reader(f)
        next(reader)
        row = next(reader)
        return [float(row[0]), float(row[1])]


def main():
    os.makedirs('/app/results', exist_ok=True)
    results = {}

    for obs_num in range(1, 4):
        obs = load_observation(obs_num)
        print(f"Observation {obs_num}: ({obs[0]:.6f}, {obs[1]:.6f})")

        posterior = smc_abc(
            obs,
            num_particles=10000,
            max_generations=20,
            alpha=0.5,
            min_epsilon=0.02,
            seed=42 + obs_num,
        )
        print(f"  Generated {len(posterior)} posterior samples")

        np.save(f'/app/results/posterior_{obs_num}.npy', posterior)

        ref = np.loadtxt(
            f'/app/data/reference_posterior_{obs_num}.csv',
            delimiter=',', skiprows=1,
        )
        n = min(5000, len(posterior), len(ref))
        score = c2st(posterior[:n], ref[:n], seed=42)
        print(f"  C2ST: {score:.4f}")

        results[f'obs_{obs_num}'] = {'c2st': float(score)}

    with open('/app/results/metrics.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Done!")


if __name__ == '__main__':
    main()
