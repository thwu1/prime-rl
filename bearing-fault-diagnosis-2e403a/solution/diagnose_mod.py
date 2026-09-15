"""Full bearing diagnosis pipeline: automatic band selection -> envelope -> classification."""

import numpy as np
from scipy.signal import butter, sosfiltfilt, find_peaks as sp_find_peaks
from scipy.stats import kurtosis as sp_kurtosis

from .defect_freq import compute_defect_frequencies
from .envelope import envelope_spectrum


def diagnose(signal, sample_rate, bearing_params, shaft_hz):
    """Diagnose bearing condition from a vibration signal.

    Parameters
    ----------
    signal : array_like, 1-D
    sample_rate : float  (Hz)
    bearing_params : dict  (rd, pd, ne, ca_deg, outer_fixed)
    shaft_hz : float

    Returns
    -------
    dict with keys: fault_type, confidence, defect_frequencies,
                    detected_peaks_hz, fault_frequency_hz, severity.
    """
    signal = np.asarray(signal, dtype=np.float64)

    # 1. Theoretical defect frequencies
    defect_freqs = compute_defect_frequencies(bearing_params, shaft_hz)

    # 2. Find optimal analysis band
    band_low, band_high = _find_optimal_band(signal, sample_rate)

    # 3. Envelope spectrum in that band
    freqs, psd = envelope_spectrum(signal, sample_rate, band_low, band_high)

    # 4. Detect peaks
    peaks_hz = _detect_peaks(freqs, psd, shaft_hz)

    # 5. Classify
    fault_type, confidence, fault_freq = _classify(
        peaks_hz, defect_freqs, freqs, psd, shaft_hz,
    )

    # 6. Severity
    severity = _severity(freqs, psd, fault_freq, defect_freqs)

    return {
        "fault_type": fault_type,
        "confidence": confidence,
        "defect_frequencies": defect_freqs,
        "detected_peaks_hz": [float(p) for p in peaks_hz],
        "fault_frequency_hz": fault_freq,
        "severity": severity,
    }


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _find_optimal_band(signal, sample_rate):
    """Select the frequency band with the most impulsive, energetic content.

    For each candidate band, compute both the time-domain kurtosis (impulsiveness)
    and the RMS energy.  Among all bands with kurtosis > 3 (clearly non-Gaussian),
    pick the one with the highest RMS — this selects the structural resonance
    band excited by fault impulses.  Falls back to highest kurtosis band if
    no band exceeds the kurtosis threshold.
    """
    nyq = sample_rate / 2.0
    bw = 1500.0
    step = 500.0

    min_center = bw / 2.0 + 100.0
    max_center = nyq - bw / 2.0 - 100.0

    candidates = []  # (center, kurtosis, rms)
    best_kurt = -np.inf
    best_kurt_center = nyq / 4.0

    centers = np.arange(min_center, max_center, step)

    for center in centers:
        low = (center - bw / 2.0) / nyq
        high = (center + bw / 2.0) / nyq
        if low <= 0.005 or high >= 0.995:
            continue
        try:
            sos = butter(3, [low, high], btype="band", output="sos")
            filtered = sosfiltfilt(sos, signal)
            k = sp_kurtosis(filtered, fisher=True)
            rms = np.std(filtered)
            if k > best_kurt:
                best_kurt = k
                best_kurt_center = center
            if k > 3.0:
                candidates.append((center, k, rms))
        except Exception:
            continue

    if candidates:
        # Among impulsive bands, pick the one with the highest energy
        best = max(candidates, key=lambda x: x[2])
        best_center = best[0]
    else:
        best_center = best_kurt_center

    band_low = max(50.0, best_center - bw / 2.0)
    band_high = min(nyq * 0.98, best_center + bw / 2.0)
    return band_low, band_high


def _detect_peaks(freqs, psd, shaft_hz):
    """Return frequencies of significant peaks in the envelope PSD."""
    max_freq = min(shaft_hz * 25, freqs[-1])
    min_freq = shaft_hz * 0.3
    mask = (freqs >= min_freq) & (freqs <= max_freq)
    if not np.any(mask):
        return []

    f_roi = freqs[mask]
    p_roi = psd[mask]
    if len(p_roi) < 3:
        return []

    med = np.median(p_roi)
    mad = np.median(np.abs(p_roi - med))
    threshold = med + 4.0 * max(mad, np.std(p_roi) * 0.5)

    df = freqs[1] - freqs[0] if len(freqs) > 1 else 1.0
    min_dist = max(1, int(5.0 / df))

    indices, _ = sp_find_peaks(p_roi, height=threshold, distance=min_dist)

    if len(indices) == 0:
        threshold = med + 2.5 * max(mad, np.std(p_roi) * 0.5)
        indices, _ = sp_find_peaks(p_roi, height=threshold, distance=min_dist)

    return sorted(f_roi[indices].tolist())


def _classify(peaks, defect_freqs, freqs, psd, shaft_hz):
    """Match detected peaks to theoretical defect frequencies and classify."""
    if not peaks:
        return "healthy", 0.8, None

    df = freqs[1] - freqs[0] if len(freqs) > 1 else 1.0
    tolerance = max(3.0, df * 2.0)

    type_map = {
        "BPFO": "outer_race",
        "BPFI": "inner_race",
        "BSF": "rolling_element",
    }

    scores = {}
    for key, ftype in type_map.items():
        theoretical = defect_freqs[key]
        score = 0.0
        for harmonic in range(1, 5):
            target = theoretical * harmonic
            for peak in peaks:
                if abs(peak - target) <= tolerance:
                    idx = np.argmin(np.abs(freqs - peak))
                    height = psd[idx]
                    local_mask = (
                        (freqs > peak - 30)
                        & (freqs < peak + 30)
                        & (np.abs(freqs - peak) > 5)
                    )
                    if np.any(local_mask):
                        noise_floor = np.median(psd[local_mask])
                    else:
                        noise_floor = np.median(psd[psd > 0])
                    if noise_floor > 0:
                        score += (height / noise_floor) / harmonic
                    break
        scores[ftype] = score

    best = max(scores, key=scores.get)
    best_score = scores[best]

    if best_score < 3.5:
        return "healthy", 0.7, None

    confidence = min(1.0, best_score / 15.0)
    confidence = max(0.1, confidence)

    freq_key = {v: k for k, v in type_map.items()}[best]
    return best, confidence, defect_freqs[freq_key]


def _severity(freqs, psd, fault_freq, defect_freqs=None):
    """Severity metric based on peak envelope PSD energy at the fault frequency.

    Uses the absolute peak PSD value — for a given bearing and noise environment,
    this increases monotonically with fault intensity because the envelope energy
    at the defect frequency scales with the square of the impulse amplitude.
    """
    if fault_freq is None or fault_freq <= 0:
        return 0.0

    tol = 5.0
    mask = np.abs(freqs - fault_freq) < tol
    if not np.any(mask):
        return 0.0

    return float(np.max(psd[mask]))
