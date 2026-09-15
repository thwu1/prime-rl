"""Phonation feature extraction module.

"""

import numpy as np
from scipy.io.wavfile import read
from scipy import stats as scipy_stats


def jitter_env(f0_voiced, n_points):
    """Compute frame-wise jitter from F0 sequence."""
    f0_voiced = np.asarray(f0_voiced, dtype=float)
    n = len(f0_voiced)
    result = np.zeros(n_points)
    if n < 2:
        return result
    step = n / n_points
    max_val = np.max(f0_voiced)
    if max_val == 0:
        return result
    for idx in range(n_points - 1):
        i = int(idx * step)
        if idx > 0 and i == int((idx - 1) * step):
            result[idx] = result[idx - 1]
        else:
            if i + 1 < n:
                result[idx] = np.abs(f0_voiced[i + 1] - f0_voiced[i])
            else:
                result[idx] = 0
        result[idx] = 100 * result[idx] / max_val
    return result


def shimmer_env(amplitudes, n_points):
    """Compute frame-wise shimmer from amplitude sequence."""
    amplitudes = np.asarray(amplitudes, dtype=float)
    n = len(amplitudes)
    result = np.zeros(n_points)
    if n < 2:
        return result
    step = n / n_points
    max_val = np.max(amplitudes)
    if max_val == 0:
        return result
    for idx in range(n_points - 1):
        i = int(idx * step)
        if idx > 0 and i == int((idx - 1) * step):
            result[idx] = result[idx - 1]
        else:
            if i + 1 < n:
                result[idx] = np.abs(amplitudes[i + 1] - amplitudes[i])
            else:
                result[idx] = 0
        result[idx] = 100 * result[idx] / max_val
    return result


def perturbation_quotient(x, k):
    """Compute perturbation quotient of sequence x with window size k."""
    x = np.asarray(x, dtype=float)
    N = len(x)
    if N <= k or k % 2 == 0:
        return 0.0
    m = (k - 1) // 2
    total = 0.0
    for n in range(N - k):
        dif = 0.0
        for r in range(k):
            dif += x[n + r] - x[n + m]
        dif = np.abs(dif / float(k))
        total += dif
    num = total / (N - k)
    den = np.mean(np.abs(x))
    if den == 0:
        return 0.0
    return 100 * num / den


def apq(amplitudes):
    """Amplitude Perturbation Quotient (k=11)."""
    return perturbation_quotient(np.asarray(amplitudes, dtype=float), 11)


def ppq(f0_values):
    """Pitch Period Perturbation Quotient (k=5, operates on periods)."""
    f0_values = np.asarray(f0_values, dtype=float)
    return perturbation_quotient(1.0 / f0_values, 5)


def log_energy(frame):
    """Compute log10(mean(frame^2))."""
    frame = np.asarray(frame, dtype=float)
    power = np.mean(frame ** 2)
    if power <= 0:
        return -100.0
    return np.log10(power)


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


def extract_f0(wav_path, min_f0=60, max_f0=350, frame_ms=40, step_ms=20):
    """Extract F0 contour using autocorrelation-based pitch detection."""
    fs, data = _preprocess(wav_path)
    frame_samples = int(frame_ms * fs / 1000)
    step_samples = int(step_ms * fs / 1000)
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

        # Energy-based silence detection
        energy = np.mean(frame ** 2)
        if energy < 1e-6:
            continue

        # Apply Hamming window
        windowed = frame * np.hamming(len(frame))

        # FFT-based autocorrelation
        fft_size = 1
        while fft_size < 2 * len(windowed):
            fft_size *= 2
        fft_frame = np.fft.rfft(windowed, fft_size)
        acf = np.fft.irfft(fft_frame * np.conj(fft_frame))
        acf = acf[:len(windowed)]

        if acf[0] <= 0:
            continue
        acf = acf / acf[0]

        # Search for peak in valid lag range
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
            # Parabolic interpolation for sub-sample precision
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


def extract_static(wav_path):
    """Extract 28-element static phonation feature vector."""
    fs, data = _preprocess(wav_path)
    frame_ms = 40
    step_ms = 20
    frame_samples = int(frame_ms * fs / 1000)
    step_samples = int(step_ms * fs / 1000)

    f0 = extract_f0(wav_path)
    f0_nz = f0[f0 != 0]

    if len(f0_nz) < 3:
        return np.zeros(28)

    # Compute descriptors over voiced frames
    jitter_arr = jitter_env(f0_nz, len(f0_nz))

    n_frames = len(f0)
    amp_list = []
    loge_list = []
    apq_list = []
    ppq_list = []
    df0 = np.diff(f0_nz, 1)
    ddf0 = np.diff(df0, 1)

    voiced_count = 0
    for i in range(n_frames):
        if f0[i] == 0:
            continue
        start = i * step_samples
        end = start + frame_samples
        if end > len(data):
            break
        frame = data[start:end]
        amp_list.append(np.max(np.abs(frame)))
        loge_list.append(10 * log_energy(frame))

        if voiced_count >= 12:
            amp_window = np.array(amp_list[voiced_count - 12:voiced_count])
            apq_list.append(apq(amp_window))

        if voiced_count >= 6:
            f0_window = f0_nz[voiced_count - 6:voiced_count]
            ppq_list.append(ppq(f0_window))

        voiced_count += 1

    shimmer_arr = shimmer_env(amp_list, len(amp_list))
    apq_arr = np.array(apq_list) if apq_list else shimmer_arr.copy()
    ppq_arr = np.array(ppq_list) if ppq_list else np.zeros(1)
    loge_arr = np.array(loge_list)

    # Aggregate with functionals
    descriptors = [df0, ddf0, jitter_arr, shimmer_arr,
                   apq_arr, ppq_arr, loge_arr]

    means = [np.mean(d) for d in descriptors]
    stds = [np.std(d) for d in descriptors]
    skews = []
    kurts = []
    for d in descriptors:
        d_arr = np.asarray(d, dtype=float)
        if len(d_arr) < 2 or np.std(d_arr) < 1e-10:
            skews.append(0.0)
            kurts.append(0.0)
        else:
            sv = float(scipy_stats.skew(d_arr))
            kv = float(scipy_stats.kurtosis(d_arr))
            skews.append(sv if np.isfinite(sv) else 0.0)
            kurts.append(kv if np.isfinite(kv) else 0.0)

    result = np.array(means + stds + skews + kurts)
    return np.nan_to_num(result, nan=0.0, posinf=0.0, neginf=0.0)


def extract_dynamic(wav_path):
    """Extract (N, 7) dynamic phonation feature matrix."""
    fs, data = _preprocess(wav_path)
    frame_ms = 40
    step_ms = 20
    frame_samples = int(frame_ms * fs / 1000)
    step_samples = int(step_ms * fs / 1000)

    f0 = extract_f0(wav_path)
    f0_nz = f0[f0 != 0]

    if len(f0_nz) < 13:
        return np.zeros((0, 7))

    jitter_arr = jitter_env(f0_nz, len(f0_nz))
    df0 = np.diff(f0_nz, 1)
    ddf0 = np.diff(df0, 1)

    n_frames = len(f0)
    amp_list = []
    loge_list = []
    apq_list = []
    ppq_list = []

    voiced_count = 0
    for i in range(n_frames):
        if f0[i] == 0:
            continue
        start = i * step_samples
        end = start + frame_samples
        if end > len(data):
            break
        frame = data[start:end]
        amp_list.append(np.max(np.abs(frame)))
        loge_list.append(10 * log_energy(frame))

        if voiced_count >= 12:
            amp_window = np.array(amp_list[voiced_count - 12:voiced_count])
            apq_list.append(apq(amp_window))

        if voiced_count >= 6:
            f0_window = f0_nz[voiced_count - 6:voiced_count]
            ppq_list.append(ppq(f0_window))

        voiced_count += 1

    shimmer_arr = shimmer_env(amp_list, len(amp_list))

    # Align arrays (skip first frames to align APQ/PPQ)
    if len(shimmer_arr) == len(apq_list):
        min_len = min(len(df0) - 5, len(ddf0) - 4, len(jitter_arr) - 6,
                      len(shimmer_arr) - 6, len(apq_list) - 6,
                      len(ppq_list), len(loge_list) - 6)
        if min_len <= 0:
            return np.zeros((0, 7))
        feat = np.column_stack([
            df0[5:5 + min_len],
            ddf0[4:4 + min_len],
            jitter_arr[6:6 + min_len],
            shimmer_arr[6:6 + min_len],
            np.array(apq_list)[6:6 + min_len],
            np.array(ppq_list)[:min_len],
            np.array(loge_list)[6:6 + min_len]
        ])
    else:
        min_len = min(len(df0) - 11, len(ddf0) - 10, len(jitter_arr) - 12,
                      len(shimmer_arr) - 12, len(apq_list),
                      len(ppq_list) - 6, len(loge_list) - 12)
        if min_len <= 0:
            return np.zeros((0, 7))
        feat = np.column_stack([
            df0[11:11 + min_len],
            ddf0[10:10 + min_len],
            jitter_arr[12:12 + min_len],
            shimmer_arr[12:12 + min_len],
            np.array(apq_list)[:min_len],
            np.array(ppq_list)[6:6 + min_len],
            np.array(loge_list)[12:12 + min_len]
        ])

    return feat
