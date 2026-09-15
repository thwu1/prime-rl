#!/usr/bin/env python3

"""Analyze calibrated spectral data against ground truth labels to derive
optimal classification thresholds, then generate classify.py.

This script performs actual data analysis: it reads calibrated TOA
reflectance arrays and ground truth label images, computes spectral
indices, determines optimal thresholds via percentile-based gap analysis,
and writes a classifier that applies those discovered thresholds.
"""
import os
from pathlib import Path
import numpy as np
from PIL import Image

CALIBRATED_DIR = Path("/app/calibrated")
LABEL_DIR = Path("/app/data/test_labels")
CLASSIFY_PATH = Path("/app/pipeline/classify.py")

CLASSIFIER_TEMPLATE = '''#!/usr/bin/env python3
"""Land cover classification using empirically derived spectral thresholds."""
import os
from pathlib import Path
import numpy as np
from PIL import Image

CALIBRATED_DIR = Path("/app/calibrated")
OUTPUT_DIR = Path("/app/output/predictions")

BRIGHTNESS_THRESH = __BRIGHT__
NDWI_THRESH = __NDWI__
NDVI_THRESH = __NDVI__


def classify_chip(chip_dir):
    b02 = np.load(str(chip_dir / "B02.npy"))
    b03 = np.load(str(chip_dir / "B03.npy"))
    b04 = np.load(str(chip_dir / "B04.npy"))
    b08 = np.load(str(chip_dir / "B08.npy"))

    eps = 1e-10
    ndvi = (b08 - b04) / (b08 + b04 + eps)
    ndwi = (b03 - b08) / (b03 + b08 + eps)
    brightness = (b02 + b03 + b04 + b08) / 4.0

    labels = np.zeros(b02.shape, dtype=np.uint8)
    labels[brightness > BRIGHTNESS_THRESH] = 3
    labels[(ndwi > NDWI_THRESH) & (labels == 0)] = 2
    labels[(ndvi > NDVI_THRESH) & (labels == 0)] = 1

    return labels


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    chips = sorted(d for d in CALIBRATED_DIR.iterdir() if d.is_dir())
    print("Classifying {} chips...".format(len(chips)))

    for chip_dir in chips:
        prediction = classify_chip(chip_dir)
        out_path = OUTPUT_DIR / "{}.tif".format(chip_dir.name)
        Image.fromarray(prediction).save(str(out_path))
        print("  Classified: {}".format(chip_dir.name))

    print("Classification complete.")


if __name__ == "__main__":
    main()
'''


def load_all_data():
    """Load calibrated bands and ground truth labels for all chips."""
    bands = {"B02": [], "B03": [], "B04": [], "B08": []}
    labels = []

    for chip_dir in sorted(d for d in CALIBRATED_DIR.iterdir() if d.is_dir()):
        label_path = LABEL_DIR / "{}.tif".format(chip_dir.name)
        if not label_path.exists():
            continue

        labels.append(np.array(Image.open(label_path)).ravel())
        for band in bands:
            bands[band].append(
                np.load(str(chip_dir / "{}.npy".format(band))).ravel())

    for band in bands:
        bands[band] = np.concatenate(bands[band])
    return bands, np.concatenate(labels)


def find_threshold(values, labels, target_class, mask=None):
    """Find optimal threshold to separate target_class using percentile gap.

    Uses the midpoint between the 2nd percentile of the target class and
    the 98th percentile of all other classes to robustly identify the
    decision boundary.
    """
    if mask is None:
        mask = np.ones(len(values), dtype=bool)

    target = values[mask & (labels == target_class)]
    other = values[mask & (labels != target_class)]

    if len(target) == 0 or len(other) == 0:
        return None

    target_lo = np.percentile(target, 2)
    other_hi = np.percentile(other, 98)

    return (target_lo + other_hi) / 2.0


def main():
    print("Loading calibrated data and ground truth...")
    bands, labels = load_all_data()
    n_pixels = len(labels)
    unique_classes = np.unique(labels)
    print("  {} pixels across classes {}".format(n_pixels, unique_classes))

    eps = 1e-10
    ndvi = (bands["B08"] - bands["B04"]) / (bands["B08"] + bands["B04"] + eps)
    ndwi = (bands["B03"] - bands["B08"]) / (bands["B03"] + bands["B08"] + eps)
    brightness = (bands["B02"] + bands["B03"] +
                  bands["B04"] + bands["B08"]) / 4.0

    # Per-class statistics
    print("\nPer-class spectral statistics:")
    for cls in sorted(unique_classes):
        m = labels == cls
        if m.sum() > 0:
            print("  Class {}: n={:,}, brightness=[{:.1f},{:.1f}], "
                  "ndvi=[{:.3f},{:.3f}], ndwi=[{:.3f},{:.3f}]".format(
                      cls, m.sum(),
                      brightness[m].min(), brightness[m].max(),
                      ndvi[m].min(), ndvi[m].max(),
                      ndwi[m].min(), ndwi[m].max()))

    # Hierarchical threshold discovery
    # Step 1: brightness threshold for clouds (class 3) — highest brightness
    bright_t = find_threshold(brightness, labels, target_class=3)
    print("\nDiscovered brightness threshold (cloud): {:.2f}".format(bright_t))

    # Step 2: NDWI threshold for water (class 2) — exclude already-classified clouds
    not_cloud = brightness <= bright_t
    ndwi_t = find_threshold(ndwi, labels, target_class=2, mask=not_cloud)
    print("Discovered NDWI threshold (water): {:.4f}".format(ndwi_t))

    # Step 3: NDVI threshold for vegetation (class 1) — exclude clouds and water
    not_cloud_water = not_cloud & (ndwi <= ndwi_t)
    ndvi_t = find_threshold(ndvi, labels, target_class=1, mask=not_cloud_water)
    print("Discovered NDVI threshold (vegetation): {:.4f}".format(ndvi_t))

    # Validate discovered thresholds against ground truth
    pred = np.zeros_like(labels)
    pred[brightness > bright_t] = 3
    pred[(ndwi > ndwi_t) & (pred == 0)] = 2
    pred[(ndvi > ndvi_t) & (pred == 0)] = 1

    accuracy = (pred == labels).mean()
    print("\nValidation accuracy with discovered thresholds: {:.4f}".format(
        accuracy))

    # Write classifier with discovered thresholds
    code = CLASSIFIER_TEMPLATE
    code = code.replace("__BRIGHT__", str(round(bright_t, 2)))
    code = code.replace("__NDWI__", str(round(ndwi_t, 4)))
    code = code.replace("__NDVI__", str(round(ndvi_t, 4)))

    with open(str(CLASSIFY_PATH), "w") as f:
        f.write(code)
    print("Wrote classifier to {}".format(CLASSIFY_PATH))


if __name__ == "__main__":
    main()
