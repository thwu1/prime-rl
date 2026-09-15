"""Prosody feature extraction module.

"""

import numpy as np
from scipy.io.wavfile import read
from scipy import stats as scipy_stats


def _preprocess(wav_path):
    """Read and preprocess WAV file."""
    fs, data = read(wav_path)
    if len(data.shape) > 1:
        data = data.mean(axis=1)
    data = data.astype(float)
    data -= np.mean(data)
    mx = np.max(np.abs(data))
    if mx > 0:
        data /= mx
    return fs, data


def _extract_f0_internal(data, fs, min_f0, max_f0, frame_samples, step_samples):
    """Autocorrelation-based F0 extraction on preprocessed data."""
    min_lag = int(fs / max_f0)
    max_lag = int(fs / min_f0)

    n_frames = max(0, int((len(data) - frame_samples) / step_samples) + 1)
    f0 = np.zeros(n_frames)

    for i in range(n_frames):
        start = i * step_samples
        end = start + frame_samples
        if end > len(data):
            break
        frame = data[start:end]

        energy = np.mean(frame ** 2)
        if energy < 1e-6:
            continue

        windowed = frame * np.hamming(len(frame))

        fft_size = 1
        while fft_size < 2 * len(windowed):
            fft_size *= 2
        fft_frame = np.fft.rfft(windowed, fft_size)
        acf = np.fft.irfft(fft_frame * np.conj(fft_frame))
        acf = acf[:len(windowed)]

        if acf[0] <= 0:
            continue
        acf = acf / acf[0]

        search_min = max(min_lag, 1)
        search_max = min(max_lag, len(acf) - 1)
        if search_min >= search_max:
            continue

        search_region = acf[search_min:search_max + 1]
        if len(search_region) == 0:
            continue

        peak_idx = np.argmax(search_region) + search_min
        peak_val = acf[peak_idx]

        if peak_val > 0.25:
            if 0 < peak_idx < len(acf) - 1:
                alpha = acf[peak_idx - 1]
                beta = acf[peak_idx]
                gamma = acf[peak_idx + 1]
                denom = alpha - 2 * beta + gamma
                if abs(denom) > 1e-12:
                    p = 0.5 * (alpha - gamma) / denom
                    refined_lag = peak_idx + p
                else:
                    refined_lag = float(peak_idx)
            else:
                refined_lag = float(peak_idx)

            detected_f0 = fs / refined_lag
            if min_f0 <= detected_f0 <= max_f0:
                f0[i] = detected_f0

    return f0


def _compute_energy_frames(segment, frame_samples, step_samples):
    """Compute per-frame energy in dB for a signal segment."""
    n_frames = max(0, int((len(segment) - frame_samples) / step_samples) + 1)
    energies = []
    for i in range(n_frames):
        start = i * step_samples
        end = start + frame_samples
        if end > len(segment):
            break
        frame = segment[start:end]
        power = np.mean(frame ** 2)
        if power > 0:
            energies.append(10 * np.log10(power))
        else:
            energies.append(-100.0)
    return np.array(energies) if energies else np.array([])


def _stats6(values):
    """Compute [mean, std, max, min, skewness, kurtosis]."""
    values = np.asarray(values, dtype=float)
    if len(values) == 0:
        return np.zeros(6)
    if len(values) == 1:
        return np.array([values[0], 0.0, values[0], values[0], 0.0, 0.0])
    s = np.std(values)
    if s < 1e-15:
        return np.array([np.mean(values), 0.0, np.max(values),
                         np.min(values), 0.0, 0.0])
    return np.array([
        np.mean(values),
        s,
        np.max(values),
        np.min(values),
        float(scipy_stats.skew(values)),
        float(scipy_stats.kurtosis(values))
    ])


def _stats4(values):
    """Compute [mean, std, skewness, kurtosis]."""
    values = np.asarray(values, dtype=float)
    if len(values) == 0:
        return np.zeros(4)
    if len(values) == 1:
        return np.array([values[0], 0.0, 0.0, 0.0])
    s = np.std(values)
    if s < 1e-15:
        return np.array([np.mean(values), 0.0, 0.0, 0.0])
    return np.array([
        np.mean(values),
        s,
        float(scipy_stats.skew(values)),
        float(scipy_stats.kurtosis(values))
    ])


def _segment_voiced_unvoiced(f0, data, step_samples):
    """Segment signal into voiced and unvoiced regions based on F0 contour.

    Returns:
        voiced_segments: list of audio segments (numpy arrays)
        unvoiced_segments: list of audio segments (numpy arrays)
        voiced_f0_segments: list of F0 arrays per voiced segment
    """
    voiced_segments = []
    unvoiced_segments = []
    voiced_f0_segments = []

    n_frames = len(f0)
    if n_frames == 0:
        return voiced_segments, unvoiced_segments, voiced_f0_segments

    in_voiced = f0[0] > 0
    seg_start_frame = 0

    for i in range(1, n_frames + 1):
        is_voiced = (i < n_frames) and (f0[i] > 0)

        if is_voiced != in_voiced or i == n_frames:
            # Segment boundary
            start_sample = seg_start_frame * step_samples
            end_sample = min(i * step_samples, len(data))

            if end_sample > start_sample:
                segment = data[start_sample:end_sample]
                if in_voiced:
                    voiced_segments.append(segment)
                    voiced_f0_segments.append(f0[seg_start_frame:i].copy())
                else:
                    unvoiced_segments.append(segment)

            seg_start_frame = i
            in_voiced = is_voiced

    return voiced_segments, unvoiced_segments, voiced_f0_segments


def _energy_features(segments, fs, frame_samples, step_samples):
    """Compute 24 energy features for a list of signal segments."""
    all_energies = []
    per_seg_energies = []
    tilts = []
    mses = []

    for seg in segments:
        e = _compute_energy_frames(seg, frame_samples, step_samples)
        if len(e) > 0:
            all_energies.extend(e.tolist())
            per_seg_energies.append(e)

            if len(e) >= 2:
                x = np.arange(len(e))
                coeffs = np.polyfit(x, e, 1)
                tilts.append(coeffs[0])
                predicted = np.polyval(coeffs, x)
                mse = np.mean((e - predicted) ** 2)
                mses.append(mse)

    # Energy contour stats (4)
    energy_stats = _stats4(all_energies) if all_energies else np.zeros(4)
    # Tilt stats (4)
    tilt_stats = _stats4(tilts) if tilts else np.zeros(4)
    # MSE stats (4)
    mse_stats = _stats4(mses) if mses else np.zeros(4)

    # First segment stats (6)
    if per_seg_energies:
        first_stats = _stats6(per_seg_energies[0])
        last_stats = _stats6(per_seg_energies[-1])
    else:
        first_stats = np.zeros(6)
        last_stats = np.zeros(6)

    return np.concatenate([energy_stats, tilt_stats, mse_stats,
                           first_stats, last_stats])


def _duration_features(voiced_segs, unvoiced_segs, pause_segs, data, fs):
    """Compute 25 duration features."""
    total_duration = len(data) / float(fs)

    # Voiced rate
    voiced_rate = len(voiced_segs) / total_duration if total_duration > 0 else 0

    # Segment durations
    v_durs = np.array([len(s) / float(fs) for s in voiced_segs]) \
        if voiced_segs else np.array([0.0])
    u_durs = np.array([len(s) / float(fs) for s in unvoiced_segs]) \
        if unvoiced_segs else np.array([0.0])
    p_durs = np.array([len(s) / float(fs) for s in pause_segs]) \
        if pause_segs else np.array([0.0])

    v_stats = _stats6(v_durs)
    u_stats = _stats6(u_durs)
    p_stats = _stats6(p_durs)

    # Duration ratios
    total_v = float(np.sum(v_durs)) if voiced_segs else 0.0
    total_u = float(np.sum(u_durs)) if unvoiced_segs else 0.0
    total_p = float(np.sum(p_durs)) if pause_segs else 0.0

    vu = total_v + total_u

    ratios = np.array([
        total_p / vu if vu > 0 else 0,
        total_p / total_u if total_u > 0 else 0,
        total_u / vu if vu > 0 else 0,
        total_v / vu if vu > 0 else 0,
        total_v / total_p if total_p > 0 else 0,
        total_u / total_p if total_p > 0 else 0
    ])

    return np.concatenate([[voiced_rate], v_stats, u_stats, p_stats, ratios])


def extract_static(wav_path, frame_ms=20, step_ms=10, min_f0=60, max_f0=350,
                   pause_threshold_ms=140, poly_degree=5):
    """Extract 103-element static prosody feature vector."""
    fs, data = _preprocess(wav_path)
    frame_samples = int(frame_ms * fs / 1000)
    step_samples = int(step_ms * fs / 1000)
    pause_threshold_samples = int(pause_threshold_ms * fs / 1000)

    # Extract F0
    f0 = _extract_f0_internal(data, fs, min_f0, max_f0,
                              frame_samples, step_samples)

    # Segment
    voiced_segs, all_unvoiced, voiced_f0_segs = \
        _segment_voiced_unvoiced(f0, data, step_samples)

    # Split unvoiced into short unvoiced and pauses
    pauses = []
    unvoiced_segs = []
    for seg in all_unvoiced:
        if len(seg) > pause_threshold_samples:
            pauses.append(seg)
        else:
            unvoiced_segs.append(seg)

    # --- F0 features (30) ---
    f0_nz = f0[f0 > 0]
    overall_f0 = _stats6(f0_nz) if len(f0_nz) > 0 else np.zeros(6)

    # Per-segment F0 tilt and MSE
    tilts = []
    mses = []
    for seg_f0 in voiced_f0_segs:
        seg_f0_nz = seg_f0[seg_f0 > 0]
        if len(seg_f0_nz) >= 2:
            x = np.arange(len(seg_f0_nz))
            coeffs = np.polyfit(x, seg_f0_nz, 1)
            tilts.append(coeffs[0])
            predicted = np.polyval(coeffs, x)
            mse = np.mean((seg_f0_nz - predicted) ** 2)
            mses.append(mse)

    tilt_stats = _stats6(tilts) if tilts else np.zeros(6)
    mse_stats = _stats6(mses) if mses else np.zeros(6)

    # First and last segment F0
    if voiced_f0_segs:
        first_f0_vals = voiced_f0_segs[0]
        first_f0_vals = first_f0_vals[first_f0_vals > 0]
        last_f0_vals = voiced_f0_segs[-1]
        last_f0_vals = last_f0_vals[last_f0_vals > 0]
        first_f0 = _stats6(first_f0_vals) if len(first_f0_vals) > 0 \
            else np.zeros(6)
        last_f0 = _stats6(last_f0_vals) if len(last_f0_vals) > 0 \
            else np.zeros(6)
    else:
        first_f0 = np.zeros(6)
        last_f0 = np.zeros(6)

    f0_features = np.concatenate([overall_f0, tilt_stats, mse_stats,
                                  first_f0, last_f0])

    # --- Energy features (24 each for voiced and unvoiced) ---
    energy_v = _energy_features(voiced_segs, fs, frame_samples, step_samples)
    energy_u = _energy_features(unvoiced_segs, fs, frame_samples, step_samples)

    # --- Duration features (25) ---
    dur_features = _duration_features(voiced_segs, unvoiced_segs, pauses,
                                      data, fs)

    result = np.concatenate([f0_features, energy_v, energy_u, dur_features])
    assert len(result) == 103, f"Expected 103 features, got {len(result)}"
    return result


def extract_dynamic(wav_path, frame_ms=20, step_ms=10, min_f0=60, max_f0=350,
                    poly_degree=5):
    """Extract (N, 13) dynamic prosody features per voiced segment."""
    fs, data = _preprocess(wav_path)
    frame_samples = int(frame_ms * fs / 1000)
    step_samples = int(step_ms * fs / 1000)

    f0 = _extract_f0_internal(data, fs, min_f0, max_f0,
                              frame_samples, step_samples)

    voiced_segs, _, voiced_f0_segs = \
        _segment_voiced_unvoiced(f0, data, step_samples)

    features = []
    for seg, seg_f0 in zip(voiced_segs, voiced_f0_segs):
        if len(seg) <= frame_samples:
            continue

        dur = len(seg) / float(fs)

        # F0 polynomial fit
        seg_f0_nz = seg_f0[seg_f0 > 0]
        if len(seg_f0_nz) >= poly_degree + 1:
            x = np.arange(len(seg_f0_nz))
            f0_coeffs = np.polyfit(x, seg_f0_nz, poly_degree)
        else:
            f0_coeffs = np.zeros(poly_degree + 1)

        # Energy polynomial fit
        energy = _compute_energy_frames(seg, frame_samples, step_samples)
        if len(energy) >= poly_degree + 1:
            x = np.arange(len(energy))
            e_coeffs = np.polyfit(x, energy, poly_degree)
        else:
            e_coeffs = np.zeros(poly_degree + 1)

        row = np.concatenate([f0_coeffs, e_coeffs, [dur]])
        features.append(row)

    if features:
        return np.array(features)
    return np.zeros((0, 13))
