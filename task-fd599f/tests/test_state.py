"""
Tests for the Geospatial Dataset Catalog Reconciler.

"""

import json
import pytest
import os


REPORT_PATH = "/app/output/report.json"


@pytest.fixture(scope="module")
def report():
    assert os.path.exists(REPORT_PATH), f"Report file not found at {REPORT_PATH}"
    with open(REPORT_PATH) as f:
        data = json.load(f)
    return data


# -- Structure and completeness ------------------------------------------------


def test_report_top_level_keys(report):
    """Report must contain all required top-level keys."""
    required_keys = {
        "datasets",
        "spatial_overlaps",
        "temporal_overlaps",
        "aoi_coverage",
        "duplicate_candidates",
        "stac_items",
        "data_quality",
    }
    missing = required_keys - set(report.keys())
    assert not missing, f"Missing top-level keys: {missing}"


def test_datasets_count(report):
    """All 13 metadata files must be parsed."""
    assert len(report["datasets"]) == 13, (
        f"Expected 13 datasets, got {len(report['datasets'])}"
    )


def test_dataset_required_fields(report):
    """Each dataset object must contain required normalized fields."""
    required = {"name", "bbox", "temporal_start", "temporal_end", "resolution_m", "original_crs", "theme"}
    for ds in report["datasets"]:
        missing = required - set(ds.keys())
        assert not missing, f"Dataset '{ds.get('name', '?')}' missing fields: {missing}"


# -- Bounding box validation ---------------------------------------------------


def test_wgs84_bbox_format(report):
    """All bboxes must be valid WGS84 [west, south, east, north]."""
    for ds in report["datasets"]:
        bbox = ds["bbox"]
        assert isinstance(bbox, list) and len(bbox) == 4, (
            f"bbox must be 4-element list for '{ds['name']}', got {bbox}"
        )
        west, south, east, north = bbox
        assert -180.0 <= west <= 180.0, f"west out of range for '{ds['name']}': {west}"
        assert -90.0 <= south <= 90.0, f"south out of range for '{ds['name']}': {south}"
        assert -180.0 <= east <= 180.0, f"east out of range for '{ds['name']}': {east}"
        assert -90.0 <= north <= 90.0, f"north out of range for '{ds['name']}': {north}"
        assert west <= east, f"west > east for '{ds['name']}'"
        assert south < north, f"south >= north for '{ds['name']}'"


def _find_datasets(datasets, keyword):
    """Find all datasets whose name contains keyword (case-insensitive)."""
    return [ds for ds in datasets if keyword.lower() in ds["name"].lower()]


def _find_dataset(datasets, keyword):
    """Find first dataset whose name contains keyword."""
    matches = _find_datasets(datasets, keyword)
    return matches[0] if matches else None


def test_known_wgs84_bboxes(report):
    """Datasets natively in EPSG:4326 must have exact expected bboxes."""
    expected_bboxes = {
        "esri": [-180.0, -90.0, 180.0, 90.0],
        "copernicus dem": [-180.0, -90.0, 180.0, 90.0],
        "landscan": [-180.0, -90.0, 180.0, 90.0],
        "forest change": [-180.0, -60.0, 180.0, 80.0],
        "surface water": [-180.0, -56.0, 180.0, 78.0],
    }
    for keyword, expected in expected_bboxes.items():
        ds = _find_dataset(report["datasets"], keyword)
        assert ds is not None, f"Dataset matching '{keyword}' not found"
        assert ds["bbox"] == expected, (
            f"bbox mismatch for '{ds['name']}': got {ds['bbox']}, expected {expected}"
        )


def test_worldpop_bbox(report):
    """WorldPop datasets must have bbox [-180, -60, 180, 85]."""
    wp_datasets = _find_datasets(report["datasets"], "worldpop")
    assert len(wp_datasets) >= 2, "Expected at least 2 WorldPop datasets"
    for ds in wp_datasets:
        assert ds["bbox"] == [-180.0, -60.0, 180.0, 85.0], (
            f"WorldPop bbox mismatch for '{ds['name']}': {ds['bbox']}"
        )


def test_copernicus_landcover_bbox(report):
    """Copernicus Land Cover must have bbox [-180, -60, 180, 80]."""
    ds = None
    for d in report["datasets"]:
        if "copernicus" in d["name"].lower() and "land" in d["name"].lower():
            ds = d
            break
    assert ds is not None, "Copernicus Land Cover dataset not found"
    assert ds["bbox"] == [-180.0, -60.0, 180.0, 80.0], (
        f"Copernicus LC bbox mismatch: {ds['bbox']}"
    )


def test_reprojected_global_datasets(report):
    """GHSL (Mollweide), MODIS (Sinusoidal), SoilGrids (Homolosine) must cover ~full globe."""
    keywords = ["ghs", "built", "modis", "mod13", "ndvi", "soilgrid"]
    found_count = 0
    for ds in report["datasets"]:
        name_lower = ds["name"].lower()
        if any(k in name_lower for k in keywords):
            found_count += 1
            w, s, e, n = ds["bbox"]
            assert w <= -170.0, f"'{ds['name']}' west bound too narrow: {w}"
            assert e >= 170.0, f"'{ds['name']}' east bound too narrow: {e}"
            assert s <= -80.0, f"'{ds['name']}' south bound too narrow: {s}"
            assert n >= 80.0, f"'{ds['name']}' north bound too narrow: {n}"
    assert found_count >= 3, (
        f"Expected >= 3 reprojected global datasets, found {found_count}"
    )


def test_kenya_erosion_bbox(report):
    """Kenya erosion (UTM 37S) bbox must match pyproj reference transform."""
    import numpy as np
    from pyproj import Transformer

    transformer = Transformer.from_crs("EPSG:32737", "EPSG:4326", always_xy=True)

    xmin, ymin, xmax, ymax = 150000.0, 9450000.0, 950000.0, 10560000.0
    n = 30
    xs_b = np.linspace(xmin, xmax, n)
    xs_t = np.linspace(xmin, xmax, n)
    ys_l = np.linspace(ymin, ymax, n)
    ys_r = np.linspace(ymin, ymax, n)

    all_x = list(xs_b) + list(xs_t) + [xmin] * n + [xmax] * n
    all_y = [ymin] * n + [ymax] * n + list(ys_l) + list(ys_r)

    lons, lats = transformer.transform(all_x, all_y)
    lons = [v for v in lons if np.isfinite(v)]
    lats = [v for v in lats if np.isfinite(v)]
    expected_bbox = [min(lons), min(lats), max(lons), max(lats)]

    ds = None
    for d in report["datasets"]:
        if "kenya" in d["name"].lower() or "erosion" in d["name"].lower():
            ds = d
            break
    assert ds is not None, "Kenya erosion dataset not found"

    for i, label in enumerate(["west", "south", "east", "north"]):
        assert abs(ds["bbox"][i] - expected_bbox[i]) < 0.5, (
            f"Kenya bbox {label}: got {ds['bbox'][i]}, expected ~{expected_bbox[i]:.2f}"
        )

    # Verify it's roughly in East Africa
    w, s, e, n = ds["bbox"]
    assert 33.0 < w < 38.0, f"Kenya west bound not in East Africa: {w}"
    assert e < 46.0, f"Kenya east bound too far east: {e}"
    assert -7.0 < s < 0.0, f"Kenya south bound not plausible: {s}"
    assert 3.0 < n < 8.0, f"Kenya north bound not plausible: {n}"


def test_rift_valley_bbox(report):
    """Rift Valley dataset has mislabeled CRS; corrected bbox must be in East Africa."""
    import numpy as np
    from pyproj import Transformer

    # The raw coordinates are in EPSG:32736 (UTM Zone 36S) but file claims EPSG:4326
    transformer = Transformer.from_crs("EPSG:32736", "EPSG:4326", always_xy=True)

    xmin, ymin, xmax, ymax = 220000.0, 9660000.0, 780000.0, 10170000.0
    n = 30
    all_x = (list(np.linspace(xmin, xmax, n)) + list(np.linspace(xmin, xmax, n))
             + [xmin] * n + [xmax] * n)
    all_y = ([ymin] * n + [ymax] * n
             + list(np.linspace(ymin, ymax, n)) + list(np.linspace(ymin, ymax, n)))

    lons, lats = transformer.transform(all_x, all_y)
    lons = [v for v in lons if np.isfinite(v)]
    lats = [v for v in lats if np.isfinite(v)]
    expected_bbox = [min(lons), min(lats), max(lons), max(lats)]

    ds = None
    for d in report["datasets"]:
        if "rift" in d["name"].lower() or ("precipitation" in d["name"].lower()
                                            and "east" in d["name"].lower()):
            ds = d
            break
    assert ds is not None, "Rift Valley Precipitation dataset not found"

    # Verify it's roughly in East Africa (not raw meter values)
    w, s, e, n = ds["bbox"]
    assert 28.0 < w < 33.0, f"Rift Valley west bound not in East Africa: {w}"
    assert e < 38.0, f"Rift Valley east bound too far east: {e}"
    assert -5.0 < s < 0.0, f"Rift Valley south bound not plausible: {s}"
    assert 0.0 < n < 3.0, f"Rift Valley north bound not plausible: {n}"

    # Check against computed reference transform
    for i, label in enumerate(["west", "south", "east", "north"]):
        assert abs(ds["bbox"][i] - expected_bbox[i]) < 0.5, (
            f"Rift Valley bbox {label}: got {ds['bbox'][i]}, expected ~{expected_bbox[i]:.2f}"
        )


# -- Spatial overlaps ----------------------------------------------------------


def test_spatial_overlaps_structure(report):
    """Spatial overlaps must have required fields."""
    for ov in report["spatial_overlaps"]:
        assert "dataset_a" in ov, "spatial_overlap missing 'dataset_a'"
        assert "dataset_b" in ov, "spatial_overlap missing 'dataset_b'"
        assert "intersection_area_sq_deg" in ov, "spatial_overlap missing 'intersection_area_sq_deg'"
        assert "iou" in ov, "spatial_overlap missing 'iou'"
        assert 0.0 <= ov["iou"] <= 1.0, f"IoU out of range: {ov['iou']}"
        assert ov["intersection_area_sq_deg"] >= 0, "Negative intersection area"


def test_spatial_overlap_esri_worldpop(report):
    """ESRI [-180,-90,180,90] vs WorldPop [-180,-60,180,85] must have IoU ~0.8056."""
    # intersection = [-180,-60,180,85] = 360*145 = 52200
    # area_esri = 360*180 = 64800
    # area_wp = 360*145 = 52200
    # union = 64800 + 52200 - 52200 = 64800
    # iou = 52200/64800 = 0.80556
    overlaps = report["spatial_overlaps"]
    found = False
    for ov in overlaps:
        a, b = ov["dataset_a"].lower(), ov["dataset_b"].lower()
        is_esri = "esri" in a or "esri" in b
        # Match original WorldPop (not v2/PPP)
        is_wp = False
        for name in [a, b]:
            if "worldpop" in name and "ppp" not in name and "v2" not in name:
                is_wp = True
        if is_esri and is_wp:
            assert abs(ov["iou"] - 0.80556) < 0.02, (
                f"ESRI/WorldPop IoU: got {ov['iou']}, expected ~0.80556"
            )
            assert abs(ov["intersection_area_sq_deg"] - 52200) < 200, (
                f"ESRI/WorldPop intersection area: got {ov['intersection_area_sq_deg']}, expected ~52200"
            )
            found = True
            break
    assert found, "ESRI / WorldPop (original) spatial overlap not found"


def test_spatial_overlap_identical_bbox(report):
    """Datasets with identical global bbox must have IoU = 1.0."""
    # ESRI, Copernicus DEM, LandScan all have [-180,-90,180,90]
    overlaps = report["spatial_overlaps"]
    found = False
    for ov in overlaps:
        a, b = ov["dataset_a"].lower(), ov["dataset_b"].lower()
        names = {a, b}
        has_esri = any("esri" in n for n in names)
        has_dem = any("copernicus" in n and "dem" in n.lower().replace("land", "") for n in names) or \
                  any("dem" in n and "copernicus" in n for n in names)
        has_landscan = any("landscan" in n for n in names)
        # Check any pair among ESRI/DEM/LandScan
        global_names = sum([has_esri, has_dem, has_landscan])
        if global_names >= 1:
            if abs(ov["iou"] - 1.0) < 0.01:
                found = True
                break
    assert found, "No IoU=1.0 pair found among global datasets"


def test_spatial_overlaps_count(report):
    """With 13 datasets, there should be many spatial overlap pairs."""
    assert len(report["spatial_overlaps"]) >= 40, (
        f"Expected >= 40 spatial overlap pairs, got {len(report['spatial_overlaps'])}"
    )


# -- Temporal overlaps ---------------------------------------------------------


def test_temporal_overlaps_structure(report):
    """Temporal overlaps must have required fields."""
    for ov in report["temporal_overlaps"]:
        assert "dataset_a" in ov, "temporal_overlap missing 'dataset_a'"
        assert "dataset_b" in ov, "temporal_overlap missing 'dataset_b'"
        assert "overlap_days" in ov, "temporal_overlap missing 'overlap_days'"
        assert ov["overlap_days"] > 0, f"overlap_days must be positive, got {ov['overlap_days']}"


def test_temporal_overlap_worldpop_landscan(report):
    """WorldPop (2000-2020) and LandScan (2000-2022) must overlap ~7670 days."""
    overlaps = report["temporal_overlaps"]
    found = False
    for ov in overlaps:
        a, b = ov["dataset_a"].lower(), ov["dataset_b"].lower()
        has_wp = ("worldpop" in a and "ppp" not in a) or ("worldpop" in b and "ppp" not in b)
        has_ls = "landscan" in a or "landscan" in b
        if has_wp and has_ls:
            assert ov["overlap_days"] > 7000, (
                f"WorldPop/LandScan overlap too short: {ov['overlap_days']} days"
            )
            assert ov["overlap_days"] < 8000, (
                f"WorldPop/LandScan overlap too long: {ov['overlap_days']} days"
            )
            found = True
            break
    assert found, "WorldPop/LandScan temporal overlap not found"


def test_no_temporal_overlap_worldpop_dem(report):
    """WorldPop (ends 2020-12-31) must NOT temporally overlap Copernicus DEM (starts 2021-04-01)."""
    overlaps = report["temporal_overlaps"]
    for ov in overlaps:
        a, b = ov["dataset_a"].lower(), ov["dataset_b"].lower()
        has_wp = ("worldpop" in a and "ppp" not in a and "v2" not in a) or \
                 ("worldpop" in b and "ppp" not in b and "v2" not in b)
        has_dem = ("copernicus" in a and ("dem" in a or "glo" in a)) or \
                  ("copernicus" in b and ("dem" in b or "glo" in b))
        if has_wp and has_dem:
            pytest.fail(
                f"WorldPop and Copernicus DEM should NOT overlap temporally, "
                f"but found {ov['overlap_days']} days"
            )


def test_temporal_overlap_count(report):
    """There should be a substantial number of temporal overlap pairs."""
    assert len(report["temporal_overlaps"]) >= 30, (
        f"Expected >= 30 temporal overlap pairs, got {len(report['temporal_overlaps'])}"
    )


# -- Duplicate detection -------------------------------------------------------


def test_duplicate_candidates(report):
    """The two WorldPop datasets must be flagged as duplicate candidates."""
    duplicates = report["duplicate_candidates"]
    assert len(duplicates) >= 1, "Should detect at least one duplicate pair"

    found = False
    for pair in duplicates:
        if isinstance(pair, list):
            names = [p.lower() for p in pair]
        elif isinstance(pair, dict):
            names = [
                pair.get("dataset_a", pair.get("a", "")).lower(),
                pair.get("dataset_b", pair.get("b", "")).lower(),
            ]
        else:
            continue

        if len(names) == 2 and all("worldpop" in n or "ppp" in n for n in names):
            found = True
            break

    assert found, f"WorldPop duplicate pair not detected. Got: {duplicates}"


# -- STAC items ----------------------------------------------------------------


def test_stac_items_count(report):
    """Must generate at least 12 STAC items (13 datasets minus duplicates)."""
    assert len(report["stac_items"]) >= 12, (
        f"Expected >= 12 STAC items, got {len(report['stac_items'])}"
    )


def test_stac_item_required_fields(report):
    """Each STAC item must have all required fields per v1.0.0 spec."""
    for item in report["stac_items"]:
        assert item.get("type") == "Feature", (
            f"STAC item type must be 'Feature', got '{item.get('type')}'"
        )
        assert item.get("stac_version") == "1.0.0", (
            f"stac_version must be '1.0.0', got '{item.get('stac_version')}'"
        )
        assert "id" in item and isinstance(item["id"], str), "STAC item must have string 'id'"
        assert "geometry" in item, "STAC item must have 'geometry'"
        assert "bbox" in item and isinstance(item["bbox"], list), "STAC item must have list 'bbox'"
        assert "properties" in item, "STAC item must have 'properties'"
        assert "datetime" in item["properties"], "properties must include 'datetime'"
        assert "links" in item and isinstance(item["links"], list), "STAC item must have list 'links'"
        assert "assets" in item and isinstance(item["assets"], dict), "STAC item must have dict 'assets'"


def test_stac_geometry(report):
    """STAC geometry must be a valid closed GeoJSON Polygon."""
    for item in report["stac_items"]:
        geom = item["geometry"]
        assert geom["type"] == "Polygon", (
            f"STAC geometry for '{item['id']}' must be Polygon, got {geom['type']}"
        )
        coords = geom["coordinates"]
        assert len(coords) >= 1, "Polygon must have at least one ring"
        ring = coords[0]
        assert len(ring) >= 4, f"Ring must have >= 4 points for '{item['id']}'"
        assert ring[0] == ring[-1], f"Ring must be closed for '{item['id']}'"


def test_stac_bbox_matches_geometry(report):
    """STAC item bbox must be consistent with its geometry."""
    for item in report["stac_items"]:
        bbox = item["bbox"]
        ring = item["geometry"]["coordinates"][0]
        lons = [p[0] for p in ring]
        lats = [p[1] for p in ring]
        assert abs(min(lons) - bbox[0]) < 0.01, f"bbox west mismatch for '{item['id']}'"
        assert abs(min(lats) - bbox[1]) < 0.01, f"bbox south mismatch for '{item['id']}'"
        assert abs(max(lons) - bbox[2]) < 0.01, f"bbox east mismatch for '{item['id']}'"
        assert abs(max(lats) - bbox[3]) < 0.01, f"bbox north mismatch for '{item['id']}'"


# -- AOI coverage --------------------------------------------------------------


def test_aoi_coverage_structure(report):
    """AOI coverage must be a dict mapping names to percentages."""
    cov = report["aoi_coverage"]
    assert isinstance(cov, dict), "aoi_coverage must be a dict"
    assert len(cov) >= 10, f"Expected coverage for >= 10 datasets, got {len(cov)}"
    for name, pct in cov.items():
        assert isinstance(pct, (int, float)), f"Coverage for '{name}' must be numeric"
        assert 0.0 <= pct <= 100.0, f"Coverage for '{name}' out of range: {pct}"


def test_aoi_coverage_global_datasets(report):
    """Global datasets (bbox covers entire AOI) must have ~100% coverage."""
    cov = report["aoi_coverage"]
    # AOI is [29, -12, 42, 5]
    # Datasets with bbox [-180,-90,180,90] fully contain it
    global_keywords = ["esri", "landscan"]
    for keyword in global_keywords:
        found = False
        for name, pct in cov.items():
            if keyword.lower() in name.lower():
                assert pct >= 99.0, (
                    f"Global dataset '{name}' should have ~100% AOI coverage, got {pct}%"
                )
                found = True
                break
        assert found, f"No coverage entry matching '{keyword}'"


def test_aoi_coverage_kenya_partial(report):
    """Kenya erosion (regional) must have partial AOI coverage."""
    cov = report["aoi_coverage"]
    for name, pct in cov.items():
        if "kenya" in name.lower() or "erosion" in name.lower():
            assert 5.0 < pct < 70.0, (
                f"Kenya dataset AOI coverage should be partial, got {pct}%"
            )
            return
    pytest.fail("Kenya erosion dataset not found in aoi_coverage")


# -- Data quality diagnostics --------------------------------------------------


def test_data_quality_exists(report):
    """Report must include a non-empty data_quality section."""
    assert "data_quality" in report, "Missing 'data_quality' key in report"
    assert isinstance(report["data_quality"], list), "data_quality must be a list"
    assert len(report["data_quality"]) >= 1, "Should detect at least one data quality issue"


def test_data_quality_entry_structure(report):
    """Each data_quality entry must have required fields."""
    for issue in report["data_quality"]:
        assert "dataset" in issue, "data_quality entry missing 'dataset'"
        assert "issue_type" in issue, "data_quality entry missing 'issue_type'"
        assert "description" in issue, "data_quality entry missing 'description'"
        assert isinstance(issue["description"], str) and len(issue["description"]) > 10, (
            "data_quality description must be a meaningful string"
        )


def test_data_quality_crs_mismatch_detected(report):
    """Agent must detect the CRS mismatch in the Rift Valley precipitation dataset."""
    issues = report["data_quality"]

    found = False
    for issue in issues:
        name = issue.get("dataset", "").lower()
        itype = issue.get("issue_type", "").lower()
        desc = issue.get("description", "").lower()
        if ("rift" in name or "precipitation" in name) and (
            "crs" in itype or "crs" in desc
            or "mismatch" in itype or "coordinate" in itype
            or "projection" in itype
        ):
            found = True
            break

    assert found, (
        f"CRS mismatch for Rift Valley dataset not detected. Issues found: {issues}"
    )
