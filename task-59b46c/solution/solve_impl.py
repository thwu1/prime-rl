"""Write the full pipeline implementation to /app/pipeline.py."""

IMPLEMENTATION = r'''"""Cross-subject EEG motor imagery decoding pipeline."""

import numpy as np
from typing import List, Dict, Tuple
from scipy import signal, linalg
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis


def _bandpass(data, low, high, fs, order=5):
    """Butterworth bandpass via SOS + zero-phase filtering."""
    sos = signal.butter(order, [low, high], btype="band", fs=fs, output="sos")
    return signal.sosfiltfilt(sos, data, axis=-1)


def _covariance(trial):
    """Trace-normalized sample covariance."""
    cov = trial @ trial.T / trial.shape[1]
    cov /= np.trace(cov)
    return cov


def _euclidean_align(subjects_data):
    """Euclidean Alignment: whiten each subject so mean covariance -> I."""
    aligned = []
    for subj in subjects_data:
        trials = subj["trials"]
        n_trials = trials.shape[0]
        covs = np.array([_covariance(trials[i]) for i in range(n_trials)])
        mean_cov = np.mean(covs, axis=0)
        eigvals, eigvecs = linalg.eigh(mean_cov)
        eigvals = np.maximum(eigvals, 1e-12)
        R = eigvecs @ np.diag(1.0 / np.sqrt(eigvals)) @ eigvecs.T
        aligned_trials = np.array([R @ trials[i] for i in range(n_trials)])
        out = dict(subj)
        out["trials"] = aligned_trials
        aligned.append(out)
    return aligned


def _csp_filters(X0, X1, n_filters=3):
    """Common Spatial Patterns via simultaneous diagonalization."""
    cov0 = np.mean([_covariance(X0[i]) for i in range(len(X0))], axis=0)
    cov1 = np.mean([_covariance(X1[i]) for i in range(len(X1))], axis=0)
    cov_c = cov0 + cov1
    lam, U = linalg.eigh(cov_c)
    lam = np.maximum(lam, 1e-12)
    P = np.diag(1.0 / np.sqrt(lam)) @ U.T
    S = P @ cov0 @ P.T
    d, B = linalg.eigh(S)
    idx = np.argsort(d)[::-1]
    B = B[:, idx]
    W_full = B.T @ P
    return np.vstack([W_full[:n_filters], W_full[-n_filters:]])


def _csp_features(trials, W):
    """Log-variance features from spatially filtered signals."""
    n_trials = trials.shape[0]
    n_comp = W.shape[0]
    features = np.zeros((n_trials, n_comp))
    for i in range(n_trials):
        Z = W @ trials[i]
        variances = np.var(Z, axis=1)
        total = np.sum(variances)
        if total < 1e-15:
            total = 1e-15
        features[i] = np.log(variances / total)
    return features


def decode(dataset_params: dict) -> dict:
    """Leave-one-subject-out cross-subject EEG motor imagery decoding."""
    from eeg_data import generate_dataset

    subjects_data = generate_dataset(**dataset_params)
    fs = subjects_data[0]["fs"]
    n_subjects = len(subjects_data)
    n_csp = 3
    low_hz, high_hz = 8.0, 30.0

    accuracies = []
    predictions = []

    for test_idx in range(n_subjects):
        # Bandpass filter all subjects
        filtered = []
        for s in subjects_data:
            sc = dict(s)
            sc["trials"] = _bandpass(s["trials"], low_hz, high_hz, fs)
            filtered.append(sc)

        train_subjs = [filtered[i] for i in range(n_subjects) if i != test_idx]
        test_subj = filtered[test_idx]

        # Euclidean Alignment on all subjects together
        all_subjs = train_subjs + [test_subj]
        aligned = _euclidean_align(all_subjs)
        aligned_train = aligned[:-1]
        aligned_test = aligned[-1]

        # Aggregate training data
        X_train = np.concatenate([s["trials"] for s in aligned_train], axis=0)
        y_train = np.concatenate([s["labels"] for s in aligned_train], axis=0)
        X_test = aligned_test["trials"]
        y_test = aligned_test["labels"]

        # CSP spatial filters
        W = _csp_filters(X_train[y_train == 0], X_train[y_train == 1], n_csp)
        feat_train = _csp_features(X_train, W)
        feat_test = _csp_features(X_test, W)

        # LDA classification
        clf = LinearDiscriminantAnalysis()
        clf.fit(feat_train, y_train)
        preds = clf.predict(feat_test)

        accuracies.append(float(np.mean(preds == y_test)))
        predictions.append(preds)

    return {
        "accuracies": accuracies,
        "mean_accuracy": float(np.mean(accuracies)),
        "predictions": predictions,
    }
'''

import pathlib

# Write the implementation
pathlib.Path("/app/pipeline.py").write_text(IMPLEMENTATION)
print("pipeline.py written to /app/pipeline.py")

# Smoke test
import sys
sys.path.insert(0, "/app")
import importlib
if "pipeline" in sys.modules:
    del sys.modules["pipeline"]
import pipeline
import json

with open("/app/config.json") as f:
    cfg = json.load(f)

results = pipeline.decode(cfg["dataset"])
print(f"Mean accuracy: {results['mean_accuracy']:.4f}")
for i, acc in enumerate(results["accuracies"]):
    print(f"  Subject {i}: {acc:.4f}")
