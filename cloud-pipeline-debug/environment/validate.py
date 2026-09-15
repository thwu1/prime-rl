#!/usr/bin/env python3
"""Validate prediction outputs for format compliance.

Checks that predictions exist for every input chip, have the correct
spatial dimensions, data type, and contain only valid class labels.
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

PREDICTION_DIR = Path("/app/output/predictions")
FEATURE_DIR = Path("/app/data/test_features")
EXPECTED_SHAPE = (256, 256)
VALID_CLASSES = {0, 1, 2}
MAX_FILE_SIZE = 512 * 512 * 2


def main():
    if not PREDICTION_DIR.exists():
        print("ERROR: Prediction directory not found: {}".format(
            PREDICTION_DIR))
        sys.exit(1)

    chip_ids = sorted(d.name for d in FEATURE_DIR.iterdir() if d.is_dir())
    pred_ids = sorted(f.stem for f in PREDICTION_DIR.glob("*.tif"))

    errors = []

    missing = set(chip_ids) - set(pred_ids)
    if missing:
        errors.append("Missing predictions for: {}".format(
            ", ".join(sorted(missing))))

    extra = set(pred_ids) - set(chip_ids)
    if extra:
        errors.append("Extra prediction files: {}".format(
            ", ".join(sorted(extra))))

    for pred_path in sorted(PREDICTION_DIR.glob("*.tif")):
        img = np.array(Image.open(pred_path))

        if img.shape != EXPECTED_SHAPE:
            errors.append("{}: shape {} != expected {}".format(
                pred_path.name, img.shape, EXPECTED_SHAPE))

        if img.dtype != np.uint8:
            errors.append("{}: dtype {} != expected uint8".format(
                pred_path.name, img.dtype))

        invalid_vals = set(np.unique(img)) - VALID_CLASSES
        if invalid_vals:
            errors.append("{}: invalid class values {}".format(
                pred_path.name, invalid_vals))

        if pred_path.stat().st_size > MAX_FILE_SIZE:
            errors.append("{}: file too large".format(pred_path.name))

    if errors:
        print("VALIDATION FAILED:")
        for e in errors:
            print("  - {}".format(e))
        sys.exit(1)

    print("VALIDATION PASSED: {} predictions verified".format(len(pred_ids)))


if __name__ == "__main__":
    main()
