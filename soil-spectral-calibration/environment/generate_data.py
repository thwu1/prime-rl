#!/usr/bin/env python3
"""Generate synthetic soil vis-NIR spectral data for calibration pipeline task."""

import numpy as np
import os


def gaussian(x, center, fwhm, depth):
    """Gaussian absorption feature parameterized by center, FWHM, and depth."""
    sigma = fwhm / (2.0 * np.sqrt(2.0 * np.log(2.0)))
    return depth * np.exp(-0.5 * ((x - center) / sigma) ** 2)


def generate_data(seed=42, n_samples=200, output_dir="/app/data"):
    rng = np.random.RandomState(seed)

    # Wavelength grid: 400-2500 nm at 0.5 nm spacing (4201 bands)
    wavelengths = np.arange(800, 5001) / 2.0
    n_bands = len(wavelengths)
    wl_norm = (wavelengths - 1450.0) / 1000.0

    # Soil properties with realistic correlations via Cholesky
    n = n_samples
    z = rng.randn(n, 4)
    L = np.array([
        [1.0,   0.0,   0.0,   0.0],
        [0.3,   0.954, 0.0,   0.0],
        [-0.4, -0.3,   0.866, 0.0],
        [0.1,   0.2,  -0.1,   0.966],
    ])
    corr_z = z @ L.T

    OC = np.exp(2.0 + 0.8 * corr_z[:, 0])
    OC = np.clip(OC, 1.5, 150.0)
    clay = 5.0 + 45.0 * (0.5 + 0.5 * np.tanh(corr_z[:, 1] * 0.8))
    sand = 5.0 + 75.0 * (0.5 + 0.5 * np.tanh(corr_z[:, 2] * 0.8))
    pH = 5.0 + 2.5 * (0.5 + 0.5 * np.tanh(corr_z[:, 3] * 0.8))

    total = sand + clay
    mask = total > 95.0
    sand[mask] = sand[mask] * 95.0 / total[mask]
    clay[mask] = clay[mask] * 95.0 / total[mask]

    # Indices that get anomalously large splice offsets
    outlier_set = {15, 42, 88, 127, 163}
    outlier_offsets = {15: 0.085, 42: 0.110, 88: 0.078, 127: 0.095, 163: 0.120}

    spectra = np.zeros((n_samples, n_bands))

    for i in range(n_samples):
        bg_level = 0.25 + rng.uniform(-0.05, 0.05)
        bg_slope = 0.08 + rng.uniform(-0.02, 0.02)
        bg_curve = 0.03 + rng.uniform(-0.01, 0.01)
        background = bg_level + bg_slope * wl_norm + bg_curve * wl_norm ** 2

        scatter_mult = 1.0 + rng.uniform(-0.2, 0.2)
        scatter_slope = rng.uniform(-0.08, 0.08)
        scatter = scatter_mult + scatter_slope * wl_norm

        oc_feat = gaussian(wavelengths, 620, 180, OC[i] * 0.0025)
        oc_feat2 = gaussian(wavelengths, 530, 80, OC[i] * 0.001)

        clay_1415 = gaussian(wavelengths, 1415, 30, clay[i] * 0.0018)
        clay_1915 = gaussian(wavelengths, 1915, 45, clay[i] * 0.0025)
        clay_2207 = gaussian(wavelengths, 2207, 25, clay[i] * 0.0022)

        water_1455 = gaussian(wavelengths, 1455, 35, 0.06 + rng.uniform(-0.02, 0.02))
        water_1915 = gaussian(wavelengths, 1915, 50, 0.10 + rng.uniform(-0.03, 0.03))

        caco3_depth = rng.exponential(0.015)
        caco3 = gaussian(wavelengths, 2340, 30, caco3_depth)

        fe_540 = gaussian(wavelengths, 540, 60, rng.exponential(0.02))
        fe_900 = gaussian(wavelengths, 900, 100, rng.exponential(0.015))

        total_abs = (background + oc_feat + oc_feat2 + clay_1415 + clay_1915
                     + clay_2207 + water_1455 + water_1915 + caco3
                     + fe_540 + fe_900)
        spectrum = total_abs * scatter

        # Normal splice offset (always consume rng state for reproducibility)
        splice_offset = rng.uniform(0.015, 0.045)
        # Override for outlier samples
        if i in outlier_set:
            splice_offset = outlier_offsets[i]

        splice_mask = wavelengths > 1100.0
        spectrum[splice_mask] += splice_offset

        spectrum += rng.normal(0, 0.0008, n_bands)
        spectrum = np.maximum(spectrum, 0.001)

        spectra[i] = spectrum

    os.makedirs(output_dir, exist_ok=True)
    np.savetxt(os.path.join(output_dir, "spectra.csv"), spectra,
               delimiter=",", fmt="%.6f")
    np.savetxt(os.path.join(output_dir, "wavelengths.csv"), wavelengths,
               fmt="%.1f")

    with open(os.path.join(output_dir, "properties.csv"), "w") as f:
        f.write("sample_id,OC,clay,sand,pH\n")
        for idx in range(n_samples):
            f.write(f"{idx},{OC[idx]:.4f},{clay[idx]:.4f},"
                    f"{sand[idx]:.4f},{pH[idx]:.4f}\n")


if __name__ == "__main__":
    generate_data()
