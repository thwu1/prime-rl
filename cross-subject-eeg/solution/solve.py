#!/usr/bin/env python3
"""
Cross-subject EEG motor imagery decoding pipeline.

Implements:
1. Bandpass filtering (8-30 Hz) to isolate mu/beta motor imagery bands
2. Euclidean Alignment to normalize subject covariance structures
3. One-vs-Rest Common Spatial Patterns (CSP) for spatial feature extraction
4. Linear Discriminant Analysis for classification
"""

import numpy as np
from scipy.signal import butter, filtfilt
from scipy.linalg import sqrtm, inv, eigh
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
import json
import os


def load_data():
    with open('/app/data/metadata.json') as f:
        meta = json.load(f)

    subjects = {}
    for s in range(meta['n_subjects']):
        trials = np.load('/app/data/subject_{:02d}_trials.npy'.format(s))
        labels_path = '/app/data/subject_{:02d}_labels.npy'.format(s)
        labels = np.load(labels_path) if os.path.exists(labels_path) else None
        subjects[s] = {'trials': trials, 'labels': labels}

    return meta, subjects


def bandpass_filter(trials, fs, low=8.0, high=30.0, order=5):
    """Apply zero-phase Butterworth bandpass filter to isolate mu/beta bands."""
    nyq = fs / 2.0
    b, a = butter(order, [low / nyq, high / nyq], btype='band')
    filtered = np.zeros_like(trials)
    for i in range(trials.shape[0]):
        for ch in range(trials.shape[1]):
            filtered[i, ch] = filtfilt(b, a, trials[i, ch])
    return filtered


def euclidean_alignment(trials):
    """
    Euclidean Alignment (He & Wu, 2020): normalize each subject's data
    by whitening with the mean covariance matrix. This removes subject-specific
    spatial mixing, making spatial features transferable across subjects.
    """
    n_trials, n_ch, n_samples = trials.shape

    # Compute per-trial covariance matrices and their mean
    mean_cov = np.zeros((n_ch, n_ch))
    for i in range(n_trials):
        mean_cov += trials[i] @ trials[i].T / n_samples
    mean_cov /= n_trials

    # Regularize for numerical stability
    mean_cov += 1e-6 * np.eye(n_ch)

    # Compute whitening transform: R_bar^(-1/2)
    sqrt_cov = sqrtm(mean_cov)
    sqrt_cov = np.real(sqrt_cov)
    W = inv(sqrt_cov)

    # Apply whitening to all trials
    aligned = np.zeros_like(trials)
    for i in range(n_trials):
        aligned[i] = W @ trials[i]

    return aligned


def compute_csp(X_pos, X_neg, n_components=3):
    """
    Common Spatial Patterns: find spatial filters that maximize the
    variance ratio between two classes via generalized eigenvalue decomposition.

    Returns spatial filter matrix W of shape (2*n_components, n_channels).
    """
    n_ch = X_pos.shape[1]
    n_samples = X_pos.shape[2]

    # Class covariance matrices (average over trials)
    cov_pos = np.zeros((n_ch, n_ch))
    for trial in X_pos:
        cov_pos += trial @ trial.T / n_samples
    cov_pos /= len(X_pos)

    cov_neg = np.zeros((n_ch, n_ch))
    for trial in X_neg:
        cov_neg += trial @ trial.T / n_samples
    cov_neg /= len(X_neg)

    # Regularize
    reg = 1e-6 * np.eye(n_ch)
    cov_pos += reg
    cov_neg += reg

    # Generalized eigenvalue problem: cov_pos @ w = lam * (cov_pos + cov_neg) @ w
    eigenvalues, eigenvectors = eigh(cov_pos, cov_pos + cov_neg)

    # Sort by eigenvalue (descending)
    idx = np.argsort(eigenvalues)[::-1]
    eigenvectors = eigenvectors[:, idx]

    # Take top n_components (maximize class 1) and bottom n_components (maximize class 2)
    W = np.vstack([
        eigenvectors[:, :n_components].T,
        eigenvectors[:, -n_components:].T
    ])

    return W


def extract_csp_features(trials, W):
    """Extract log-variance features from CSP-projected signals."""
    features = np.zeros((len(trials), W.shape[0]))
    for i, trial in enumerate(trials):
        projected = W @ trial
        var = np.var(projected, axis=1)
        # Clip to avoid log(0)
        var = np.clip(var, 1e-10, None)
        features[i] = np.log(var)
    return features


def main():
    meta, subjects = load_data()
    fs = meta['fs']
    train_subjects = meta['train_subjects']
    test_subjects = meta['test_subjects']
    n_classes = meta['n_classes']

    # Step 1: Bandpass filter all subjects (8-30 Hz for mu + beta bands)
    print("Bandpass filtering...")
    for s in subjects:
        subjects[s]['trials'] = bandpass_filter(subjects[s]['trials'], fs)

    # Step 2: Euclidean Alignment per subject
    print("Euclidean alignment...")
    for s in subjects:
        subjects[s]['trials'] = euclidean_alignment(subjects[s]['trials'])

    # Step 3: Pool training data
    X_train = np.concatenate([subjects[s]['trials'] for s in train_subjects])
    y_train = np.concatenate([subjects[s]['labels'] for s in train_subjects])

    # Step 4: One-vs-Rest CSP feature extraction
    print("Computing CSP filters...")
    csp_filters = []
    for cls in range(n_classes):
        mask_pos = y_train == cls
        mask_neg = ~mask_pos
        W = compute_csp(X_train[mask_pos], X_train[mask_neg], n_components=3)
        csp_filters.append(W)

    W_combined = np.vstack(csp_filters)

    # Step 5: Extract features and train LDA
    print("Training classifier...")
    X_train_feat = extract_csp_features(X_train, W_combined)
    clf = LinearDiscriminantAnalysis(solver='lsqr', shrinkage='auto')
    clf.fit(X_train_feat, y_train)

    # Step 6: Predict on test subjects
    print("Evaluating test subjects...")
    results = {
        'overall_accuracy': 0.0,
        'subject_accuracies': {},
        'predictions': {}
    }

    all_correct = 0
    all_total = 0

    for s in test_subjects:
        X_test = subjects[s]['trials']
        X_test_feat = extract_csp_features(X_test, W_combined)
        y_pred = clf.predict(X_test_feat).astype(int)

        results['predictions'][str(s)] = y_pred.tolist()

        # If ground truth is available (for self-evaluation), compute accuracy
        if subjects[s]['labels'] is not None:
            y_true = subjects[s]['labels']
            acc = float(np.mean(y_pred == y_true))
            results['subject_accuracies'][str(s)] = acc
            all_correct += int(np.sum(y_pred == y_true))
            all_total += len(y_true)
        else:
            # No labels available; accuracy will be computed by the evaluator
            results['subject_accuracies'][str(s)] = -1.0
            all_total += len(y_pred)

    if all_total > 0 and all_correct > 0:
        results['overall_accuracy'] = float(all_correct / all_total)

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")
    print("Overall accuracy: {:.4f}".format(results['overall_accuracy']))
    for s_key, acc in sorted(results['subject_accuracies'].items()):
        print("  Subject {}: {:.4f}".format(s_key, acc))


if __name__ == '__main__':
    main()
