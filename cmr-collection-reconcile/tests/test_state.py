
import json
import os
import pytest


@pytest.fixture(scope="module")
def report():
    path = "/app/output/reconciliation.json"
    assert os.path.exists(path), (
        "Reconciliation report not found at /app/output/reconciliation.json. "
        "Ensure reconcile.py has been run."
    )
    with open(path) as f:
        return json.load(f)


def _errors_for(report, file_id):
    return [e for e in report["errors"] if e["file_id"] == file_id]


def _errors_of_type(report, error_type):
    return [e for e in report["errors"] if e["error_type"] == error_type]


def _flatten_bbox(val):
    """Handle both [w,s,e,n] and [[w,s,e,n]] formats."""
    if isinstance(val, list) and len(val) == 1 and isinstance(val[0], list):
        return val[0]
    return val


# ── Structure tests ─────────────────────────────────────────────────────────

def test_output_has_required_keys(report):
    for key in ("files_analyzed", "errors", "summary"):
        assert key in report, f"Missing top-level key: {key}"


def test_summary_has_required_keys(report):
    s = report["summary"]
    for key in ("total_files", "total_errors", "critical_count", "major_count"):
        assert key in s, f"Missing summary key: {key}"


# ── Summary statistics ──────────────────────────────────────────────────────

def test_summary_file_count(report):
    assert report["summary"]["total_files"] == 6


def test_summary_error_count(report):
    assert report["summary"]["total_errors"] == 7


def test_summary_severity_counts(report):
    s = report["summary"]
    assert s["critical_count"] == 5
    assert s["major_count"] == 2


# ── global_sst: temporal error ──────────────────────────────────────────────

def test_global_sst_temporal_error(report):
    """start_datetime > end_datetime is a temporal error."""
    errors = _errors_for(report, "global_sst")
    temporal = [e for e in errors if e["error_type"] == "temporal_extent"]
    assert len(temporal) == 1, (
        f"Expected 1 temporal error for global_sst, got {len(temporal)}"
    )
    assert temporal[0]["severity"] == "major"


def test_global_sst_no_spatial_error(report):
    """global_sst bbox is correct — no false positive."""
    spatial = [e for e in _errors_for(report, "global_sst")
               if e["error_type"] == "spatial_extent"]
    assert len(spatial) == 0, f"False positive spatial error for global_sst: {spatial}"


def test_global_sst_no_band_error(report):
    bands = [e for e in _errors_for(report, "global_sst")
             if e["error_type"] == "band_count"]
    assert len(bands) == 0


def test_global_sst_total_errors(report):
    assert len(_errors_for(report, "global_sst")) == 1


# ── landsat_california: spatial error (bbox in UTM meters) ──────────────────

def test_landsat_spatial_error(report):
    errors = _errors_for(report, "landsat_california")
    spatial = [e for e in errors if e["error_type"] == "spatial_extent"]
    assert len(spatial) == 1, (
        f"Expected 1 spatial error for landsat_california, got {len(spatial)}"
    )
    assert spatial[0]["severity"] == "critical"


def test_landsat_stac_bbox_in_meters(report):
    """STAC bbox values should be the erroneous UTM meter values (> 1000)."""
    errors = _errors_for(report, "landsat_california")
    spatial = [e for e in errors if e["error_type"] == "spatial_extent"][0]
    stac_bbox = _flatten_bbox(spatial["stac_value"])
    assert isinstance(stac_bbox, list) and len(stac_bbox) == 4
    assert any(abs(v) > 1000 for v in stac_bbox), (
        f"STAC bbox should contain UTM meter values, got {stac_bbox}"
    )


def test_landsat_correct_bbox_in_california(report):
    """File-derived WGS84 bbox should be in California lat/lon range."""
    errors = _errors_for(report, "landsat_california")
    spatial = [e for e in errors if e["error_type"] == "spatial_extent"][0]
    file_bbox = _flatten_bbox(spatial["file_value"])
    assert isinstance(file_bbox, list) and len(file_bbox) == 4
    west, south, east, north = file_bbox
    assert -120 < west < -114, f"West lon {west} not in California range"
    assert 33 < south < 36, f"South lat {south} not in California range"
    assert -118 < east < -113, f"East lon {east} not in California range"
    assert 34 < north < 36, f"North lat {north} not in California range"


def test_landsat_total_errors(report):
    assert len(_errors_for(report, "landsat_california")) == 1


# ── greenland_ice: spatial error (longitude signs inverted) ─────────────────

def test_greenland_spatial_error(report):
    errors = _errors_for(report, "greenland_ice")
    spatial = [e for e in errors if e["error_type"] == "spatial_extent"]
    assert len(spatial) == 1, (
        f"Expected 1 spatial error for greenland_ice, got {len(spatial)}"
    )
    assert spatial[0]["severity"] == "critical"


def test_greenland_stac_bbox_positive_lons(report):
    """Erroneous STAC bbox should have positive longitudes."""
    errors = _errors_for(report, "greenland_ice")
    spatial = [e for e in errors if e["error_type"] == "spatial_extent"][0]
    stac_bbox = _flatten_bbox(spatial["stac_value"])
    assert isinstance(stac_bbox, list) and len(stac_bbox) == 4
    assert stac_bbox[0] > 0, f"STAC west lon should be positive, got {stac_bbox[0]}"
    assert stac_bbox[2] > 0, f"STAC east lon should be positive, got {stac_bbox[2]}"


def test_greenland_correct_bbox_negative_lons(report):
    """Greenland is in the western hemisphere — correct bbox must have negative lons."""
    errors = _errors_for(report, "greenland_ice")
    spatial = [e for e in errors if e["error_type"] == "spatial_extent"][0]
    file_bbox = _flatten_bbox(spatial["file_value"])
    assert isinstance(file_bbox, list) and len(file_bbox) == 4
    assert file_bbox[0] < 0, f"West lon should be negative for Greenland, got {file_bbox[0]}"
    assert file_bbox[2] < 0, f"East lon should be negative for Greenland, got {file_bbox[2]}"


def test_greenland_total_errors(report):
    assert len(_errors_for(report, "greenland_ice")) == 1


# ── modis_sinusoidal: spatial error (bbox in sinusoidal meters) ─────────────

def test_modis_spatial_error(report):
    errors = _errors_for(report, "modis_sinusoidal")
    spatial = [e for e in errors if e["error_type"] == "spatial_extent"]
    assert len(spatial) == 1, (
        f"Expected 1 spatial error for modis_sinusoidal, got {len(spatial)}"
    )
    assert spatial[0]["severity"] == "critical"


def test_modis_stac_bbox_in_meters(report):
    """STAC bbox should contain sinusoidal projection meter values."""
    errors = _errors_for(report, "modis_sinusoidal")
    spatial = [e for e in errors if e["error_type"] == "spatial_extent"][0]
    stac_bbox = _flatten_bbox(spatial["stac_value"])
    assert isinstance(stac_bbox, list) and len(stac_bbox) == 4
    assert any(abs(v) > 1000 for v in stac_bbox), (
        f"STAC bbox should contain sinusoidal meter values, got {stac_bbox}"
    )


def test_modis_correct_bbox_in_asia(report):
    """File-derived WGS84 bbox should be in South/Southeast Asia range."""
    errors = _errors_for(report, "modis_sinusoidal")
    spatial = [e for e in errors if e["error_type"] == "spatial_extent"][0]
    file_bbox = _flatten_bbox(spatial["file_value"])
    assert isinstance(file_bbox, list) and len(file_bbox) == 4
    west, south, east, north = file_bbox
    assert 70 < west < 100, f"West lon {west} not in expected Asian range"
    assert 8 < south < 22, f"South lat {south} not in expected range"


def test_modis_total_errors(report):
    assert len(_errors_for(report, "modis_sinusoidal")) == 1


# ── sentinel1_sar: CRS error + spatial error ───────────────────────────────

def test_sentinel1_crs_error(report):
    errors = _errors_for(report, "sentinel1_sar")
    crs = [e for e in errors if e["error_type"] == "crs_mismatch"]
    assert len(crs) == 1, (
        f"Expected 1 CRS mismatch for sentinel1_sar, got {len(crs)}"
    )
    assert crs[0]["severity"] == "critical"


def test_sentinel1_crs_values(report):
    """STAC says EPSG:32632, file is EPSG:32633."""
    errors = _errors_for(report, "sentinel1_sar")
    crs = [e for e in errors if e["error_type"] == "crs_mismatch"][0]
    stac_val = crs["stac_value"]
    file_val = crs["file_value"]
    assert str(stac_val).replace("EPSG:", "") == "32632", (
        f"STAC CRS should be 32632, got {stac_val}"
    )
    assert str(file_val).replace("EPSG:", "") == "32633", (
        f"File CRS should be 32633, got {file_val}"
    )


def test_sentinel1_spatial_error(report):
    errors = _errors_for(report, "sentinel1_sar")
    spatial = [e for e in errors if e["error_type"] == "spatial_extent"]
    assert len(spatial) == 1, (
        f"Expected 1 spatial error for sentinel1_sar, got {len(spatial)}"
    )
    assert spatial[0]["severity"] == "critical"


def test_sentinel1_correct_bbox_norway(report):
    """Correct bbox should have longitudes > 10 (Norway coast, not Sweden/Denmark)."""
    errors = _errors_for(report, "sentinel1_sar")
    spatial = [e for e in errors if e["error_type"] == "spatial_extent"][0]
    file_bbox = _flatten_bbox(spatial["file_value"])
    assert isinstance(file_bbox, list) and len(file_bbox) == 4
    west = file_bbox[0]
    assert west > 10, f"West lon should be > 10 for Norway coast, got {west}"


def test_sentinel1_total_errors(report):
    assert len(_errors_for(report, "sentinel1_sar")) == 2


# ── antarctic_ice: band count error ────────────────────────────────────────

def test_antarctic_band_count_error(report):
    errors = _errors_for(report, "antarctic_ice")
    bands = [e for e in errors if e["error_type"] == "band_count"]
    assert len(bands) == 1, (
        f"Expected 1 band_count error for antarctic_ice, got {len(bands)}"
    )
    assert bands[0]["severity"] == "major"


def test_antarctic_band_count_values(report):
    """STAC lists 3 bands, file has 2."""
    errors = _errors_for(report, "antarctic_ice")
    bands = [e for e in errors if e["error_type"] == "band_count"][0]
    assert bands["stac_value"] == 3, f"STAC band count should be 3, got {bands['stac_value']}"
    assert bands["file_value"] == 2, f"File band count should be 2, got {bands['file_value']}"


def test_antarctic_no_spatial_error(report):
    """antarctic_ice bbox is correct — no false positive."""
    spatial = [e for e in _errors_for(report, "antarctic_ice")
               if e["error_type"] == "spatial_extent"]
    assert len(spatial) == 0, f"False positive spatial error for antarctic_ice: {spatial}"


def test_antarctic_total_errors(report):
    assert len(_errors_for(report, "antarctic_ice")) == 1


# ── Error type counts ──────────────────────────────────────────────────────

def test_spatial_error_count(report):
    assert len(_errors_of_type(report, "spatial_extent")) == 4


def test_crs_error_count(report):
    assert len(_errors_of_type(report, "crs_mismatch")) == 1


def test_temporal_error_count(report):
    assert len(_errors_of_type(report, "temporal_extent")) == 1


def test_band_count_error_count(report):
    assert len(_errors_of_type(report, "band_count")) == 1


# ── Error field validity ───────────────────────────────────────────────────

def test_each_error_has_valid_type(report):
    valid_types = {"spatial_extent", "crs_mismatch", "temporal_extent", "band_count"}
    for e in report["errors"]:
        assert e["error_type"] in valid_types, f"Invalid error_type: {e['error_type']}"


def test_each_error_has_valid_severity(report):
    valid_sev = {"critical", "major"}
    for e in report["errors"]:
        assert e["severity"] in valid_sev, f"Invalid severity: {e['severity']}"


def test_each_error_has_required_fields(report):
    required = {"file_id", "error_type", "field", "stac_value", "file_value",
                "severity", "description"}
    for e in report["errors"]:
        for field in required:
            assert field in e, f"Error missing field '{field}': {e}"


# ── Total error count ──────────────────────────────────────────────────────

def test_total_error_count(report):
    assert len(report["errors"]) == 7
