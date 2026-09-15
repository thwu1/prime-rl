#!/usr/bin/env python3
"""Generate synthetic HMM data with Gaussian emissions.
Saves observations only — no ground truth parameters or states are exposed."""
import os
import numpy as np

K = 3
T_TRAIN = 60
T_TEST = 40
N_TRAIN = 5
N_TEST = 2

mu_true = np.array([-2.0, 0.5, 3.0])
sigma_true = np.array([0.4, 0.3, 0.6])
transition_true = np.array([
    [0.75, 0.15, 0.10],
    [0.10, 0.75, 0.15],
    [0.15, 0.10, 0.75],
])
pi_true = np.array([1.0 / 3, 1.0 / 3, 1.0 / 3])


def generate_sequence(T, rng):
    states = np.zeros(T, dtype=np.int64)
    obs = np.zeros(T, dtype=np.float64)
    states[0] = rng.choice(K, p=pi_true)
    obs[0] = rng.normal(mu_true[states[0]], sigma_true[states[0]])
    for t in range(1, T):
        states[t] = rng.choice(K, p=transition_true[states[t - 1]])
        obs[t] = rng.normal(mu_true[states[t]], sigma_true[states[t]])
    return states, obs


rng = np.random.RandomState(20240815)

train_obs = np.zeros((N_TRAIN, T_TRAIN), dtype=np.float64)
for i in range(N_TRAIN):
    _, train_obs[i] = generate_sequence(T_TRAIN, rng)

test_obs = np.zeros((N_TEST, T_TEST), dtype=np.float64)
for i in range(N_TEST):
    _, test_obs[i] = generate_sequence(T_TEST, rng)

# Split training data across two experiment batches
os.makedirs("/app/data/experiment_1", exist_ok=True)
os.makedirs("/app/data/experiment_2", exist_ok=True)
os.makedirs("/app/data/holdout", exist_ok=True)

np.save("/app/data/experiment_1/obs.npy", train_obs[:3])
np.save("/app/data/experiment_2/obs.npy", train_obs[3:])
np.save("/app/data/holdout/obs.npy", test_obs)

print("Data generation complete.")
print(f"experiment_1: {3} sequences of length {T_TRAIN}")
print(f"experiment_2: {2} sequences of length {T_TRAIN}")
print(f"holdout: {N_TEST} sequences of length {T_TEST}")
