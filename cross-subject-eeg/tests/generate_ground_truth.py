#!/usr/bin/env python3
"""
Regenerate ground truth labels for test subjects at verification time.
Replays the exact same RNG sequence used during data generation to recover
the per-subject label permutations. This script is part of tests/ and is
NOT accessible to the agent during the task.
"""
import numpy as np
import os


def regenerate_ground_truth():
    rng = np.random.RandomState(42)

    n_subjects = 10
    n_channels = 22
    n_classes = 4
    n_trials_per_class = 40
    fs = 250
    trial_duration = 3.0
    n_samples = int(fs * trial_duration)
    n_sources = 2

    source_patterns = np.zeros((n_classes, n_sources, n_channels))
    source_patterns[0, 0, [3, 4, 5]] = [0.8, 1.0, 0.6]
    source_patterns[0, 1, [9, 10, 11]] = [0.3, 0.5, 0.3]
    source_patterns[1, 0, [0, 1, 2]] = [0.8, 1.0, 0.6]
    source_patterns[1, 1, [6, 7, 8]] = [0.3, 0.5, 0.3]
    source_patterns[2, 0, [10, 11, 12]] = [0.7, 1.0, 0.7]
    source_patterns[2, 1, [15, 16, 17]] = [0.4, 0.6, 0.4]
    source_patterns[3, 0, [18, 19, 20]] = [0.6, 0.9, 0.7]
    source_patterns[3, 1, [13, 14, 21]] = [0.3, 0.5, 0.4]

    gt_dir = '/tmp/eeg_ground_truth'
    os.makedirs(gt_dir, exist_ok=True)

    for subj in range(n_subjects):
        # Replay subject-specific random draws to advance RNG state identically
        random_mat = rng.randn(n_channels, n_channels)
        np.linalg.qr(random_mat)  # Q not needed, just advance state
        rng.rand()   # mixing_strength
        rng.rand()   # noise_level
        rng.randn()  # alpha_freq

        all_labels = []

        for cls in range(n_classes):
            for _ in range(n_trials_per_class):
                # Advance RNG for background noise (same draws as generation)
                freqs = np.fft.rfftfreq(n_samples, 1.0 / fs)
                n_freq = len(freqs)
                for ch in range(n_channels):
                    rng.randn(n_freq)  # real part of spectrum
                    rng.randn(n_freq)  # imag part of spectrum

                # Advance RNG for signal sources
                for src in range(n_sources):
                    pattern = source_patterns[cls, src]
                    if np.any(pattern != 0):
                        rng.rand()    # phase
                        rng.randn()   # amplitude modulation
                        rng.randn()   # beta_freq
                        rng.rand()    # beta_phase

                all_labels.append(cls)

        labels = np.array(all_labels)

        # Replay the same permutation
        perm = rng.permutation(len(labels))
        labels = labels[perm]

        # Only save labels for test subjects (6-9)
        if subj >= 6:
            np.save(os.path.join(gt_dir, 'subject_{:02d}_labels.npy'.format(subj)), labels)


if __name__ == '__main__':
    regenerate_ground_truth()
    print("Ground truth labels regenerated.")
