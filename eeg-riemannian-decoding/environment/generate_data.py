"""Generate synthetic multi-subject motor imagery EEG data.

Creates realistic EEG signals with class-discriminative spatial patterns
(lateralized mu/beta power for left vs right hand motor imagery) and
subject-specific variability (different mixing matrices, noise levels,
frequency peaks).
"""
import numpy as np
import os

np.random.seed(42)

N_SUBJECTS = 6
N_CHANNELS = 22
N_TRIALS_PER_CLASS = 60
N_CLASSES = 2
SFREQ = 250
DURATION = 3.0
N_SAMPLES = int(SFREQ * DURATION)

CHANNELS = [
    'Fp1', 'Fp2', 'F3', 'F4', 'F7', 'F8', 'Fz', 'C3', 'C4', 'Cz',
    'T3', 'T4', 'T5', 'T6', 'P3', 'P4', 'Pz', 'O1', 'O2', 'A1', 'A2', 'Fpz'
]

C3_IDX = 7
C4_IDX = 8
CZ_IDX = 9
F3_IDX = 2
F4_IDX = 3


def generate_1f_noise(rng, n_channels, n_samples):
    """Generate 1/f (pink) noise using FFT method."""
    freqs = np.fft.rfftfreq(n_samples)
    freqs[0] = 1.0
    amplitude = 1.0 / np.sqrt(freqs)
    noise = np.zeros((n_channels, n_samples))
    for ch in range(n_channels):
        phases = rng.uniform(0, 2 * np.pi, len(freqs))
        spectrum = amplitude * np.exp(1j * phases)
        noise[ch] = np.fft.irfft(spectrum, n=n_samples)
        noise[ch] /= (np.std(noise[ch]) + 1e-12)
    return noise


def generate_subject_data(subject_id):
    """Generate synthetic EEG data for one subject."""
    n_trials = N_TRIALS_PER_CLASS * N_CLASSES
    labels = np.array([0] * N_TRIALS_PER_CLASS + [1] * N_TRIALS_PER_CLASS)

    rng = np.random.RandomState(subject_id * 100 + 7)

    # Subject-specific spatial mixing matrix (simulates head geometry variability)
    A = np.eye(N_CHANNELS) + rng.randn(N_CHANNELS, N_CHANNELS) * 0.25

    # Subject-specific signal parameters
    snr = 0.7 + rng.rand() * 0.5          # SNR factor [0.7, 1.2]
    mu_freq = 10.0 + rng.randn() * 1.0     # mu peak ~10 Hz
    beta_freq = 22.0 + rng.randn() * 2.0   # beta peak ~22 Hz

    data = np.zeros((n_trials, N_CHANNELS, N_SAMPLES))
    t = np.linspace(0, DURATION, N_SAMPLES, endpoint=False)

    for trial in range(n_trials):
        trial_rng = np.random.RandomState(subject_id * 10000 + trial + 13)

        # Background: 1/f noise
        noise = generate_1f_noise(trial_rng, N_CHANNELS, N_SAMPLES) * 0.8
        # Add white noise
        noise += trial_rng.randn(N_CHANNELS, N_SAMPLES) * 0.3

        # Class-specific cortical signal
        sig = np.zeros((N_CHANNELS, N_SAMPLES))
        phase = trial_rng.rand() * 2 * np.pi

        # Baseline mu activity in both C3 and C4
        baseline = 0.25 * snr
        sig[C3_IDX] += baseline * np.sin(2 * np.pi * mu_freq * t + phase + 0.3)
        sig[C4_IDX] += baseline * np.sin(2 * np.pi * mu_freq * t + phase + 1.7)

        if labels[trial] == 0:
            # Class 0: more power at C3
            sig[C3_IDX] += snr * np.sin(2 * np.pi * mu_freq * t + phase)
            sig[C3_IDX] += snr * 0.5 * np.sin(2 * np.pi * beta_freq * t + phase * 0.7)
            sig[CZ_IDX] += snr * 0.2 * np.sin(2 * np.pi * mu_freq * t + phase)
            sig[F3_IDX] += snr * 0.15 * np.sin(2 * np.pi * mu_freq * t + phase)
        else:
            # Class 1: more power at C4
            sig[C4_IDX] += snr * np.sin(2 * np.pi * mu_freq * t + phase)
            sig[C4_IDX] += snr * 0.5 * np.sin(2 * np.pi * beta_freq * t + phase * 0.7)
            sig[CZ_IDX] += snr * 0.2 * np.sin(2 * np.pi * mu_freq * t + phase)
            sig[F4_IDX] += snr * 0.15 * np.sin(2 * np.pi * mu_freq * t + phase)

        # Apply subject-specific spatial mixing
        mixed_sig = A @ sig

        data[trial] = mixed_sig + noise

    # Shuffle trials (deterministic per subject)
    perm = rng.permutation(n_trials)
    data = data[perm]
    labels = labels[perm]

    return data, labels


def main():
    os.makedirs('/app/data', exist_ok=True)

    for s in range(N_SUBJECTS):
        data, labels = generate_subject_data(s)
        np.savez(
            '/app/data/subject_{:02d}.npz'.format(s),
            data=data,
            labels=labels
        )
        print('Subject {}: data shape {}, labels shape {}'.format(s, data.shape, labels.shape))

    np.savez(
        '/app/data/metadata.npz',
        n_subjects=np.array([N_SUBJECTS]),
        n_channels=np.array([N_CHANNELS]),
        n_trials_per_class=np.array([N_TRIALS_PER_CLASS]),
        n_classes=np.array([N_CLASSES]),
        sfreq=np.array([SFREQ]),
        duration=np.array([DURATION]),
        channels=np.array(CHANNELS),
        class_names=np.array(['left_hand', 'right_hand'])
    )
    print('Data generation complete: {} subjects, {} trials each.'.format(
        N_SUBJECTS, N_TRIALS_PER_CLASS * N_CLASSES))


if __name__ == '__main__':
    main()
