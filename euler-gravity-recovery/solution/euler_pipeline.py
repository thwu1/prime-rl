#!/usr/bin/env python3
"""
Gravity anomaly source recovery pipeline.

Reads survey data (TOML config + CSV measurements), identifies and locates
buried mass concentrations from their gravitational signatures.
"""

import csv
import os
import sys
import tomllib

import numpy as np
from scipy.cluster.hierarchy import fclusterdata


# ── 1. Data I/O ─────────────────────────────────────────────────────────

def read_gravity_data(csv_path, config_path):
    """Read gravity grid from CSV and survey parameters from TOML."""
    with open(config_path, 'rb') as f:
        config = tomllib.load(f)

    survey = config['survey']
    spacing = survey['grid_spacing_m']
    n_northings = survey['n_northings']
    n_eastings = survey['n_eastings']
    shape = (n_northings, n_eastings)
    region = survey['region']

    es, ns, gs = [], [], []
    with open(csv_path) as f:
        for row in csv.DictReader(f):
            es.append(float(row["easting"]))
            ns.append(float(row["northing"]))
            val = row["g_z"].strip()
            gs.append(float(val) if val else float('nan'))

    easting = np.array(es).reshape(shape)
    northing = np.array(ns).reshape(shape)
    g_z = np.array(gs).reshape(shape)

    # Handle any NaN values by interpolation from neighbours
    nan_mask = np.isnan(g_z)
    if nan_mask.any():
        from scipy.ndimage import generic_filter
        def nanmean_filter(values):
            valid = values[~np.isnan(values)]
            return np.mean(valid) if len(valid) > 0 else 0.0
        filled = generic_filter(g_z, nanmean_filter, size=3, mode='nearest')
        g_z[nan_mask] = filled[nan_mask]

    return easting, northing, g_z, spacing, region


def write_results(sources, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["easting", "northing", "upward"])
        w.writeheader()
        for s in sources:
            w.writerow({
                "easting":  f"{s['easting']:.1f}",
                "northing": f"{s['northing']:.1f}",
                "upward":   f"{s['upward']:.1f}",
            })


# ── 2. Regional trend removal ───────────────────────────────────────────

def remove_regional(easting, northing, g_z, order=2):
    """Fit and subtract a polynomial of given order from the gravity grid."""
    ef = easting.ravel()
    nf = northing.ravel()
    gf = g_z.ravel()

    cols = []
    for i in range(order + 1):
        for j in range(order + 1 - i):
            cols.append(ef ** i * nf ** j)
    A = np.column_stack(cols)

    coeffs, *_ = np.linalg.lstsq(A, gf, rcond=None)
    return (gf - A @ coeffs).reshape(g_z.shape)


# ── 3. FFT-based spatial derivatives ────────────────────────────────────

def fft_derivatives(grid, spacing):
    """
    Compute df/de, df/dn, df/du for a harmonic field.

    Uses the frequency-domain relationships:
        F{df/de} = i kx F{f}
        F{df/dn} = i ky F{f}
        F{df/du} = -|k| F{f}   (upward continuation derivative)
    """
    ny, nx = grid.shape
    pad_y, pad_x = ny // 4, nx // 4
    padded = np.pad(grid, ((pad_y, pad_y), (pad_x, pad_x)), mode="edge")
    npy, npx = padded.shape

    kx = np.fft.fftfreq(npx, d=spacing) * 2 * np.pi
    ky = np.fft.fftfreq(npy, d=spacing) * 2 * np.pi
    KX, KY = np.meshgrid(kx, ky)
    K = np.sqrt(KX ** 2 + KY ** 2)

    F = np.fft.fft2(padded)

    de = np.real(np.fft.ifft2(1j * KX * F))[pad_y:pad_y+ny, pad_x:pad_x+nx]
    dn = np.real(np.fft.ifft2(1j * KY * F))[pad_y:pad_y+ny, pad_x:pad_x+nx]
    du = np.real(np.fft.ifft2(-K * F))      [pad_y:pad_y+ny, pad_x:pad_x+nx]

    return de, dn, du


# ── 4. Moving-window Euler deconvolution ─────────────────────────────────

def euler_moving_window(easting, northing, field, de, dn, du,
                        si=2, win=15, step=3):
    """
    Apply Euler's homogeneity equation in a moving window to estimate
    source positions. The structural index (si) controls the assumed
    source geometry: si=2 for point masses in gravity data.
    """
    ny, nx = field.shape
    half = win // 2
    solutions = []

    for iy in range(half, ny - half, step):
        for ix in range(half, nx - half, step):
            sl = (slice(iy - half, iy + half + 1),
                  slice(ix - half, ix + half + 1))

            ew  = easting[sl].ravel()
            nw  = northing[sl].ravel()
            fw  = field[sl].ravel()
            dew = de[sl].ravel()
            dnw = dn[sl].ravel()
            duw = du[sl].ravel()

            if np.std(fw) < 0.05:
                continue

            nd = fw.size
            A = np.empty((nd, 4))
            A[:, 0] = dew
            A[:, 1] = dnw
            A[:, 2] = duw
            A[:, 3] = si

            b = ew * dew + nw * dnw + si * fw

            try:
                x, res, rank, sv = np.linalg.lstsq(A, b, rcond=None)
            except np.linalg.LinAlgError:
                continue

            e0, n0, u0, bl = x

            cond = sv[0] / sv[-1] if sv.size >= 2 and sv[-1] > 1e-15 else np.inf
            pred = A @ x
            rms  = np.sqrt(np.mean((b - pred) ** 2))

            solutions.append({
                "easting": e0,
                "northing": n0,
                "upward": u0,
                "cond": cond,
                "rms": rms,
            })

    return solutions


# ── 5. Solution filtering ───────────────────────────────────────────────

def filter_solutions(solutions, region):
    xmin, xmax, ymin, ymax = region
    if not solutions:
        return []

    margin = 5000
    valid = []
    for s in solutions:
        if s["upward"] >= 0 or s["upward"] < -25000:
            continue
        if not (xmin - margin <= s["easting"] <= xmax + margin):
            continue
        if not (ymin - margin <= s["northing"] <= ymax + margin):
            continue
        valid.append(s)

    if not valid:
        return []

    cond_ok = [s for s in valid if s["cond"] < 10000]
    if not cond_ok:
        cond_ok = [s for s in valid if s["cond"] < 50000]
    if not cond_ok:
        return []

    rms_vals = np.array([s["rms"] for s in cond_ok])
    threshold = np.percentile(rms_vals, 80)
    out = [s for s, r in zip(cond_ok, rms_vals) if r <= threshold]

    return out


# ── 6. Clustering ───────────────────────────────────────────────────────

def cluster_solutions(solutions, dist_thresh=15000, min_size=2):
    if len(solutions) < min_size:
        if len(solutions) >= 1:
            return [{"easting": s["easting"],
                     "northing": s["northing"],
                     "upward": s["upward"]} for s in solutions]
        return []

    horiz = np.array([[s["easting"], s["northing"]] for s in solutions])
    all_coords = np.array([[s["easting"], s["northing"], s["upward"]]
                            for s in solutions])

    labels = fclusterdata(horiz, t=dist_thresh,
                          criterion="distance", method="average")

    centroids = []
    for lab in np.unique(labels):
        mask = labels == lab
        if mask.sum() < min_size:
            continue
        cluster = all_coords[mask]
        med = np.median(cluster, axis=0)
        centroids.append({
            "easting":  med[0],
            "northing": med[1],
            "upward":   med[2],
        })
    return centroids


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    easting, northing, g_z, spacing, region = read_gravity_data(
        "/app/data/gravity_data.csv", "/app/data/survey_config.toml"
    )

    # Structural index = 2 is appropriate for point-mass sources in
    # vertical gravitational acceleration data
    si = 2

    residual = remove_regional(easting, northing, g_z, order=2)
    de, dn, du = fft_derivatives(residual, spacing)

    raw = euler_moving_window(easting, northing, residual, de, dn, du,
                              si=si, win=15, step=3)
    print(f"Raw Euler solutions: {len(raw)}")

    filt = filter_solutions(raw, region)
    print(f"After filtering:     {len(filt)}")

    sources = cluster_solutions(filt, dist_thresh=15000, min_size=2)
    print(f"Identified sources:  {len(sources)}")

    write_results(sources, "/app/results/sources.csv")
    print("Results written to /app/results/sources.csv")


if __name__ == "__main__":
    main()
