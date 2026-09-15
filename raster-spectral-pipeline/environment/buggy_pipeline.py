#!/usr/bin/env python3
"""Geospatial raster processing pipeline.

Reads a multi-band satellite image and produces spectral indices,
land cover classification, vector polygons, and summary statistics.
"""
import json
import os

import numpy as np
import rasterio
from rasterio.features import shapes as rasterio_shapes
from rasterio.transform import Affine
from shapely.geometry import mapping, shape
from shapely.ops import unary_union


def load_config(path="/app/config.json"):
    with open(path) as f:
        return json.load(f)


def tile_positions(size, tile_size, overlap):
    """Return start positions along one axis so every pixel is covered."""
    stride = tile_size - overlap
    positions = list(range(0, size - tile_size + 1, stride))
    if not positions or positions[-1] + tile_size < size:
        positions.append(max(0, size - tile_size))
    return positions


def blend_weights_1d(length, overlap):
    """Linear ramp from near-zero at edges to 1.0 at overlap pixels in."""
    w = np.ones(length, dtype=np.float64)
    for d in range(min(overlap, length)):
        alpha = (d + 1.0) / (overlap + 1.0)
        w[d] = min(w[d], alpha)
        w[length - 1 - d] = min(w[length - 1 - d], alpha)
    return w


def blend_weights_2d(h, w, overlap):
    """2-D blend weights as outer product of 1-D ramps."""
    wy = blend_weights_1d(h, overlap)
    wx = blend_weights_1d(w, overlap)
    return wy[:, np.newaxis] * wx[np.newaxis, :]


def safe_ratio(a, b):
    """Element-wise a / b, returning 0 where b == 0."""
    out = np.zeros_like(a, dtype=np.float64)
    nz = b != 0
    out[nz] = a[nz] / b[nz]
    return out


def compute_indices(blue, green, red, nir, nodata_mask):
    ndvi = safe_ratio(nir - red, nir + red)
    ndwi = safe_ratio(green - nir, green + nir)
    bsi = safe_ratio((red + blue) - (nir + green), (red + blue) + (nir + green))
    ndvi[nodata_mask] = 0.0
    ndwi[nodata_mask] = 0.0
    bsi[nodata_mask] = 0.0
    return ndvi, ndwi, bsi


def tiled_index_computation(bands, nodata_mask, tile_size, overlap):
    """Compute spectral indices via tiled processing with overlap blending."""
    height, width = bands.shape[1], bands.shape[2]
    blue, green, nir, red = (
        bands[0].astype(np.float64),
        bands[1].astype(np.float64),
        bands[2].astype(np.float64),
        bands[3].astype(np.float64),
    )

    acc_ndvi = np.zeros((height, width), dtype=np.float64)
    acc_ndwi = np.zeros((height, width), dtype=np.float64)
    acc_bsi = np.zeros((height, width), dtype=np.float64)
    wsum = np.zeros((height, width), dtype=np.float64)

    row_starts = tile_positions(height, tile_size, overlap)
    col_starts = tile_positions(width, tile_size, overlap)

    for rs in row_starts:
        re = min(rs + tile_size, height)
        for cs in col_starts:
            ce = min(cs + tile_size, width)
            th, tw = re - rs, ce - cs

            sl = (slice(rs, re), slice(cs, ce))
            t_nd = nodata_mask[sl]

            t_ndvi, t_ndwi, t_bsi = compute_indices(
                blue[sl], green[sl], red[sl], nir[sl], t_nd
            )

            w = blend_weights_2d(th, tw, overlap)
            w[t_nd] = 0.0

            acc_ndvi[sl] += t_ndvi * w
            acc_ndwi[sl] += t_ndwi * w
            acc_bsi[sl] += t_bsi * w
            wsum[sl] += w

    valid = wsum > 0
    for arr in (acc_ndvi, acc_ndwi, acc_bsi):
        arr[valid] /= wsum[valid]
        arr[nodata_mask] = 0.0

    return (
        acc_ndvi.astype(np.float32),
        acc_ndwi.astype(np.float32),
        acc_bsi.astype(np.float32),
    )


def classify(ndvi, ndwi, bsi, nodata_mask):
    """Ordered-rule classification; first match wins."""
    cls = np.zeros(ndvi.shape, dtype=np.uint8)
    valid = ~nodata_mask

    water = valid & (ndwi > 0.3)
    cls[water] = 1

    dense = valid & (cls == 0) & (ndvi > 0.6)
    cls[dense] = 2

    sparse = valid & (cls == 0) & (ndvi > 0.2) & (ndwi <= 0.3)
    cls[sparse] = 3

    bare = valid & (cls == 0) & (bsi > 0.1) & (ndvi <= 0.2) & (ndwi <= 0.3)
    cls[bare] = 4

    urban = valid & (cls == 0)
    cls[urban] = 5

    return cls


def vectorise(classification, src_transform, config):
    """Raster to vector with simplification and small-polygon merging."""
    tolerance = config["vectorization"]["simplification_tolerance_m"]
    min_area = config["vectorization"]["min_area_sqm"]
    class_names = {r["class"]: r["name"] for r in config["classification_rules"]}

    mask = classification != 0

    per_class = {}
    for geom_dict, value in rasterio_shapes(
        classification.astype(np.int32), mask=mask, transform=Affine.identity()
    ):
        cid = int(value)
        if cid == 0:
            continue
        per_class.setdefault(cid, []).append(shape(geom_dict))

    all_polys = []
    for cid in sorted(per_class):
        merged = unary_union(per_class[cid])
        simplified = merged.simplify(tolerance, preserve_topology=True)
        if simplified.is_empty:
            continue
        if simplified.geom_type == "Polygon":
            all_polys.append((cid, simplified))
        elif simplified.geom_type == "MultiPolygon":
            for p in simplified.geoms:
                all_polys.append((cid, p))

    large = [(cid, p) for cid, p in all_polys if p.area >= min_area]
    small = [(cid, p) for cid, p in all_polys if p.area < min_area]

    if small:
        from shapely.strtree import STRtree

        large_geoms = [p for _, p in large]
        tree = STRtree(large_geoms)

        for s_cid, s_poly in small:
            best_idx = None
            best_length = -1.0
            candidates = tree.query(s_poly)
            for idx in candidates:
                l_cid = large[idx][0]
                l_poly = large_geoms[idx]
                if l_cid == s_cid:
                    continue
                if s_poly.intersects(l_poly) or s_poly.touches(l_poly):
                    shared = s_poly.boundary.intersection(l_poly.boundary).length
                    if shared > best_length:
                        best_length = shared
                        best_idx = idx

            if best_idx is not None:
                l_cid_found, l_poly_old = large[best_idx]
                new_poly = l_poly_old.union(s_poly)
                large[best_idx] = (l_cid_found, new_poly)
                large_geoms[best_idx] = new_poly

    features = []
    for cid, poly in large:
        if poly.is_empty:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": mapping(poly),
                "properties": {
                    "class_id": cid,
                    "class_name": class_names.get(cid, f"Class_{cid}"),
                    "area_sqm": round(poly.area, 2),
                },
            }
        )

    return {"type": "FeatureCollection", "features": features}


def zonal_statistics(classification, ndvi, ndwi, bsi, bands, nodata_mask, config):
    class_names = {r["class"]: r["name"] for r in config["classification_rules"]}
    band_names = list(config["bands"].keys())
    pixel_area = 10.0

    valid = ~nodata_mask
    stats = {}

    for cval, cname in class_names.items():
        mask = valid & (classification == cval)
        count = int(mask.sum())

        if count == 0:
            stats[cname] = {
                "pixel_count": 0,
                "area_sqm": 0.0,
                "mean_ndvi": 0.0,
                "mean_ndwi": 0.0,
                "mean_bsi": 0.0,
                "mean_reflectance": {bn: 0.0 for bn in band_names},
            }
            continue

        refl = {}
        for i, bn in enumerate(band_names):
            refl[bn] = float(np.mean(bands[i][mask]))

        stats[cname] = {
            "pixel_count": count,
            "area_sqm": count * pixel_area,
            "mean_ndvi": float(np.mean(ndvi[mask])),
            "mean_ndwi": float(np.mean(ndwi[mask])),
            "mean_bsi": float(np.mean(bsi[mask])),
            "mean_reflectance": refl,
        }

    return stats


def accuracy_assessment(classification, gt_path, config):
    class_names = {r["class"]: r["name"] for r in config["classification_rules"]}
    n = len(class_names) - 1

    with rasterio.open(gt_path) as ds:
        gt = ds.read(1).astype(np.uint8)

    valid = (gt != 0) & (classification != 0)
    pred = classification[valid]
    truth = gt[valid]

    cm = np.zeros((n, n), dtype=np.int64)
    for i in range(len(pred)):
        t, p = int(truth[i]) - 1, int(pred[i]) - 1
        if 0 <= t < n and 0 <= p < n:
            cm[t, p] += 1

    total = cm.sum()
    overall = float(np.diag(cm).sum()) / total if total else 0.0

    pe = (
        sum(cm[c, :].sum() * cm[:, c].sum() for c in range(n)) / (total * total)
        if total
        else 0.0
    )
    kappa = (overall - pe) / (1 - pe) if pe < 1 else 0.0

    per_class_f1 = {}
    for c in range(n):
        cname = class_names[c + 1]
        tp = cm[c, c]
        fp = cm[:, c].sum() - tp
        fn = cm[c, :].sum() - tp
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0
        per_class_f1[cname] = round(float(f1), 6)

    return {
        "overall_accuracy": round(float(overall), 6),
        "kappa": round(float(kappa), 6),
        "per_class_f1": per_class_f1,
    }


def main():
    config = load_config()
    input_path = config["input_path"]
    gt_path = config["ground_truth_path"]
    out_dir = config["output_dir"]
    os.makedirs(out_dir, exist_ok=True)

    with rasterio.open(input_path) as src:
        bands = src.read()
        profile = src.profile.copy()
        transform = src.transform

    nodata_mask = np.all(bands == 0, axis=0)

    print("Computing spectral indices (tiled)...")
    ndvi, ndwi, bsi = tiled_index_computation(
        bands, nodata_mask, config["tile_size"], config["tile_overlap"]
    )

    idx_profile = profile.copy()
    idx_profile.update(count=3, dtype="float32", nodata=0)
    with rasterio.open(f"{out_dir}/indices.tif", "w", **idx_profile) as dst:
        dst.write(ndvi, 1)
        dst.write(ndwi, 2)
        dst.write(bsi, 3)
    print("  -> indices.tif")

    print("Classifying...")
    classification = classify(ndvi, ndwi, bsi, nodata_mask)

    cls_profile = profile.copy()
    cls_profile.update(count=1, dtype="uint8", nodata=0)
    with rasterio.open(f"{out_dir}/classification.tif", "w", **cls_profile) as dst:
        dst.write(classification, 1)
    print("  -> classification.tif")

    print("Vectorising...")
    geojson = vectorise(classification, transform, config)
    with open(f"{out_dir}/polygons.geojson", "w") as f:
        json.dump(geojson, f, indent=2)
    print(f"  -> polygons.geojson ({len(geojson['features'])} features)")

    print("Computing statistics...")
    stats = zonal_statistics(
        classification, ndvi, ndwi, bsi, bands, nodata_mask, config
    )
    acc = accuracy_assessment(classification, gt_path, config)

    result = {"class_statistics": stats, "accuracy": acc}
    with open(f"{out_dir}/statistics.json", "w") as f:
        json.dump(result, f, indent=2)
    print("  -> statistics.json")

    print("Pipeline complete.")


if __name__ == "__main__":
    main()
