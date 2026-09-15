#!/usr/bin/env python3
"""Generate synthetic DEM for terrain shadow analysis task."""
import json
import numpy as np

rows, cols = 200, 200
pixel_size = 30.0  # meters

y, x = np.mgrid[0:rows, 0:cols]
yf = y.astype(np.float64)
xf = x.astype(np.float64)

# Base: flat plain at 500m
elevation = np.full((rows, cols), 500.0, dtype=np.float64)

# Feature 1: East-west escarpment - linear ramp from 500m to 800m
# between rows 80 (500m) and 100 (800m)
ramp = np.clip((yf - 80.0) / 20.0, 0.0, 1.0) * 300.0
elevation += ramp

# Feature 2: Gaussian hill centered at (row=150, col=140)
# Amplitude 250m above local terrain, sigma=10 pixels
hill_dist_sq = (yf - 150.0) ** 2 + (xf - 140.0) ** 2
hill = 250.0 * np.exp(-hill_dist_sq / (2.0 * 10.0 ** 2))
elevation += hill

# Feature 3: Nodata rectangle ("lake") at rows 35-50, cols 100-120
nodata_mask = (y >= 35) & (y <= 50) & (x >= 100) & (x <= 120)
elevation[nodata_mask] = np.nan

# Save elevation data as numpy array
np.save("/app/data/elevation.npy", elevation)

# Save metadata
metadata = {
    "rows": rows,
    "cols": cols,
    "pixel_size_m": pixel_size,
    "description": "Row 0 is north, row 199 is south. Col 0 is west, col 199 is east. NaN indicates nodata (lake). Elevation in meters above sea level."
}
with open("/app/data/metadata.json", "w") as f:
    json.dump(metadata, f, indent=2)

print("DEM generated: /app/data/elevation.npy")
print(f"  Size: {cols}x{rows}, pixel: {pixel_size}m")
print(f"  Nodata pixels: {int(np.sum(nodata_mask))}")
