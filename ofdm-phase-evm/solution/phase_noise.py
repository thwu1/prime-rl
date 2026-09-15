import numpy as np
from scipy.interpolate import interp1d
from scipy.signal import welch


def generate_phase_noise(psd_breakpoints, num_samples, sample_rate, seed=None):
    """
    Generate time-domain phase noise matching a target PSD.

    Args:
        psd_breakpoints: list of [offset_freq_hz, dBc_per_Hz]
        num_samples: int, number of output samples
        sample_rate: float, sampling rate in Hz
        seed: int or None, random seed

    Returns:
        np.ndarray of phase noise in radians, shape (num_samples,)
    """
    rng = np.random.default_rng(seed)
    N = num_samples

    # Frequency bins for rfft: 0, df, 2*df, ..., fs/2
    freqs = np.fft.rfftfreq(N, d=1.0 / sample_rate)
    n_rfft = len(freqs)

    # Interpolate PSD on log-linear scale (dBc/Hz linear in log-frequency)
    bp_f = np.array([bp[0] for bp in psd_breakpoints], dtype=float)
    bp_psd_dB = np.array([bp[1] for bp in psd_breakpoints], dtype=float)

    interp_func = interp1d(
        np.log10(bp_f),
        bp_psd_dB,
        kind="linear",
        fill_value=(bp_psd_dB[0], bp_psd_dB[-1]),
        bounds_error=False,
    )

    # Target PSD at each frequency bin
    target_psd_dB = np.full(n_rfft, -300.0)
    mask = freqs > 0
    target_psd_dB[mask] = interp_func(np.log10(freqs[mask]))
    target_psd_linear = 10.0 ** (target_psd_dB / 10.0)  # rad^2/Hz
    target_psd_linear[0] = 0.0  # no DC component

    # Frequency-domain filtering of white noise:
    # White noise x ~ N(0,1) has PSD = 1/fs after FFT.
    # To achieve target PSD, multiply FFT by H = sqrt(target_PSD * fs).
    white = rng.standard_normal(N)
    W = np.fft.rfft(white)

    H = np.sqrt(target_psd_linear * sample_rate)
    shaped = W * H

    phase_noise = np.fft.irfft(shaped, n=N)

    return phase_noise


def measure_psd(signal, sample_rate, nperseg=None):
    """
    Measure the PSD of a signal using Welch's method.

    Returns:
        freqs: frequency vector (Hz)
        psd_dB: PSD in dBc/Hz (10*log10)
    """
    if nperseg is None:
        nperseg = min(len(signal) // 4, 8192)

    freqs, psd = welch(
        signal, fs=sample_rate, nperseg=nperseg, return_onesided=True, scaling="density"
    )

    psd_dB = 10.0 * np.log10(psd + 1e-30)
    return freqs, psd_dB
