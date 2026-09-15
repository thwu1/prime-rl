#!/usr/bin/env python3
"""LiDAR terrain analysis pipeline — reference solution."""

import json
import os

import laspy
import numpy as np
from osgeo import gdal, osr
from scipy.interpolate import griddata
from scipy.ndimage import minimum_filter, maximum_filter
from scipy.spatial import cKDTree

INPUT = "/app/data/survey.las"
OUTPUT = "/app/output"
CRS_EPSG = 32618
RESOLUTION = 1.0


# ── helpers ───────────────────────────────────────────────────


def write_geotiff(path, arr, x_min, y_max, res, epsg=CRS_EPSG, nodata=-9999.0):
    driver = gdal.GetDriverByName("GTiff")
    rows, cols = arr.shape
    ds = driver.Create(path, cols, rows, 1, gdal.GDT_Float32)
    ds.SetGeoTransform([x_min, res, 0.0, y_max, 0.0, -res])
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(epsg)
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(float(nodata))
    out = np.where(np.isnan(arr), nodata, arr).astype(np.float32)
    band.WriteArray(out)
    band.FlushCache()
    ds = None


# ── step 1: read ──────────────────────────────────────────────


def read_input():
    las = laspy.read(INPUT)
    x = np.array(las.x, dtype=np.float64)
    y = np.array(las.y, dtype=np.float64)
    z = np.array(las.z, dtype=np.float64)
    return x, y, z, las


# ── step 2: noise removal ────────────────────────────────────


def remove_noise(x, y, z, k=16, std_ratio=2.0):
    pts = np.column_stack([x, y, z])
    tree = cKDTree(pts)
    dists, _ = tree.query(pts, k=k + 1)
    mean_d = np.mean(dists[:, 1:], axis=1)
    mu = np.mean(mean_d)
    sigma = np.std(mean_d)
    mask = mean_d < (mu + std_ratio * sigma)
    return mask


# ── step 3: ground classification ────────────────────────────


def classify_ground(x, y, z, cell=1.0, slope=0.15, max_win=20,
                    base_thresh=0.5):
    x_min, x_max = np.min(x), np.max(x)
    y_min, y_max = np.min(y), np.max(y)
    nx = int(np.ceil((x_max - x_min) / cell)) + 1
    ny = int(np.ceil((y_max - y_min) / cell)) + 1

    col = np.clip(((x - x_min) / cell).astype(int), 0, nx - 1)
    row = np.clip(((y - y_min) / cell).astype(int), 0, ny - 1)

    # minimum surface
    surface = np.full((ny, nx), np.inf)
    for i in range(len(x)):
        r, c = row[i], col[i]
        if z[i] < surface[r, c]:
            surface[r, c] = z[i]

    # fill empty cells via nearest-neighbour
    empty = np.isinf(surface)
    if np.any(empty):
        r_ok, c_ok = np.where(~empty)
        vals_ok = surface[~empty]
        r_em, c_em = np.where(empty)
        filled = griddata((r_ok, c_ok), vals_ok, (r_em, c_em),
                          method="nearest")
        surface[empty] = filled

    # progressive morphological opening
    for w in range(1, int(max_win / cell) + 1):
        k = 2 * w + 1
        opened = maximum_filter(minimum_filter(surface, size=k), size=k)
        thresh = slope * w * cell + base_thresh
        diff = surface - opened
        surface = np.where(diff > thresh, opened, surface)

    # classify points
    ground_mask = np.zeros(len(x), dtype=bool)
    for i in range(len(x)):
        r, c = row[i], col[i]
        dz = z[i] - surface[r, c]
        if -1.5 < dz < 1.0:
            ground_mask[i] = True

    return ground_mask, surface, x_min, y_min, nx, ny


# ── step 4: write LAS ────────────────────────────────────────


def write_las_subset(src_las, indices, path, classification_override=None):
    hdr = laspy.LasHeader(point_format=src_las.header.point_format,
                          version=src_las.header.version)
    hdr.offsets = src_las.header.offsets
    hdr.scales = src_las.header.scales
    out = laspy.LasData(hdr)
    for dim in src_las.point_format.dimension_names:
        setattr(out, dim, getattr(src_las, dim)[indices])
    if classification_override is not None:
        out.classification = np.full(len(indices), classification_override,
                                     dtype=np.uint8)
    out.write(path)


# ── main pipeline ─────────────────────────────────────────────


def main():
    os.makedirs(OUTPUT, exist_ok=True)

    # read
    x, y, z, las = read_input()
    total_points = len(x)
    bbox = dict(minx=float(np.min(x)), maxx=float(np.max(x)),
                miny=float(np.min(y)), maxy=float(np.max(y)),
                minz=float(np.min(z)), maxz=float(np.max(z)))

    # noise removal
    clean_mask = remove_noise(x, y, z)
    noise_count = int(np.sum(~clean_mask))
    xc, yc, zc = x[clean_mask], y[clean_mask], z[clean_mask]

    # ground classification
    gnd_mask, _, gx_min, gy_min, gnx, gny = classify_ground(xc, yc, zc)
    ground_count = int(np.sum(gnd_mask))
    non_ground_count = int(np.sum(~gnd_mask))

    # write ground / non-ground LAS
    clean_idx = np.where(clean_mask)[0]
    ground_idx = clean_idx[gnd_mask]
    non_ground_idx = clean_idx[~gnd_mask]
    write_las_subset(las, ground_idx, f"{OUTPUT}/ground.las",
                     classification_override=2)
    write_las_subset(las, non_ground_idx, f"{OUTPUT}/non_ground.las")

    # ── DTM ───────────────────────────────────────────────────
    gx, gy, gz = xc[gnd_mask], yc[gnd_mask], zc[gnd_mask]
    x_lo = float(np.floor(np.min(xc)))
    y_lo = float(np.floor(np.min(yc)))
    x_hi = float(np.ceil(np.max(xc)))
    y_hi = float(np.ceil(np.max(yc)))
    ncols = int(np.ceil((x_hi - x_lo) / RESOLUTION))
    nrows = int(np.ceil((y_hi - y_lo) / RESOLUTION))

    grid_x = np.linspace(x_lo + RESOLUTION / 2,
                         x_lo + (ncols - 0.5) * RESOLUTION, ncols)
    grid_y = np.linspace(y_hi - RESOLUTION / 2,
                         y_hi - (nrows - 0.5) * RESOLUTION, nrows)
    gxx, gyy = np.meshgrid(grid_x, grid_y)

    dtm = griddata((gx, gy), gz, (gxx, gyy), method="linear")
    nans = np.isnan(dtm)
    if np.any(nans):
        dtm_nn = griddata((gx, gy), gz, (gxx, gyy), method="nearest")
        dtm[nans] = dtm_nn[nans]

    write_geotiff(f"{OUTPUT}/dtm.tif", dtm, x_lo, y_hi, RESOLUTION)

    # ── DSM (max Z per cell) ──────────────────────────────────
    dsm = np.full((nrows, ncols), np.nan)
    col_i = np.clip(((xc - x_lo) / RESOLUTION).astype(int), 0, ncols - 1)
    row_i = np.clip(((y_hi - yc) / RESOLUTION).astype(int), 0, nrows - 1)
    for i in range(len(xc)):
        r, c = row_i[i], col_i[i]
        if np.isnan(dsm[r, c]) or zc[i] > dsm[r, c]:
            dsm[r, c] = zc[i]
    dsm_nans = np.isnan(dsm)
    dsm[dsm_nans] = dtm[dsm_nans]

    # ── CHM ───────────────────────────────────────────────────
    chm = np.maximum(0.0, dsm - dtm)
    write_geotiff(f"{OUTPUT}/chm.tif", chm, x_lo, y_hi, RESOLUTION)

    # ── slope (degrees) ───────────────────────────────────────
    dzdx = np.gradient(dtm, RESOLUTION, axis=1)
    dzdy = np.gradient(dtm, RESOLUTION, axis=0)
    slope_deg = np.degrees(np.arctan(np.sqrt(dzdx ** 2 + dzdy ** 2)))
    write_geotiff(f"{OUTPUT}/slope.tif", slope_deg, x_lo, y_hi, RESOLUTION)

    # ── report ────────────────────────────────────────────────
    dtm_valid = dtm[~np.isnan(dtm)]
    chm_valid = chm[~np.isnan(chm)]
    veg_cells = int(np.sum(chm_valid > 0.5))
    total_cells = int(len(chm_valid))
    slope_valid = slope_deg[~np.isnan(slope_deg)]

    report = {
        "total_points": total_points,
        "noise_points_removed": noise_count,
        "ground_points": ground_count,
        "non_ground_points": non_ground_count,
        "bounding_box": bbox,
        "dtm": {
            "min": float(np.min(dtm_valid)),
            "max": float(np.max(dtm_valid)),
            "mean": float(np.mean(dtm_valid)),
            "width_pixels": ncols,
            "height_pixels": nrows,
            "crs": "EPSG:32618",
        },
        "chm": {
            "max_height": float(np.max(chm_valid)),
            "mean_height": float(np.mean(chm_valid)),
            "vegetation_coverage_pct": round(
                veg_cells / total_cells * 100.0, 2) if total_cells else 0.0,
        },
        "slope": {
            "max_degrees": float(np.max(slope_valid)),
            "mean_degrees": float(np.mean(slope_valid)),
        },
    }

    with open(f"{OUTPUT}/report.json", "w") as f:
        json.dump(report, f, indent=2)

    print(f"Pipeline complete — {total_points} points")
    print(f"  Noise removed : {noise_count}")
    print(f"  Ground        : {ground_count}")
    print(f"  Non-ground    : {non_ground_count}")
    print(f"  DTM RMSE hint : check with tests")


if __name__ == "__main__":
    main()
