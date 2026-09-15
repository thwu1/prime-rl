#!/usr/bin/env python3
"""
Bathymetric gridding optimization pipeline using GMT CLI tools.

Implements spatial cross-validation to select optimal spline tension,
then produces a final grid, computes residuals, and extracts a profile.

"""

import csv
import json
import math
import os
import subprocess
import tempfile
from io import StringIO

import numpy as np
import pandas as pd

REGION = "245/255/20/30"
SPACING = "10m"  # 10 arc-minutes
TENSIONS = [0.0, 0.1, 0.25, 0.35, 0.5, 0.75, 1.0]
DATA_FILE = "/app/data/ship_bathymetry.xyz"
RESULTS = "/app/results"


def gmt(*args):
    """Run a GMT command and return completed process."""
    cmd = ["gmt"] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"GMT command failed: {' '.join(cmd)}\nstderr: {result.stderr}"
        )
    return result


def haversine_km(lon1, lat1, lon2, lat2):
    """Great-circle distance in kilometres using the Haversine formula."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.asin(min(1.0, math.sqrt(a)))


def write_xyz(path, df, cols):
    """Write a DataFrame to a whitespace-separated XYZ file."""
    df[cols].to_csv(path, sep="\t", header=False, index=False, float_format="%.6f")


def parse_gmt_xyz(text):
    """Parse whitespace-delimited GMT output into list of float-tuples."""
    rows = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith(">") or line.startswith("#"):
            continue
        rows.append([float(v) for v in line.split()])
    return rows


def main():
    os.makedirs(RESULTS, exist_ok=True)

    # ── Step 1: Block-median preprocessing ──────────────────────────────────
    print("Step 1: Block-median preprocessing ...")
    bm = gmt("blockmedian", DATA_FILE, f"-R{REGION}", f"-I{SPACING}")
    data = pd.read_csv(
        StringIO(bm.stdout), sep=r"\s+", header=None, names=["lon", "lat", "depth"]
    )
    # Also write to temp file for later surface calls
    bm_path = tempfile.NamedTemporaryFile(
        mode="w", suffix=".xyz", delete=False, dir="/tmp"
    ).name
    write_xyz(bm_path, data, ["lon", "lat", "depth"])
    print(f"  {len(data)} blocked observations")

    # ── Step 2: 4-fold spatial cross-validation ─────────────────────────────
    print("Step 2: Spatial cross-validation ...")
    folds = [
        data[(data.lon < 250) & (data.lat < 25)].reset_index(drop=True),   # SW
        data[(data.lon >= 250) & (data.lat < 25)].reset_index(drop=True),   # SE
        data[(data.lon < 250) & (data.lat >= 25)].reset_index(drop=True),   # NW
        data[(data.lon >= 250) & (data.lat >= 25)].reset_index(drop=True),  # NE
    ]
    print(f"  Fold sizes: {[len(f) for f in folds]}")

    cv_results = []
    for tension in TENSIONS:
        fold_rmses = []
        for holdout in range(4):
            test_df = folds[holdout]
            if len(test_df) < 2:
                continue
            train_df = pd.concat(
                [f for i, f in enumerate(folds) if i != holdout], ignore_index=True
            )

            # Write training XYZ
            train_path = tempfile.NamedTemporaryFile(
                suffix=".xyz", delete=False, dir="/tmp"
            ).name
            write_xyz(train_path, train_df, ["lon", "lat", "depth"])

            # Write test locations (lon lat only)
            test_path = tempfile.NamedTemporaryFile(
                suffix=".xy", delete=False, dir="/tmp"
            ).name
            write_xyz(test_path, test_df, ["lon", "lat"])

            # Grid training data
            grid_path = tempfile.NamedTemporaryFile(
                suffix=".nc", delete=False, dir="/tmp"
            ).name
            gmt(
                "surface", train_path,
                f"-R{REGION}", f"-I{SPACING}", f"-T{tension}", f"-G{grid_path}",
            )

            # Sample grid at test locations
            track = gmt("grdtrack", test_path, f"-G{grid_path}")
            predicted = []
            for row in parse_gmt_xyz(track.stdout):
                if len(row) >= 3:
                    predicted.append(row[2])

            # Compute RMSE
            actual = test_df["depth"].values
            n_compare = min(len(predicted), len(actual))
            sq_err = []
            for j in range(n_compare):
                if math.isfinite(predicted[j]):
                    sq_err.append((predicted[j] - actual[j]) ** 2)
            if sq_err:
                fold_rmses.append(math.sqrt(sum(sq_err) / len(sq_err)))

            # Clean up temp files
            for p in (train_path, test_path, grid_path):
                try:
                    os.unlink(p)
                except OSError:
                    pass

        mean_rmse = (
            sum(fold_rmses) / len(fold_rmses) if fold_rmses else float("inf")
        )
        cv_results.append((tension, mean_rmse))
        print(f"  T={tension:.2f}  RMSE={mean_rmse:.1f}")

    # Write CV results
    with open(os.path.join(RESULTS, "cv_results.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["tension", "mean_rmse"])
        for t, r in cv_results:
            writer.writerow([t, r])

    # Select optimal tension
    best_idx = min(range(len(cv_results)), key=lambda i: cv_results[i][1])
    optimal_t = cv_results[best_idx][0]
    with open(os.path.join(RESULTS, "optimal_tension.txt"), "w") as f:
        f.write(str(optimal_t))
    print(f"  Optimal tension: {optimal_t}")

    # ── Step 3: Final grid ──────────────────────────────────────────────────
    print("Step 3: Final grid ...")
    final_grid = os.path.join(RESULTS, "final_grid.nc")
    gmt(
        "surface", bm_path,
        f"-R{REGION}", f"-I{SPACING}", f"-T{optimal_t}", f"-G{final_grid}",
    )

    info = gmt("grdinfo", final_grid)
    with open(os.path.join(RESULTS, "grid_info.txt"), "w") as f:
        f.write(info.stdout)

    # ── Step 4: Gaussian filter + residual analysis ─────────────────────────
    print("Step 4: Filtering and residual analysis ...")
    filtered_path = tempfile.NamedTemporaryFile(
        suffix=".nc", delete=False, dir="/tmp"
    ).name
    residual_path = tempfile.NamedTemporaryFile(
        suffix=".nc", delete=False, dir="/tmp"
    ).name

    # Mark grid as geographic so grdfilter accepts -D4 (flat-earth distances)
    gmt("grdedit", final_grid, "-fg")
    gmt("grdfilter", final_grid, f"-G{filtered_path}", "-Fg600", "-D4")
    gmt("grdmath", final_grid, filtered_path, "SUB", "=", residual_path)

    # Dump residual grid to XYZ for statistics
    xyz = gmt("grd2xyz", residual_path)
    r_lons, r_lats, r_vals = [], [], []
    for row in parse_gmt_xyz(xyz.stdout):
        if len(row) >= 3 and math.isfinite(row[2]):
            r_lons.append(row[0])
            r_lats.append(row[1])
            r_vals.append(row[2])

    arr = np.array(r_vals)
    imin, imax = int(np.argmin(arr)), int(np.argmax(arr))

    residual_stats = {
        "mean": float(np.mean(arr)),
        "std": float(np.std(arr)),
        "min": float(arr[imin]),
        "max": float(arr[imax]),
        "min_lon": r_lons[imin],
        "min_lat": r_lats[imin],
        "max_lon": r_lons[imax],
        "max_lat": r_lats[imax],
    }
    with open(os.path.join(RESULTS, "residual_stats.json"), "w") as f:
        json.dump(residual_stats, f, indent=2)
    print(f"  Residual: mean={residual_stats['mean']:.1f}, "
          f"std={residual_stats['std']:.1f}")

    # Clean up intermediate grids
    for p in (filtered_path, residual_path):
        try:
            os.unlink(p)
        except OSError:
            pass

    # ── Step 5: Depth-profile transect ──────────────────────────────────────
    print("Step 5: Profile extraction ...")
    start_lon, start_lat = 246.0, 22.0
    end_lon, end_lat = 254.0, 28.0
    n_pts = 50

    # Generate equally-spaced profile points
    prof_pts = []
    for i in range(n_pts):
        t = i / (n_pts - 1)
        prof_pts.append((
            start_lon + t * (end_lon - start_lon),
            start_lat + t * (end_lat - start_lat),
        ))

    # Write profile points and sample grid
    prof_path = tempfile.NamedTemporaryFile(
        mode="w", suffix=".xy", delete=False, dir="/tmp"
    ).name
    with open(prof_path, "w") as f:
        for plon, plat in prof_pts:
            f.write(f"{plon:.6f}\t{plat:.6f}\n")

    track = gmt("grdtrack", prof_path, f"-G{final_grid}")
    os.unlink(prof_path)

    # Parse sampled values and compute great-circle distances
    profile_rows = []
    for row in parse_gmt_xyz(track.stdout):
        if len(row) >= 3:
            plon, plat, depth = row[0], row[1], row[2]
            dist = haversine_km(start_lon, start_lat, plon, plat)
            profile_rows.append({
                "longitude": round(plon, 6),
                "latitude": round(plat, 6),
                "distance": round(dist, 4),
                "depth": round(depth, 4),
            })

    with open(os.path.join(RESULTS, "profile.csv"), "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["longitude", "latitude", "distance", "depth"]
        )
        writer.writeheader()
        writer.writerows(profile_rows)

    depths = [r["depth"] for r in profile_rows]
    profile_stats = {
        "min_depth": min(depths),
        "max_depth": max(depths),
        "mean_depth": float(np.mean(depths)),
        "n_points": len(profile_rows),
    }
    with open(os.path.join(RESULTS, "profile_stats.json"), "w") as f:
        json.dump(profile_stats, f, indent=2)
    print(f"  Profile: {len(profile_rows)} points, "
          f"depth [{min(depths):.0f}, {max(depths):.0f}]")

    # Final cleanup
    try:
        os.unlink(bm_path)
    except OSError:
        pass

    print("\nPipeline complete. All results in /app/results/")


if __name__ == "__main__":
    main()
