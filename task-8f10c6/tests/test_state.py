
import pytest
import numpy as np
import rasterio
import json
import os

INDEX_NAMES = ["NDVI", "NDWI", "EVI", "SAVI", "NDRE"]
INPUT_RASTER = "/app/data/multiband.tif"
CONFIG_PATH = "/app/data/analysis_config.json"
OUTPUT_DIR = "/app/output"
INDICES_DIR = os.path.join(OUTPUT_DIR, "indices")
ZONAL_STATS_PATH = os.path.join(OUTPUT_DIR, "zonal_stats.json")


def _read_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


# ---- Structural tests ----

def test_output_files_exist():
    """All required output files must be present."""
    for idx in INDEX_NAMES:
        path = os.path.join(INDICES_DIR, f"{idx}.tif")
        assert os.path.isfile(path), f"Missing output: {path}"
    assert os.path.isfile(ZONAL_STATS_PATH), f"Missing: {ZONAL_STATS_PATH}"


def test_ndvi_crs_and_shape():
    """NDVI raster must have correct CRS and dimensions matching the input."""
    with rasterio.open(os.path.join(INDICES_DIR, "NDVI.tif")) as src:
        assert src.crs.to_epsg() == 32633, f"Expected EPSG:32633, got {src.crs}"
        assert src.width == 300, f"Expected width 300, got {src.width}"
        assert src.height == 300, f"Expected height 300, got {src.height}"
        assert src.count == 1, f"Expected 1 band, got {src.count}"


def test_transform_preserved():
    """Output affine transform must match the input raster grid."""
    with rasterio.open(INPUT_RASTER) as src_in:
        in_t = src_in.transform
    with rasterio.open(os.path.join(INDICES_DIR, "NDVI.tif")) as src_out:
        out_t = src_out.transform
    for attr in ['a', 'b', 'c', 'd', 'e', 'f']:
        assert abs(getattr(in_t, attr) - getattr(out_t, attr)) < 1e-6, \
            f"Transform mismatch on '{attr}'"


# ---- Value correctness ----

def test_ndvi_values_in_range():
    """Valid NDVI pixels must be within [-1, 1]."""
    with rasterio.open(os.path.join(INDICES_DIR, "NDVI.tif")) as src:
        data = src.read(1)
        nodata = src.nodata
    valid = data[data != nodata]
    assert len(valid) > 0, "No valid NDVI pixels found"
    assert np.all(valid >= -1.0) and np.all(valid <= 1.0), \
        f"NDVI out of range: [{valid.min()}, {valid.max()}]"


def test_nodata_propagation():
    """Where ANY input band is nodata, all index outputs must be nodata."""
    with rasterio.open(INPUT_RASTER) as src:
        input_data = src.read()
        in_nodata = src.nodata
    input_nodata_mask = np.any(input_data == in_nodata, axis=0)

    for idx in INDEX_NAMES:
        with rasterio.open(os.path.join(INDICES_DIR, f"{idx}.tif")) as src:
            out_data = src.read(1)
            out_nodata = src.nodata
        out_nodata_mask = (out_data == out_nodata)
        missed = input_nodata_mask & ~out_nodata_mask
        assert not np.any(missed), \
            f"{idx}: {missed.sum()} input-nodata pixels are not nodata in output"


def test_division_by_zero_handling():
    """Hazard pixels (Red=NIR=0) must be nodata with no inf/nan in valid data."""
    with rasterio.open(os.path.join(INDICES_DIR, "NDVI.tif")) as src:
        data = src.read(1)
        nodata = src.nodata

    valid = data[data != nodata]
    assert not np.any(np.isinf(valid)), "Found inf in valid NDVI pixels"
    assert not np.any(np.isnan(valid)), "Found nan in valid NDVI pixels"

    # Specific hazard pixels at rows 100, cols 100-102
    for r, c in [(100, 100), (100, 101), (100, 102)]:
        assert data[r, c] == nodata, \
            f"Hazard pixel ({r},{c}) should be nodata, got {data[r, c]}"


# ---- COG structure ----

def test_cog_structure():
    """Each index raster must be internally tiled with overview pyramids."""
    for idx in INDEX_NAMES:
        path = os.path.join(INDICES_DIR, f"{idx}.tif")
        with rasterio.open(path) as src:
            bs = src.block_shapes
            assert bs[0][0] > 1 and bs[0][1] > 1, \
                f"{idx}: output must be internally tiled, got block {bs[0]}"
            overviews = src.overviews(1)
            assert len(overviews) >= 2, \
                f"{idx}: expected >= 2 overview levels, got {len(overviews)}"


# ---- Zonal statistics ----

def test_zonal_stats_format():
    """Zonal stats JSON must have correct structure."""
    with open(ZONAL_STATS_PATH) as f:
        stats = json.load(f)
    assert isinstance(stats, list), "zonal_stats.json must be a JSON array"
    assert len(stats) == 5, f"Expected 5 zones, got {len(stats)}"

    required_stats = ["mean", "std", "min", "max", "median", "count"]
    for zone in stats:
        assert "zone_id" in zone, "Missing zone_id"
        assert "zone_name" in zone, "Missing zone_name"
        for idx in INDEX_NAMES:
            assert idx in zone, f"Missing index '{idx}' for zone {zone.get('zone_name')}"
            for s in required_stats:
                assert s in zone[idx], \
                    f"Missing stat '{s}' for {idx} in zone {zone.get('zone_name')}"


def test_forest_high_ndvi():
    """Forest zone (dense vegetation) should have high mean NDVI."""
    with open(ZONAL_STATS_PATH) as f:
        stats = json.load(f)
    forest = next(z for z in stats if z["zone_id"] == 1)
    assert forest["NDVI"]["mean"] > 0.3, \
        f"Forest NDVI mean should be > 0.3, got {forest['NDVI']['mean']}"


def test_lake_water_signature():
    """Lake zone (water body) should have negative NDVI and positive NDWI."""
    with open(ZONAL_STATS_PATH) as f:
        stats = json.load(f)
    lake = next(z for z in stats if z["zone_id"] == 2)
    assert lake["NDVI"]["mean"] < 0, \
        f"Lake NDVI mean should be < 0, got {lake['NDVI']['mean']}"
    assert lake["NDWI"]["mean"] > 0, \
        f"Lake NDWI mean should be > 0, got {lake['NDWI']['mean']}"


def test_nodata_excluded_from_stats():
    """Agriculture zone (mostly clean) must have more valid pixels than Mixed zone (clouds)."""
    with open(ZONAL_STATS_PATH) as f:
        stats = json.load(f)
    mixed = next(z for z in stats if z["zone_id"] == 3)
    agri = next(z for z in stats if z["zone_id"] == 4)
    assert agri["NDVI"]["count"] > mixed["NDVI"]["count"], \
        "Agriculture should have more valid pixels than cloud-affected Mixed zone"


def test_partial_zone_coverage():
    """Edge zone (extends beyond raster) must still produce valid results."""
    with open(ZONAL_STATS_PATH) as f:
        stats = json.load(f)
    edge = next(z for z in stats if z["zone_id"] == 5)
    assert edge["NDVI"]["count"] > 0, "Edge zone should have some valid pixels"


# ---- Independent recomputation ----

def test_ndvi_recomputation():
    """Independently recompute NDVI and compare against pipeline output."""
    with rasterio.open(INPUT_RASTER) as src:
        red = src.read(4).astype(np.float64)
        nir = src.read(6).astype(np.float64)
        nodata_in = src.nodata

    with rasterio.open(os.path.join(INDICES_DIR, "NDVI.tif")) as src:
        ndvi_out = src.read(1).astype(np.float64)
        nodata_out = src.nodata

    valid_mask = (red != nodata_in) & (nir != nodata_in)
    denom = nir + red

    with np.errstate(divide='ignore', invalid='ignore'):
        expected = np.where(valid_mask, (nir - red) / denom, nodata_in)

    bad = np.isinf(expected) | np.isnan(expected)
    expected[bad] = nodata_in

    expected[expected != nodata_in] = np.clip(
        expected[expected != nodata_in], -1.0, 1.0
    )

    out_valid = ndvi_out != nodata_out
    exp_valid = expected != nodata_in
    both = out_valid & exp_valid

    if np.any(both):
        diff = np.abs(ndvi_out[both] - expected[both])
        assert np.max(diff) < 0.01, f"NDVI recomputation differs by up to {np.max(diff)}"


def test_evi_recomputation():
    """Independently recompute EVI and compare against pipeline output."""
    config = _read_config()
    valid_range = config["indices"]["EVI"].get("valid_range")

    with rasterio.open(INPUT_RASTER) as src:
        blue = src.read(2).astype(np.float64)
        red = src.read(4).astype(np.float64)
        nir = src.read(6).astype(np.float64)
        nodata_in = src.nodata

    with rasterio.open(os.path.join(INDICES_DIR, "EVI.tif")) as src:
        evi_out = src.read(1).astype(np.float64)
        nodata_out = src.nodata

    valid_mask = (blue != nodata_in) & (red != nodata_in) & (nir != nodata_in)
    denom = nir + 6.0 * red - 7.5 * blue + 10000.0

    with np.errstate(divide='ignore', invalid='ignore'):
        expected = np.where(valid_mask, 2.5 * (nir - red) / denom, nodata_in)

    bad = np.isinf(expected) | np.isnan(expected)
    expected[bad] = nodata_in

    if valid_range:
        v = expected != nodata_in
        expected[v] = np.clip(expected[v], valid_range[0], valid_range[1])

    out_valid = evi_out != nodata_out
    exp_valid = expected != nodata_in
    both = out_valid & exp_valid

    if np.any(both):
        diff = np.abs(evi_out[both] - expected[both])
        assert np.max(diff) < 0.01, f"EVI recomputation differs by up to {np.max(diff)}"
