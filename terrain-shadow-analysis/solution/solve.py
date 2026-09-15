#!/usr/bin/env python3
"""
Terrain cast shadow and illumination analysis.

Reads a DEM numpy array and sun parameters, then:
  1. Computes slope and aspect via finite differences.
  2. Computes cos(incidence angle) for direct beam illumination.
  3. Performs vectorized ray-tracing toward the sun to detect cast shadows.
  4. Produces output numpy arrays and an analysis JSON.
"""

import json
import math
import os

import numpy as np


def compute_slope_aspect(elevation, valid, pixel_size):
    """Return (slope_rad, aspect_rad) with NaN-safe gradient computation."""
    rows, cols = elevation.shape
    elev = elevation.copy()
    elev[~valid] = np.nan

    # Eastward gradient dz/de
    dz_de = np.full_like(elev, np.nan)
    dz_de[:, 1:-1] = (elev[:, 2:] - elev[:, :-2]) / (2.0 * pixel_size)
    dz_de[:, 0] = (elev[:, 1] - elev[:, 0]) / pixel_size
    dz_de[:, -1] = (elev[:, -1] - elev[:, -2]) / pixel_size

    # Northward gradient dz/dn (row 0 = north; increasing row = south)
    dz_dn = np.full_like(elev, np.nan)
    dz_dn[1:-1, :] = -(elev[2:, :] - elev[:-2, :]) / (2.0 * pixel_size)
    dz_dn[0, :] = -(elev[1, :] - elev[0, :]) / pixel_size
    dz_dn[-1, :] = -(elev[-1, :] - elev[-2, :]) / pixel_size

    # Replace NaN gradients (from nodata neighbours) with 0 → flat assumption
    dz_de = np.nan_to_num(dz_de, nan=0.0)
    dz_dn = np.nan_to_num(dz_dn, nan=0.0)

    grad_mag = np.sqrt(dz_de ** 2 + dz_dn ** 2)
    slope = np.arctan(grad_mag)

    # Aspect = direction of steepest descent, from north CW
    aspect = np.arctan2(-dz_de, -dz_dn) % (2.0 * np.pi)
    flat = grad_mag < 1e-10
    aspect[flat] = 0.0

    return slope, aspect


def cos_incidence(slope, aspect, sun_az, sun_alt):
    """cos(angle between sun vector and surface normal), clamped to [0,1]."""
    zen = math.pi / 2.0 - sun_alt
    ci = (math.cos(zen) * np.cos(slope)
          + math.sin(zen) * np.sin(slope) * np.cos(sun_az - aspect))
    return np.clip(ci, 0.0, 1.0)


def compute_cast_shadows(elevation, valid, pixel_size, sun_az, sun_alt):
    """Vectorized cast shadow detection via ray-tracing toward the sun."""
    rows, cols = elevation.shape

    # Direction toward sun in grid coords (row↑=south, col↑=east)
    dr = -math.cos(sun_az)   # az=195° → +0.966 (south)
    dc = math.sin(sun_az)    # az=195° → −0.259 (west)

    # Real-world distance per normalised grid step
    step_m = pixel_size * math.sqrt(dr ** 2 + dc ** 2)
    dz_step = step_m * math.tan(sun_alt)

    max_n = int(math.ceil(math.sqrt(rows ** 2 + cols ** 2))) + 1

    rr, cc = np.mgrid[0:rows, 0:cols]
    shadow = np.zeros((rows, cols), dtype=bool)

    # Nodata pixels: make them non-blocking and non-shadowable
    elev_blocking = elevation.copy()
    elev_blocking[~valid] = -1e30

    base_elev = elevation.copy()
    base_elev[~valid] = 1e30

    for n in range(1, max_n):
        tr = np.round(rr + n * dr).astype(np.intp)
        tc = np.round(cc + n * dc).astype(np.intp)

        in_bounds = (tr >= 0) & (tr < rows) & (tc >= 0) & (tc < cols)

        still_active = in_bounds & valid & ~shadow
        if not np.any(still_active):
            break

        tr_safe = np.clip(tr, 0, rows - 1)
        tc_safe = np.clip(tc, 0, cols - 1)

        target_elev = elev_blocking[tr_safe, tc_safe]
        ray_z = base_elev + n * dz_step

        shadow |= (in_bounds & valid & (target_elev > ray_z))

    return shadow.astype(np.uint8)


def main():
    elevation = np.load("/app/data/elevation.npy")
    with open("/app/data/config.json") as f:
        cfg = json.load(f)
    with open("/app/data/metadata.json") as f:
        meta = json.load(f)

    sun_az = math.radians(cfg["sun_azimuth_degrees"])
    sun_alt = math.radians(cfg["sun_altitude_degrees"])
    px = meta["pixel_size_m"]

    valid = ~np.isnan(elevation)

    # 1. Slope and aspect
    slope, aspect = compute_slope_aspect(elevation, valid, px)

    # 2. Direct-beam incidence
    ci = cos_incidence(slope, aspect, sun_az, sun_alt)

    # 3. Cast shadows
    print("Computing cast shadows (vectorized ray-tracing) ...")
    cast_shadow = compute_cast_shadows(elevation, valid, px, sun_az, sun_alt)
    print("  done.")

    # 4. Final illumination
    illum = ci.astype(np.float32)
    illum[cast_shadow == 1] = 0.0
    illum[~valid] = np.nan

    # 5. Prepare shadow output (nodata → 255)
    shadow_out = cast_shadow.copy()
    shadow_out[~valid] = 255

    # 6. Write outputs
    os.makedirs("/app/output", exist_ok=True)
    np.save("/app/output/cast_shadow.npy", shadow_out)
    np.save("/app/output/illumination.npy", illum)

    # 7. Statistics
    valid_shadow = cast_shadow[valid]
    valid_illum = illum[valid]
    n_valid = int(np.sum(valid))
    n_shadow = int(np.sum(valid_shadow == 1))

    stats = {
        "cast_shadow_fraction": float(n_shadow) / n_valid,
        "mean_illumination": float(np.mean(valid_illum)),
        "shadow_area_sq_m": float(n_shadow * px * px),
        "max_slope_degrees": float(np.nanmax(np.degrees(slope[valid]))),
    }
    with open("/app/output/analysis.json", "w") as f:
        json.dump(stats, f, indent=2)

    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
