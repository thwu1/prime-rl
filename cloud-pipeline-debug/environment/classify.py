#!/usr/bin/env python3
"""Land cover classification from calibrated multi-spectral imagery.

Reads calibrated TOA reflectance arrays from /app/calibrated/ and
produces per-pixel land cover classification maps.

Target classes:
    0 - bare soil
    1 - vegetation
    2 - water
    3 - cloud

Output: single-band uint8 TIF images with pixel values in {0, 1, 2, 3},
written to /app/output/predictions/.
"""
import os
from pathlib import Path

import numpy as np
from PIL import Image

CALIBRATED_DIR = Path("/app/calibrated")
OUTPUT_DIR = Path("/app/output/predictions")
BANDS = ["B02", "B03", "B04", "B08"]


def load_calibrated_bands(chip_dir):
    """Load all calibrated band arrays for a chip."""
    bands = {}
    for band_name in BANDS:
        npy_path = chip_dir / "{}.npy".format(band_name)
        if npy_path.exists():
            bands[band_name] = np.load(str(npy_path))
        else:
            raise FileNotFoundError(
                "Missing calibrated band: {}".format(npy_path))
    return bands


def classify_chip(bands):
    """Classify a chip into land cover classes.

    TODO: Implement classification logic using spectral indices computed
    from the calibrated band reflectance values. Analyze the relationship
    between calibrated band values and ground truth labels in
    /app/data/test_labels/ to determine appropriate spectral indices
    and decision thresholds.

    Available bands: B02 (blue), B03 (green), B04 (red), B08 (NIR)
    """
    sample = next(iter(bands.values()))
    return np.zeros(sample.shape, dtype=np.uint8)


def main():
    if not CALIBRATED_DIR.exists():
        print("ERROR: Calibrated data not found: {}".format(CALIBRATED_DIR))
        raise SystemExit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    chips = sorted(d for d in CALIBRATED_DIR.iterdir() if d.is_dir())
    if not chips:
        print("ERROR: No calibrated data in {}".format(CALIBRATED_DIR))
        raise SystemExit(1)

    print("Classifying {} chips...".format(len(chips)))

    for chip_dir in chips:
        bands = load_calibrated_bands(chip_dir)
        prediction = classify_chip(bands)
        out_path = OUTPUT_DIR / "{}.tif".format(chip_dir.name)
        Image.fromarray(prediction).save(str(out_path))
        print("  Classified: {}".format(chip_dir.name))

    print("Classification complete.")


if __name__ == "__main__":
    main()
