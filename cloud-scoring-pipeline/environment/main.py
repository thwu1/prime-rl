#!/usr/bin/env python3
"""Baseline cloud cover detection submission.

Reads multi-band Sentinel-2 satellite image chips and produces binary
cloud masks using NDVI (Normalized Difference Vegetation Index) thresholding.

NDVI = (NIR - Red) / (NIR + Red) = (B08 - B04) / (B08 + B04)

Clouds are non-vegetated and have low NDVI, while clear vegetation has high NDVI.
"""

from pathlib import Path
import numpy as np
from PIL import Image

DATA_DIR = Path("/app/data/test_features")
PREDICTIONS_DIR = Path("predictions")


def detect_clouds(chip_dir):
    """Detect clouds using NDVI thresholding.

    Clouds have low NDVI (bright in visible, not special in NIR).
    Clear vegetation has high NDVI (high NIR reflectance).
    """
    b04 = np.array(Image.open(chip_dir / "B04.tif")).astype(np.float32)
    b08 = np.array(Image.open(chip_dir / "B08.tif")).astype(np.float32)

    # Compute NDVI
    denominator = b08 + b04
    denominator[denominator == 0] = 1  # Avoid division by zero
    ndvi = (b08 - b04) / denominator

    # Threshold to identify clouds
    cloud_mask = (ndvi > 0.1).astype(np.uint8)

    return cloud_mask


def main():
    PREDICTIONS_DIR.mkdir(parents=True, exist_ok=True)

    chips = sorted(d for d in DATA_DIR.iterdir() if d.is_dir())
    print(f"Processing {len(chips)} chips...")

    for chip_dir in chips:
        cloud_mask = detect_clouds(chip_dir)
        output_path = PREDICTIONS_DIR / f"{chip_dir.name}.tif"
        Image.fromarray(cloud_mask).save(output_path)
        print(f"  Saved prediction for {chip_dir.name}")

    print("Done!")


if __name__ == "__main__":
    main()
