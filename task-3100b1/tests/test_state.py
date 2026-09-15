
"""Verification tests for the Landsat LST processing pipeline."""

import json
import numpy as np
import pytest
from osgeo import gdal, osr


# ─── helpers ───────────────────────────────────────────────────────────────

def _open(path):
    ds = gdal.Open(path)
    assert ds is not None, f"Cannot open {path}"
    return ds


def _read(path):
    ds = _open(path)
    data = ds.GetRasterBand(1).ReadAsArray()
    return ds, data


# ─── cloud_mask.tif ───────────────────────────────────────────────────────

class TestCloudMask:
    def test_exists_and_shape(self):
        ds, data = _read("/app/output/cloud_mask.tif")
        assert ds.RasterXSize == 100
        assert ds.RasterYSize == 100
        assert ds.GetRasterBand(1).DataType == gdal.GDT_Byte

    def test_known_cloud_pixel(self):
        _, data = _read("/app/output/cloud_mask.tif")
        # Row 10, col 40 is inside cloud region [8:14, 35:55]
        assert data[10, 40] == 1

    def test_known_shadow_pixel(self):
        _, data = _read("/app/output/cloud_mask.tif")
        # Row 16, col 40 is inside shadow region [14:20, 33:53]
        assert data[16, 40] == 1

    def test_known_clear_land_pixel(self):
        _, data = _read("/app/output/cloud_mask.tif")
        assert data[0, 0] == 0

    def test_known_clear_water_pixel(self):
        _, data = _read("/app/output/cloud_mask.tif")
        # Water zone has no clouds; water bit (7) is NOT a contamination bit
        assert data[90, 50] == 0

    def test_total_contaminated_count(self):
        _, data = _read("/app/output/cloud_mask.tif")
        # 2 cloud regions (6x20=120 each) + 2 shadow regions (6x20=120 each) = 480
        assert int(np.sum(data == 1)) == 480

    def test_only_binary_values(self):
        _, data = _read("/app/output/cloud_mask.tif")
        unique = set(np.unique(data))
        assert unique <= {0, 1}


# ─── ndvi.tif ─────────────────────────────────────────────────────────────

class TestNDVI:
    def test_exists_and_dtype(self):
        ds = _open("/app/output/ndvi.tif")
        assert ds.GetRasterBand(1).DataType == gdal.GDT_Float32

    def test_nodata_at_cloud(self):
        _, data = _read("/app/output/ndvi.tif")
        val = float(data[10, 40])
        assert val < -9990, f"Cloud pixel NDVI should be nodata (-9999), got {val}"

    def test_forest_ndvi_range(self):
        _, data = _read("/app/output/ndvi.tif")
        # Clear forest pixel (row 5, col 5)
        val = float(data[5, 5])
        assert 0.7 < val < 0.95, f"Forest NDVI expected 0.7-0.95, got {val}"

    def test_water_ndvi_negative(self):
        _, data = _read("/app/output/ndvi.tif")
        val = float(data[90, 50])
        assert val < 0, f"Water NDVI expected negative, got {val}"

    def test_urban_ndvi_low_positive(self):
        _, data = _read("/app/output/ndvi.tif")
        # Clear urban pixel (row 50, col 10)
        val = float(data[50, 10])
        assert 0.05 < val < 0.45, f"Urban NDVI expected 0.05-0.45, got {val}"

    def test_valid_range(self):
        _, data = _read("/app/output/ndvi.tif")
        valid = data[data > -9990]
        assert np.all(valid >= -1.0)
        assert np.all(valid <= 1.0)


# ─── lst_kelvin.tif ───────────────────────────────────────────────────────

class TestLST:
    def test_exists_and_dtype(self):
        ds = _open("/app/output/lst_kelvin.tif")
        assert ds.GetRasterBand(1).DataType == gdal.GDT_Float32

    def test_nodata_at_cloud(self):
        _, data = _read("/app/output/lst_kelvin.tif")
        val = float(data[10, 40])
        assert val < -9990, f"Cloud pixel LST should be nodata, got {val}"

    def test_forest_lst_range(self):
        _, data = _read("/app/output/lst_kelvin.tif")
        val = float(data[5, 5])
        assert 290 < val < 310, f"Forest LST expected 290-310K, got {val}"

    def test_urban_lst_range(self):
        _, data = _read("/app/output/lst_kelvin.tif")
        val = float(data[50, 10])
        assert 300 < val < 320, f"Urban LST expected 300-320K, got {val}"

    def test_water_lst_range(self):
        _, data = _read("/app/output/lst_kelvin.tif")
        val = float(data[90, 50])
        assert 285 < val < 305, f"Water LST expected 285-305K, got {val}"

    def test_urban_warmer_than_forest(self):
        _, data = _read("/app/output/lst_kelvin.tif")
        forest_lst = float(data[5, 5])
        urban_lst = float(data[50, 10])
        assert urban_lst > forest_lst, (
            f"Urban ({urban_lst:.1f}K) should be warmer than forest ({forest_lst:.1f}K)"
        )

    def test_valid_kelvin_range(self):
        _, data = _read("/app/output/lst_kelvin.tif")
        valid = data[data > -9990]
        assert np.all(valid > 250), "LST values below 250K are unrealistic"
        assert np.all(valid < 350), "LST values above 350K are unrealistic"


# ─── slope.tif ────────────────────────────────────────────────────────────

class TestSlope:
    def test_exists_and_dtype(self):
        ds = _open("/app/output/slope.tif")
        assert ds.GetRasterBand(1).DataType == gdal.GDT_Float32

    def test_non_negative(self):
        _, data = _read("/app/output/slope.tif")
        assert np.all(data >= 0), "Slope must be non-negative"

    def test_bounded(self):
        _, data = _read("/app/output/slope.tif")
        assert np.all(data <= 90), "Slope must not exceed 90 degrees"

    def test_center_flatter_than_flank(self):
        _, data = _read("/app/output/slope.tif")
        # DEM has gaussian hill at (50,50); center is flat, flanks are steep
        center = float(data[50, 50])
        flank = float(data[30, 50])
        assert flank > center, (
            f"Flank slope ({flank:.2f}°) should exceed center ({center:.2f}°)"
        )

    def test_dimensions(self):
        ds = _open("/app/output/slope.tif")
        assert ds.RasterXSize == 100
        assert ds.RasterYSize == 100


# ─── zonal_stats.json ─────────────────────────────────────────────────────

class TestZonalStats:
    @pytest.fixture
    def stats(self):
        with open("/app/output/zonal_stats.json") as f:
            return json.load(f)

    def test_all_zones_present(self, stats):
        for z in ("forest_grassland", "urban_bare", "lake"):
            assert z in stats, f"Missing zone: {z}"

    def test_required_fields(self, stats):
        required = {"mean_lst", "mean_ndvi", "cloud_fraction",
                     "mean_slope", "clear_pixel_count", "total_pixel_count",
                     "lst_p10", "lst_p50", "lst_p90"}
        for zone_name, zone_data in stats.items():
            for field in required:
                assert field in zone_data, f"{zone_name} missing field: {field}"

    def test_forest_grassland_pixel_counts(self, stats):
        fg = stats["forest_grassland"]
        assert fg["total_pixel_count"] == 4000
        # 240 contaminated pixels (120 cloud + 120 shadow)
        assert fg["clear_pixel_count"] == 3760

    def test_urban_bare_pixel_counts(self, stats):
        ub = stats["urban_bare"]
        assert ub["total_pixel_count"] == 4000
        assert ub["clear_pixel_count"] == 3760

    def test_lake_no_clouds(self, stats):
        lk = stats["lake"]
        assert lk["total_pixel_count"] == 2000
        assert lk["clear_pixel_count"] == 2000
        assert lk["cloud_fraction"] == pytest.approx(0.0, abs=1e-6)

    def test_cloud_fractions_positive(self, stats):
        assert stats["forest_grassland"]["cloud_fraction"] > 0
        assert stats["urban_bare"]["cloud_fraction"] > 0

    def test_vegetation_ndvi_ordering(self, stats):
        fg_ndvi = stats["forest_grassland"]["mean_ndvi"]
        ub_ndvi = stats["urban_bare"]["mean_ndvi"]
        assert fg_ndvi > ub_ndvi, "Forest/grassland should have higher NDVI than urban/bare"

    def test_urban_warmer_than_forest(self, stats):
        fg_lst = stats["forest_grassland"]["mean_lst"]
        ub_lst = stats["urban_bare"]["mean_lst"]
        assert ub_lst > fg_lst, "Urban/bare zone should be warmer than forest/grassland"

    def test_lake_negative_ndvi(self, stats):
        assert stats["lake"]["mean_ndvi"] < 0, "Lake zone should have negative NDVI"

    def test_lake_cooler_than_urban(self, stats):
        assert stats["lake"]["mean_lst"] < stats["urban_bare"]["mean_lst"]

    # ─── percentile tests ────────────────────────────────────────────────

    def test_percentile_ordering(self, stats):
        for zone_name, zone_data in stats.items():
            p10 = zone_data["lst_p10"]
            p50 = zone_data["lst_p50"]
            p90 = zone_data["lst_p90"]
            assert p10 <= p50 <= p90, (
                f"{zone_name}: percentiles not ordered ({p10}, {p50}, {p90})"
            )

    def test_percentiles_in_valid_range(self, stats):
        for zone_name, zone_data in stats.items():
            for p in ["lst_p10", "lst_p50", "lst_p90"]:
                val = zone_data[p]
                assert 250 < val < 350, (
                    f"{zone_name} {p} = {val}, outside valid thermal range"
                )

    def test_mixed_zone_percentile_spread(self, stats):
        # forest_grassland has two land cover types with different LST → spread
        fg = stats["forest_grassland"]
        spread = fg["lst_p90"] - fg["lst_p10"]
        assert spread > 2.0, (
            f"Forest/grassland zone expected LST spread > 2K, got {spread:.2f}K"
        )

    def test_uniform_zone_percentile_tight(self, stats):
        # Lake zone is uniform water → tight percentile spread
        lk = stats["lake"]
        spread = lk["lst_p90"] - lk["lst_p10"]
        assert spread < 5.0, (
            f"Lake zone expected tight LST spread < 5K, got {spread:.2f}K"
        )

    def test_urban_p50_warmer_than_forest_p50(self, stats):
        ub_p50 = stats["urban_bare"]["lst_p50"]
        fg_p50 = stats["forest_grassland"]["lst_p50"]
        assert ub_p50 > fg_p50, (
            f"Urban p50 ({ub_p50:.1f}K) should exceed forest p50 ({fg_p50:.1f}K)"
        )


# ─── CRS consistency ──────────────────────────────────────────────────────

class TestCRS:
    def test_all_outputs_match_input_crs(self):
        ref_ds = _open("/data/landsat/SR_B4.tif")
        ref_srs = osr.SpatialReference()
        ref_srs.ImportFromWkt(ref_ds.GetProjection())

        for name in ("cloud_mask.tif", "ndvi.tif", "lst_kelvin.tif", "slope.tif"):
            ds = _open(f"/app/output/{name}")
            out_srs = osr.SpatialReference()
            out_srs.ImportFromWkt(ds.GetProjection())
            assert ref_srs.IsSame(out_srs), f"CRS mismatch for {name}"
