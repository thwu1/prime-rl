#!/usr/bin/env python3
"""Baseline cloud cover detection submission.

Uses NDVI (Normalized Difference Vegetation Index) thresholding to detect clouds.
NDVI = (NIR - Red) / (NIR + Red) = (B08 - B04) / (B08 + B04)

Clouds are non-vegetated and have low NDVI, while clear vegetation has high NDVI.
This approach uses a single global threshold and works well for vegetation terrain
but performs poorly on water bodies and urban/bare-soil surfaces.
"""

from pathlib import Path
import numpy as np
from PIL import Image

DATA_DIR = Path("/app/data/test_features")
PREDICTIONS_DIR = Path("/app/predictions")


def detect_clouds(chip_dir):
    """Detect clouds using NDVI thresholding with a fixed global threshold."""
    b04 = np.array(Image.open(chip_dir / "B04.tif")).astype(np.float32)
    b08 = np.array(Image.open(chip_dir / "B08.tif")).astype(np.float32)

    denom = b08 + b04
    denom[denom == 0] = 1
    ndvi = (b08 - b04) / denom

    cloud_mask = (ndvi < 0.2).astype(np.uint8)
    return cloud_mask


def main():
    PREDICTIONS_DIR.mkdir(parents=True, exist_ok=True)

    chips = sorted(d for d in DATA_DIR.iterdir() if d.is_dir())
    print(f"Processing {len(chips)} chips with NDVI baseline...")

    for chip_dir in chips:
        cloud_mask = detect_clouds(chip_dir)
        Image.fromarray(cloud_mask).save(PREDICTIONS_DIR / f"{chip_dir.name}.tif")
        print(f"  {chip_dir.name}: {np.mean(cloud_mask)*100:.1f}% cloud")

    print("Done!")


if __name__ == "__main__":
    main()
