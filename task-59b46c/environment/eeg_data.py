"""Synthetic multi-subject EEG motor imagery data generator.

Generates 2-class EEG data (class 0: dominant mu rhythm 8-13 Hz,
class 1: dominant beta rhythm 18-25 Hz) with shared-but-perturbed
discriminative spatial patterns and subject-specific noise to simulate
realistic cross-subject variability in brain-computer interfaces.
"""

import numpy as np
from typing import Dict, List


def generate_subject_data(
    subject_id: int,
    n_channels: int = 22,
    n_trials_per_class: int = 40,
    n_samples: int = 1000,
    fs: int = 250,
    random_seed: int = None,
) -> Dict:
    """Generate synthetic EEG motor imagery data for one subject.

    The discriminative spatial patterns are based on a shared template
    with subject-specific perturbation, mirroring the fact that motor
    cortex activation projects similarly (but not identically) across
    people.  Channel scaling, noise structure, and perturbation magnitude
    are subject-specific.

    Args:
        subject_id: Integer subject identifier.
        n_channels: Number of EEG channels.
        n_trials_per_class: Trials per class (total trials = 2x this).
        n_samples: Samples per trial.
        fs: Sampling frequency in Hz.
        random_seed: RNG seed (default: 42 + subject_id).

    Returns:
        Dict with keys: trials (n_trials, n_channels, n_samples),
        labels (n_trials,), subject_id, fs, n_channels, mixing_matrix.
    """
    if random_seed is None:
        random_seed = 42 + subject_id
    rng = np.random.RandomState(random_seed)

    n_trials = 2 * n_trials_per_class
    n_disc = 4  # discriminative sources

    # ---- Shared discriminative spatial patterns (template) ----
    shared_rng = np.random.RandomState(0)
    A_disc_template = shared_rng.randn(n_channels, n_disc)
    for j in range(n_disc):
        A_disc_template[:, j] /= np.linalg.norm(A_disc_template[:, j])

    # ---- Subject-specific perturbation of discriminative patterns ----
    perturbation = rng.randn(n_channels, n_disc) * 0.28
    A_disc = A_disc_template + perturbation
    for j in range(n_disc):
        A_disc[:, j] /= np.linalg.norm(A_disc[:, j])

    # ---- Subject-specific noise spatial patterns ----
    n_noise = n_channels - n_disc
    A_noise = rng.randn(n_channels, n_noise)
    for j in range(n_noise):
        A_noise[:, j] /= np.linalg.norm(A_noise[:, j])

    # ---- Subject-specific channel scaling ----
    scales = 0.5 + rng.rand(n_channels) * 1.0  # [0.5, 1.5]
    S = np.diag(scales)

    # Full mixing matrix
    A = S @ np.hstack([A_disc, A_noise])

    t = np.arange(n_samples) / fs
    freqs_rfft = np.fft.rfftfreq(n_samples, 1.0 / fs)

    trials = []
    labels = []

    for trial_idx in range(n_trials):
        label = trial_idx % 2
        sources = np.zeros((n_channels, n_samples))

        # ---- Class-discriminative sources ----
        if label == 0:  # dominant mu rhythm (8-13 Hz)
            sources[0] = np.sin(2 * np.pi * 10 * t + rng.uniform(0, 2 * np.pi)) * rng.uniform(1.2, 1.8)
            sources[1] = np.sin(2 * np.pi * 12 * t + rng.uniform(0, 2 * np.pi)) * rng.uniform(1.0, 1.5)
            sources[2] = np.sin(2 * np.pi * 22 * t + rng.uniform(0, 2 * np.pi)) * rng.uniform(0.08, 0.22)
            sources[3] = np.sin(2 * np.pi * 20 * t + rng.uniform(0, 2 * np.pi)) * rng.uniform(0.08, 0.20)
        else:  # dominant beta rhythm (18-25 Hz)
            sources[0] = np.sin(2 * np.pi * 10 * t + rng.uniform(0, 2 * np.pi)) * rng.uniform(0.08, 0.22)
            sources[1] = np.sin(2 * np.pi * 12 * t + rng.uniform(0, 2 * np.pi)) * rng.uniform(0.08, 0.20)
            sources[2] = np.sin(2 * np.pi * 22 * t + rng.uniform(0, 2 * np.pi)) * rng.uniform(1.2, 1.8)
            sources[3] = np.sin(2 * np.pi * 20 * t + rng.uniform(0, 2 * np.pi)) * rng.uniform(1.0, 1.5)

        # ---- Background noise sources ----
        for ch in range(n_disc, n_channels):
            sources[ch] = rng.randn(n_samples) * 0.45

        # ---- In-band oscillatory noise on all sources (survives bandpass) ----
        for ch in range(n_channels):
            for nf in [9, 11, 15, 19, 24, 28]:
                sources[ch] += (np.sin(2 * np.pi * nf * t + rng.uniform(0, 2 * np.pi))
                                * rng.uniform(0.12, 0.30))

        # ---- 1/f noise on all sources ----
        for ch in range(n_channels):
            spectrum = rng.randn(len(freqs_rfft)) + 1j * rng.randn(len(freqs_rfft))
            pink_filter = np.ones_like(freqs_rfft)
            pink_filter[1:] = 1.0 / np.sqrt(freqs_rfft[1:])
            sources[ch] += np.fft.irfft(spectrum * pink_filter * 0.25, n=n_samples)

        # ---- Apply mixing + measurement noise ----
        eeg = A @ sources
        eeg += rng.randn(n_channels, n_samples) * 0.08

        trials.append(eeg)
        labels.append(label)

    return {
        "trials": np.array(trials),
        "labels": np.array(labels),
        "subject_id": subject_id,
        "fs": fs,
        "n_channels": n_channels,
        "mixing_matrix": A,
    }


def generate_dataset(
    n_subjects: int = 9,
    n_channels: int = 22,
    n_trials_per_class: int = 40,
    n_samples: int = 1000,
    fs: int = 250,
    base_seed: int = 42,
) -> List[Dict]:
    """Generate a full multi-subject EEG dataset.

    Returns:
        List of per-subject data dicts (see generate_subject_data).
    """
    return [
        generate_subject_data(
            subject_id=sid,
            n_channels=n_channels,
            n_trials_per_class=n_trials_per_class,
            n_samples=n_samples,
            fs=fs,
            random_seed=base_seed + sid,
        )
        for sid in range(n_subjects)
    ]
