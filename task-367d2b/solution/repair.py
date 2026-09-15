#!/usr/bin/env python3
"""
Repair corrupted geospatial catalog and compute coverage strategy.
"""

import json
import os
from itertools import combinations
from osgeo import ogr, osr

CATALOG_PATH = "/app/catalog.gpkg"
FIXED_PATH = "/app/catalog_fixed.gpkg"
MISSIONS_PATH = "/app/missions.json"
DIAG_PATH = "/app/diagnostic_report.json"
STRATEGY_PATH = "/app/strategy.json"


# ==================== REPAIR ====================

def detect_and_fix():
    """Read corrupted catalog, detect issues, produce fixed catalog + diagnostic report."""
    ds = ogr.Open(CATALOG_PATH)
    layer = ds.GetLayer("datasets")

    src_srs = osr.SpatialReference()
    src_srs.ImportFromEPSG(3857)
    src_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    dst_srs = osr.SpatialReference()
    dst_srs.ImportFromEPSG(4326)
    dst_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    transform = osr.CoordinateTransformation(src_srs, dst_srs)

    corrupted_records = []
    fixed_features = []

    layer.ResetReading()
    feat = layer.GetNextFeature()
    while feat is not None:
        did = feat.GetField("dataset_id")
        name = feat.GetField("name")
        cat = feat.GetField("category")
        res = feat.GetField("resolution_m")
        qual = feat.GetField("quality_score")
        size = feat.GetField("size_gb")
        bands = feat.GetField("bands")
        ts = feat.GetField("temporal_start")
        te = feat.GetField("temporal_end")
        geom = feat.GetGeometryRef().Clone()

        corruption = None
        env = geom.GetEnvelope()  # (minX, maxX, minY, maxY)

        # Check 1: CRS mismatch — coordinates far outside WGS84 range
        if abs(env[0]) > 180 or abs(env[1]) > 180 or abs(env[2]) > 90 or abs(env[3]) > 90:
            if abs(env[0]) > 1000:
                # Coordinates are in EPSG:3857 (meters), reproject to EPSG:4326
                geom.Transform(transform)
                new_env = geom.GetEnvelope()
                geom = _make_bbox(new_env[0], new_env[2], new_env[1], new_env[3])
                corruption = (
                    "CRS mismatch: coordinates stored in EPSG:3857 "
                    "(Web Mercator meters) instead of EPSG:4326 (WGS84 degrees). "
                    "Identified by coordinate magnitudes in the millions, "
                    "far exceeding the WGS84 range of [-180,180] x [-90,90]."
                )
            else:
                # Coordinate swap — Y values outside latitude range
                ring = geom.GetGeometryRef(0)
                new_coords = []
                for i in range(ring.GetPointCount()):
                    x, y = ring.GetX(i), ring.GetY(i)
                    new_coords.append((y, x))
                geom = _make_polygon(new_coords)
                corruption = (
                    "Coordinate transposition: latitude and longitude values are "
                    "swapped. Identified by Y coordinates outside the valid "
                    "WGS84 latitude range [-90, 90] while X values fall within "
                    "typical longitude range for the Pacific Northwest."
                )

        # Check 2: Invalid geometry (self-intersection)
        elif not geom.IsValid():
            geom = _make_bbox(env[0], env[2], env[1], env[3])
            corruption = (
                "Invalid geometry: self-intersecting polygon ring (bowtie shape). "
                "Identified via OGR IsValid() check. Reconstructed as axis-aligned "
                "rectangle from the geometry envelope."
            )

        # Check 3: Temporal inversion
        if ts > te:
            ts, te = te, ts
            if corruption:
                corruption += " Additionally, temporal_start > temporal_end (dates swapped)."
            else:
                corruption = (
                    "Temporal inversion: temporal_start and temporal_end are swapped "
                    "(start date is after end date). Identified by string comparison "
                    "of ISO date fields."
                )

        if corruption:
            corrupted_records.append({
                "dataset_id": did,
                "description": corruption,
            })

        fixed_features.append({
            "id": did, "name": name, "cat": cat, "res": res,
            "qual": qual, "size": size, "bands": bands,
            "ts": ts, "te": te, "geom": geom,
        })
        feat = layer.GetNextFeature()
    ds = None

    # Write diagnostic report
    diag = {
        "corrupted_records": corrupted_records,
        "total_corrupted": len(corrupted_records),
    }
    with open(DIAG_PATH, "w") as f:
        json.dump(diag, f, indent=2)
    print(f"Diagnostic report: {len(corrupted_records)} corrupted records")

    # Write fixed GeoPackage
    _write_fixed_gpkg(fixed_features)
    print(f"Fixed catalog written to {FIXED_PATH}")

    return fixed_features


def _make_bbox(w, s, e, n):
    ring = ogr.Geometry(ogr.wkbLinearRing)
    ring.AddPoint(w, s)
    ring.AddPoint(e, s)
    ring.AddPoint(e, n)
    ring.AddPoint(w, n)
    ring.AddPoint(w, s)
    poly = ogr.Geometry(ogr.wkbPolygon)
    poly.AddGeometry(ring)
    return poly


def _make_polygon(coords):
    ring = ogr.Geometry(ogr.wkbLinearRing)
    for x, y in coords:
        ring.AddPoint(x, y)
    poly = ogr.Geometry(ogr.wkbPolygon)
    poly.AddGeometry(ring)
    return poly


def _write_fixed_gpkg(features):
    if os.path.exists(FIXED_PATH):
        os.remove(FIXED_PATH)

    driver = ogr.GetDriverByName("GPKG")
    ds = driver.CreateDataSource(FIXED_PATH)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    layer = ds.CreateLayer("datasets", srs, ogr.wkbPolygon)

    layer.CreateField(ogr.FieldDefn("dataset_id", ogr.OFTString))
    layer.CreateField(ogr.FieldDefn("name", ogr.OFTString))
    layer.CreateField(ogr.FieldDefn("category", ogr.OFTString))
    layer.CreateField(ogr.FieldDefn("resolution_m", ogr.OFTInteger))
    fld = ogr.FieldDefn("quality_score", ogr.OFTReal)
    fld.SetWidth(10)
    fld.SetPrecision(2)
    layer.CreateField(fld)
    fld = ogr.FieldDefn("size_gb", ogr.OFTReal)
    fld.SetWidth(10)
    fld.SetPrecision(1)
    layer.CreateField(fld)
    layer.CreateField(ogr.FieldDefn("bands", ogr.OFTString))
    layer.CreateField(ogr.FieldDefn("temporal_start", ogr.OFTString))
    layer.CreateField(ogr.FieldDefn("temporal_end", ogr.OFTString))

    for rec in features:
        feat = ogr.Feature(layer.GetLayerDefn())
        feat.SetField("dataset_id", rec["id"])
        feat.SetField("name", rec["name"])
        feat.SetField("category", rec["cat"])
        feat.SetField("resolution_m", rec["res"])
        feat.SetField("quality_score", rec["qual"])
        feat.SetField("size_gb", rec["size"])
        feat.SetField("bands", rec["bands"])
        feat.SetField("temporal_start", rec["ts"])
        feat.SetField("temporal_end", rec["te"])
        feat.SetGeometry(rec["geom"])
        layer.CreateFeature(feat)
        feat = None

    ds = None


# ==================== SPATIAL UTILITIES ====================

def env_to_bbox(env):
    """Convert OGR envelope (minX, maxX, minY, maxY) to [west, south, east, north]."""
    return [env[0], env[2], env[1], env[3]]


def clip_area(bbox, target):
    """Area of bbox clipped to target. Both as [west, south, east, north]."""
    w = max(bbox[0], target[0])
    s = max(bbox[1], target[1])
    e = min(bbox[2], target[2])
    n = min(bbox[3], target[3])
    if w >= e or s >= n:
        return 0.0
    return (e - w) * (n - s)


def union_area_clipped(bboxes, target):
    """Union area of multiple bboxes, each clipped to target, using coordinate compression."""
    clipped = []
    for b in bboxes:
        w = max(b[0], target[0])
        s = max(b[1], target[1])
        e = min(b[2], target[2])
        n = min(b[3], target[3])
        if w < e and s < n:
            clipped.append((w, s, e, n))
    if not clipped:
        return 0.0

    xs = sorted(set(c[0] for c in clipped) | set(c[2] for c in clipped))
    ys = sorted(set(c[1] for c in clipped) | set(c[3] for c in clipped))

    total = 0.0
    for i in range(len(xs) - 1):
        for j in range(len(ys) - 1):
            cw, ce = xs[i], xs[i + 1]
            cs, cn = ys[j], ys[j + 1]
            for r in clipped:
                if r[0] <= cw and ce <= r[2] and r[1] <= cs and cn <= r[3]:
                    total += (ce - cw) * (cn - cs)
                    break
    return total


# ==================== STRATEGY ====================

def compute_strategy(features):
    """Compute portfolio optimization and efficiency analysis."""
    with open(MISSIONS_PATH) as f:
        missions = json.load(f)

    target = missions["target_region"]
    target_area = (target[2] - target[0]) * (target[3] - target[1])

    # Build feature data with bboxes
    feat_data = []
    for rec in features:
        env = rec["geom"].GetEnvelope()
        bbox = env_to_bbox(env)
        ca = clip_area(bbox, target)
        feat_data.append({
            "id": rec["id"],
            "cat": rec["cat"],
            "res": rec["res"],
            "qual": rec["qual"],
            "size": rec["size"],
            "bands": rec["bands"],
            "ts": rec["ts"],
            "te": rec["te"],
            "bbox": bbox,
            "clipped_area": ca,
        })

    # --- Efficiency Analysis ---
    ranking = []
    for fd in feat_data:
        if fd["clipped_area"] > 0 and fd["size"] > 0:
            eff = fd["qual"] * (fd["clipped_area"] / target_area) / fd["size"]
        else:
            eff = 0.0
        ranking.append({"dataset_id": fd["id"], "efficiency": round(eff, 6)})

    ranking.sort(key=lambda x: (-x["efficiency"], x["dataset_id"]))

    # Category best: highest efficiency per category
    cat_best = {}
    for item in ranking:
        fd = next(f for f in feat_data if f["id"] == item["dataset_id"])
        cat = fd["cat"]
        if cat not in cat_best or item["efficiency"] > cat_best[cat][1]:
            cat_best[cat] = (item["dataset_id"], item["efficiency"])
    category_best = {cat: did for cat, (did, _) in cat_best.items()}

    # --- Portfolio Optimization ---
    constraints = missions["portfolio_optimization"]["constraints"]
    budget = constraints["storage_budget_gb"]
    min_cats = constraints["min_categories"]
    min_cov = constraints["min_per_category_coverage_fraction"]
    min_qual = constraints["min_quality_score"]
    temp_req = constraints["temporal_overlap_required"]

    # Filter eligible datasets for portfolio
    eligible = []
    for fd in feat_data:
        if fd["qual"] < min_qual:
            continue
        # Temporal overlap: dataset.ts <= range_end AND dataset.te >= range_start
        if fd["ts"] > temp_req[1] or fd["te"] < temp_req[0]:
            continue
        if fd["clipped_area"] <= 0:
            continue
        eligible.append(fd)

    # Group eligible by category
    by_cat = {}
    for fd in eligible:
        by_cat.setdefault(fd["cat"], []).append(fd)

    min_cov_area = min_cov * target_area

    # For each category, find minimum cost subset achieving coverage threshold
    cat_solutions = {}
    for cat, datasets in by_cat.items():
        best_cost = float("inf")
        best_ids = None
        n = len(datasets)
        for k in range(1, n + 1):
            for combo in combinations(range(n), k):
                total_cost = sum(datasets[i]["size"] for i in combo)
                if total_cost >= best_cost:
                    continue
                if total_cost > budget:
                    continue
                bboxes = [datasets[i]["bbox"] for i in combo]
                union = union_area_clipped(bboxes, target)
                if union >= min_cov_area - 1e-9:
                    best_cost = total_cost
                    best_ids = [datasets[i]["id"] for i in combo]
        if best_ids is not None:
            cat_solutions[cat] = (best_cost, best_ids)

    # Find cheapest combination of >= min_cats categories
    best_portfolio = None
    best_portfolio_cost = float("inf")
    best_portfolio_cats = None

    cat_list = list(cat_solutions.keys())
    for ncats in range(min_cats, len(cat_list) + 1):
        for cat_combo in combinations(cat_list, ncats):
            total_cost = sum(cat_solutions[c][0] for c in cat_combo)
            if total_cost < best_portfolio_cost and total_cost <= budget:
                best_portfolio_cost = total_cost
                best_portfolio_cats = sorted(cat_combo)
                all_ids = []
                for c in cat_combo:
                    all_ids.extend(cat_solutions[c][1])
                best_portfolio = sorted(set(all_ids))

    # Compute per-category coverage for the selected portfolio
    per_cat_cov = {}
    if best_portfolio:
        for cat in best_portfolio_cats:
            cat_ids = cat_solutions[cat][1]
            cat_bboxes = [fd["bbox"] for fd in feat_data if fd["id"] in cat_ids]
            union = union_area_clipped(cat_bboxes, target)
            per_cat_cov[cat] = round(union / target_area, 6)

    strategy = {
        "portfolio": {
            "selected_dataset_ids": best_portfolio or [],
            "total_storage_gb": round(best_portfolio_cost, 2) if best_portfolio else 0.0,
            "categories": best_portfolio_cats or [],
            "per_category_coverage": per_cat_cov,
        },
        "efficiency_analysis": {
            "ranking": ranking,
            "category_best": category_best,
        },
    }

    with open(STRATEGY_PATH, "w") as f:
        json.dump(strategy, f, indent=2)
    print(f"Strategy written to {STRATEGY_PATH}")

    # Summary
    if best_portfolio:
        print(f"  Portfolio: {len(best_portfolio)} datasets, "
              f"{best_portfolio_cost:.1f} GB, "
              f"categories: {best_portfolio_cats}")
    print(f"  Top efficiency: {ranking[0]['dataset_id']} "
          f"({ranking[0]['efficiency']:.4f})")


def main():
    fixed_features = detect_and_fix()
    compute_strategy(fixed_features)
    print("Done.")


if __name__ == "__main__":
    main()
