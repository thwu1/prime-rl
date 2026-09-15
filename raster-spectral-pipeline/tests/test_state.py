
import pytest
import json
import os
import numpy as np

OUTPUT_DIR = "/app/output"


# ---------------------------------------------------------------------------
# File existence
# ---------------------------------------------------------------------------
class TestOutputFilesExist:
    def test_suitability_tif(self):
        assert os.path.isfile(f"{OUTPUT_DIR}/suitability.tif")

    def test_suitability_classified_tif(self):
        assert os.path.isfile(f"{OUTPUT_DIR}/suitability_classified.tif")

    def test_suitable_sites_geojson(self):
        assert os.path.isfile(f"{OUTPUT_DIR}/suitable_sites.geojson")

    def test_report_json(self):
        assert os.path.isfile(f"{OUTPUT_DIR}/report.json")


# ---------------------------------------------------------------------------
# Suitability raster
# ---------------------------------------------------------------------------
class TestSuitabilityRaster:
    @pytest.fixture(autouse=True)
    def setup(self):
        import rasterio

        self.ds = rasterio.open(f"{OUTPUT_DIR}/suitability.tif")
        self.data = self.ds.read(1)
        yield
        self.ds.close()

    def test_single_band(self):
        assert self.ds.count == 1

    def test_dimensions(self):
        assert self.ds.width == 400 and self.ds.height == 400

    def test_crs(self):
        assert self.ds.crs.to_epsg() == 32617

    def test_resolution(self):
        assert abs(self.ds.res[0] - 30.0) < 0.1
        assert abs(self.ds.res[1] - 30.0) < 0.1

    def test_values_in_unit_interval(self):
        valid = self.data[self.data != 0]
        if len(valid) > 0:
            assert valid.min() >= -0.001, f"Min suitability {valid.min()} < 0"
            assert valid.max() <= 1.001, f"Max suitability {valid.max()} > 1"

    def test_nodata_strip_zero(self):
        strip = self.data[:, 380:]
        assert np.all(strip == 0), "Nodata strip (cols 380-399) should be 0"

    def test_protected_area_zero(self):
        val = self.data[200, 210]
        assert val == 0, f"Protected pixel (200,210) should be 0, got {val}"

    def test_protected_area_small_reserve_zero(self):
        val = self.data[50, 50]
        assert val == 0, f"Small reserve pixel (50,50) should be 0, got {val}"

    def test_urban_zero(self):
        val = self.data[85, 285]
        assert val == 0, f"Urban pixel (85,285) should be 0, got {val}"

    def test_water_center_zero(self):
        val = self.data[350, 100]
        assert val == 0, f"Water center pixel (350,100) should be 0, got {val}"

    def test_flood_zone_nonwater_zero(self):
        val = self.data[320, 120]
        assert val == 0, f"Flood zone pixel (320,120) should be 0, got {val}"

    def test_suitable_barren_pixel_positive(self):
        val = self.data[350, 255]
        assert val > 0.5, f"Barren pixel near road (350,255) should be > 0.5, got {val}"

    def test_has_spatial_variation(self):
        valid = self.data[(self.data > 0) & (self.data <= 1)]
        assert valid.std() > 0.05, "Suitability should have spatial variation"


# ---------------------------------------------------------------------------
# Classified raster
# ---------------------------------------------------------------------------
class TestClassifiedRaster:
    @pytest.fixture(autouse=True)
    def setup(self):
        import rasterio

        self.ds = rasterio.open(f"{OUTPUT_DIR}/suitability_classified.tif")
        self.data = self.ds.read(1)
        yield
        self.ds.close()

    def test_single_band(self):
        assert self.ds.count == 1

    def test_dimensions(self):
        assert self.ds.width == 400 and self.ds.height == 400

    def test_crs(self):
        assert self.ds.crs.to_epsg() == 32617

    def test_valid_class_values(self):
        unique = set(np.unique(self.data))
        assert unique.issubset({0, 1, 2, 3, 4, 5}), f"Unexpected classes: {unique}"

    def test_five_classes_present(self):
        unique = set(np.unique(self.data)) - {0}
        assert len(unique) == 5, f"Expected 5 classes, got {len(unique)}: {unique}"

    def test_constrained_pixels_class_zero(self):
        assert self.data[200, 210] == 0, "Protected pixel should be class 0"
        assert self.data[85, 285] == 0, "Urban pixel should be class 0"

    def test_class_monotonic_suitability(self):
        """Higher class number should correspond to higher mean suitability."""
        import rasterio

        with rasterio.open(f"{OUTPUT_DIR}/suitability.tif") as suit_ds:
            suit = suit_ds.read(1)
        means = []
        for c in range(1, 6):
            mask = self.data == c
            if mask.sum() > 0:
                means.append(float(suit[mask].mean()))
            else:
                means.append(0)
        for i in range(len(means) - 1):
            assert means[i] <= means[i + 1] + 0.01, (
                f"Class {i+1} mean ({means[i]:.4f}) > class {i+2} mean ({means[i+1]:.4f})"
            )


# ---------------------------------------------------------------------------
# Report JSON
# ---------------------------------------------------------------------------
class TestReport:
    @pytest.fixture(autouse=True)
    def setup(self):
        with open(f"{OUTPUT_DIR}/report.json") as f:
            self.report = json.load(f)

    def test_has_ahp_weights(self):
        assert "ahp_weights" in self.report
        w = self.report["ahp_weights"]
        assert len(w) == 5

    def test_weights_sum_to_one(self):
        total = sum(self.report["ahp_weights"].values())
        assert abs(total - 1.0) < 0.01, f"Weights sum to {total}"

    def test_slope_weight_range(self):
        w = self.report["ahp_weights"]["slope"]
        assert 0.28 < w < 0.36, f"Slope weight {w} outside [0.28, 0.36]"

    def test_aspect_weight_range(self):
        w = self.report["ahp_weights"]["aspect"]
        assert 0.08 < w < 0.14, f"Aspect weight {w} outside [0.08, 0.14]"

    def test_road_distance_weight_range(self):
        w = self.report["ahp_weights"]["road_distance"]
        assert 0.15 < w < 0.22, f"Road weight {w} outside [0.15, 0.22]"

    def test_landcover_weight_range(self):
        w = self.report["ahp_weights"]["landcover"]
        assert 0.04 < w < 0.10, f"Landcover weight {w} outside [0.04, 0.10]"

    def test_irradiance_weight_range(self):
        w = self.report["ahp_weights"]["irradiance"]
        assert 0.28 < w < 0.36, f"Irradiance weight {w} outside [0.28, 0.36]"

    def test_slope_equals_irradiance_weight(self):
        ws = self.report["ahp_weights"]["slope"]
        wi = self.report["ahp_weights"]["irradiance"]
        assert abs(ws - wi) < 0.005, (
            f"Slope ({ws}) and irradiance ({wi}) should be equal (identical AHP rows)"
        )

    def test_consistency_ratio_below_threshold(self):
        cr = self.report["consistency_ratio"]
        assert 0 <= cr < 0.10, f"CR {cr} not in [0, 0.10)"

    def test_has_criterion_statistics(self):
        assert "criterion_statistics" in self.report
        cs = self.report["criterion_statistics"]
        for name in ["slope", "aspect", "road_distance", "landcover", "irradiance"]:
            assert name in cs, f"Missing criterion stats: {name}"

    def test_criterion_stat_fields(self):
        required = [
            "raw_min",
            "raw_max",
            "raw_mean",
            "normalized_min",
            "normalized_max",
            "normalized_mean",
        ]
        for name, stat in self.report["criterion_statistics"].items():
            for field in required:
                assert field in stat, f"{name} missing field {field}"

    def test_normalized_bounds(self):
        for name, stat in self.report["criterion_statistics"].items():
            assert stat["normalized_min"] >= -0.001, f"{name} norm min < 0"
            assert stat["normalized_max"] <= 1.001, f"{name} norm max > 1"

    def test_has_site_summary(self):
        assert "site_summary" in self.report
        assert len(self.report["site_summary"]) > 0, "No sites found"

    def test_site_summary_fields(self):
        required = [
            "site_id",
            "area_ha",
            "mean_suitability",
            "max_suitability",
            "centroid_x",
            "centroid_y",
        ]
        for site in self.report["site_summary"]:
            for field in required:
                assert field in site, f"Site missing field {field}"

    def test_sites_ranked_by_suitability(self):
        ss = self.report["site_summary"]
        for i in range(len(ss) - 1):
            assert ss[i]["mean_suitability"] >= ss[i + 1]["mean_suitability"] - 0.0001, (
                f"Sites not sorted: site {ss[i]['site_id']} ({ss[i]['mean_suitability']:.4f}) "
                f"< site {ss[i+1]['site_id']} ({ss[i+1]['mean_suitability']:.4f})"
            )

    def test_has_sensitivity(self):
        assert "sensitivity" in self.report
        sens = self.report["sensitivity"]
        assert len(sens) == 5

    def test_sensitivity_fields(self):
        for name, s in self.report["sensitivity"].items():
            assert "weight_plus_10pct" in s, f"{name} missing weight_plus_10pct"
            assert "weight_minus_10pct" in s, f"{name} missing weight_minus_10pct"
            assert "delta" in s, f"{name} missing delta"

    def test_sensitivity_has_nonzero_delta(self):
        sens = self.report["sensitivity"]
        deltas = [abs(s["delta"]) for s in sens.values()]
        assert max(deltas) > 0, "All sensitivity deltas are zero"

    def test_sensitivity_all_criteria(self):
        sens = self.report["sensitivity"]
        for name in ["slope", "aspect", "road_distance", "landcover", "irradiance"]:
            assert name in sens, f"Missing sensitivity for {name}"


# ---------------------------------------------------------------------------
# Suitable sites GeoJSON
# ---------------------------------------------------------------------------
class TestSitesGeoJSON:
    @pytest.fixture(autouse=True)
    def setup(self):
        with open(f"{OUTPUT_DIR}/suitable_sites.geojson") as f:
            self.geojson = json.load(f)

    def test_is_feature_collection(self):
        assert self.geojson["type"] == "FeatureCollection"

    def test_has_features(self):
        assert len(self.geojson["features"]) > 0

    def test_feature_properties_present(self):
        required = [
            "site_id",
            "area_ha",
            "mean_suitability",
            "max_suitability",
            "centroid_x",
            "centroid_y",
        ]
        for feat in self.geojson["features"]:
            props = feat["properties"]
            for field in required:
                assert field in props, f"Feature missing property {field}"

    def test_min_site_area(self):
        for feat in self.geojson["features"]:
            ha = feat["properties"]["area_ha"]
            assert ha >= 4.9, (
                f"Site {feat['properties']['site_id']} area {ha:.2f} ha < 5.0 ha"
            )

    def test_suitability_above_threshold(self):
        for feat in self.geojson["features"]:
            ms = feat["properties"]["mean_suitability"]
            assert ms >= 0.59, (
                f"Site {feat['properties']['site_id']} mean suitability {ms:.4f} < 0.6"
            )

    def test_geometry_valid(self):
        from shapely.geometry import shape

        for feat in self.geojson["features"]:
            geom = shape(feat["geometry"])
            assert geom.is_valid, (
                f"Invalid geometry for site {feat['properties']['site_id']}"
            )

    def test_centroids_in_projected_crs(self):
        for feat in self.geojson["features"]:
            cx = feat["properties"]["centroid_x"]
            cy = feat["properties"]["centroid_y"]
            assert 490000 < cx < 520000, f"centroid_x {cx} not in UTM range"
            assert 4990000 < cy < 5020000, f"centroid_y {cy} not in UTM range"

    def test_site_ids_sequential(self):
        ids = [f["properties"]["site_id"] for f in self.geojson["features"]]
        assert ids == list(range(1, len(ids) + 1)), f"Site IDs not sequential: {ids}"
