#!/usr/bin/env python3
"""Generate synthetic motor imagery EEG dataset for cross-subject decoding benchmark.

Ground truth labels for test subjects are NOT saved anywhere in the image.
They are regenerated deterministically at test time from the same seed.
"""

import numpy as np
import os
import json
import sys


def pink_noise(n_samples, sfreq, rng, target_std=1.0):
    """Generate 1/f (pink) noise with target standard deviation."""
    freqs = np.fft.rfftfreq(n_samples, d=1.0 / sfreq)
    spectrum = rng.standard_normal(len(freqs)) + 1j * rng.standard_normal(len(freqs))
    scaling = np.ones_like(freqs)
    scaling[1:] = 1.0 / np.sqrt(freqs[1:])
    spectrum *= scaling
    spectrum[0] = 0
    sig = np.fft.irfft(spectrum, n=n_samples)
    sig_std = np.std(sig)
    if sig_std > 0:
        sig = sig * (target_std / sig_std)
    return sig


def generate_dataset(output_dir, seed=42):
    n_channels = 22
    sfreq = 250
    trial_duration = 4.0
    n_samples = int(trial_duration * sfreq)

    channel_names = [
        "Fp1", "Fp2", "F3", "Fz", "F4", "FC3", "FCz", "FC4",
        "C3", "Cz", "C4", "CP3", "CPz", "CP4", "P3", "Pz",
        "P4", "PO3", "POz", "PO4", "O1", "O2",
    ]

    # Motor cortex channel indices
    left_motor = [5, 8, 11]   # FC3, C3, CP3
    right_motor = [7, 10, 13]  # FC4, C4, CP4
    # Occipital channels (alpha distractor)
    occipital = [17, 18, 19, 20, 21]

    n_subjects = 10
    n_train = 7

    os.makedirs(output_dir, exist_ok=True)

    freqs = np.fft.rfftfreq(n_samples, d=1.0 / sfreq)
    mu_beta_mask = (freqs >= 8) & (freqs <= 30)
    alpha_mask = (freqs >= 8) & (freqs <= 12)

    for subj in range(n_subjects):
        subj_id = "subject_{:02d}".format(subj + 1)
        subj_dir = os.path.join(output_dir, subj_id)
        os.makedirs(subj_dir, exist_ok=True)

        subj_rng = np.random.RandomState(seed + subj * 137)

        n_trials_per_class = subj_rng.randint(45, 56)
        n_trials = n_trials_per_class * 2

        # ERD strength (subtle — requires spatial filtering to detect)
        erd_strength = subj_rng.uniform(0.04, 0.09)
        ers_strength = subj_rng.uniform(0.01, 0.03)

        # Per-channel amplitude scaling: the KEY source of inter-subject variability.
        channel_scales = subj_rng.uniform(0.4, 2.5, size=n_channels)

        # Overall amplitude
        amp_scale = subj_rng.uniform(0.5, 2.0)

        # Sensor noise
        sensor_noise_std = subj_rng.uniform(0.45, 0.65)

        # Alpha distractor amplitude
        alpha_amp = subj_rng.uniform(0.3, 0.8)

        eeg_data = np.zeros((n_trials, n_channels, n_samples), dtype=np.float64)
        labels = np.zeros(n_trials, dtype=np.int32)
        labels[:n_trials_per_class] = 0
        labels[n_trials_per_class:] = 1

        for trial in range(n_trials):
            cls = labels[trial]
            trial_rng = np.random.RandomState(seed + subj * 137 + trial * 17 + 1000)

            # Background: 1/f noise per channel
            for ch in range(n_channels):
                eeg_data[trial, ch] = pink_noise(n_samples, sfreq, trial_rng)

            # Class-independent alpha in occipital channels
            alpha_spec = trial_rng.standard_normal(len(freqs)) + 1j * trial_rng.standard_normal(len(freqs))
            alpha_spec[~alpha_mask] = 0
            alpha_signal = np.fft.irfft(alpha_spec, n=n_samples) * alpha_amp
            for ch in occipital:
                eeg_data[trial, ch] += alpha_signal * trial_rng.uniform(0.5, 1.5)

            # Trial-specific ERD modulation
            trial_erd_mod = trial_rng.uniform(0.2, 1.8)
            erd_effective = erd_strength * trial_erd_mod

            # ERD: attenuate 8-30 Hz in contralateral motor channels
            target_chs = right_motor if cls == 0 else left_motor
            ipsi_chs = left_motor if cls == 0 else right_motor

            for ch in target_chs:
                spectrum = np.fft.rfft(eeg_data[trial, ch])
                spectrum[mu_beta_mask] *= (1.0 - erd_effective)
                eeg_data[trial, ch] = np.fft.irfft(spectrum, n=n_samples)

            for ch in ipsi_chs:
                spectrum = np.fft.rfft(eeg_data[trial, ch])
                spectrum[mu_beta_mask] *= (1.0 + ers_strength * trial_erd_mod)
                eeg_data[trial, ch] = np.fft.irfft(spectrum, n=n_samples)

        # Per-channel amplitude scaling
        for trial in range(n_trials):
            eeg_data[trial] *= channel_scales[:, np.newaxis]

        # Overall amplitude scaling
        eeg_data *= amp_scale

        # Sensor noise
        sensor_rng = np.random.RandomState(seed + subj * 137 + 99999)
        for trial in range(n_trials):
            eeg_data[trial] += sensor_rng.standard_normal((n_channels, n_samples)) * sensor_noise_std

        # Shuffle
        shuffle_idx = subj_rng.permutation(n_trials)
        eeg_data = eeg_data[shuffle_idx]
        labels = labels[shuffle_idx]

        np.save(os.path.join(subj_dir, "eeg_data.npy"), eeg_data.astype(np.float32))

        # Only save labels for training subjects — test labels are never in the image
        if subj < n_train:
            np.save(os.path.join(subj_dir, "labels.npy"), labels)

        metadata = {
            "subject_id": subj_id,
            "n_channels": n_channels,
            "n_trials": int(n_trials),
            "n_samples": n_samples,
            "sfreq": sfreq,
            "channel_names": channel_names,
            "subject_type": "train" if subj < n_train else "test",
            "trial_duration_sec": trial_duration,
            "classes": {"0": "left_hand", "1": "right_hand"},
            "paradigm": "motor_imagery",
        }
        with open(os.path.join(subj_dir, "metadata.json"), "w") as f:
            json.dump(metadata, f, indent=2)

        print("  Generated {}  ({} trials, type={})".format(
            subj_id, n_trials, metadata["subject_type"]))

    info = {
        "n_subjects": n_subjects,
        "n_train_subjects": n_train,
        "n_test_subjects": n_subjects - n_train,
        "train_subjects": ["subject_{:02d}".format(i + 1) for i in range(n_train)],
        "test_subjects": ["subject_{:02d}".format(i + 1) for i in range(n_train, n_subjects)],
        "task": "binary_motor_imagery",
        "description": (
            "Cross-subject motor imagery EEG decoding. "
            "Train on subjects 01-07 (labels provided), "
            "predict on subjects 08-10 (labels withheld)."
        ),
    }
    with open(os.path.join(output_dir, "dataset_info.json"), "w") as f:
        json.dump(info, f, indent=2)

    print("Dataset info written to {}".format(os.path.join(output_dir, "dataset_info.json")))


if __name__ == "__main__":
    try:
        generate_dataset("/app/data")
        print("Dataset generation complete.")
    except Exception as e:
        print("ERROR during data generation: {}".format(e), file=sys.stderr)
        sys.exit(1)
