#!/usr/bin/env python3
"""Generate synthetic EEG motor imagery data for cross-subject decoding benchmark.

Training subjects get both trial data and labels.
Test subjects get ONLY trial data -- no labels are stored in the image.
Ground truth labels for test subjects are regenerated at test time only.
"""
import numpy as np
import os
import json


def generate_eeg_data():
    rng = np.random.RandomState(42)

    n_subjects = 10
    n_channels = 22
    n_classes = 4
    n_trials_per_class = 40
    fs = 250
    trial_duration = 3.0
    n_samples = int(fs * trial_duration)
    n_sources = 2
    signal_scale = 3.0

    # Class-specific spatial source patterns (which channels are active per class)
    source_patterns = np.zeros((n_classes, n_sources, n_channels))

    # Class 0 (left hand): right motor cortex region
    source_patterns[0, 0, [3, 4, 5]] = [0.8, 1.0, 0.6]
    source_patterns[0, 1, [9, 10, 11]] = [0.3, 0.5, 0.3]

    # Class 1 (right hand): left motor cortex region
    source_patterns[1, 0, [0, 1, 2]] = [0.8, 1.0, 0.6]
    source_patterns[1, 1, [6, 7, 8]] = [0.3, 0.5, 0.3]

    # Class 2 (feet): medial motor cortex region
    source_patterns[2, 0, [10, 11, 12]] = [0.7, 1.0, 0.7]
    source_patterns[2, 1, [15, 16, 17]] = [0.4, 0.6, 0.4]

    # Class 3 (tongue): lateral motor cortex region
    source_patterns[3, 0, [18, 19, 20]] = [0.6, 0.9, 0.7]
    source_patterns[3, 1, [13, 14, 21]] = [0.3, 0.5, 0.4]

    os.makedirs('/app/data', exist_ok=True)

    metadata = {
        'n_subjects': n_subjects,
        'n_channels': n_channels,
        'n_classes': n_classes,
        'n_trials_per_class': n_trials_per_class,
        'fs': fs,
        'trial_duration': trial_duration,
        'n_samples': n_samples,
        'train_subjects': list(range(6)),
        'test_subjects': list(range(6, 10)),
        'class_names': ['left_hand', 'right_hand', 'feet', 'tongue']
    }

    with open('/app/data/metadata.json', 'w') as f:
        json.dump(metadata, f, indent=2)

    for subj in range(n_subjects):
        # Subject-specific spatial mixing matrix (simulates anatomical variability)
        random_mat = rng.randn(n_channels, n_channels)
        Q, _ = np.linalg.qr(random_mat)
        mixing_strength = 0.4 + 0.3 * rng.rand()
        mixing_matrix = (1 - mixing_strength) * np.eye(n_channels) + mixing_strength * Q

        # Subject-specific noise level and individual alpha frequency
        noise_level = 1.0 + 1.0 * rng.rand()
        alpha_freq = 10.0 + rng.randn() * 0.5

        all_trials = []
        all_labels = []

        for cls in range(n_classes):
            for _ in range(n_trials_per_class):
                # Background 1/f (pink) noise
                background = np.zeros((n_channels, n_samples))
                freqs = np.fft.rfftfreq(n_samples, 1.0 / fs)
                freqs[0] = 1.0
                for ch in range(n_channels):
                    spectrum = rng.randn(len(freqs)) + 1j * rng.randn(len(freqs))
                    spectrum *= 1.0 / np.sqrt(freqs)
                    background[ch] = np.fft.irfft(spectrum, n_samples)

                # Class-discriminative oscillatory signal in mu/beta bands
                signal = np.zeros((n_channels, n_samples))
                t = np.arange(n_samples) / fs

                for src in range(n_sources):
                    pattern = source_patterns[cls, src]
                    if np.any(pattern != 0):
                        phase = rng.rand() * 2 * np.pi
                        mu_sig = np.sin(2 * np.pi * alpha_freq * t + phase)
                        mu_sig *= np.hanning(n_samples)
                        mu_sig *= (1 + 0.3 * rng.randn())

                        beta_freq = 2 * alpha_freq + rng.randn()
                        beta_phase = rng.rand() * 2 * np.pi
                        beta_sig = 0.5 * np.sin(2 * np.pi * beta_freq * t + beta_phase)
                        beta_sig *= np.hanning(n_samples)

                        signal += np.outer(pattern, mu_sig + beta_sig)

                # Apply subject-specific spatial mixing
                mixed = mixing_matrix @ (signal_scale * signal + noise_level * background)
                all_trials.append(mixed)
                all_labels.append(cls)

        trials = np.array(all_trials)
        labels = np.array(all_labels)

        # Shuffle trial order
        perm = rng.permutation(len(labels))
        trials = trials[perm]
        labels = labels[perm]

        # Save trial data for all subjects
        np.save('/app/data/subject_{:02d}_trials.npy'.format(subj), trials)

        if subj < 6:
            # Training subjects: labels available to the agent
            np.save('/app/data/subject_{:02d}_labels.npy'.format(subj), labels)
        # Test subjects: labels are NOT saved anywhere in the image


if __name__ == '__main__':
    generate_eeg_data()
    print("Data generation complete.")
