#!/usr/bin/env python3
"""Baseline cloud cover detection submission."""
from pathlib import Path

import numpy as np
from PIL import Image

ROOT_DIR = Path("/app")
FEATURE_DIR = ROOT_DIR / "test_features"
PREDICTION_DIR = ROOT_DIR / "predictions"


def predict_chip(chip_dir):
    """Generate cloud mask prediction for a single chip."""
    band_arrays = []
    for band_name in ["B02", "B03", "B04", "B08"]:
        band_path = chip_dir / "{}.tif".format(band_name)
        if band_path.exists():
            band_arrays.append(np.array(Image.open(band_path)))

    if not band_arrays:
        raise FileNotFoundError("No band files found in {}".format(chip_dir))

    # Stack all bands and compute mean across bands
    stacked = np.stack(band_arrays, axis=0).astype(float)
    mean_all = stacked.mean(axis=0)

    # Threshold at the per-image mean
    prediction = mean_all > mean_all.mean()

    return prediction


def main():
    chips = sorted(d for d in FEATURE_DIR.iterdir() if d.is_dir())

    if not chips:
        print("ERROR: No chip directories found in {}".format(FEATURE_DIR))
        return

    print("Processing {} chips from {}".format(len(chips), FEATURE_DIR))

    for chip_dir in chips:
        prediction = predict_chip(chip_dir)
        output_path = PREDICTION_DIR / "{}.tif".format(chip_dir.name)
        Image.fromarray(prediction).save(str(output_path))
        print("  Saved: {}".format(chip_dir.name))

    print("Prediction complete.")


if __name__ == "__main__":
    main()
