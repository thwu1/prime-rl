#!/usr/bin/env python3
"""Generate task data: observations and reference posterior samples.

This script is run during Docker build to create the task environment.
It generates deterministic observations and exact reference posterior
samples for three different parameter settings.
"""
import numpy as np
import os
import json


def simulate(theta, rng):
    """Two Moons forward model (same as simulator.py)."""
    n = theta.shape[0]
    a = rng.uniform(-np.pi / 2, np.pi / 2, size=(n, 1))
    r = rng.normal(0.1, 0.01, size=(n, 1))
    p = np.hstack([np.cos(a) * r + 0.25, np.sin(a) * r])
    ang = -np.pi / 4.0
    c, s = np.cos(ang), np.sin(ang)
    z0 = (c * theta[:, 0] - s * theta[:, 1]).reshape(-1, 1)
    z1 = (s * theta[:, 0] + c * theta[:, 1]).reshape(-1, 1)
    return p + np.hstack([-np.abs(z0), z1])


def sample_reference_posterior(observation, num_samples, prior_bound, seed):
    """Sample exact posterior via closed-form rejection method.

    The generative model admits a closed-form inversion that allows
    direct sampling from the true posterior by rejection sampling
    within the prior bounds.
    """
    rng = np.random.RandomState(seed)
    obs = observation.flatten()
    ang = np.pi / 4.0
    c, s = np.cos(ang), np.sin(ang)

    samples = []
    while len(samples) < num_samples:
        a_val = rng.uniform(-np.pi / 2, np.pi / 2)
        r_val = rng.normal(0.1, 0.01)
        p = np.array([np.cos(a_val) * r_val + 0.25, np.sin(a_val) * r_val])

        q0 = p[0] - obs[0]
        q1 = obs[1] - p[1]

        if rng.rand() < 0.5:
            q0 = -q0

        theta = np.array([c * q0 - s * q1, s * q0 + c * q1])

        if np.all(np.abs(theta) <= prior_bound):
            samples.append(theta)

    return np.array(samples)


def main():
    os.makedirs('/app/data', exist_ok=True)

    param_seeds = [42, 137, 256]
    obs_seeds = [1000011, 1000001, 1000002]
    ref_seeds = [12345, 23456, 34567]

    for i in range(3):
        rng_param = np.random.RandomState(param_seeds[i])
        theta_true = rng_param.uniform(-1, 1, size=(1, 2))

        rng_obs = np.random.RandomState(obs_seeds[i])
        observation = simulate(theta_true, rng_obs)

        np.save(f'/app/data/obs_{i + 1}.npy', observation)

        ref = sample_reference_posterior(observation, 10000, 1.0, ref_seeds[i])
        np.save(f'/app/data/ref_posterior_{i + 1}.npy', ref)

        print(f"Obs {i + 1}: theta_true={theta_true.flatten()}, "
              f"obs={observation.flatten()}, ref_shape={ref.shape}")

    config = {
        'dim_parameters': 2,
        'dim_data': 2,
        'prior_low': -1.0,
        'prior_high': 1.0,
        'num_observations': 3,
        'num_posterior_samples': 10000,
    }
    with open('/app/config.json', 'w') as f:
        json.dump(config, f, indent=2)

    print("Setup complete.")


if __name__ == '__main__':
    main()
