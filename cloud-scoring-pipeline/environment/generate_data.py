#!/usr/bin/env python3
"""Generate synthetic Sentinel-2-like multi-band satellite image chips
across three terrain types (vegetation, water, urban/bare-soil) with
known cloud patterns for evaluating cloud detection algorithms.

Each chip: 4 single-band 512x512 TIF images (B02 Blue, B03 Green, B04 Red, B08 NIR).
Ground truth: binary cloud masks (0=clear, 1=cloud).
Terrain types are NOT recorded in the manifest — they must be inferred from spectral analysis.
"""

import numpy as np
from PIL import Image
import os
import json

CHIP_SIZE = 512
NUM_CHIPS = 12
BANDS = ['B02', 'B03', 'B04', 'B08']

# Spectral reflectance profiles (uint16, range 0-10000)
# Different terrains have distinct spectral signatures in clear conditions.
# Clouds are spectrally similar across all terrains (bright visible, moderate NIR).
TERRAIN_PROFILES = {
    'vegetation': {
        'clear': {'B02': 500, 'B03': 1500, 'B04': 800, 'B08': 5000},
        'cloud': {'B02': 8000, 'B03': 8500, 'B04': 9000, 'B08': 7000},
    },
    'water': {
        'clear': {'B02': 1500, 'B03': 1200, 'B04': 500, 'B08': 200},
        'cloud': {'B02': 8000, 'B03': 8500, 'B04': 9000, 'B08': 7000},
    },
    'urban': {
        'clear': {'B02': 3000, 'B03': 3200, 'B04': 3500, 'B08': 3800},
        'cloud': {'B02': 8000, 'B03': 8500, 'B04': 9000, 'B08': 7000},
    },
}

TERRAIN_ORDER = ['vegetation'] * 4 + ['water'] * 4 + ['urban'] * 4
NOISE_STD = 200
CLEAR_SKY_CHIPS = {3, 7, 11}  # One per terrain type — tests edge cases


def make_cloud_mask(seed):
    """Generate a binary cloud mask with deterministic geometric patterns."""
    rng = np.random.RandomState(seed)
    mask = np.zeros((CHIP_SIZE, CHIP_SIZE), dtype=np.uint8)

    num_circles = rng.randint(2, 5)
    for _ in range(num_circles):
        cx = rng.randint(80, CHIP_SIZE - 80)
        cy = rng.randint(80, CHIP_SIZE - 80)
        radius = rng.randint(40, 100)
        Y, X = np.ogrid[:CHIP_SIZE, :CHIP_SIZE]
        dist_sq = (X - cx) ** 2 + (Y - cy) ** 2
        mask[dist_sq <= radius ** 2] = 1

    rx = rng.randint(0, CHIP_SIZE // 2)
    ry = rng.randint(0, CHIP_SIZE // 2)
    rw = rng.randint(60, 180)
    rh = rng.randint(60, 180)
    mask[ry:min(ry + rh, CHIP_SIZE), rx:min(rx + rw, CHIP_SIZE)] = 1

    return mask


def generate_bands(mask, terrain, seed):
    """Generate multi-band reflectance data consistent with terrain and cloud mask."""
    rng = np.random.RandomState(seed + 1000)
    profile = TERRAIN_PROFILES[terrain]
    bands = {}

    for band_name in BANDS:
        cloud_mean = profile['cloud'][band_name]
        clear_mean = profile['clear'][band_name]

        cloud_vals = rng.normal(cloud_mean, NOISE_STD, (CHIP_SIZE, CHIP_SIZE))
        clear_vals = rng.normal(clear_mean, NOISE_STD, (CHIP_SIZE, CHIP_SIZE))

        band = np.where(mask == 1, cloud_vals, clear_vals)
        band = np.clip(band, 0, 10000).astype(np.uint16)
        bands[band_name] = band

    return bands


def main():
    base_dir = '/app/data'
    os.makedirs(f'{base_dir}/test_features', exist_ok=True)
    os.makedirs(f'{base_dir}/test_labels', exist_ok=True)

    chips_info = []
    for i in range(NUM_CHIPS):
        chip_id = f'chip_{i:04d}'
        terrain = TERRAIN_ORDER[i]
        seed = (i + 1) * 137

        if i in CLEAR_SKY_CHIPS:
            mask = np.zeros((CHIP_SIZE, CHIP_SIZE), dtype=np.uint8)
        else:
            mask = make_cloud_mask(seed)

        bands = generate_bands(mask, terrain, seed)

        chip_dir = f'{base_dir}/test_features/{chip_id}'
        os.makedirs(chip_dir, exist_ok=True)
        for band_name, band_data in bands.items():
            Image.fromarray(band_data).save(f'{chip_dir}/{band_name}.tif')

        Image.fromarray(mask).save(f'{base_dir}/test_labels/{chip_id}.tif')

        chips_info.append({
            'chip_id': chip_id,
            'datetime': '2023-06-15T10:30:00Z',
            'satellite': 'Sentinel-2A',
        })

    manifest = {
        'chips': chips_info,
        'chip_size': CHIP_SIZE,
        'bands': BANDS,
        'num_chips': NUM_CHIPS,
    }
    with open(f'{base_dir}/manifest.json', 'w') as f:
        json.dump(manifest, f, indent=2)

    print(f"Generated {NUM_CHIPS} chips across 3 terrain types in {base_dir}")


if __name__ == '__main__':
    main()
