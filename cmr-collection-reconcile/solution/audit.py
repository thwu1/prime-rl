#!/usr/bin/env python3

"""NASA CMR-to-STAC Translation Audit Tool.

Cross-references CMR JSON feed cache against STAC collection files
to detect translation errors introduced by an automated pipeline.
"""

import json
import os
import glob


def load_cmr_cache(path):
    """Load CMR feed JSON and return dict keyed by concept_id."""
    with open(path) as f:
        data = json.load(f)
    return {entry["id"]: entry for entry in data["feed"]["entry"]}


def load_stac_collections(directory):
    """Load all STAC collection JSON files from a directory."""
    collections = {}
    for filepath in sorted(glob.glob(os.path.join(directory, "*.json"))):
        with open(filepath) as f:
            coll = json.load(f)
        collections[coll["id"]] = coll
    return collections


def parse_cmr_box_to_stac_bbox(box_str):
    """Convert CMR box string 'south west north east' to STAC bbox [west, south, east, north]."""
    parts = [float(x) for x in box_str.split()]
    south, west, north, east = parts
    return [west, south, east, north]


def normalize_datetime(dt_str):
    """Normalize CMR/STAC datetime strings for comparison."""
    if dt_str is None:
        return None
    return dt_str.replace(".000Z", "Z")


def cmr_level_to_stac(level_id):
    """Convert CMR processing_level_id to STAC processing:level format."""
    return f"L{level_id}"


def compare_bbox(expected, actual):
    """Compare two STAC-format bboxes with tolerance."""
    if len(expected) != len(actual):
        return False
    return all(abs(a - b) < 1e-6 for a, b in zip(expected, actual))


def compare_temporal(cmr_entry, stac_interval):
    """Compare CMR temporal fields against STAC temporal interval."""
    cmr_start = normalize_datetime(cmr_entry.get("time_start", ""))
    cmr_end = normalize_datetime(cmr_entry.get("time_end"))

    stac_start = normalize_datetime(stac_interval[0]) if stac_interval[0] else None
    stac_end = normalize_datetime(stac_interval[1]) if stac_interval[1] else None

    if cmr_start and stac_start:
        if cmr_start.rstrip("Z") != stac_start.rstrip("Z"):
            return False
    if cmr_end and stac_end:
        if cmr_end.rstrip("Z") != stac_end.rstrip("Z"):
            return False
    if (cmr_end is None) != (stac_end is None):
        return False
    return True


def classify_severity(error_type, cmr_val, stac_val):
    """Classify error severity based on downstream impact.

    - critical: wrong coordinates or impossible temporal ranges that would cause
      incorrect geospatial queries or data retrieval
    - major: wrong processing level or significant temporal gaps that would cause
      incomplete or wrong collection selection
    - minor: cosmetic differences (case normalization) that do not affect query results
    """
    if error_type == "spatial_error":
        return "critical"

    if error_type == "temporal_error":
        # Swapped dates (start > end) are critical; stale dates are major
        if isinstance(cmr_val, list) and isinstance(stac_val, list):
            if (len(cmr_val) >= 2 and len(stac_val) >= 2
                    and stac_val[0] and stac_val[1] and cmr_val[0] and cmr_val[1]):
                cmr_s = normalize_datetime(cmr_val[0])
                cmr_e = normalize_datetime(cmr_val[1])
                stac_s = normalize_datetime(stac_val[0])
                stac_e = normalize_datetime(stac_val[1])
                if (stac_s and stac_e and cmr_s and cmr_e
                        and stac_s.rstrip("Z") == cmr_e.rstrip("Z")
                        and stac_e.rstrip("Z") == cmr_s.rstrip("Z")):
                    return "critical"
        return "major"

    if error_type == "level_error":
        return "major"

    if error_type == "platform_error":
        if isinstance(cmr_val, list) and isinstance(stac_val, list):
            if sorted(p.lower() for p in cmr_val) == sorted(p.lower() for p in stac_val):
                return "minor"
        return "major"

    return "major"


def main():
    cmr_entries = load_cmr_cache("/app/cmr_cache.json")
    stac_collections = load_stac_collections("/app/stac_collections")

    cmr_ids = set(cmr_entries.keys())
    stac_ids = set(stac_collections.keys())

    matched_ids = cmr_ids & stac_ids
    missing_stac = sorted(cmr_ids - stac_ids)
    orphaned_stac = sorted(stac_ids - cmr_ids)

    errors = []

    for cid in sorted(matched_ids):
        cmr = cmr_entries[cid]
        stac = stac_collections[cid]

        # ── Spatial extent comparison ────────────────────────────────────────
        if cmr.get("boxes"):
            expected_bbox = parse_cmr_box_to_stac_bbox(cmr["boxes"][0])
            actual_bbox = stac["extent"]["spatial"]["bbox"][0]
            if not compare_bbox(expected_bbox, actual_bbox):
                errors.append({
                    "collection_id": cid,
                    "error_type": "spatial_error",
                    "field": "extent.spatial.bbox",
                    "cmr_value": expected_bbox,
                    "stac_value": actual_bbox,
                    "severity": classify_severity("spatial_error", expected_bbox, actual_bbox)
                })

        # ── Temporal extent comparison ───────────────────────────────────────
        stac_interval = stac["extent"]["temporal"]["interval"][0]
        if not compare_temporal(cmr, stac_interval):
            cmr_temporal = [
                normalize_datetime(cmr.get("time_start", "")),
                normalize_datetime(cmr.get("time_end"))
            ]
            stac_temporal = [
                normalize_datetime(stac_interval[0]) if stac_interval[0] else None,
                normalize_datetime(stac_interval[1]) if stac_interval[1] else None
            ]
            errors.append({
                "collection_id": cid,
                "error_type": "temporal_error",
                "field": "extent.temporal.interval",
                "cmr_value": cmr_temporal,
                "stac_value": stac_temporal,
                "severity": classify_severity("temporal_error", cmr_temporal, stac_temporal)
            })

        # ── Platform comparison ──────────────────────────────────────────────
        cmr_platforms = sorted(cmr.get("platforms", []))
        stac_platforms = sorted(stac.get("summaries", {}).get("platform", []))
        if cmr_platforms != stac_platforms:
            errors.append({
                "collection_id": cid,
                "error_type": "platform_error",
                "field": "summaries.platform",
                "cmr_value": cmr_platforms,
                "stac_value": stac_platforms,
                "severity": classify_severity("platform_error", cmr_platforms, stac_platforms)
            })

        # ── Processing level comparison ──────────────────────────────────────
        cmr_level = cmr_level_to_stac(cmr.get("processing_level_id", ""))
        stac_level = stac.get("summaries", {}).get("processing:level", "")
        if cmr_level != stac_level:
            errors.append({
                "collection_id": cid,
                "error_type": "level_error",
                "field": "summaries.processing:level",
                "cmr_value": cmr_level,
                "stac_value": stac_level,
                "severity": classify_severity("level_error", cmr_level, stac_level)
            })

    # ── Compute summary ──────────────────────────────────────────────────────
    critical = sum(1 for e in errors if e["severity"] == "critical")
    major = sum(1 for e in errors if e["severity"] == "major")
    minor = sum(1 for e in errors if e["severity"] == "minor")

    report = {
        "collections_audited": len(matched_ids),
        "missing_stac": missing_stac,
        "orphaned_stac": orphaned_stac,
        "errors": errors,
        "summary": {
            "total_cmr_collections": len(cmr_ids),
            "total_stac_files": len(stac_ids),
            "total_matched": len(matched_ids),
            "total_errors": len(errors),
            "critical_count": critical,
            "major_count": major,
            "minor_count": minor
        }
    }

    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/audit_report.json", "w") as f:
        json.dump(report, f, indent=2)


if __name__ == "__main__":
    main()
