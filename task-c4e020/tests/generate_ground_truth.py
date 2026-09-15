#!/usr/bin/env python3
"""Regenerate ground truth labels for test subjects at test time.

Uses the same deterministic seed and RNG sequence as the data generator
so that labels match the shuffled EEG trials exactly. This script is
in /tests/ and is never accessible to the agent during task solving.
"""

import numpy as np
import os


def regenerate_test_labels(output_dir, seed=42):
    n_channels = 22
    n_subjects = 10
    n_train = 7

    os.makedirs(output_dir, exist_ok=True)

    for subj in range(n_subjects):
        if subj < n_train:
            continue

        subj_id = "subject_{:02d}".format(subj + 1)
        subj_rng = np.random.RandomState(seed + subj * 137)

        # Reproduce the exact RNG draws from generate_data.py to advance state
        n_trials_per_class = subj_rng.randint(45, 56)
        n_trials = n_trials_per_class * 2

        _ = subj_rng.uniform(0.04, 0.09)                     # erd_strength
        _ = subj_rng.uniform(0.01, 0.03)                     # ers_strength
        _ = subj_rng.uniform(0.4, 2.5, size=n_channels)      # channel_scales
        _ = subj_rng.uniform(0.5, 2.0)                       # amp_scale
        _ = subj_rng.uniform(0.45, 0.65)                     # sensor_noise_std
        _ = subj_rng.uniform(0.3, 0.8)                       # alpha_amp

        # Create labels in the same order as generate_data.py
        labels = np.zeros(n_trials, dtype=np.int32)
        labels[:n_trials_per_class] = 0
        labels[n_trials_per_class:] = 1

        # Apply the same deterministic shuffle
        shuffle_idx = subj_rng.permutation(n_trials)
        labels = labels[shuffle_idx]

        np.save(os.path.join(output_dir, "{}_labels.npy".format(subj_id)), labels)


if __name__ == "__main__":
    regenerate_test_labels("/tmp/ground_truth")
    print("Ground truth labels regenerated at /tmp/ground_truth/")
