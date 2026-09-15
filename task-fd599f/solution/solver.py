#!/usr/bin/env python3
"""
Geospatial Dataset Catalog Reconciler — Reference Solution

"""

import json
import csv
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml
import numpy as np
from pyproj import Transformer, CRS
from dateutil import parser as dateparser


# ===================================================================
# Main
# ===================================================================

def main():
    datasets_dir = "/app/datasets/"
    config_path = "/app/config.json"
    output_path = "/app/output/report.json"

    with open(config_path) as f:
        config = json.load(f)

    datasets = parse_all_files(datasets_dir)
    print(f"Parsed {len(datasets)} datasets from {datasets_dir}", file=sys.stderr)

    # Detect and fix CRS mismatches before bbox normalization
    quality_issues = detect_and_fix_crs_mismatches(datasets)
    print(f"CRS quality issues found: {len(quality_issues)}", file=sys.stderr)

    for ds in datasets:
        try:
            ds["bbox"] = normalize_bbox_to_wgs84(ds["bbox_native"], ds["original_crs"])
        except Exception as exc:
            print(f"Warning: bbox normalization failed for '{ds['name']}' "
                  f"(CRS={ds['original_crs']}): {exc}", file=sys.stderr)
            ds["bbox"] = [-180.0, -90.0, 180.0, 90.0]

    for ds in datasets:
        ds["theme"] = map_theme(
            ds["raw_theme"], ds["name"], ds.get("description", ""),
            config["taxonomy"],
        )

    spatial_overlaps = compute_spatial_overlaps(datasets)
    temporal_overlaps = compute_temporal_overlaps(datasets)
    duplicate_candidates = detect_duplicates(
        datasets, config.get("duplicate_thresholds", {}),
    )
    aoi_coverage = compute_aoi_coverage(datasets, config["aoi"]["bbox"])
    stac_items = generate_stac_items(datasets)

    report = {
        "datasets": [serialize_dataset(ds) for ds in datasets],
        "spatial_overlaps": spatial_overlaps,
        "temporal_overlaps": temporal_overlaps,
        "aoi_coverage": aoi_coverage,
        "duplicate_candidates": duplicate_candidates,
        "stac_items": stac_items,
        "data_quality": quality_issues,
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Report written to {output_path}")
    print(f"  Datasets: {len(datasets)}")
    print(f"  Spatial overlaps: {len(spatial_overlaps)}")
    print(f"  Temporal overlaps: {len(temporal_overlaps)}")
    print(f"  Duplicate candidates: {len(duplicate_candidates)}")
    print(f"  Data quality issues: {len(quality_issues)}")


# ===================================================================
# CRS mismatch detection
# ===================================================================

def detect_and_fix_crs_mismatches(datasets):
    """Detect datasets where declared CRS doesn't match coordinate values."""
    issues = []
    for ds in datasets:
        bbox = ds.get("bbox_native")
        crs_str = ds.get("original_crs", "EPSG:4326")

        if bbox is None:
            continue

        w, s, e, n = [float(v) for v in bbox]

        # Check if CRS claims to be geographic but coordinates are in meters
        is_geographic = False
        try:
            crs_obj = CRS.from_user_input(crs_str)
            is_geographic = crs_obj.is_geographic
        except Exception:
            # If we can't parse CRS, check manually
            crs_upper = str(crs_str).upper()
            if crs_upper in ("EPSG:4326", "EPSG:4269", "EPSG:4258"):
                is_geographic = True

        if is_geographic:
            # Geographic CRS uses degrees; values > 360 mean projected units
            if abs(w) > 360 or abs(s) > 360 or abs(e) > 360 or abs(n) > 360:
                corrected_crs = _guess_crs_from_metadata(ds)
                if corrected_crs:
                    issues.append({
                        "dataset": ds["name"],
                        "issue_type": "crs_mismatch",
                        "description": (
                            f"Declared CRS '{crs_str}' is geographic but bounding box "
                            f"values ({w}, {s}, {e}, {n}) are in projected units "
                            f"(meters). Corrected to '{corrected_crs}' based on "
                            f"metadata analysis."
                        ),
                    })
                    ds["original_crs"] = corrected_crs
                    print(f"CRS corrected for '{ds['name']}': "
                          f"{crs_str} -> {corrected_crs}", file=sys.stderr)
                else:
                    issues.append({
                        "dataset": ds["name"],
                        "issue_type": "crs_mismatch",
                        "description": (
                            f"Declared CRS '{crs_str}' is geographic but bounding box "
                            f"values ({w}, {s}, {e}, {n}) are in projected units "
                            f"(meters). Could not determine correct CRS from metadata."
                        ),
                    })
                    print(f"Warning: CRS mismatch for '{ds['name']}' but no "
                          f"correction found", file=sys.stderr)

    return issues


def _guess_crs_from_metadata(ds):
    """Search metadata text fields for CRS hints."""
    texts = []
    for field in ["description", "notes", "processing_notes", "abstract",
                   "summary", "info"]:
        val = ds.get(field, "")
        if val:
            texts.append(str(val))

    search_text = " ".join(texts).lower()

    # Look for UTM zone references like "UTM Zone 36S"
    m = re.search(r"utm\s+zone\s+(\d+)\s*([ns])", search_text)
    if m:
        zone = int(m.group(1))
        hemisphere = m.group(2).lower()
        if hemisphere == "s":
            return f"EPSG:{32700 + zone}"
        else:
            return f"EPSG:{32600 + zone}"

    # Look for EPSG codes mentioned in text
    m = re.search(r"epsg[:\s]+(\d{4,5})", search_text)
    if m:
        return f"EPSG:{m.group(1)}"

    return None


# ===================================================================
# Parsing
# ===================================================================

def parse_all_files(dirpath):
    datasets = []
    parsed_files = []
    failed_files = []

    for f in sorted(Path(dirpath).iterdir()):
        if not f.is_file():
            continue
        try:
            ds = parse_file(f)
            if ds:
                datasets.append(ds)
                parsed_files.append(f.name)
            else:
                failed_files.append((f.name, "parse_file returned None"))
        except Exception as e:
            failed_files.append((f.name, str(e)))
            print(f"Warning: failed to parse {f}: {e}", file=sys.stderr)

    if failed_files:
        print(f"WARNING: {len(failed_files)} files failed to parse: "
              f"{failed_files}", file=sys.stderr)

    print(f"Successfully parsed files: {parsed_files}", file=sys.stderr)
    return datasets


def parse_file(filepath):
    filepath = Path(filepath)
    ext = filepath.suffix.lower()

    if ext == ".json":
        with open(filepath) as f:
            raw = json.load(f)
    elif ext in (".yaml", ".yml"):
        with open(filepath) as f:
            raw = yaml.safe_load(f)
    elif ext == ".csv":
        raw = _parse_csv_kv(filepath)
    else:
        return None

    if raw is None:
        print(f"Warning: {filepath} parsed to None", file=sys.stderr)
        return None

    return _extract_metadata(raw, filepath)


def _parse_csv_kv(filepath):
    data = {}
    with open(filepath) as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) >= 2:
                key = row[0].strip()
                if key.lower() != "field":
                    data[key] = row[1].strip()
    return data


def _extract_metadata(raw, filepath):
    name = _extract_field(
        raw,
        ["name", "title", "full_name", "dataset_name", "product_name",
         "dataset", "identifier"],
        default=filepath.stem,
    )
    description = _extract_field(
        raw, ["description", "abstract", "summary", "info"], default="",
    )
    original_crs = _extract_crs(raw)
    bbox_native = _extract_bbox(raw)
    temporal_start, temporal_end = _extract_temporal(raw)
    resolution_m = _extract_resolution(raw)
    bands = _extract_bands(raw)
    provider = _extract_field(
        raw,
        ["provider", "source", "data_provider", "origin", "institution",
         "organization", "creator", "data_source", "producer"],
        default="",
    )
    license_info = _extract_field(
        raw,
        ["license", "license_type", "data_license", "use_terms", "access",
         "terms", "usage_rights", "usage"],
        default="",
    )
    raw_theme = _extract_field(
        raw,
        ["theme", "category", "classification", "topic", "thematic_area",
         "domain", "field", "thematic_category"],
        default="",
    )
    processing_notes = _extract_field(
        raw,
        ["processing_notes", "notes", "metadata_notes", "processing_info"],
        default="",
    )

    return {
        "name": str(name),
        "description": str(description),
        "original_crs": original_crs,
        "bbox_native": bbox_native,
        "bbox": None,
        "temporal_start": temporal_start,
        "temporal_end": temporal_end,
        "resolution_m": resolution_m,
        "bands": bands,
        "provider": str(provider),
        "license": str(license_info),
        "raw_theme": str(raw_theme),
        "theme": None,
        "processing_notes": str(processing_notes),
    }


# ===================================================================
# Field extraction helpers
# ===================================================================

def _extract_field(data, keys, default=None):
    for key in keys:
        if key in data:
            val = data[key]
            if isinstance(val, (dict, list)):
                continue
            return val
    return default


def _extract_crs(data):
    # First pass: common CRS keys
    for key in ["spatial_reference", "crs", "srs", "projection",
                "coordinate_system"]:
        if key in data:
            val = data[key]
            if isinstance(val, str):
                upper = val.upper()
                if upper.startswith(("EPSG:", "ESRI:")):
                    return val
                if val.startswith("+proj"):
                    return val
                try:
                    return f"EPSG:{int(val)}"
                except ValueError:
                    return val
            elif isinstance(val, int):
                return f"EPSG:{val}"
            elif isinstance(val, dict):
                return _crs_from_dict(val)

    # Second pass: EPSG-specific keys
    for key in ["epsg", "crs_epsg"]:
        if key in data:
            val = data[key]
            if isinstance(val, int):
                return f"EPSG:{val}"
            if isinstance(val, str):
                try:
                    return f"EPSG:{int(val)}"
                except ValueError:
                    return val

    # Third pass: long-form keys
    for key in ["coordinate_reference_system", "spatial_ref",
                "spatial_reference_system"]:
        if key in data:
            val = data[key]
            if isinstance(val, dict):
                return _crs_from_dict(val)
            if isinstance(val, str):
                return val

    return "EPSG:4326"


def _crs_from_dict(d):
    if "authority" in d and "code" in d:
        return f"{d['authority']}:{d['code']}"
    if "epsg" in d and d["epsg"] is not None:
        return f"EPSG:{d['epsg']}"
    if "code" in d:
        val = str(d["code"])
        if val.upper().startswith(("EPSG:", "ESRI:")):
            return val
        try:
            return f"EPSG:{int(val)}"
        except ValueError:
            return val
    for key in ["proj4", "proj_string", "proj"]:
        if key in d:
            return d[key]
    if "type" in d:
        crs_type = str(d["type"]).lower()
        if "sinusoidal" in crs_type:
            return "+proj=sinu +lon_0=0 +x_0=0 +y_0=0 +R=6371007.181 +units=m +no_defs"
        if "homolosine" in crs_type or "igh" in crs_type:
            return "+proj=igh +datum=WGS84 +no_defs"
    return "EPSG:4326"


def _extract_bbox(data):
    if "bbox" in data:
        val = data["bbox"]
        if isinstance(val, list) and len(val) == 4:
            return [float(v) for v in val]

    for key in ["extent", "bounding_box", "bounds", "geographic_extent",
                "spatial_extent", "geographic_bounds"]:
        if key in data and isinstance(data[key], dict):
            result = _bbox_from_dict(data[key])
            if result:
                return result

    result = _bbox_from_flat(data)
    if result:
        return result

    return [-180.0, -90.0, 180.0, 90.0]


_WEST_KEYS = [
    "west", "min_x", "x_min", "xmin", "left", "min_longitude",
    "west_longitude", "lon_min", "westBoundLongitude",
]
_SOUTH_KEYS = [
    "south", "min_y", "y_min", "ymin", "bottom", "min_latitude",
    "south_latitude", "lat_min", "southBoundLatitude",
]
_EAST_KEYS = [
    "east", "max_x", "x_max", "xmax", "right", "max_longitude",
    "east_longitude", "lon_max", "eastBoundLongitude",
]
_NORTH_KEYS = [
    "north", "max_y", "y_max", "ymax", "top", "max_latitude",
    "north_latitude", "lat_max", "northBoundLatitude",
]


def _first_float(d, keys):
    for k in keys:
        if k in d:
            try:
                return float(d[k])
            except (ValueError, TypeError):
                continue
    return None


def _bbox_from_dict(d):
    w = _first_float(d, _WEST_KEYS)
    s = _first_float(d, _SOUTH_KEYS)
    e = _first_float(d, _EAST_KEYS)
    n = _first_float(d, _NORTH_KEYS)
    if all(v is not None for v in [w, s, e, n]):
        return [w, s, e, n]
    return None


def _bbox_from_flat(data):
    flat_west = ["west_bound", "west", "min_x", "x_min"]
    flat_south = ["south_bound", "south", "min_y", "y_min"]
    flat_east = ["east_bound", "east", "max_x", "x_max"]
    flat_north = ["north_bound", "north", "max_y", "y_max"]
    w = _first_float(data, flat_west)
    s = _first_float(data, flat_south)
    e = _first_float(data, flat_east)
    n = _first_float(data, flat_north)
    if all(v is not None for v in [w, s, e, n]):
        return [w, s, e, n]
    return None


def _extract_temporal(data):
    # Range string fields: "start/end", "YYYY/YYYY"
    for key in ["time_coverage", "time_range", "temporal_coverage",
                "time_extent"]:
        if key in data and isinstance(data[key], str):
            val = data[key]
            if "/" in val:
                parts = val.split("/")
                if len(parts) == 2:
                    start = _parse_date_str(parts[0].strip(), is_start=True)
                    end = _parse_date_str(parts[1].strip(), is_start=False)
                    if start and end:
                        return start, end

    # Dict temporal fields
    for key in ["temporal_range", "date_range", "time_period",
                "temporal_coverage", "temporal_extent", "period"]:
        if key in data and isinstance(data[key], dict):
            d = data[key]
            start = end = None
            for sk in ["start", "begin", "from", "start_datetime"]:
                if sk in d:
                    start = _parse_date_value(d[sk], is_start=True)
                    break
            for ek in ["end", "to", "end_datetime"]:
                if ek in d:
                    end = _parse_date_value(d[ek], is_start=False)
                    break
            if start and end:
                return start, end

    # Separate top-level fields
    start = end = None
    for sk in ["start_date", "start_datetime", "start_time"]:
        if sk in data:
            start = _parse_date_value(data[sk], is_start=True)
            break
    for ek in ["end_date", "end_datetime", "end_time"]:
        if ek in data:
            end = _parse_date_value(data[ek], is_start=False)
            break
    if start and end:
        return start, end

    # Year-only fields
    if "start_year" in data and "end_year" in data:
        return (
            f"{int(data['start_year'])}-01-01",
            f"{int(data['end_year'])}-12-31",
        )

    return None, None


def _parse_date_value(val, is_start=True):
    if isinstance(val, (int, float)):
        if val > 1e9:
            return datetime.fromtimestamp(val, tz=timezone.utc).strftime("%Y-%m-%d")
        elif val < 3000:
            return f"{int(val)}-01-01" if is_start else f"{int(val)}-12-31"
    if isinstance(val, str):
        return _parse_date_str(val, is_start)
    return None


def _parse_date_str(s, is_start=True):
    s = s.strip()

    if re.match(r"^\d{4}$", s):
        year = int(s)
        return f"{year}-01-01" if is_start else f"{year}-12-31"

    m = re.match(r"^(\d{4})/(\d{1,2})/(\d{1,2})$", s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    m = re.match(r"^(\d{4}-\d{2}-\d{2})", s)
    if m:
        return m.group(1)

    try:
        dt = dateparser.parse(s)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        pass

    return None


def _extract_resolution(data):
    for key in [
        "resolution_meters", "resolution_m", "resolution", "pixel_size",
        "pixel_spacing_m", "spatial_resolution", "spatial_resolution_m",
        "ground_sample_distance_m", "native_resolution_m",
        "ground_resolution_m",
    ]:
        if key in data:
            try:
                return float(data[key])
            except (ValueError, TypeError):
                continue

    if "cell_size_arcsec" in data:
        try:
            arcsec = float(data["cell_size_arcsec"])
            return round(arcsec * (111000.0 / 3600.0), 2)
        except (ValueError, TypeError):
            pass

    return None


def _extract_bands(data):
    for key in [
        "bands", "layers", "variables", "parameters", "science_data_sets",
        "data_fields", "outputs", "data_layers",
    ]:
        if key in data and isinstance(data[key], list):
            result = []
            for item in data[key]:
                if isinstance(item, str):
                    result.append(item)
                elif isinstance(item, dict):
                    result.append(item.get("name", str(item)))
            return result

    if "band_names" in data:
        return [b.strip() for b in str(data["band_names"]).split(",")]

    return []


# ===================================================================
# CRS normalization
# ===================================================================

def _is_wgs84(crs_string):
    try:
        crs = CRS.from_user_input(crs_string)
        epsg = crs.to_epsg()
        return epsg == 4326
    except Exception:
        return str(crs_string).upper() in ("EPSG:4326", "4326")


def normalize_bbox_to_wgs84(bbox, crs_string):
    if bbox is None:
        return [-180.0, -90.0, 180.0, 90.0]

    if _is_wgs84(crs_string):
        return [float(v) for v in bbox]

    xmin, ymin, xmax, ymax = (float(v) for v in bbox)

    try:
        src_crs = CRS.from_user_input(crs_string)
        dst_crs = CRS.from_epsg(4326)
        transformer = Transformer.from_crs(src_crs, dst_crs, always_xy=True)
    except Exception as e:
        print(f"CRS creation error for '{crs_string}': {e}", file=sys.stderr)
        return [-180.0, -90.0, 180.0, 90.0]

    # Use dense grid sampling — this handles projections with non-rectangular
    # valid areas (Mollweide ellipse, IGH lobes, etc.) much better than
    # edge-only densification, since many edge/corner points fall outside
    # the valid projection domain and produce NaN.
    all_lons = []
    all_lats = []

    # Grid interior sampling
    try:
        n_grid = 80
        xs = np.linspace(xmin, xmax, n_grid)
        ys = np.linspace(ymin, ymax, n_grid)
        gx, gy = np.meshgrid(xs, ys)
        lons, lats = transformer.transform(gx.ravel(), gy.ravel())
        lons = np.asarray(lons)
        lats = np.asarray(lats)
        valid = np.isfinite(lons) & np.isfinite(lats)
        all_lons.extend(lons[valid].tolist())
        all_lats.extend(lats[valid].tolist())
    except Exception as e:
        print(f"Grid sampling failed for '{crs_string}': {e}", file=sys.stderr)

    # Edge densification as supplement
    try:
        n_pts = 60
        edge_x, edge_y = [], []
        for x in np.linspace(xmin, xmax, n_pts):
            edge_x.extend([x, x])
            edge_y.extend([ymin, ymax])
        for y in np.linspace(ymin, ymax, n_pts):
            edge_x.extend([xmin, xmax])
            edge_y.extend([y, y])
        lons, lats = transformer.transform(edge_x, edge_y)
        for lon, lat in zip(lons, lats):
            if np.isfinite(lon) and np.isfinite(lat):
                all_lons.append(lon)
                all_lats.append(lat)
    except Exception as e:
        print(f"Edge densification failed for '{crs_string}': {e}",
              file=sys.stderr)

    if all_lons and all_lats:
        return [
            max(min(all_lons), -180.0),
            max(min(all_lats), -90.0),
            min(max(all_lons), 180.0),
            min(max(all_lats), 90.0),
        ]

    # Last resort: transform_bounds
    try:
        result = transformer.transform_bounds(
            xmin, ymin, xmax, ymax, densify_pts=21
        )
        w, s, e, n = result
        if all(np.isfinite(v) for v in [w, s, e, n]):
            return [
                max(w, -180.0),
                max(s, -90.0),
                min(e, 180.0),
                min(n, 90.0),
            ]
    except Exception as e:
        print(f"transform_bounds failed for '{crs_string}': {e}",
              file=sys.stderr)

    print(f"Warning: all reprojection methods failed for CRS '{crs_string}', "
          f"returning global bbox", file=sys.stderr)
    return [-180.0, -90.0, 180.0, 90.0]


# ===================================================================
# Theme mapping
# ===================================================================

def map_theme(raw_theme, name, description, taxonomy):
    raw = str(raw_theme).lower().strip()
    text = f"{raw} {name} {description}".lower()

    for canonical in taxonomy:
        if raw == canonical or raw.replace(" ", "_") == canonical:
            return canonical

    for canonical, keywords in taxonomy.items():
        for kw in keywords:
            if kw in text:
                return canonical

    return raw_theme if raw_theme else "other"


# ===================================================================
# Spatial overlaps
# ===================================================================

def _bbox_intersection(b1, b2):
    w = max(b1[0], b2[0])
    s = max(b1[1], b2[1])
    e = min(b1[2], b2[2])
    n = min(b1[3], b2[3])
    if w >= e or s >= n:
        return None
    return [w, s, e, n]


def _bbox_area(b):
    return (b[2] - b[0]) * (b[3] - b[1])


def compute_spatial_overlaps(datasets):
    overlaps = []
    for i in range(len(datasets)):
        for j in range(i + 1, len(datasets)):
            inter = _bbox_intersection(datasets[i]["bbox"], datasets[j]["bbox"])
            if inter:
                inter_area = _bbox_area(inter)
                union_area = (
                    _bbox_area(datasets[i]["bbox"])
                    + _bbox_area(datasets[j]["bbox"])
                    - inter_area
                )
                iou = inter_area / union_area if union_area > 0 else 0.0
                overlaps.append({
                    "dataset_a": datasets[i]["name"],
                    "dataset_b": datasets[j]["name"],
                    "intersection_area_sq_deg": round(inter_area, 2),
                    "iou": round(iou, 5),
                })
    return overlaps


# ===================================================================
# Temporal overlaps
# ===================================================================

def compute_temporal_overlaps(datasets):
    overlaps = []
    for i in range(len(datasets)):
        for j in range(i + 1, len(datasets)):
            di, dj = datasets[i], datasets[j]
            if not all([di["temporal_start"], di["temporal_end"],
                        dj["temporal_start"], dj["temporal_end"]]):
                continue
            try:
                s_i = datetime.strptime(di["temporal_start"], "%Y-%m-%d")
                e_i = datetime.strptime(di["temporal_end"], "%Y-%m-%d")
                s_j = datetime.strptime(dj["temporal_start"], "%Y-%m-%d")
                e_j = datetime.strptime(dj["temporal_end"], "%Y-%m-%d")
            except ValueError:
                continue

            overlap_start = max(s_i, s_j)
            overlap_end = min(e_i, e_j)
            days = (overlap_end - overlap_start).days

            if days > 0:
                overlaps.append({
                    "dataset_a": di["name"],
                    "dataset_b": dj["name"],
                    "overlap_days": days,
                })
    return overlaps


# ===================================================================
# Duplicate detection
# ===================================================================

def _name_similarity(n1, n2):
    def tokenize(n):
        stop = {"the", "and", "for", "from", "with", "global", "data",
                "dataset", "version"}
        return set(re.findall(r"[a-zA-Z]{3,}", n.lower())) - stop

    t1, t2 = tokenize(n1), tokenize(n2)
    if not t1 or not t2:
        return 0.0
    return len(t1 & t2) / min(len(t1), len(t2))


def detect_duplicates(datasets, thresholds):
    bbox_tol = thresholds.get("bbox_tolerance_deg", 1.0)
    res_ratio = thresholds.get("resolution_ratio", 2.0)

    pairs = []
    for i in range(len(datasets)):
        for j in range(i + 1, len(datasets)):
            d1, d2 = datasets[i], datasets[j]

            if _name_similarity(d1["name"], d2["name"]) < 0.3:
                continue

            b1, b2 = d1["bbox"], d2["bbox"]
            if not all(abs(b1[k] - b2[k]) <= bbox_tol for k in range(4)):
                continue

            r1, r2 = d1.get("resolution_m"), d2.get("resolution_m")
            if r1 and r2 and r1 > 0 and r2 > 0:
                if max(r1, r2) / min(r1, r2) > res_ratio:
                    continue

            if all([d1["temporal_start"], d1["temporal_end"],
                    d2["temporal_start"], d2["temporal_end"]]):
                s1 = datetime.strptime(d1["temporal_start"], "%Y-%m-%d")
                e1 = datetime.strptime(d1["temporal_end"], "%Y-%m-%d")
                s2 = datetime.strptime(d2["temporal_start"], "%Y-%m-%d")
                e2 = datetime.strptime(d2["temporal_end"], "%Y-%m-%d")
                ov_start = max(s1, s2)
                ov_end = min(e1, e2)
                if ov_end <= ov_start:
                    continue
                span = max((e1 - s1).days, (e2 - s2).days)
                if span > 0 and (ov_end - ov_start).days / span < 0.5:
                    continue

            pairs.append([d1["name"], d2["name"]])
    return pairs


# ===================================================================
# AOI coverage
# ===================================================================

def compute_aoi_coverage(datasets, aoi_bbox):
    aoi_area = _bbox_area(aoi_bbox)
    coverage = {}
    for ds in datasets:
        inter = _bbox_intersection(ds["bbox"], aoi_bbox)
        if inter:
            pct = (_bbox_area(inter) / aoi_area) * 100.0
            coverage[ds["name"]] = round(min(pct, 100.0), 2)
        else:
            coverage[ds["name"]] = 0.0
    return coverage


# ===================================================================
# STAC generation
# ===================================================================

def generate_stac_items(datasets):
    items = []
    for ds in datasets:
        w, s, e, n = ds["bbox"]

        geometry = {
            "type": "Polygon",
            "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]],
        }

        dt_str = None
        start_dt = ds.get("temporal_start")
        end_dt = ds.get("temporal_end")
        if start_dt and end_dt and start_dt == end_dt:
            dt_str = f"{start_dt}T00:00:00Z"

        properties = {"datetime": dt_str}
        if start_dt:
            properties["start_datetime"] = f"{start_dt}T00:00:00Z"
        if end_dt:
            properties["end_datetime"] = f"{end_dt}T00:00:00Z"
        if ds.get("theme"):
            properties["theme"] = ds["theme"]

        item_id = re.sub(
            r"[^a-zA-Z0-9_-]", "_", ds["name"].lower().replace(" ", "_"),
        )

        items.append({
            "type": "Feature",
            "stac_version": "1.0.0",
            "id": item_id,
            "geometry": geometry,
            "bbox": [w, s, e, n],
            "properties": properties,
            "links": [],
            "assets": {
                "data": {
                    "href": f"https://example.com/datasets/{item_id}",
                    "type": "application/geo+json",
                    "title": ds["name"],
                }
            },
        })
    return items


# ===================================================================
# Serialization
# ===================================================================

def serialize_dataset(ds):
    return {
        "name": ds["name"],
        "description": ds.get("description", ""),
        "bbox": ds["bbox"],
        "temporal_start": ds.get("temporal_start"),
        "temporal_end": ds.get("temporal_end"),
        "resolution_m": ds.get("resolution_m"),
        "original_crs": ds.get("original_crs", "EPSG:4326"),
        "theme": ds.get("theme", ""),
        "bands": ds.get("bands", []),
        "provider": ds.get("provider", ""),
        "license": ds.get("license", ""),
    }


if __name__ == "__main__":
    main()
