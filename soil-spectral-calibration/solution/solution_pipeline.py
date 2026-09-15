#!/usr/bin/env python3
"""Reference solution: soil vis-NIR spectral calibration pipeline."""

import csv
import json
import os
import subprocess
import sys

import numpy as np
from scipy.signal import savgol_filter
from scipy.spatial.distance import cdist
from sklearn.cross_decomposition import PLSRegression
from sklearn.model_selection import KFold


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_config(path="/app/config.json"):
    with open(path) as f:
        return json.load(f)


def load_data(data_dir="/app/data"):
    spectra = np.loadtxt(
        os.path.join(data_dir, "spectra.csv"), delimiter=","
    )
    wavelengths = np.loadtxt(
        os.path.join(data_dir, "wavelengths.csv"), delimiter=","
    ).ravel()
    oc = []
    with open(os.path.join(data_dir, "properties.csv")) as f:
        reader = csv.DictReader(f)
        for row in reader:
            oc.append(float(row["OC"]))
    return spectra, wavelengths, np.array(oc)


# ---------------------------------------------------------------------------
# Preprocessing helpers
# ---------------------------------------------------------------------------

def trim_wavelengths(spectra, wavelengths, wl_range):
    mask = (wavelengths >= wl_range[0]) & (wavelengths <= wl_range[1])
    return spectra[:, mask], wavelengths[mask]


def compute_splice_offsets(spectra, wavelengths, splice_wl, n_bands):
    """Compute per-sample splice offset magnitudes."""
    si_mask = wavelengths <= splice_wl
    pbs_mask = wavelengths > splice_wl
    si_idx = np.where(si_mask)[0][-n_bands:]
    pbs_idx = np.where(pbs_mask)[0][:n_bands]
    offsets = np.zeros(spectra.shape[0])
    for i in range(spectra.shape[0]):
        offsets[i] = np.median(spectra[i, pbs_idx]) - np.median(spectra[i, si_idx])
    return offsets


def splice_correction(spectra, wavelengths, splice_wl, n_bands):
    corrected = spectra.copy()
    si_mask = wavelengths <= splice_wl
    pbs_mask = wavelengths > splice_wl
    si_idx = np.where(si_mask)[0][-n_bands:]
    pbs_idx = np.where(pbs_mask)[0][:n_bands]
    for i in range(spectra.shape[0]):
        offset = np.median(spectra[i, pbs_idx]) - np.median(spectra[i, si_idx])
        corrected[i, pbs_mask] -= offset
    return corrected


def apply_sg(spectra, window_length, polyorder, deriv):
    return savgol_filter(spectra, window_length, polyorder, deriv=deriv, axis=1)


def apply_snv(spectra):
    means = spectra.mean(axis=1, keepdims=True)
    stds = spectra.std(axis=1, keepdims=True, ddof=0)
    return (spectra - means) / stds


def decimate(spectra, step):
    return spectra[:, ::step]


# ---------------------------------------------------------------------------
# Continuum removal (upper convex hull)
# ---------------------------------------------------------------------------

def upper_convex_hull(x, y):
    hull = []
    for i in range(len(x)):
        while len(hull) >= 2:
            p0x, p0y = hull[-2]
            p1x, p1y = hull[-1]
            cross = (p1x - p0x) * (y[i] - p0y) - (p1y - p0y) * (x[i] - p0x)
            if cross >= 0:
                hull.pop()
            else:
                break
        hull.append((x[i], y[i]))
    return np.array(hull)


def continuum_removal(spectra, wavelengths):
    n_samples = spectra.shape[0]
    cr = np.zeros_like(spectra)
    for i in range(n_samples):
        hull = upper_convex_hull(wavelengths, spectra[i])
        continuum = np.interp(wavelengths, hull[:, 0], hull[:, 1])
        cr[i] = spectra[i] / np.maximum(continuum, 1e-10)
    return cr


# ---------------------------------------------------------------------------
# PCA
# ---------------------------------------------------------------------------

def pca_transform(X, variance_threshold):
    X_c = X - X.mean(axis=0)
    U, S, _ = np.linalg.svd(X_c, full_matrices=False)
    ev = S ** 2
    cumvar = np.cumsum(ev) / np.sum(ev)
    n_comp = int(np.searchsorted(cumvar, variance_threshold)) + 1
    return U[:, :n_comp] * S[:n_comp]


def standardize(X):
    return (X - X.mean(axis=0)) / X.std(axis=0, ddof=0)


# ---------------------------------------------------------------------------
# Kennard-Stone
# ---------------------------------------------------------------------------

def kennard_stone(X, n_train):
    n = X.shape[0]
    D = cdist(X, X, "euclidean")
    flat = int(np.argmax(D))
    i, j = divmod(flat, n)
    selected = [i, j]
    min_dist = np.minimum(D[i], D[j])
    min_dist[i] = -1.0
    min_dist[j] = -1.0
    while len(selected) < n_train:
        nxt = int(np.argmax(min_dist))
        selected.append(nxt)
        min_dist = np.minimum(min_dist, D[nxt])
        min_dist[nxt] = -1.0
    return selected


# ---------------------------------------------------------------------------
# PLS with cross-validation
# ---------------------------------------------------------------------------

def pls_cv(X_train, y_train, max_components, n_folds, seed):
    max_comp = min(
        max_components,
        X_train.shape[0] - X_train.shape[0] // n_folds,
        X_train.shape[1],
    )
    kf = KFold(n_splits=n_folds, shuffle=True, random_state=seed)
    best_n = 1
    best_rmsecv = np.inf
    cv_curve = []
    for n_comp in range(1, max_comp + 1):
        mse_list = []
        for tr, va in kf.split(X_train):
            pls = PLSRegression(n_components=n_comp, scale=False)
            pls.fit(X_train[tr], y_train[tr])
            pred = pls.predict(X_train[va]).ravel()
            mse_list.extend((pred - y_train[va]) ** 2)
        rmsecv = float(np.sqrt(np.mean(mse_list)))
        cv_curve.append({"n_components": n_comp, "rmsecv": rmsecv})
        if rmsecv < best_rmsecv:
            best_rmsecv = rmsecv
            best_n = n_comp
    return best_n, cv_curve


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def compute_metrics(y_obs, y_pred):
    residuals = y_pred - y_obs
    bias = float(np.mean(residuals))
    rmsep = float(np.sqrt(np.mean(residuals ** 2)))
    sep_b = float(np.std(residuals, ddof=0))
    sd_obs = float(np.std(y_obs, ddof=1))
    rpd = sd_obs / rmsep if rmsep > 0 else 0.0
    ss_res = float(np.sum(residuals ** 2))
    ss_tot = float(np.sum((y_obs - np.mean(y_obs)) ** 2))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return {
        "rmsep": rmsep,
        "rpd": rpd,
        "bias": bias,
        "sep_b": sep_b,
        "r_squared": r_squared,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    cfg = load_config()

    # Ensure data exists
    if not os.path.exists("/app/data/spectra.csv"):
        subprocess.run([sys.executable, "/app/generate_data.py"], check=True)

    spectra, wavelengths, oc = load_data()

    # Common: trim + splice correction
    spec_trim, wl_trim = trim_wavelengths(
        spectra, wavelengths, cfg["wavelength_trim"]
    )

    # Diagnostics: characterize the splice discontinuity
    splice_offsets = compute_splice_offsets(
        spec_trim, wl_trim, cfg["splice_wavelength"], cfg["splice_n_bands"]
    )
    abs_offsets = np.abs(splice_offsets)
    mean_offset = float(np.mean(abs_offsets))
    std_offset = float(np.std(abs_offsets, ddof=0))
    outlier_threshold = mean_offset + 2.0 * std_offset
    outlier_indices = sorted(
        int(i) for i in range(len(abs_offsets)) if abs_offsets[i] > outlier_threshold
    )

    spec_splice = splice_correction(
        spec_trim, wl_trim, cfg["splice_wavelength"], cfg["splice_n_bands"]
    )

    # Branch A: SG -> SNV -> decimate
    sg_cfg = cfg["savitzky_golay"]
    spec_sg = apply_sg(
        spec_splice, sg_cfg["window_length"], sg_cfg["polyorder"], sg_cfg["deriv"]
    )
    spec_snv = apply_snv(spec_sg)
    step = int(cfg["resample_interval_nm"] / cfg["original_spacing_nm"])
    preprocessed = decimate(spec_snv, step)

    # Branch B: reflectance -> continuum removal -> PCA -> standardize -> KS
    reflectance = np.power(10.0, -spec_splice)
    cr = continuum_removal(reflectance, wl_trim)

    ks_cfg = cfg["kennard_stone"]
    scores = pca_transform(cr, ks_cfg["pca_variance_threshold"])
    scores_std = standardize(scores)

    n_train = int(round(spectra.shape[0] * ks_cfg["train_fraction"]))
    train_raw = kennard_stone(scores_std, n_train)
    train_indices = sorted(train_raw)
    test_indices = sorted(set(range(spectra.shape[0])) - set(train_indices))

    # PLS calibration
    pls_cfg = cfg["pls"]
    X_tr = preprocessed[train_indices]
    y_tr = oc[train_indices]
    X_te = preprocessed[test_indices]
    y_te = oc[test_indices]

    n_components, cv_curve = pls_cv(
        X_tr, y_tr, pls_cfg["max_components"],
        pls_cfg["cv_folds"], pls_cfg["cv_seed"],
    )
    pls = PLSRegression(n_components=n_components, scale=False)
    pls.fit(X_tr, y_tr)
    y_pred = pls.predict(X_te).ravel()

    # Metrics
    metrics = compute_metrics(y_te, y_pred)
    metrics["n_components"] = n_components

    # Write outputs
    out = "/app/output"
    os.makedirs(out, exist_ok=True)

    # Diagnostics
    diagnostics = {
        "splice_location_nm": float(cfg["splice_wavelength"]),
        "mean_splice_offset": mean_offset,
        "n_bands_processed": int(preprocessed.shape[1]),
        "outlier_indices": outlier_indices,
    }
    with open(os.path.join(out, "diagnostics.json"), "w") as f:
        json.dump(diagnostics, f, indent=2)

    np.savetxt(
        os.path.join(out, "preprocessed.csv"),
        preprocessed, delimiter=",", fmt="%.10f",
    )
    with open(os.path.join(out, "train_indices.json"), "w") as f:
        json.dump(train_indices, f)
    with open(os.path.join(out, "test_indices.json"), "w") as f:
        json.dump(test_indices, f)
    with open(os.path.join(out, "predictions.csv"), "w") as f:
        f.write("sample_id,observed,predicted\n")
        for idx, obs, pred in zip(test_indices, y_te, y_pred):
            f.write(f"{idx},{obs:.4f},{pred:.4f}\n")
    with open(os.path.join(out, "metrics.json"), "w") as f:
        json.dump(metrics, f, indent=2)
    with open(os.path.join(out, "cv_curve.json"), "w") as f:
        json.dump(cv_curve, f, indent=2)


if __name__ == "__main__":
    main()
