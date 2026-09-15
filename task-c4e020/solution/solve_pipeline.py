#!/usr/bin/env python3
"""Cross-subject EEG motor imagery decoding pipeline.

Implements: bandpass filter -> Euclidean alignment -> CSP -> LDA
"""

import json
import os

import numpy as np
from scipy.linalg import eigh, inv, sqrtm
from scipy.signal import butter, filtfilt


# ---------------------------------------------------------------------------
# Signal preprocessing
# ---------------------------------------------------------------------------

def bandpass_filter(data, f_low, f_high, sfreq, order=5):
    """Bandpass-filter each channel. data: (n_channels, n_samples)."""
    nyq = sfreq / 2.0
    b, a = butter(order, [f_low / nyq, f_high / nyq], btype="band")
    out = np.zeros_like(data)
    for ch in range(data.shape[0]):
        out[ch] = filtfilt(b, a, data[ch])
    return out


# ---------------------------------------------------------------------------
# Domain adaptation: Euclidean alignment
# ---------------------------------------------------------------------------

def compute_trial_covariance(trial):
    """Covariance of a single trial. trial: (n_channels, n_samples)."""
    n = trial.shape[1]
    return trial @ trial.T / n


def euclidean_alignment(trials):
    """Per-subject Euclidean alignment (He & Wu, 2020).

    Computes mean covariance R, then transforms each trial by R^{-1/2}.
    Returns aligned trials.
    """
    covs = np.array([compute_trial_covariance(t) for t in trials])
    R = np.mean(covs, axis=0)
    R += 1e-6 * np.eye(R.shape[0])
    R_inv_sqrt = np.real(inv(sqrtm(R)))
    aligned = np.array([R_inv_sqrt @ t for t in trials])
    return aligned


# ---------------------------------------------------------------------------
# Feature extraction: Common Spatial Patterns
# ---------------------------------------------------------------------------

def fit_csp(X_class0, X_class1, n_components=6):
    """Fit CSP spatial filters.

    X_class0, X_class1: lists of (n_channels, n_samples) arrays.
    Returns W: (n_components, n_channels).
    """
    cov0 = np.mean([compute_trial_covariance(x) for x in X_class0], axis=0)
    cov1 = np.mean([compute_trial_covariance(x) for x in X_class1], axis=0)

    reg = 1e-6 * np.eye(cov0.shape[0])
    cov0 += reg
    cov1 += reg

    eigenvalues, eigenvectors = eigh(cov0, cov0 + cov1)
    idx = np.argsort(eigenvalues)
    eigenvectors = eigenvectors[:, idx]

    n_half = n_components // 2
    W = np.vstack([eigenvectors[:, :n_half].T, eigenvectors[:, -n_half:].T])
    return W


def csp_features(trials, W):
    """Extract log-variance CSP features.

    trials: (n_trials, n_channels, n_samples)
    W: (n_components, n_channels)
    Returns: (n_trials, n_components)
    """
    features = np.zeros((len(trials), W.shape[0]))
    for i, trial in enumerate(trials):
        projected = W @ trial
        var = np.var(projected, axis=1)
        total_var = np.sum(var)
        if total_var < 1e-12:
            total_var = 1e-12
        features[i] = np.log(var / total_var)
    return features


# ---------------------------------------------------------------------------
# Classifier: regularized LDA
# ---------------------------------------------------------------------------

def lda_fit(X, y, shrinkage=0.1):
    """Fit LDA with Ledoit-Wolf-style shrinkage."""
    classes = np.unique(y)
    means = {c: np.mean(X[y == c], axis=0) for c in classes}

    S_w = np.zeros((X.shape[1], X.shape[1]))
    for c in classes:
        diff = X[y == c] - means[c]
        S_w += diff.T @ diff
    S_w /= len(X)

    S_w = (1 - shrinkage) * S_w + shrinkage * np.trace(S_w) / S_w.shape[0] * np.eye(S_w.shape[0])

    w = np.linalg.solve(S_w, means[1] - means[0])
    threshold = 0.5 * w @ (means[0] + means[1])
    return w, threshold


def lda_predict(X, w, threshold):
    return (X @ w > threshold).astype(int)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def discover_subjects(data_dir):
    """Discover train/test subjects from filesystem."""
    all_dirs = sorted([
        d for d in os.listdir(data_dir)
        if d.startswith("subject_") and os.path.isdir(os.path.join(data_dir, d))
    ])
    train_subjects = []
    test_subjects = []
    for d in all_dirs:
        labels_path = os.path.join(data_dir, d, "labels.npy")
        if os.path.isfile(labels_path):
            train_subjects.append(d)
        else:
            test_subjects.append(d)
    return train_subjects, test_subjects


def main():
    data_dir = "/app/data"

    # Discover subjects from filesystem (robust — no dependency on dataset_info.json)
    train_subjects, test_subjects = discover_subjects(data_dir)
    print("Train subjects: {}".format(train_subjects))
    print("Test subjects:  {}".format(test_subjects))

    # Read sfreq from first subject metadata
    with open(os.path.join(data_dir, train_subjects[0], "metadata.json")) as f:
        meta = json.load(f)
    sfreq = meta["sfreq"]

    f_low, f_high = 8, 30
    n_csp = 6

    # ------------------------------------------------------------------
    # Load and preprocess training data
    # ------------------------------------------------------------------
    all_train_trials = []
    all_train_labels = []

    for subj_id in train_subjects:
        subj_dir = os.path.join(data_dir, subj_id)
        eeg = np.load(os.path.join(subj_dir, "eeg_data.npy"))
        labels = np.load(os.path.join(subj_dir, "labels.npy"))

        filtered = np.array([bandpass_filter(trial, f_low, f_high, sfreq) for trial in eeg])
        aligned = euclidean_alignment(filtered)

        all_train_trials.append(aligned)
        all_train_labels.append(labels)

    X_train = np.concatenate(all_train_trials, axis=0)
    y_train = np.concatenate(all_train_labels, axis=0)

    # ------------------------------------------------------------------
    # Fit CSP on pooled aligned training data
    # ------------------------------------------------------------------
    X_c0 = X_train[y_train == 0]
    X_c1 = X_train[y_train == 1]
    W = fit_csp(X_c0, X_c1, n_components=n_csp)

    # ------------------------------------------------------------------
    # Extract features and train LDA
    # ------------------------------------------------------------------
    features_train = csp_features(X_train, W)
    w_lda, thresh_lda = lda_fit(features_train, y_train)

    # ------------------------------------------------------------------
    # Predict on test subjects
    # ------------------------------------------------------------------
    predictions = {}

    for subj_id in test_subjects:
        subj_dir = os.path.join(data_dir, subj_id)
        eeg = np.load(os.path.join(subj_dir, "eeg_data.npy"))

        filtered = np.array([bandpass_filter(trial, f_low, f_high, sfreq) for trial in eeg])
        aligned = euclidean_alignment(filtered)

        features = csp_features(aligned, W)
        preds = lda_predict(features, w_lda, thresh_lda)
        predictions[subj_id] = preds.tolist()
        print("  {}: {} trials predicted".format(subj_id, len(preds)))

    # ------------------------------------------------------------------
    # Save outputs
    # ------------------------------------------------------------------
    with open("/app/predictions.json", "w") as f:
        json.dump(predictions, f, indent=2)

    pipeline_config = {
        "preprocessing": "butterworth_bandpass_8_30Hz_order5_filtfilt",
        "feature_extraction": "common_spatial_patterns_6_components_log_variance",
        "domain_adaptation": "euclidean_alignment_per_subject_covariance_whitening",
        "classifier": "shrinkage_linear_discriminant_analysis",
    }
    with open("/app/pipeline_config.json", "w") as f:
        json.dump(pipeline_config, f, indent=2)

    print("Pipeline complete. Outputs saved to /app/")


if __name__ == "__main__":
    main()
