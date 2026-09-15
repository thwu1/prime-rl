#!/usr/bin/env python3
"""EMG signal processing and analysis pipeline.

"""

import argparse
import json
import math
import os
import numpy as np
from scipy.signal import butter, iirnotch, filtfilt


# ============================================================
# Feature group definitions
# ============================================================

FEATURE_GROUPS = {
    "HTD": ["MAV", "ZC", "SSC", "WL"],
    "TDPSD": ["M0", "M2", "M4", "SPARSI", "IRF", "WLF"],
    "HJORTH": ["ACT", "MOB", "COMP"],
}


def expand_features(feature_list):
    expanded = []
    for f in feature_list:
        if f in FEATURE_GROUPS:
            expanded.extend(FEATURE_GROUPS[f])
        else:
            expanded.append(f)
    seen = set()
    result = []
    for f in expanded:
        if f not in seen:
            seen.add(f)
            result.append(f)
    return result


# ============================================================
# Signal filtering
# ============================================================

def apply_filters(data, filters, fs):
    filtered = data.copy()
    for filt in filters:
        name = filt["name"]
        if name == "bandpass":
            nyq = fs / 2
            b, a = butter(filt["order"], [c / nyq for c in filt["cutoff"]], btype="bandpass")
            filtered = filtfilt(b, a, filtered, axis=0)
        elif name == "highpass":
            nyq = fs / 2
            b, a = butter(filt["order"], filt["cutoff"] / nyq, btype="highpass")
            filtered = filtfilt(b, a, filtered, axis=0)
        elif name == "notch":
            q = filt["cutoff"] / filt["bandwidth"]
            b, a = iirnotch(filt["cutoff"], q, fs)
            filtered = filtfilt(b, a, filtered, axis=0)
    return filtered


# ============================================================
# Windowing
# ============================================================

def get_windows(data, window_size, window_increment):
    n_samples = data.shape[0]
    n_channels = data.shape[1]
    n_windows = (n_samples - window_size) // window_increment + 1
    windows = np.zeros((n_windows, n_channels, window_size))
    for i in range(n_windows):
        start = i * window_increment
        windows[i] = data[start : start + window_size].T
    return windows


# ============================================================
# HTD features
# ============================================================

def feat_mav(windows):
    return np.mean(np.abs(windows), axis=2)


def feat_zc(windows):
    sgn_change = np.diff(np.sign(windows), axis=2)
    return np.sum(sgn_change == -2, axis=2) + np.sum(sgn_change == 2, axis=2)


def feat_ssc(windows):
    w2 = windows[:, :, 2:]
    w1 = windows[:, :, 1:-1]
    w0 = windows[:, :, :-2]
    return np.sum(((w1 - w0) * (w1 - w2)) >= 0.0, axis=2)


def feat_wl(windows):
    return np.sum(np.abs(np.diff(windows, axis=2)), axis=2)


# ============================================================
# TDPSD features
# ============================================================

def _efp_transform(windows):
    return np.log(windows ** 2 + np.spacing(1))


def _tdpsd_combine(ebp, efp):
    num = -2 * efp * ebp
    den = efp ** 2 + ebp ** 2
    return num / den


def _tdpsd_moments(w):
    m0 = np.sqrt(np.sum(w ** 2, axis=2)) / (w.shape[2] - 1)
    m0 = m0 ** 0.1 / 0.1
    d1 = np.diff(w, n=1, axis=2)
    m2 = np.sqrt(np.sum(d1 ** 2, axis=2) / (w.shape[2] - 1))
    m2 = m2 ** 0.1 / 0.1
    d2 = np.diff(d1, n=1, axis=2)
    m4 = np.sqrt(np.sum(d2 ** 2, axis=2) / (w.shape[2] - 1))
    m4 = m4 ** 0.1 / 0.1
    return m0, m2, m4


def feat_m0(windows):
    def closure(w):
        m0 = np.sqrt(np.sum(w ** 2, axis=2)) / (w.shape[2] - 1)
        m0 = m0 ** 0.1 / 0.1
        return np.log(np.abs(m0))
    ebp = closure(windows)
    efp = closure(_efp_transform(windows))
    return _tdpsd_combine(ebp, efp)


def feat_m2(windows):
    def closure(w):
        m0 = np.sqrt(np.sum(w ** 2, axis=2)) / (w.shape[2] - 1)
        m0 = m0 ** 0.1 / 0.1
        d1 = np.diff(w, n=1, axis=2)
        m2 = np.sqrt(np.sum(d1 ** 2, axis=2) / (w.shape[2] - 1))
        m2 = m2 ** 0.1 / 0.1
        return np.log(np.abs(m0 - m2))
    ebp = closure(windows)
    efp = closure(_efp_transform(windows))
    return _tdpsd_combine(ebp, efp)


def feat_m4(windows):
    def closure(w):
        m0 = np.sqrt(np.sum(w ** 2, axis=2)) / (w.shape[2] - 1)
        m0 = m0 ** 0.1 / 0.1
        d1 = np.diff(w, n=1, axis=2)
        d2 = np.diff(d1, n=1, axis=2)
        m4 = np.sqrt(np.sum(d2 ** 2, axis=2) / (w.shape[2] - 1))
        m4 = m4 ** 0.1 / 0.1
        return np.log(np.abs(m0 - m4))
    ebp = closure(windows)
    efp = closure(_efp_transform(windows))
    return _tdpsd_combine(ebp, efp)


def feat_sparsi(windows):
    def closure(w):
        m0, m2, m4 = _tdpsd_moments(w)
        sparsi = np.sqrt(np.abs((m0 - m2) * (m0 - m4))) / m0
        return np.log(np.abs(sparsi))
    ebp = closure(windows)
    efp = closure(_efp_transform(windows))
    return _tdpsd_combine(ebp, efp)


def feat_irf(windows):
    def closure(w):
        m0, m2, m4 = _tdpsd_moments(w)
        irf = m2 / np.sqrt(m0 * m4)
        return np.log(np.abs(irf))
    ebp = closure(windows)
    efp = closure(_efp_transform(windows))
    return _tdpsd_combine(ebp, efp)


def feat_wlf(windows):
    def closure(w):
        d1 = np.diff(w, n=1, axis=2)
        d2 = np.diff(d1, n=1, axis=2)
        wlf = np.sqrt(np.sum(np.abs(d1), axis=2) / np.sum(np.abs(d2), axis=2))
        return np.log(np.abs(wlf))
    ebp = closure(windows)
    efp = closure(_efp_transform(windows))
    return _tdpsd_combine(ebp, efp)


# ============================================================
# Hjorth parameters
# ============================================================

def feat_act(windows):
    return np.mean(windows ** 2, axis=2)


def feat_mob(windows):
    m0 = np.mean(windows ** 2, axis=2)
    m2 = np.sum(np.diff(windows, axis=2) ** 2, axis=2) / windows.shape[2]
    return np.sqrt(m2 / m0)


def feat_comp(windows):
    m2 = np.sum(np.diff(windows, axis=2) ** 2, axis=2) / windows.shape[2]
    m4 = np.sum(np.diff(np.diff(windows, axis=2), axis=2) ** 2, axis=2) / windows.shape[2]
    return np.sqrt(m4 / m2)


# ============================================================
# Sample Entropy
# ============================================================

def feat_sampen(windows, dim=2, tolerance=0.3):
    N = windows.shape[2]
    wmean = np.mean(windows, axis=2, keepdims=True)
    wstd = np.std(windows, axis=2, keepdims=True)
    series = (windows - wmean) / wstd

    sampen = np.zeros((windows.shape[0], windows.shape[1]))
    for wi in range(windows.shape[0]):
        for ch in range(windows.shape[1]):
            results = []
            for j in [1, 2]:
                m = dim + j - 1
                patterns = np.zeros((m, N - m + 1))
                count = np.zeros(N - m)
                for k in range(m):
                    patterns[k, :] = series[wi, ch, k : N - m + k + 1]

                for k in range(N - m):
                    dist = np.max(
                        np.abs(patterns - patterns[:, k : k + 1]), axis=0
                    )
                    mask = dist <= tolerance
                    count[k] = np.sum(mask) - 1  # exclude self

                count = count / (N - dim - 1)
                results.append(np.mean(count))

            sampen[wi, ch] = np.log(
                (results[0] + np.spacing(1)) / (results[1] + np.spacing(1))
            )
    return sampen


# ============================================================
# Fuzzy Entropy
# ============================================================

def feat_fuzzyen(windows, dim=2, tolerance=0.3, win=2):
    r = tolerance * np.std(windows, axis=2)
    N = windows.shape[2]
    fuzzyen = np.zeros((windows.shape[0], windows.shape[1]))
    for w_idx in range(windows.shape[0]):
        for ch in range(windows.shape[1]):
            results = []
            for j in [1, 2]:
                m = dim + j - 1
                dataMat = np.zeros((m, N - m + 1))
                phi = np.zeros(N - m + 1)
                for k in range(m):
                    dataMat[k, :] = windows[w_idx, ch, k : N - m + k + 1]
                # subtract local mean from each pattern
                for k in range(N - m + 1):
                    dataMat[:, k] -= np.mean(dataMat[:, k])
                for k in range(N - m):
                    tmp = np.max(
                        np.abs(dataMat - dataMat[:, k : k + 1]), axis=0
                    )
                    simi = np.exp((-1) * (tmp ** win) / r[w_idx, ch])
                    phi[k] = (np.sum(simi) - 1) / (N - m - 1)
                results.append(np.sum(phi) / (N - m))
            fuzzyen[w_idx, ch] = np.log(
                (results[0] + np.spacing(1)) / (results[1] + np.spacing(1))
            )
    return fuzzyen


# ============================================================
# Frequency features
# ============================================================

def _nextpow2(n):
    if n == 0:
        return 1
    return 2 ** math.ceil(math.log2(n))


def feat_mdf(windows, fs=1000):
    nfft = _nextpow2(windows.shape[2])
    spec = np.fft.fft(windows, n=nfft, axis=2) / windows.shape[2]
    spec = spec[:, :, : nfft // 2]
    POW = np.real(spec * np.conj(spec))
    totalPOW = np.sum(POW, axis=2)
    cumPOW = np.cumsum(POW, axis=2)
    medfreq = np.zeros((windows.shape[0], windows.shape[1]))
    for i in range(windows.shape[0]):
        for j in range(windows.shape[1]):
            idx = np.argwhere(cumPOW[i, j, :] > totalPOW[i, j] / 2)[0][0]
            medfreq[i, j] = (fs / 2) * idx / (nfft / 2)
    return medfreq


def feat_mnf(windows, fs=1000):
    nfft = _nextpow2(windows.shape[2])
    spec = np.fft.fft(windows, n=nfft, axis=2) / windows.shape[2]
    f = np.fft.fftfreq(nfft) * fs
    spec = spec[:, :, : nfft // 2]
    f = f[: nfft // 2]
    f_broadcast = np.broadcast_to(f, spec.shape)
    POW = spec * np.conj(spec)
    return np.real(np.sum(POW * f_broadcast, axis=2) / np.sum(POW, axis=2))


# ============================================================
# Feature dispatcher
# ============================================================

def extract_feature(name, windows, fs):
    extractors = {
        "MAV": lambda w: feat_mav(w),
        "ZC": lambda w: feat_zc(w),
        "SSC": lambda w: feat_ssc(w),
        "WL": lambda w: feat_wl(w),
        "M0": lambda w: feat_m0(w),
        "M2": lambda w: feat_m2(w),
        "M4": lambda w: feat_m4(w),
        "SPARSI": lambda w: feat_sparsi(w),
        "IRF": lambda w: feat_irf(w),
        "WLF": lambda w: feat_wlf(w),
        "ACT": lambda w: feat_act(w),
        "MOB": lambda w: feat_mob(w),
        "COMP": lambda w: feat_comp(w),
        "SAMPEN": lambda w: feat_sampen(w),
        "FUZZYEN": lambda w: feat_fuzzyen(w),
        "MDF": lambda w: feat_mdf(w, fs),
        "MNF": lambda w: feat_mnf(w, fs),
    }
    return extractors[name](windows)


# ============================================================
# Classification metrics
# ============================================================

def compute_metrics(labels_file, predictions_file, null_label):
    y_true = np.loadtxt(labels_file, delimiter=",").astype(int)
    y_pred_orig = np.loadtxt(predictions_file, delimiter=",").astype(int)

    # REJ_RATE on original predictions
    rej_rate = float(np.sum(y_pred_orig == -1) / len(y_pred_orig))

    # Remove rejections
    valid = y_pred_orig != -1
    y_true_f = y_true[valid]
    y_pred_f = y_pred_orig[valid]

    # CA
    if len(y_true_f) > 0:
        ca = float(np.sum(y_pred_f == y_true_f) / len(y_true_f))
    else:
        ca = 1.0

    # AER
    aer = 0.0
    if null_label is not None:
        non_null = y_pred_f != null_label
        y_true_active = y_true_f[non_null]
        y_pred_active = y_pred_f[non_null]
        if len(y_true_active) > 0:
            aer = float(1.0 - np.sum(y_pred_active == y_true_active) / len(y_true_active))

    # INS
    if len(y_pred_f) > 1:
        gt_changes = int(np.count_nonzero(y_true_f[:-1] != y_true_f[1:]))
        pred_changes = int(np.count_nonzero(y_pred_f[:-1] != y_pred_f[1:]))
        ins = float(max(0.0, (pred_changes - gt_changes) / len(y_pred_f)))
    else:
        ins = 0.0

    # F1 (weighted)
    classes = np.sort(np.unique(y_true_f))
    f1_per_class = np.zeros(len(classes))
    weights = np.zeros(len(classes))

    for i, c in enumerate(classes):
        c_true_idx = y_true_f == c
        c_false_idx = y_true_f != c
        tp = int(np.sum(y_pred_f[c_true_idx] == c))
        fn = int(np.sum(y_pred_f[c_true_idx] != c))
        fp = int(np.sum(y_pred_f[c_false_idx] == c))

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1_per_class[i] = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )
        weights[i] = np.sum(c_true_idx) / len(y_true_f)

    f1 = float(np.average(f1_per_class, weights=weights))

    # CONF_MAT
    n_classes = len(classes)
    conf_mat = np.zeros((n_classes, n_classes), dtype=int)
    for r in range(n_classes):
        c_true = np.where(y_true_f == classes[r])[0]
        for col in range(n_classes):
            conf_mat[r, col] = int(np.sum(y_pred_f[c_true] == classes[col]))

    return {
        "CA": ca,
        "AER": aer,
        "INS": ins,
        "REJ_RATE": rej_rate,
        "F1": f1,
        "CONF_MAT": conf_mat.tolist(),
    }


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="EMG signal processing pipeline")
    parser.add_argument("--input", required=True, help="Input CSV file")
    parser.add_argument("--config", required=True, help="Config JSON file")
    parser.add_argument("--output", required=True, help="Output directory")
    args = parser.parse_args()

    with open(args.config) as f:
        config = json.load(f)

    # Load data
    data = np.loadtxt(args.input, delimiter=",")
    if data.ndim == 1:
        data = data.reshape(-1, 1)

    # Apply filters
    fs = config["sampling_frequency"]
    filters = config.get("filters", [])
    if filters:
        data = apply_filters(data, filters, fs)

    # Create windows
    ws = config["window_size"]
    wi = config["window_increment"]
    windows = get_windows(data, ws, wi)

    # Expand and extract features
    feat_list = expand_features(config.get("features", []))
    features = {}
    for feat_name in feat_list:
        features[feat_name] = extract_feature(feat_name, windows, fs)

    # Create output directory
    os.makedirs(args.output, exist_ok=True)

    # Write features
    features_json = {k: v.tolist() for k, v in features.items()}
    with open(os.path.join(args.output, "features.json"), "w") as f:
        json.dump(features_json, f)

    # Write summary
    summary = {
        "num_windows": int(windows.shape[0]),
        "num_channels": int(windows.shape[1]),
        "features_extracted": feat_list,
        "sampling_frequency": fs,
    }
    with open(os.path.join(args.output, "summary.json"), "w") as f:
        json.dump(summary, f)

    # Compute metrics if applicable
    labels_file = config.get("labels_file")
    predictions_file = config.get("predictions_file")
    if labels_file and predictions_file:
        metrics = compute_metrics(
            labels_file, predictions_file, config.get("null_label")
        )
        with open(os.path.join(args.output, "metrics.json"), "w") as f:
            json.dump(metrics, f)


if __name__ == "__main__":
    main()
