
import json
import os
import math

from osgeo import ogr, osr

FIXED_CATALOG = "/app/catalog_fixed.gpkg"
DIAG_REPORT = "/app/diagnostic_report.json"
STRATEGY = "/app/strategy.json"

TOL_DEG = 0.05  # tolerance for coordinate comparison (degrees)
TOL_FRAC = 0.02  # tolerance for coverage fractions
TOL_AREA = 1.0  # tolerance for area sums (degree^2)
TOL_EFF = 0.02  # tolerance for efficiency values
TOL_STORAGE = 0.5  # tolerance for total storage

# Expected corrupted record IDs (9 total)
EXPECTED_CORRUPTED_IDS = sorted([
    "MODIS-LST-1000", "SENTINEL-NDVI-10", "LANDSAT-TC-30",
    "ASTER-DEM-30", "SRTM-FILL-90",
    "NLCD-LC-30", "PRISM-PRECIP-800",
    "WA-LIDAR-1", "GRIDMET-CLIMATE-4000",
])

# Expected correct bounding boxes for geometry-corrupted records
# Format: [west, south, east, north]
EXPECTED_BBOXES = {
    "MODIS-LST-1000": [-130, 40, -110, 55],
    "SENTINEL-NDVI-10": [-125, 46, -117, 49],
    "LANDSAT-TC-30": [-128, 42, -115, 52],
    "ASTER-DEM-30": [-122.5, 46, -120.5, 48],
    "SRTM-FILL-90": [-124, 44, -119, 49],
    "NLCD-LC-30": [-125, 42, -115, 49],
    "PRISM-PRECIP-800": [-130, 35, -105, 55],
}

# Expected temporal fixes
EXPECTED_TEMPORAL = {
    "WA-LIDAR-1": ("2019-01-01", "2023-06-30"),
    "GRIDMET-CLIMATE-4000": ("2018-01-01", "2023-12-31"),
}

# --- Portfolio optimization expected ---
EXPECTED_PORTFOLIO_IDS = sorted([
    "GRIDMET-CLIMATE-4000", "OR-FOREST-20", "PNW-FIRE-20",
    "PNW-SNOW-100", "PNW-SOIL-250", "WA-FOREST-20",
])
EXPECTED_PORTFOLIO_STORAGE = 11.5
EXPECTED_PORTFOLIO_CATEGORIES = sorted([
    "climate", "hazard", "hydrology", "landcover", "soil",
])

# --- Efficiency ranking expected ---
EXPECTED_TOP5_IDS = [
    "GRIDMET-CLIMATE-4000",
    "SRTM-FILL-90",
    "PNW-TEMP-1000",
    "PNW-PRECIP-1000",
    "MODIS-LST-1000",
]
EXPECTED_TOP5_EFFS = [4.15, 2.1944, 2.175, 1.70, 1.025]

EXPECTED_BOTTOM3_IDS = ["PNW-LC-10", "BC-ELEV-10", "WA-LIDAR-1"]

EXPECTED_CATEGORY_BEST = {
    "elevation": "SRTM-FILL-90",
    "landcover": "OR-FOREST-20",
    "vegetation": "PNW-VEG-30",
    "climate": "GRIDMET-CLIMATE-4000",
    "soil": "PNW-SOIL-250",
    "hydrology": "PNW-SNOW-100",
    "hazard": "PNW-FIRE-20",
}


def _open_fixed():
    ds = ogr.Open(FIXED_CATALOG)
    assert ds is not None, f"Cannot open {FIXED_CATALOG}"
    layer = ds.GetLayer("datasets")
    assert layer is not None, "Layer 'datasets' not found in fixed catalog"
    return ds, layer


# ==================== DIAGNOSTIC REPORT TESTS ====================

def test_diagnostic_report_exists():
    assert os.path.exists(DIAG_REPORT), f"{DIAG_REPORT} not found"


def test_diagnostic_report_structure():
    with open(DIAG_REPORT) as f:
        data = json.load(f)
    assert "corrupted_records" in data, "Missing 'corrupted_records' key"
    assert "total_corrupted" in data, "Missing 'total_corrupted' key"
    assert isinstance(data["corrupted_records"], list)


def test_diagnostic_report_total_count():
    with open(DIAG_REPORT) as f:
        data = json.load(f)
    assert data["total_corrupted"] == 9, (
        f"Expected 9 corrupted records, got {data['total_corrupted']}"
    )


def test_diagnostic_report_record_ids():
    with open(DIAG_REPORT) as f:
        data = json.load(f)
    reported_ids = sorted([r["dataset_id"] for r in data["corrupted_records"]])
    assert reported_ids == EXPECTED_CORRUPTED_IDS, (
        f"Corrupted IDs mismatch.\n"
        f"  Expected: {EXPECTED_CORRUPTED_IDS}\n"
        f"  Got:      {reported_ids}"
    )


def test_diagnostic_report_descriptions_nonempty():
    with open(DIAG_REPORT) as f:
        data = json.load(f)
    for rec in data["corrupted_records"]:
        assert "description" in rec and len(rec["description"]) > 5, (
            f"Record {rec.get('dataset_id', '?')} has empty/missing description"
        )


# ==================== FIXED CATALOG TESTS ====================

def test_fixed_catalog_exists():
    assert os.path.exists(FIXED_CATALOG), f"{FIXED_CATALOG} not found"


def test_fixed_catalog_record_count():
    ds, layer = _open_fixed()
    count = layer.GetFeatureCount()
    ds = None
    assert count == 28, f"Expected 28 records, got {count}"


def test_fixed_catalog_all_geometries_valid():
    ds, layer = _open_fixed()
    invalid = []
    layer.ResetReading()
    feat = layer.GetNextFeature()
    while feat is not None:
        geom = feat.GetGeometryRef()
        did = feat.GetField("dataset_id")
        if geom is None or not geom.IsValid():
            invalid.append(did)
        feat = layer.GetNextFeature()
    ds = None
    assert not invalid, f"Invalid geometries in: {invalid}"


def test_fixed_catalog_coordinates_in_wgs84_range():
    ds, layer = _open_fixed()
    out_of_range = []
    layer.ResetReading()
    feat = layer.GetNextFeature()
    while feat is not None:
        geom = feat.GetGeometryRef()
        did = feat.GetField("dataset_id")
        if geom is not None:
            env = geom.GetEnvelope()  # (minX, maxX, minY, maxY)
            if env[0] < -180 or env[1] > 180 or env[2] < -90 or env[3] > 90:
                out_of_range.append(
                    f"{did}: X=[{env[0]:.2f},{env[1]:.2f}] Y=[{env[2]:.2f},{env[3]:.2f}]"
                )
        feat = layer.GetNextFeature()
    ds = None
    assert not out_of_range, f"Coordinates outside WGS84 range:\n" + "\n".join(out_of_range)


def test_fixed_catalog_temporal_consistency():
    ds, layer = _open_fixed()
    inconsistent = []
    layer.ResetReading()
    feat = layer.GetNextFeature()
    while feat is not None:
        did = feat.GetField("dataset_id")
        ts = feat.GetField("temporal_start")
        te = feat.GetField("temporal_end")
        if ts is not None and te is not None and ts > te:
            inconsistent.append(f"{did}: {ts} > {te}")
        feat = layer.GetNextFeature()
    ds = None
    assert not inconsistent, (
        "Temporal inconsistencies found:\n" + "\n".join(inconsistent)
    )


def test_fixed_catalog_corrected_geometries():
    """Verify that geometry-corrupted records have correct bounding boxes after fix."""
    ds, layer = _open_fixed()
    checked = set()
    layer.ResetReading()
    feat = layer.GetNextFeature()
    while feat is not None:
        did = feat.GetField("dataset_id")
        if did in EXPECTED_BBOXES:
            geom = feat.GetGeometryRef()
            assert geom is not None, f"{did}: geometry is None"
            env = geom.GetEnvelope()  # (minX, maxX, minY, maxY)
            exp = EXPECTED_BBOXES[did]  # [west, south, east, north]
            assert abs(env[0] - exp[0]) < TOL_DEG, (
                f"{did}: minX={env[0]:.4f}, expected {exp[0]}"
            )
            assert abs(env[1] - exp[2]) < TOL_DEG, (
                f"{did}: maxX={env[1]:.4f}, expected {exp[2]}"
            )
            assert abs(env[2] - exp[1]) < TOL_DEG, (
                f"{did}: minY={env[2]:.4f}, expected {exp[1]}"
            )
            assert abs(env[3] - exp[3]) < TOL_DEG, (
                f"{did}: maxY={env[3]:.4f}, expected {exp[3]}"
            )
            checked.add(did)
        feat = layer.GetNextFeature()
    ds = None
    missing = set(EXPECTED_BBOXES.keys()) - checked
    assert not missing, f"Expected records not found in fixed catalog: {missing}"


def test_fixed_catalog_corrected_temporal():
    """Verify that temporal-corrupted records have correct date ranges after fix."""
    ds, layer = _open_fixed()
    checked = set()
    layer.ResetReading()
    feat = layer.GetNextFeature()
    while feat is not None:
        did = feat.GetField("dataset_id")
        if did in EXPECTED_TEMPORAL:
            ts = feat.GetField("temporal_start")
            te = feat.GetField("temporal_end")
            exp_ts, exp_te = EXPECTED_TEMPORAL[did]
            assert ts == exp_ts, f"{did}: temporal_start={ts}, expected {exp_ts}"
            assert te == exp_te, f"{did}: temporal_end={te}, expected {exp_te}"
            checked.add(did)
        feat = layer.GetNextFeature()
    ds = None
    missing = set(EXPECTED_TEMPORAL.keys()) - checked
    assert not missing, f"Expected records not found: {missing}"


def test_fixed_catalog_geometries_are_rectangles():
    """All geometries should be axis-aligned rectangles (4 corners + closing point)."""
    ds, layer = _open_fixed()
    non_rect = []
    layer.ResetReading()
    feat = layer.GetNextFeature()
    while feat is not None:
        did = feat.GetField("dataset_id")
        geom = feat.GetGeometryRef()
        if geom is not None:
            ring = geom.GetGeometryRef(0)
            n_points = ring.GetPointCount()
            if n_points != 5:
                non_rect.append(f"{did}: {n_points} points (expected 5)")
            else:
                pts = [(ring.GetX(i), ring.GetY(i)) for i in range(4)]
                xs = set(round(p[0], 4) for p in pts)
                ys = set(round(p[1], 4) for p in pts)
                if len(xs) != 2 or len(ys) != 2:
                    non_rect.append(f"{did}: not axis-aligned rectangle")
        feat = layer.GetNextFeature()
    ds = None
    assert not non_rect, "Non-rectangle geometries:\n" + "\n".join(non_rect)


# ==================== STRATEGY TESTS ====================

def test_strategy_exists():
    assert os.path.exists(STRATEGY), f"{STRATEGY} not found"


def test_strategy_valid_json():
    with open(STRATEGY) as f:
        data = json.load(f)
    assert "portfolio" in data, "Missing 'portfolio' key"
    assert "efficiency_analysis" in data, "Missing 'efficiency_analysis' key"


# --- Portfolio tests ---

def test_portfolio_dataset_ids():
    with open(STRATEGY) as f:
        data = json.load(f)
    p = data["portfolio"]
    actual = sorted(p["selected_dataset_ids"])
    assert actual == EXPECTED_PORTFOLIO_IDS, (
        f"Portfolio IDs mismatch.\n"
        f"  Expected: {EXPECTED_PORTFOLIO_IDS}\n"
        f"  Got:      {actual}"
    )


def test_portfolio_total_storage():
    with open(STRATEGY) as f:
        data = json.load(f)
    p = data["portfolio"]
    actual = p["total_storage_gb"]
    assert abs(actual - EXPECTED_PORTFOLIO_STORAGE) < TOL_STORAGE, (
        f"Portfolio storage: {actual:.2f}, expected {EXPECTED_PORTFOLIO_STORAGE:.2f}"
    )


def test_portfolio_categories():
    with open(STRATEGY) as f:
        data = json.load(f)
    p = data["portfolio"]
    actual = sorted(p["categories"])
    assert actual == EXPECTED_PORTFOLIO_CATEGORIES, (
        f"Portfolio categories mismatch.\n"
        f"  Expected: {EXPECTED_PORTFOLIO_CATEGORIES}\n"
        f"  Got:      {actual}"
    )


def test_portfolio_per_category_coverage():
    with open(STRATEGY) as f:
        data = json.load(f)
    p = data["portfolio"]
    cov = p["per_category_coverage"]
    for cat in EXPECTED_PORTFOLIO_CATEGORIES:
        assert cat in cov, f"Missing coverage for category '{cat}'"
        assert cov[cat] >= 0.60 - TOL_FRAC, (
            f"Category '{cat}' coverage {cov[cat]:.4f} below threshold 0.60"
        )


# --- Efficiency ranking tests ---

def test_efficiency_ranking_count():
    with open(STRATEGY) as f:
        data = json.load(f)
    ranking = data["efficiency_analysis"]["ranking"]
    assert len(ranking) == 28, (
        f"Expected 28 entries in ranking, got {len(ranking)}"
    )


def test_efficiency_top5_ids():
    with open(STRATEGY) as f:
        data = json.load(f)
    ranking = data["efficiency_analysis"]["ranking"]
    top5 = [r["dataset_id"] for r in ranking[:5]]
    assert top5 == EXPECTED_TOP5_IDS, (
        f"Top-5 efficiency IDs mismatch.\n"
        f"  Expected: {EXPECTED_TOP5_IDS}\n"
        f"  Got:      {top5}"
    )


def test_efficiency_top5_values():
    with open(STRATEGY) as f:
        data = json.load(f)
    ranking = data["efficiency_analysis"]["ranking"]
    for i, (expected_id, expected_eff) in enumerate(
        zip(EXPECTED_TOP5_IDS, EXPECTED_TOP5_EFFS)
    ):
        actual = ranking[i]
        assert actual["dataset_id"] == expected_id
        assert abs(actual["efficiency"] - expected_eff) < TOL_EFF, (
            f"#{i+1} {expected_id}: efficiency={actual['efficiency']:.4f}, "
            f"expected {expected_eff:.4f}"
        )


def test_efficiency_bottom3_ids():
    with open(STRATEGY) as f:
        data = json.load(f)
    ranking = data["efficiency_analysis"]["ranking"]
    bottom3 = [r["dataset_id"] for r in ranking[-3:]]
    assert bottom3 == EXPECTED_BOTTOM3_IDS, (
        f"Bottom-3 efficiency IDs mismatch.\n"
        f"  Expected: {EXPECTED_BOTTOM3_IDS}\n"
        f"  Got:      {bottom3}"
    )


def test_efficiency_category_best():
    with open(STRATEGY) as f:
        data = json.load(f)
    cat_best = data["efficiency_analysis"]["category_best"]
    for cat, expected_id in EXPECTED_CATEGORY_BEST.items():
        assert cat in cat_best, f"Missing category '{cat}' in category_best"
        assert cat_best[cat] == expected_id, (
            f"Category '{cat}': best={cat_best[cat]}, expected {expected_id}"
        )


def test_efficiency_no_extra_categories():
    with open(STRATEGY) as f:
        data = json.load(f)
    cat_best = data["efficiency_analysis"]["category_best"]
    extra = set(cat_best.keys()) - set(EXPECTED_CATEGORY_BEST.keys())
    assert not extra, f"Unexpected categories in category_best: {extra}"


def test_efficiency_descending_order():
    """Verify the ranking is sorted by efficiency descending."""
    with open(STRATEGY) as f:
        data = json.load(f)
    ranking = data["efficiency_analysis"]["ranking"]
    for i in range(len(ranking) - 1):
        assert ranking[i]["efficiency"] >= ranking[i + 1]["efficiency"], (
            f"Ranking not descending at position {i}: "
            f"{ranking[i]['dataset_id']}={ranking[i]['efficiency']:.6f} < "
            f"{ranking[i+1]['dataset_id']}={ranking[i+1]['efficiency']:.6f}"
        )
