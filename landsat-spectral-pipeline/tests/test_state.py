"""Tests for corrected Landsat surface reflectance pipeline outputs."""

import os
import csv
import json
import pytest
import numpy as np
import rasterio

OUTPUT_DIR = "/app/output"


class TestOutputFilesExist:
    """All required output files must be present."""

    @pytest.mark.parametrize("filename", [
        "cloud_mask.tif",
        "ndvi.tif",
        "mndwi.tif",
        "land_cover.tif",
        "zonal_stats.csv",
        "ndvi_wgs84.tif",
        "quality_assessment.json",
    ])
    def test_file_exists(self, filename):
        path = os.path.join(OUTPUT_DIR, filename)
        assert os.path.isfile(path), f"Missing output: {path}"


class TestCloudMask:
    """Verify cloud mask pixel values at known locations."""

    @pytest.fixture(autouse=True)
    def load_mask(self):
        with rasterio.open(os.path.join(OUTPUT_DIR, "cloud_mask.tif")) as ds:
            self.data = ds.read(1)
            self.rows, self.cols = self.data.shape

    def test_dimensions(self):
        assert self.rows == 200 and self.cols == 200

    def test_dtype(self):
        assert self.data.dtype == np.uint8

    def test_fill_pixels_masked(self):
        assert self.data[1, 1] == 0, "Fill pixel should be masked"
        assert self.data[1, 198] == 0, "Fill pixel should be masked"

    def test_dilated_cloud_masked(self):
        """Dilated cloud buffer zones around cloud bodies must be masked."""
        assert self.data[29, 50] == 0, "Dilated cloud pixel should be masked"
        assert self.data[51, 40] == 0, "Dilated cloud pixel should be masked"

    def test_cloud_pixels_masked(self):
        assert self.data[40, 50] == 0, "Cloud pixel should be masked"
        assert self.data[35, 30] == 0, "Cloud pixel should be masked"

    def test_cloud_shadow_masked(self):
        assert self.data[65, 60] == 0, "Cloud shadow pixel should be masked"
        assert self.data[70, 80] == 0, "Cloud shadow pixel should be masked"

    def test_cirrus_masked(self):
        assert self.data[150, 150] == 0, "Cirrus pixel should be masked"
        assert self.data[145, 145] == 0, "Cirrus pixel should be masked"

    def test_clear_vegetation_unmasked(self):
        assert self.data[10, 10] == 1, "Clear vegetation pixel should be unmasked"
        assert self.data[80, 80] == 1, "Clear vegetation pixel should be unmasked"

    def test_water_pixels_unmasked(self):
        """Water bit (bit 7) does NOT indicate contamination."""
        assert self.data[10, 150] == 1, "Water pixel should be unmasked"
        assert self.data[50, 120] == 1, "Water pixel should be unmasked"

    def test_clear_urban_unmasked(self):
        assert self.data[150, 50] == 1, "Clear urban pixel should be unmasked"

    def test_clear_barren_unmasked(self):
        assert self.data[180, 180] == 1, "Clear barren pixel should be unmasked"


class TestNDVI:
    """Verify NDVI computation and masking."""

    @pytest.fixture(autouse=True)
    def load_ndvi(self):
        with rasterio.open(os.path.join(OUTPUT_DIR, "ndvi.tif")) as ds:
            self.nodata = ds.nodata
            self.data = ds.read(1)
            self.dtype = self.data.dtype

    def test_dtype_float32(self):
        assert self.dtype == np.float32

    def test_nodata_value(self):
        assert self.nodata is not None
        assert abs(self.nodata - (-9999.0)) < 1.0

    def test_vegetation_ndvi_high(self):
        val = self.data[10, 10]
        assert 0.65 < val < 0.95, f"Vegetation NDVI={val}, expected ~0.80"

    def test_water_ndvi_negative(self):
        val = self.data[10, 150]
        assert -0.55 < val < -0.15, f"Water NDVI={val}, expected ~-0.33"

    def test_urban_ndvi_low(self):
        val = self.data[150, 50]
        assert 0.0 < val < 0.30, f"Urban NDVI={val}, expected ~0.14"

    def test_bare_soil_ndvi_low(self):
        val = self.data[180, 180]
        assert 0.0 < val < 0.25, f"Bare soil NDVI={val}, expected ~0.12"

    def test_cloud_pixel_is_nodata(self):
        val = self.data[40, 50]
        assert abs(val - (-9999.0)) < 1.0, "Clouded pixel should be nodata"

    def test_shadow_pixel_is_nodata(self):
        val = self.data[65, 60]
        assert abs(val - (-9999.0)) < 1.0, "Shadow pixel should be nodata"

    def test_dilated_cloud_pixel_is_nodata(self):
        val = self.data[29, 50]
        assert abs(val - (-9999.0)) < 1.0, "Dilated cloud pixel should be nodata"

    def test_valid_range(self):
        valid = self.data[np.abs(self.data - (-9999.0)) > 1.0]
        assert np.all(valid >= -1.0) and np.all(valid <= 1.0), \
            "Valid NDVI must be in [-1, 1]"


class TestMNDWI:
    """Verify MNDWI computation."""

    @pytest.fixture(autouse=True)
    def load_mndwi(self):
        with rasterio.open(os.path.join(OUTPUT_DIR, "mndwi.tif")) as ds:
            self.nodata = ds.nodata
            self.data = ds.read(1)

    def test_water_mndwi_positive(self):
        val = self.data[10, 150]
        assert 0.4 < val < 0.9, f"Water MNDWI={val}, expected ~0.71"

    def test_vegetation_mndwi_negative(self):
        val = self.data[10, 10]
        assert -0.55 < val < -0.20, f"Vegetation MNDWI={val}, expected ~-0.38"

    def test_urban_mndwi_negative(self):
        val = self.data[150, 50]
        assert -0.60 < val < -0.25, f"Urban MNDWI={val}, expected ~-0.40"

    def test_cloud_pixel_is_nodata(self):
        val = self.data[40, 50]
        assert abs(val - (-9999.0)) < 1.0, "Clouded pixel should be nodata"

    def test_valid_range(self):
        valid = self.data[np.abs(self.data - (-9999.0)) > 1.0]
        assert np.all(valid >= -1.0) and np.all(valid <= 1.0), \
            "Valid MNDWI must be in [-1, 1]"


class TestLandCover:
    """Verify land cover classification."""

    @pytest.fixture(autouse=True)
    def load_lc(self):
        with rasterio.open(os.path.join(OUTPUT_DIR, "land_cover.tif")) as ds:
            self.data = ds.read(1)

    def test_dtype(self):
        assert self.data.dtype == np.uint8

    def test_water_classification(self):
        assert self.data[25, 150] == 1, "Water quadrant center should be class 1"

    def test_vegetation_classification(self):
        assert self.data[25, 25] == 2, "Vegetation quadrant center should be class 2"

    def test_urban_classification(self):
        assert self.data[150, 25] == 3, "Urban quadrant center should be class 3"

    def test_bare_soil_classification(self):
        assert self.data[175, 175] == 4, "Bare soil quadrant center should be class 4"

    def test_cloud_pixel_nodata(self):
        assert self.data[40, 50] == 0, "Clouded pixel should be class 0 (NoData)"

    def test_cirrus_pixel_nodata(self):
        assert self.data[150, 150] == 0, "Cirrus pixel should be class 0 (NoData)"

    def test_only_valid_classes(self):
        unique = set(np.unique(self.data))
        assert unique.issubset({0, 1, 2, 3, 4}), f"Unexpected classes: {unique}"


class TestZonalStats:
    """Verify zonal statistics CSV."""

    @pytest.fixture(autouse=True)
    def load_csv(self):
        csv_path = os.path.join(OUTPUT_DIR, "zonal_stats.csv")
        assert os.path.isfile(csv_path), "zonal_stats.csv missing"
        with open(csv_path) as f:
            reader = csv.DictReader(f)
            self.rows = list(reader)
        self.by_zone = {int(r["zone_id"]): r for r in self.rows}

    def test_has_four_zones(self):
        assert len(self.rows) == 4

    def test_header_columns(self):
        expected = {"zone_id", "zone_name", "mean_ndvi", "mean_mndwi", "clear_pixel_count"}
        assert expected.issubset(set(self.rows[0].keys()))

    def test_vegetation_zone_ndvi(self):
        val = float(self.by_zone[1]["mean_ndvi"])
        assert 0.5 < val < 0.95, f"Zone 1 mean NDVI={val}, expected ~0.80"

    def test_water_zone_ndvi(self):
        val = float(self.by_zone[2]["mean_ndvi"])
        assert -0.55 < val < -0.10, f"Zone 2 mean NDVI={val}, expected ~-0.33"

    def test_urban_zone_ndvi(self):
        val = float(self.by_zone[3]["mean_ndvi"])
        assert 0.0 < val < 0.30, f"Zone 3 mean NDVI={val}, expected ~0.14"

    def test_barren_zone_ndvi(self):
        val = float(self.by_zone[4]["mean_ndvi"])
        assert 0.0 < val < 0.25, f"Zone 4 mean NDVI={val}, expected ~0.12"

    def test_water_zone_mndwi(self):
        val = float(self.by_zone[2]["mean_mndwi"])
        assert 0.3 < val < 0.9, f"Zone 2 mean MNDWI={val}, expected ~0.71"

    def test_vegetation_zone_mndwi(self):
        val = float(self.by_zone[1]["mean_mndwi"])
        assert -0.55 < val < -0.20, f"Zone 1 mean MNDWI={val}, expected ~-0.38"

    def test_clear_pixel_counts_positive(self):
        for zid in [1, 2, 3, 4]:
            count = int(self.by_zone[zid]["clear_pixel_count"])
            assert count > 1000, f"Zone {zid} has too few clear pixels: {count}"

    def test_vegetation_zone_has_fewer_clear_pixels(self):
        """Zone 1 overlaps with cloud, shadow, and dilated cloud; should have fewer clear pixels than zone 2."""
        z1 = int(self.by_zone[1]["clear_pixel_count"])
        z2 = int(self.by_zone[2]["clear_pixel_count"])
        assert z1 < z2, f"Zone 1 ({z1}) should have fewer clear pixels than zone 2 ({z2})"


class TestNDVIWGS84:
    """Verify reprojected NDVI raster."""

    @pytest.fixture(autouse=True)
    def load_reprojected(self):
        with rasterio.open(os.path.join(OUTPUT_DIR, "ndvi_wgs84.tif")) as ds:
            self.crs = ds.crs
            self.nodata = ds.nodata
            self.data = ds.read(1)
            self.bounds = ds.bounds

    def test_crs_is_wgs84(self):
        epsg = self.crs.to_epsg()
        assert epsg == 4326, f"CRS should be EPSG:4326 but got {epsg}"

    def test_nodata_preserved(self):
        assert self.nodata is not None
        assert abs(self.nodata - (-9999.0)) < 1.0

    def test_has_valid_data(self):
        valid = self.data[np.abs(self.data - (-9999.0)) > 1.0]
        assert len(valid) > 100, "Reprojected NDVI should contain valid data"

    def test_valid_range(self):
        valid = self.data[np.abs(self.data - (-9999.0)) > 1.0]
        assert np.all(valid >= -1.0) and np.all(valid <= 1.0)

    def test_geographic_extent(self):
        assert -90 < self.bounds.left < -70, \
            f"West bound {self.bounds.left} outside expected range"
        assert 20 < self.bounds.top < 35, \
            f"North bound {self.bounds.top} outside expected range"


class TestQualityAssessment:
    """Verify quality assessment JSON document."""

    @pytest.fixture(autouse=True)
    def load_qa(self):
        qa_path = os.path.join(OUTPUT_DIR, "quality_assessment.json")
        assert os.path.isfile(qa_path), "quality_assessment.json missing"
        with open(qa_path) as f:
            self.qa = json.load(f)

    def test_has_required_sections(self):
        for key in ["defects", "scene_quality", "calibration_validation", "zone_quality"]:
            assert key in self.qa, f"Missing top-level key: {key}"

    def test_minimum_four_defects(self):
        assert len(self.qa["defects"]) >= 4, \
            f"Expected at least 4 defects, found {len(self.qa['defects'])}"

    def test_defect_schema(self):
        required_keys = {"id", "category", "description", "affected_pixel_count", "severity"}
        for d in self.qa["defects"]:
            missing = required_keys - set(d.keys())
            assert not missing, f"Defect {d.get('id', '?')} missing keys: {missing}"
            assert d["severity"] in ("critical", "major", "minor")
            assert isinstance(d["affected_pixel_count"], int)
            assert d["affected_pixel_count"] > 0

    def test_defects_cover_masking(self):
        all_text = " ".join(
            f"{d.get('category', '')} {d.get('description', '')}".lower()
            for d in self.qa["defects"]
        )
        assert any(kw in all_text for kw in ["mask", "qa", "fill", "cirrus", "dilated"]), \
            "Defects must identify QA masking gaps"

    def test_defects_cover_calibration(self):
        all_text = " ".join(
            f"{d.get('category', '')} {d.get('description', '')}".lower()
            for d in self.qa["defects"]
        )
        assert any(kw in all_text for kw in ["calibr", "offset", "reflectance"]), \
            "Defects must identify calibration error"

    def test_defects_cover_zonal_stats(self):
        all_text = " ".join(
            f"{d.get('category', '')} {d.get('description', '')}".lower()
            for d in self.qa["defects"]
        )
        assert any(kw in all_text for kw in ["zonal", "count", "statistic"]), \
            "Defects must identify zonal statistics error"

    def test_defects_cover_reprojection(self):
        all_text = " ".join(
            f"{d.get('category', '')} {d.get('description', '')}".lower()
            for d in self.qa["defects"]
        )
        assert any(kw in all_text for kw in
                    ["reproject", "wgs84", "4326", "missing", "completeness"]), \
            "Defects must identify missing reprojection"

    def test_scene_quality_keys(self):
        sq = self.qa["scene_quality"]
        for key in ["clear_pixel_fraction", "usability_grade", "grade_justification"]:
            assert key in sq, f"Missing scene_quality key: {key}"

    def test_clear_pixel_fraction_range(self):
        frac = self.qa["scene_quality"]["clear_pixel_fraction"]
        assert 0.85 < frac < 0.97, \
            f"Clear pixel fraction {frac} outside expected range (0.85, 0.97)"

    def test_usability_grade_valid(self):
        grade = self.qa["scene_quality"]["usability_grade"]
        assert grade in ("A", "B", "C"), \
            f"Usability grade '{grade}' unexpected for ~92% clear scene"

    def test_calibration_validation_keys(self):
        cv = self.qa["calibration_validation"]
        for key in ["nir_field_reference", "nir_pipeline_corrected",
                     "nir_residual_abs", "calibration_status"]:
            assert key in cv, f"Missing calibration_validation key: {key}"

    def test_nir_field_reference_value(self):
        ref = self.qa["calibration_validation"]["nir_field_reference"]
        assert 0.40 < ref < 0.50, \
            f"NIR field reference {ref} should be ~0.45 per validation report"

    def test_calibration_passes(self):
        cv = self.qa["calibration_validation"]
        assert cv["calibration_status"] == "pass"
        assert cv["nir_residual_abs"] < 0.05

    def test_zone_quality_count(self):
        assert len(self.qa["zone_quality"]) >= 4

    def test_zone_quality_schema(self):
        for z in self.qa["zone_quality"]:
            for key in ["zone_id", "clear_fraction", "data_usability"]:
                assert key in z, f"Missing zone_quality key: {key}"
            assert z["data_usability"] in ("high", "medium", "low")

    def test_zone1_lower_quality(self):
        by_id = {z["zone_id"]: z for z in self.qa["zone_quality"]}
        assert by_id[1]["clear_fraction"] < 0.80, \
            "Zone 1 overlaps cloud/shadow; clear_fraction should be < 0.80"
        assert by_id[1]["data_usability"] == "medium"

    def test_zone2_high_quality(self):
        by_id = {z["zone_id"]: z for z in self.qa["zone_quality"]}
        assert by_id[2]["clear_fraction"] > 0.90
        assert by_id[2]["data_usability"] == "high"
