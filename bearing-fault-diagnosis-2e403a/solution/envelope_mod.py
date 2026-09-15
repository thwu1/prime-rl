"""Envelope spectrum computation via bandpass filtering + Hilbert demodulation."""

import numpy as np
from scipy.signal import butter, filtfilt, hilbert, welch as scipy_welch


def envelope_spectrum(signal, sample_rate, band_low, band_high, nperseg=None):
    """Compute the power spectral density of the envelope of a bandpass-filtered signal.

    Parameters
    ----------
    signal : array_like, 1-D
        Raw vibration signal.
    sample_rate : float
        Sampling frequency in Hz.
    band_low, band_high : float
        Bandpass filter bounds in Hz.
    nperseg : int or None
        Welch PSD segment length.  ``None`` → ``min(len(signal), 16384)``.

    Returns
    -------
    freqs : ndarray  —  frequency axis in Hz.
    psd   : ndarray  —  PSD of the envelope.
    """
    signal = np.asarray(signal, dtype=np.float64)
    nyq = sample_rate / 2.0

    # Butterworth bandpass (4th order, zero-phase)
    low = max(band_low / nyq, 0.001)
    high = min(band_high / nyq, 0.999)
    if low >= high:
        low = high * 0.5
    b, a = butter(4, [low, high], btype="band")
    filtered = filtfilt(b, a, signal)

    # Hilbert demodulation → envelope
    analytic = hilbert(filtered)
    env = np.abs(analytic)
    env = env - np.mean(env)  # remove DC

    # PSD via Welch
    if nperseg is None:
        nperseg = min(len(env), 16384)
    nperseg = max(nperseg, 64)

    freqs, psd = scipy_welch(
        env, fs=sample_rate, nperseg=nperseg,
        noverlap=nperseg // 2, window="hann",
    )
    return freqs, psd
