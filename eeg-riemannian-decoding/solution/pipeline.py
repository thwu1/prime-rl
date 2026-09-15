
"""
Cross-subject EEG decoding pipeline using Riemannian geometry on the SPD manifold.

Implements bandpass filtering, spatial covariance estimation, Frechet mean,
tangent space projection, re-centering domain adaptation, and LOSO-CV
classification for motor imagery BCI.
"""

import numpy as np
from scipy import signal as sp_signal
from scipy import linalg as la
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
import json
import os


def bandpass_filter(data, low, high, sfreq, order=5):
    """Apply Butterworth bandpass filter along the last (time) axis.

    Parameters
    ----------
    data : ndarray, shape (..., n_samples)
    low, high : float  — cutoff frequencies in Hz
    sfreq : float — sampling frequency in Hz
    order : int — filter order

    Returns
    -------
    filtered : ndarray, same shape as data
    """
    nyq = sfreq / 2.0
    b, a = sp_signal.butter(order, [low / nyq, high / nyq], btype='band')
    return sp_signal.filtfilt(b, a, data, axis=-1)


def compute_covariance(trials):
    """Compute regularised spatial covariance matrices.

    Parameters
    ----------
    trials : ndarray, shape (n_trials, n_channels, n_samples)

    Returns
    -------
    covs : ndarray, shape (n_trials, n_channels, n_channels) — SPD matrices
    """
    n_trials, n_ch, n_samp = trials.shape
    covs = np.zeros((n_trials, n_ch, n_ch))
    for i in range(n_trials):
        X = trials[i]
        X = X - X.mean(axis=1, keepdims=True)
        C = X @ X.T / (n_samp - 1)
        # Ledoit-Wolf-style shrinkage toward scaled identity
        trace_C = np.trace(C)
        C = 0.95 * C + 0.05 * (trace_C / n_ch) * np.eye(n_ch)
        covs[i] = C
    return covs


def _matrix_pow(C, power):
    """Matrix power for a symmetric (SPD) matrix via eigendecomposition."""
    eigvals, eigvecs = la.eigh(C)
    eigvals = np.maximum(eigvals, 1e-12)
    return eigvecs @ np.diag(eigvals ** power) @ eigvecs.T


def log_map(S, P):
    """Riemannian logarithmic map at base point P applied to S.

    log_P(S) = P^{1/2} logm(P^{-1/2} S P^{-1/2}) P^{1/2}

    Parameters
    ----------
    S : ndarray, shape (n, n) — SPD matrix (point on manifold)
    P : ndarray, shape (n, n) — SPD matrix (base point)

    Returns
    -------
    V : ndarray, shape (n, n) — symmetric tangent vector at P
    """
    P_sqrt = _matrix_pow(P, 0.5)
    P_isqrt = _matrix_pow(P, -0.5)
    inner = P_isqrt @ S @ P_isqrt
    # Matrix log of SPD matrix via eigendecomposition
    eigvals, eigvecs = la.eigh(inner)
    eigvals = np.maximum(eigvals, 1e-12)
    log_inner = eigvecs @ np.diag(np.log(eigvals)) @ eigvecs.T
    return P_sqrt @ log_inner @ P_sqrt


def exp_map(V, P):
    """Riemannian exponential map at base point P applied to tangent vector V.

    exp_P(V) = P^{1/2} expm(P^{-1/2} V P^{-1/2}) P^{1/2}

    Parameters
    ----------
    V : ndarray, shape (n, n) — symmetric tangent vector
    P : ndarray, shape (n, n) — SPD base point

    Returns
    -------
    S : ndarray, shape (n, n) — SPD matrix
    """
    P_sqrt = _matrix_pow(P, 0.5)
    P_isqrt = _matrix_pow(P, -0.5)
    inner = P_isqrt @ V @ P_isqrt
    eigvals, eigvecs = la.eigh(inner)
    exp_inner = eigvecs @ np.diag(np.exp(eigvals)) @ eigvecs.T
    return P_sqrt @ exp_inner @ P_sqrt


def spd_mean(covs, tol=1e-8, max_iter=100):
    """Compute the Frechet (Karcher) mean of SPD matrices.

    Uses the iterative fixed-point algorithm:
        M_{k+1} = exp_{M_k}( (1/N) sum_i log_{M_k}(S_i) )

    Parameters
    ----------
    covs : ndarray, shape (N, n, n) — SPD matrices
    tol : float — convergence tolerance on Frobenius norm
    max_iter : int — maximum iterations

    Returns
    -------
    mean : ndarray, shape (n, n) — SPD Frechet mean
    """
    n_mats = len(covs)
    # Initialise with arithmetic mean, regularised to be SPD
    mean = np.mean(covs, axis=0)
    eigvals, eigvecs = la.eigh(mean)
    eigvals = np.maximum(eigvals, 1e-10)
    mean = eigvecs @ np.diag(eigvals) @ eigvecs.T

    for _ in range(max_iter):
        S = np.zeros_like(mean)
        for i in range(n_mats):
            S += log_map(covs[i], mean)
        S /= n_mats

        norm = la.norm(S, 'fro')
        if norm < tol:
            break

        mean = exp_map(S, mean)
        mean = (mean + mean.T) / 2  # enforce symmetry

    return mean


def tangent_vectors(covs, ref):
    """Project SPD matrices to tangent space at reference point.

    Vectorises the upper triangle of each log map with sqrt(2) scaling
    on off-diagonal elements.

    Parameters
    ----------
    covs : ndarray, shape (N, n, n)
    ref  : ndarray, shape (n, n) — reference SPD point

    Returns
    -------
    vecs : ndarray, shape (N, n*(n+1)//2)
    """
    n_mats = len(covs)
    n = covs.shape[1]
    vec_dim = n * (n + 1) // 2
    vecs = np.zeros((n_mats, vec_dim))

    for i in range(n_mats):
        L = log_map(covs[i], ref)
        idx = 0
        for r in range(n):
            for c in range(r, n):
                if r == c:
                    vecs[i, idx] = L[r, c]
                else:
                    vecs[i, idx] = L[r, c] * np.sqrt(2)
                idx += 1

    return vecs


def recenter(covs, mean_source, mean_target):
    """Re-center covariances from source mean to target mean via parallel transport.

    T = M_target^{1/2} @ M_source^{-1/2}
    recentered_i = T @ covs_i @ T^T

    Parameters
    ----------
    covs : ndarray, shape (N, n, n) — source SPD matrices
    mean_source : ndarray, shape (n, n) — SPD mean of source distribution
    mean_target : ndarray, shape (n, n) — SPD mean of target distribution

    Returns
    -------
    recentered : ndarray, shape (N, n, n) — transported SPD matrices
    """
    M_s_isqrt = _matrix_pow(mean_source, -0.5)
    M_t_sqrt = _matrix_pow(mean_target, 0.5)
    T = M_t_sqrt @ M_s_isqrt

    recentered = np.zeros_like(covs)
    for i in range(len(covs)):
        recentered[i] = T @ covs[i] @ T.T
    return recentered


def cross_subject_decode(data_dir='/app/data'):
    """Leave-one-subject-out cross-validation pipeline.

    For each target subject:
      1. Bandpass filter all data (8-30 Hz).
      2. Compute spatial covariance matrices.
      3. Re-center each source subject's covariances to the target mean.
      4. Compute global Riemannian mean, project to tangent space.
      5. Train LDA on source subjects, evaluate on target.

    Parameters
    ----------
    data_dir : str — path to directory with subject_XX.npz and metadata.npz

    Returns
    -------
    results : dict — with keys 'accuracies', 'mean_accuracy', 'n_subjects', 'method'
    """
    meta = np.load(os.path.join(data_dir, 'metadata.npz'), allow_pickle=True)
    n_subjects = int(meta['n_subjects'][0])
    sfreq = int(meta['sfreq'][0])

    # Load all subjects
    all_data = []
    all_labels = []
    for s in range(n_subjects):
        d = np.load(os.path.join(data_dir, 'subject_{:02d}.npz'.format(s)))
        all_data.append(d['data'])
        all_labels.append(d['labels'])

    results = {
        'accuracies': [],
        'mean_accuracy': 0.0,
        'n_subjects': n_subjects,
        'method': 'riemannian_tangent_space_with_recentering'
    }

    for target_subj in range(n_subjects):
        # Filter and compute covariances for target
        target_filtered = bandpass_filter(all_data[target_subj], 8, 30, sfreq)
        target_covs = compute_covariance(target_filtered)
        target_labels = all_labels[target_subj]
        target_mean = spd_mean(target_covs)

        # Process each source subject: filter, cov, recenter to target
        source_covs_list = []
        source_labels_list = []
        for s in range(n_subjects):
            if s == target_subj:
                continue
            src_filtered = bandpass_filter(all_data[s], 8, 30, sfreq)
            src_covs = compute_covariance(src_filtered)
            src_mean = spd_mean(src_covs)
            src_covs_rc = recenter(src_covs, src_mean, target_mean)
            source_covs_list.append(src_covs_rc)
            source_labels_list.append(all_labels[s])

        source_covs_all = np.concatenate(source_covs_list, axis=0)
        source_labels_all = np.concatenate(source_labels_list, axis=0)

        # Global reference point for tangent space
        all_covs = np.concatenate([source_covs_all, target_covs], axis=0)
        ref = spd_mean(all_covs)

        # Project to tangent space
        source_vecs = tangent_vectors(source_covs_all, ref)
        target_vecs = tangent_vectors(target_covs, ref)

        # Classify
        clf = LinearDiscriminantAnalysis(solver='lsqr', shrinkage='auto')
        clf.fit(source_vecs, source_labels_all)
        acc = clf.score(target_vecs, target_labels)
        results['accuracies'].append(float(acc))

        print('Subject {}: accuracy = {:.4f}'.format(target_subj, acc))

    results['mean_accuracy'] = float(np.mean(results['accuracies']))
    print('Mean accuracy: {:.4f}'.format(results['mean_accuracy']))

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    return results


if __name__ == '__main__':
    cross_subject_decode()
