#!/usr/bin/env python3
"""
EPT Dataset Validator and Fixer — LAS 1.4 data tiles.

Reads binary LAS tiles via laspy, audits for EPT / LAS 1.4 / USGS LBS
violations, produces a corrected dataset, audit report, and PDAL pipeline.
"""
import json
import os
import shutil

import numpy as np
import laspy

DATASET = "/app/dataset"
FIXED = "/app/dataset_fixed"
REPORT = "/app/audit_report.json"
PIPELINE = "/app/remediation.json"


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def load_ept(base):
    with open(os.path.join(base, "ept.json")) as f:
        return json.load(f)


def load_hierarchy(base):
    with open(os.path.join(base, "ept-hierarchy", "0-0-0-0.json")) as f:
        return json.load(f)


def load_all_las(base):
    """Return {node_key: laspy.LasData}."""
    result = {}
    data_dir = os.path.join(base, "ept-data")
    for fname in sorted(os.listdir(data_dir)):
        if fname.endswith(".las"):
            result[fname[:-4]] = laspy.read(os.path.join(data_dir, fname))
    return result


def get_point_ids(las):
    """Extract PointId extra dimension via direct attribute access."""
    return np.array(las.PointId, dtype=np.uint32)


# ---------------------------------------------------------------------------
# Octree helpers
# ---------------------------------------------------------------------------

def get_octant(px, py, pz, bounds):
    mid = [(bounds[i] + bounds[i + 3]) / 2 for i in range(3)]
    return (
        0 if px < mid[0] else 1,
        0 if py < mid[1] else 1,
        0 if pz < mid[2] else 1,
    )


def child_bounds(bounds, dx, dy, dz):
    mid = [(bounds[i] + bounds[i + 3]) / 2 for i in range(3)]
    return [
        bounds[0] if dx == 0 else mid[0],
        bounds[1] if dy == 0 else mid[1],
        bounds[2] if dz == 0 else mid[2],
        mid[0] if dx == 0 else bounds[3],
        mid[1] if dy == 0 else bounds[4],
        mid[2] if dz == 0 else bounds[5],
    ]


def compute_node_bounds(root_bounds, depth, x, y, z):
    cells = 2 ** depth
    cell = [(root_bounds[i + 3] - root_bounds[i]) / cells for i in range(3)]
    return [
        root_bounds[0] + x * cell[0],
        root_bounds[1] + y * cell[1],
        root_bounds[2] + z * cell[2],
        root_bounds[0] + (x + 1) * cell[0],
        root_bounds[1] + (y + 1) * cell[1],
        root_bounds[2] + (z + 1) * cell[2],
    ]


def build_tree(pts, bounds, span, d=0, x=0, y=0, z=0, max_depth=8):
    key = f"{d}-{x}-{y}-{z}"
    if len(pts) <= span or d >= max_depth:
        return {key: list(pts)}
    buckets = {}
    for p in pts:
        o = get_octant(p["X"], p["Y"], p["Z"], bounds)
        buckets.setdefault(o, []).append(p)
    result = {}
    for (dx, dy, dz), bpts in buckets.items():
        cb = child_bounds(bounds, dx, dy, dz)
        result.update(
            build_tree(bpts, cb, span, d + 1,
                       2 * x + dx, 2 * y + dy, 2 * z + dz, max_depth)
        )
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ept = load_ept(DATASET)
    hierarchy = load_hierarchy(DATASET)
    las_files = load_all_las(DATASET)

    errors = []

    # Collect all points as dicts
    all_pts = []
    for key, las in las_files.items():
        pids = get_point_ids(las)
        for i in range(len(las.points)):
            all_pts.append({
                "PointId": int(pids[i]),
                "X": float(las.x[i]),
                "Y": float(las.y[i]),
                "Z": float(las.z[i]),
                "Intensity": int(las.intensity[i]),
                "Classification": int(las.classification[i]),
                "ReturnNumber": int(las.return_number[i]),
                "NumberOfReturns": int(las.number_of_returns[i]),
                "GPSTime": float(las.gps_time[i]),
                "Overlap": bool(las.overlap[i]),
            })

    # --- Check 1: Cubic bounds ---
    bounds = ept["bounds"]
    ranges = [bounds[i + 3] - bounds[i] for i in range(3)]
    if not (abs(ranges[0] - ranges[1]) < 0.001
            and abs(ranges[0] - ranges[2]) < 0.001):
        errors.append({
            "type": "non_cubic_bounds",
            "description": "EPT bounds must form a perfect cube",
            "details": {"x_range": ranges[0], "y_range": ranges[1],
                        "z_range": ranges[2]},
        })

    # Compute correct cubic bounds
    xs = [p["X"] for p in all_pts]
    ys = [p["Y"] for p in all_pts]
    zs = [p["Z"] for p in all_pts]
    conf_actual = [min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)]
    data_ranges = [conf_actual[3] - conf_actual[0],
                   conf_actual[4] - conf_actual[1],
                   conf_actual[5] - conf_actual[2]]
    max_r = max(data_ranges)
    ctr = [(conf_actual[i] + conf_actual[i + 3]) / 2 for i in range(3)]
    correct_cube = (
        [round(ctr[i] - max_r / 2, 3) for i in range(3)]
        + [round(ctr[i] + max_r / 2, 3) for i in range(3)]
    )

    # --- Check 2: boundsConforming ---
    bc = ept.get("boundsConforming", [])
    if bc:
        outside = False
        details = {}
        for i, axis in enumerate(["x", "y", "z"]):
            if bc[i] < bounds[i] - 0.001:
                outside = True
                details[f"{axis}_min_conf"] = bc[i]
                details[f"{axis}_min_bounds"] = bounds[i]
            if bc[i + 3] > bounds[i + 3] + 0.001:
                outside = True
                details[f"{axis}_max_conf"] = bc[i + 3]
                details[f"{axis}_max_bounds"] = bounds[i + 3]
        if outside:
            errors.append({
                "type": "conforming_bounds_outside_bounds",
                "description": "boundsConforming extends beyond outer bounds",
                "details": details,
            })

    # --- Check 3: Hierarchy count mismatches ---
    all_keys = set(list(hierarchy.keys()) + list(las_files.keys()))
    mismatches = []
    for key in sorted(all_keys):
        h_count = hierarchy.get(key)
        d_count = len(las_files[key].points) if key in las_files else None
        if h_count is not None and d_count is not None and h_count != d_count:
            mismatches.append({"node": key, "hierarchy": h_count,
                               "data": d_count})
        elif h_count is not None and d_count is None:
            mismatches.append({"node": key, "hierarchy": h_count,
                               "data": 0, "issue": "no data file"})
        elif h_count is None and d_count is not None:
            mismatches.append({"node": key, "hierarchy": 0,
                               "data": d_count, "issue": "no hierarchy entry"})
    if mismatches:
        errors.append({
            "type": "hierarchy_count_mismatch",
            "description": f"{len(mismatches)} nodes have inconsistent counts",
            "details": {"mismatches": mismatches},
        })

    # --- Check 4: Spatial misassignment ---
    spatial_errs = []
    for key, las in las_files.items():
        parts = key.split("-")
        d, nx, ny, nz = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
        nb = compute_node_bounds(correct_cube, d, nx, ny, nz)
        pids = get_point_ids(las)
        for i in range(len(las.points)):
            px, py, pz = float(las.x[i]), float(las.y[i]), float(las.z[i])
            if not (nb[0] - 0.001 <= px <= nb[3] + 0.001
                    and nb[1] - 0.001 <= py <= nb[4] + 0.001
                    and nb[2] - 0.001 <= pz <= nb[5] + 0.001):
                spatial_errs.append({
                    "point_id": int(pids[i]),
                    "current_node": key,
                    "coordinates": [px, py, pz],
                })
    if spatial_errs:
        errors.append({
            "type": "spatial_misassignment",
            "description": f"{len(spatial_errs)} points in incorrect octree nodes",
            "details": {"count": len(spatial_errs),
                        "examples": spatial_errs[:5]},
        })

    # --- Check 5: Schema phantom dimension ---
    schema_dims = {d["name"] for d in ept.get("schema", [])}
    actual_dims = {"X", "Y", "Z", "Intensity", "Classification",
                   "ReturnNumber", "NumberOfReturns", "GPSTime", "PointId"}
    phantom = schema_dims - actual_dims
    if phantom:
        errors.append({
            "type": "schema_dimension_mismatch",
            "description": f"Schema lists dimensions not in data: {sorted(phantom)}",
            "details": {"phantom_dimensions": sorted(phantom)},
        })

    # --- Check 6: Total point count ---
    actual_total = len(all_pts)
    if ept["points"] != actual_total:
        errors.append({
            "type": "total_point_count_mismatch",
            "description": "ept.json total point count incorrect",
            "details": {"ept_json": ept["points"], "actual": actual_total},
        })

    # --- Check 7 & 8: Invalid USGS classifications ---
    c0 = sum(1 for p in all_pts if p["Classification"] == 0)
    c12 = sum(1 for p in all_pts if p["Classification"] == 12)
    if c0 or c12:
        errors.append({
            "type": "invalid_usgs_classification",
            "description": "Points with prohibited USGS classification codes",
            "details": {
                "class_0_count": c0,
                "class_0_issue": "Classification 0 (Never Classified) prohibited",
                "class_12_count": c12,
                "class_12_issue": "Classification 12 deprecated; use overlap bit flag",
            },
        })

    # --- Check 9: Return number violations ---
    rn_bad = sum(1 for p in all_pts
                 if p["ReturnNumber"] > p["NumberOfReturns"])
    if rn_bad:
        errors.append({
            "type": "return_number_violation",
            "description": f"{rn_bad} points with ReturnNumber > NumberOfReturns",
            "details": {"count": rn_bad},
        })

    # --- Check 10: FileSourceID non-zero ---
    fsi_bad = []
    for key, las in las_files.items():
        if las.header.file_source_id != 0:
            fsi_bad.append({"node": key,
                            "file_source_id": int(las.header.file_source_id)})
    if fsi_bad:
        errors.append({
            "type": "file_source_id_nonzero",
            "description": "Tiled LAS files must have FileSourceID=0 per USGS LBS",
            "details": {"count": len(fsi_bad), "examples": fsi_bad[:5]},
        })

    # ===== Write audit report =====
    with open(REPORT, "w") as f:
        json.dump({"errors": errors, "error_count": len(errors)}, f, indent=2)
    print(f"Audit: {len(errors)} error categories detected")

    # ===== Fix dataset =====
    if os.path.exists(FIXED):
        shutil.rmtree(FIXED)
    os.makedirs(os.path.join(FIXED, "ept-data"), exist_ok=True)
    os.makedirs(os.path.join(FIXED, "ept-hierarchy"), exist_ok=True)

    # Fix point attributes
    for p in all_pts:
        # overlap flag for class 12
        if p["Classification"] == 12:
            p["Overlap"] = True
        # reclassify prohibited codes
        if p["Classification"] in (0, 12):
            p["Classification"] = 1
        # clamp return number
        if p["ReturnNumber"] > p["NumberOfReturns"]:
            p["ReturnNumber"] = p["NumberOfReturns"]

    # Rebuild octree with correct cubic bounds
    span = ept.get("span", 64)
    fixed_nodes = build_tree(all_pts, correct_cube, span)

    # Write corrected LAS tiles
    for key, pts in fixed_nodes.items():
        header = laspy.LasHeader(point_format=6, version="1.4")
        header.scales = np.array([0.001, 0.001, 0.001])
        header.offsets = np.array([500000.0, 4500000.0, 0.0])
        header.file_source_id = 0  # correct for tiled data
        header.add_extra_dim(
            laspy.ExtraBytesParams(name="PointId", type=np.uint32)
        )
        las = laspy.LasData(header)
        las.x = np.array([p["X"] for p in pts])
        las.y = np.array([p["Y"] for p in pts])
        las.z = np.array([p["Z"] for p in pts])
        las.intensity = np.array([p["Intensity"] for p in pts], dtype=np.uint16)
        las.classification = np.array(
            [p["Classification"] for p in pts], dtype=np.uint8
        )
        las.return_number = np.array(
            [p["ReturnNumber"] for p in pts], dtype=np.uint8
        )
        las.number_of_returns = np.array(
            [p["NumberOfReturns"] for p in pts], dtype=np.uint8
        )
        las.gps_time = np.array([p["GPSTime"] for p in pts])
        las.PointId = np.array([p["PointId"] for p in pts], dtype=np.uint32)
        las.overlap = np.array(
            [p.get("Overlap", False) for p in pts], dtype=bool
        )
        las.write(os.path.join(FIXED, "ept-data", f"{key}.las"))

    # Write corrected hierarchy
    fixed_hierarchy = {k: len(v) for k, v in fixed_nodes.items()}
    with open(os.path.join(FIXED, "ept-hierarchy", "0-0-0-0.json"), "w") as f:
        json.dump(fixed_hierarchy, f, indent=2)

    # Write corrected ept.json
    fixed_total = sum(len(v) for v in fixed_nodes.values())
    fixed_schema = [d for d in ept.get("schema", [])
                    if d["name"] in actual_dims]
    fixed_ept = {
        "bounds": correct_cube,
        "boundsConforming": conf_actual,
        "dataType": ept.get("dataType", "las"),
        "hierarchyType": ept.get("hierarchyType", "json"),
        "points": fixed_total,
        "schema": fixed_schema,
        "span": span,
        "srs": ept.get("srs", {}),
        "version": ept.get("version", "1.0.0"),
    }
    with open(os.path.join(FIXED, "ept.json"), "w") as f:
        json.dump(fixed_ept, f, indent=2)

    # ===== Write PDAL remediation pipeline =====
    pdal_pipeline = [
        {
            "type": "readers.las",
            "filename": "/app/dataset/ept-data/0-0-0-0.las",
        },
        {
            "type": "filters.assign",
            "value": [
                "Overlap = 1 WHERE Classification == 12",
                "Classification = 1 WHERE Classification == 0",
                "Classification = 1 WHERE Classification == 12",
                "ReturnNumber = NumberOfReturns WHERE ReturnNumber > NumberOfReturns",
            ],
        },
        {
            "type": "writers.las",
            "filename": "/tmp/corrected.las",
            "minor_version": 4,
            "dataformat_id": 6,
            "filesource_id": 0,
        },
    ]
    with open(PIPELINE, "w") as f:
        json.dump(pdal_pipeline, f, indent=2)

    print(f"Fixed dataset: {fixed_total} points, {len(fixed_nodes)} nodes")
    print(f"PDAL pipeline written to {PIPELINE}")


if __name__ == "__main__":
    main()
