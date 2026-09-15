#!/usr/bin/env python3
"""Generate synthetic multi-spectral satellite imagery with binary calibration
files and multi-class ground truth labels for land cover classification.

This script runs during Docker build and is then discarded (multi-stage build).
"""
import os
import struct
import csv
import numpy as np
from PIL import Image

SEED = 2024
NUM_CHIPS = 12
IMAGE_SIZE = 512
BANDS = ["B02", "B03", "B04", "B08"]

FEATURE_DIR = "/app/data/test_features"
LABEL_DIR = "/app/data/test_labels"
CAL_DIR = "/app/data/calibration"
METADATA_PATH = "/app/data/metadata.csv"

# Base per-band radiometric calibration coefficients
# Formula: TOA_reflectance = gain * DN + offset
BASE_CAL = {
    "B02": (1.22, -18.5),
    "B03": (1.15, -12.3),
    "B04": (1.28, -22.7),
    "B08": (1.08, -4.2),
}

# Per-class TOA reflectance ranges (lo, hi inclusive)
CLASS_PROFILES = {
    0: {"B02": (85, 125), "B03": (90, 130), "B04": (95, 135), "B08": (100, 145)},
    1: {"B02": (25, 55),  "B03": (35, 65),  "B04": (20, 50),  "B08": (155, 215)},
    2: {"B02": (15, 45),  "B03": (25, 55),  "B04": (10, 35),  "B08": (5, 30)},
    3: {"B02": (200, 250), "B03": (195, 245), "B04": (190, 240), "B08": (185, 235)},
}

# Classification thresholds (hierarchical, applied in order)
BRIGHTNESS_THRESH = 167.5
NDWI_THRESH = 0.22
NDVI_THRESH = 0.38


def perturb_cal(base_cal, rng):
    """Generate per-chip calibration with random perturbation."""
    perturbed = {}
    for band, (gain, offset) in base_cal.items():
        g = gain * (1.0 + rng.uniform(-0.06, 0.06))
        o = offset + rng.uniform(-1.5, 1.5)
        perturbed[band] = (round(g, 5), round(o, 3))
    return perturbed


def write_cal_file(path, coeffs):
    """Write binary calibration file in SCAL format (little-endian)."""
    with open(path, 'wb') as f:
        f.write(b'SCAL')
        f.write(struct.pack('<H', 1))
        f.write(struct.pack('<H', len(coeffs)))
        for band_name, (gain, offset) in coeffs.items():
            name_bytes = band_name.encode('ascii').ljust(16, b'\x00')
            f.write(name_bytes)
            f.write(struct.pack('<d', gain))
            f.write(struct.pack('<d', offset))


def generate_class_regions(rng, size):
    """Generate spatial class regions using overlapping elliptical blobs."""
    class_map = np.zeros((size, size), dtype=np.uint8)

    for _ in range(rng.integers(3, 8)):
        cx, cy = rng.integers(30, size - 30, size=2)
        rx, ry = rng.integers(30, 130, size=2)
        Y, X = np.ogrid[:size, :size]
        mask = ((X - cx).astype(float) / rx) ** 2 + \
               ((Y - cy).astype(float) / ry) ** 2 <= 1.0
        class_map[mask] = 1

    for _ in range(rng.integers(1, 4)):
        cx, cy = rng.integers(50, size - 50, size=2)
        rx, ry = rng.integers(20, 90, size=2)
        Y, X = np.ogrid[:size, :size]
        mask = ((X - cx).astype(float) / rx) ** 2 + \
               ((Y - cy).astype(float) / ry) ** 2 <= 1.0
        class_map[mask] = 2

    for _ in range(rng.integers(1, 5)):
        cx, cy = rng.integers(40, size - 40, size=2)
        rx, ry = rng.integers(40, 150, size=2)
        Y, X = np.ogrid[:size, :size]
        mask = ((X - cx).astype(float) / rx) ** 2 + \
               ((Y - cy).astype(float) / ry) ** 2 <= 1.0
        class_map[mask] = 3

    return class_map


def generate_chip(rng, cal_coeffs):
    """Generate one chip: raw DN bands + ground truth labels."""
    spatial_classes = generate_class_regions(rng, IMAGE_SIZE)

    toa_bands = {}
    for band_name in BANDS:
        band = np.zeros((IMAGE_SIZE, IMAGE_SIZE), dtype=float)
        for cls in range(4):
            mask = spatial_classes == cls
            n = mask.sum()
            if n > 0:
                lo, hi = CLASS_PROFILES[cls][band_name]
                band[mask] = rng.integers(lo, hi + 1, size=n).astype(float)
        toa_bands[band_name] = band

    # Ground truth labels from spectral indices on TOA reflectance
    b02, b03 = toa_bands["B02"], toa_bands["B03"]
    b04, b08 = toa_bands["B04"], toa_bands["B08"]

    eps = 1e-10
    ndvi = (b08 - b04) / (b08 + b04 + eps)
    ndwi = (b03 - b08) / (b03 + b08 + eps)
    brightness = (b02 + b03 + b04 + b08) / 4.0

    labels = np.zeros((IMAGE_SIZE, IMAGE_SIZE), dtype=np.uint8)
    labels[brightness > BRIGHTNESS_THRESH] = 3
    labels[(ndwi > NDWI_THRESH) & (labels == 0)] = 2
    labels[(ndvi > NDVI_THRESH) & (labels == 0)] = 1

    # Convert TOA to raw DN via per-chip inverse calibration
    dn_bands = {}
    for band_name in BANDS:
        gain, offset = cal_coeffs[band_name]
        dn = (toa_bands[band_name] - offset) / gain
        dn_bands[band_name] = np.clip(dn, 0, 255).astype(np.uint8)

    return dn_bands, labels


def main():
    rng = np.random.default_rng(SEED)

    os.makedirs(FEATURE_DIR, exist_ok=True)
    os.makedirs(LABEL_DIR, exist_ok=True)
    os.makedirs(CAL_DIR, exist_ok=True)

    chip_ids = []
    for i in range(NUM_CHIPS):
        chip_id = "chip_{:05d}".format(rng.integers(10000, 99999))
        chip_ids.append(chip_id)

        chip_cal = perturb_cal(BASE_CAL, rng)

        chip_dir = os.path.join(FEATURE_DIR, chip_id)
        os.makedirs(chip_dir, exist_ok=True)

        dn_bands, labels = generate_chip(rng, chip_cal)

        for band_name, band_data in dn_bands.items():
            Image.fromarray(band_data).save(
                os.path.join(chip_dir, "{}.tif".format(band_name)))

        Image.fromarray(labels).save(
            os.path.join(LABEL_DIR, "{}.tif".format(chip_id)))

        write_cal_file(
            os.path.join(CAL_DIR, "{}.cal".format(chip_id)), chip_cal)

    with open(METADATA_PATH, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["chip_id", "datetime", "sensor", "n_classes"])
        for i, cid in enumerate(chip_ids):
            writer.writerow([
                cid,
                "2024-06-{:02d}T10:30:00Z".format(i + 1),
                "S2A",
                4,
            ])

    print("Generated {} chips at {}".format(NUM_CHIPS, FEATURE_DIR))


if __name__ == "__main__":
    main()
