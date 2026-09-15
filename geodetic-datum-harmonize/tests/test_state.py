
import json
import math
import os
import pytest
from pyproj import Transformer, Geod


SURVEY_POINTS = {
    "P01": (27700, 530068.00, 180381.00),
    "P02": (27700, 325000.00, 674000.00),
    "P03": (28992, 121000.00, 487000.00),
    "P04": (28992, 92000.00, 437000.00),
    "P05": (31467, 3399371.19, 5930724.53),
    "P06": (31467, 3478000.00, 5553000.00),
    "P07": (2154, 652000.00, 6862000.00),
    "P08": (2154, 843000.00, 6519000.00),
    "P09": (25833, 290000.00, 4640000.00),
    "P10": (25833, 603000.00, 5340000.00),
}

DATUM_TRANSFORM_EPSG = {27700, 28992, 31467}
SAME_DATUM_EPSG = {2154, 25833}

# Polygon edges in convex-hull order to avoid self-intersection
DISTANCE_PAIRS = ["P01_P03", "P03_P05", "P05_P09", "P09_P07", "P07_P01"]
POLYGON_VERTICES = ["P01", "P03", "P05", "P09", "P07"]


@pytest.fixture(scope="module")
def results():
    with open("/app/results.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def reference_coords():
    """Independently compute reference coordinates using pyproj EPSG lookups.

    For cross-datum CRS (27700, 28992, 31467), transform to WGS84 (EPSG:4326)
    since the EPSG Helmert parameters target WGS84. WGS84 and ETRS89 differ
    by ~1m, well within cross-datum test tolerances.

    For same-datum CRS (2154, 25833), transform to ETRS89 (EPSG:4258) since
    RGF93 and ETRS89/UTM share the GRS80/ETRS89 datum.

    PROJ_NETWORK is disabled to ensure deterministic behavior (no runtime grid
    downloads) and force the use of bundled Helmert-based operations.
    """
    os.environ.setdefault("PROJ_NETWORK", "OFF")
    coords = {}
    for pid, (epsg, e, n) in SURVEY_POINTS.items():
        if epsg in DATUM_TRANSFORM_EPSG:
            target_crs = "EPSG:4326"
        else:
            target_crs = "EPSG:4258"
        try:
            t = Transformer.from_crs(
                f"EPSG:{epsg}", target_crs, always_xy=True
            )
            lon, lat = t.transform(e, n)
            if math.isfinite(lon) and math.isfinite(lat):
                coords[pid] = (lon, lat)
        except Exception:
            pass
    return coords


class TestStructure:
    """Verify the output JSON has all required fields and structure."""

    def test_required_top_level_keys(self, results):
        required = [
            "pipelines",
            "etrs89_coordinates",
            "helmert_parameters",
            "geodesic_distances",
            "polygon_area_m2",
            "optimal_utm_zone",
        ]
        for key in required:
            assert key in results, f"Missing required top-level key: {key}"

    def test_pipeline_keys(self, results):
        expected_keys = {
            "27700_to_4258",
            "28992_to_4258",
            "31467_to_4258",
            "2154_to_4258",
            "25833_to_4258",
        }
        actual_keys = set(results["pipelines"].keys())
        assert expected_keys == actual_keys, (
            f"Pipeline keys mismatch: missing={expected_keys - actual_keys}, "
            f"extra={actual_keys - expected_keys}"
        )

    def test_coordinate_keys(self, results):
        expected = {f"P{i:02d}" for i in range(1, 11)}
        actual = set(results["etrs89_coordinates"].keys())
        assert expected == actual, f"Coordinate keys mismatch: missing={expected - actual}"

    def test_distance_keys(self, results):
        expected = set(DISTANCE_PAIRS)
        actual = set(results["geodesic_distances"].keys())
        assert expected.issubset(actual), f"Missing distance keys: {expected - actual}"


class TestPipelineFormat:
    """Verify pipeline strings are valid PROJ pipeline definitions."""

    def test_pipelines_contain_proj(self, results):
        for key, pipeline in results["pipelines"].items():
            assert "+proj=" in pipeline, (
                f"Pipeline {key} does not contain '+proj='"
            )

    def test_datum_pipelines_have_helmert(self, results):
        datum_keys = ["27700_to_4258", "28992_to_4258", "31467_to_4258"]
        for key in datum_keys:
            pipeline = results["pipelines"][key]
            assert "helmert" in pipeline.lower(), (
                f"Pipeline {key} should contain a Helmert transformation step"
            )

    def test_no_epsg_init_shorthand(self, results):
        for key, pipeline in results["pipelines"].items():
            assert "+init=epsg:" not in pipeline.lower(), (
                f"Pipeline {key} uses EPSG init shorthand instead of explicit parameters"
            )


class TestHelmertParameters:
    """Verify transformation parameters are present and structurally valid."""

    def test_helmert_keys_exist(self, results):
        for epsg_str in ["27700", "28992", "31467"]:
            assert epsg_str in results["helmert_parameters"], (
                f"Missing parameters for EPSG:{epsg_str}"
            )

    def test_helmert_fields(self, results):
        required_fields = ["x", "y", "z", "rx", "ry", "rz", "s", "convention"]
        for epsg_str in ["27700", "28992", "31467"]:
            params = results["helmert_parameters"][epsg_str]
            for field in required_fields:
                assert field in params, (
                    f"Missing field '{field}' in params for EPSG:{epsg_str}"
                )

    def test_helmert_convention_valid(self, results):
        valid = {"position_vector", "coordinate_frame"}
        for epsg_str in ["27700", "28992", "31467"]:
            conv = results["helmert_parameters"][epsg_str]["convention"]
            assert conv in valid, (
                f"Invalid convention '{conv}' for EPSG:{epsg_str}. "
                f"Must be one of {valid}"
            )

    def test_helmert_numeric_values(self, results):
        numeric_fields = ["x", "y", "z", "rx", "ry", "rz", "s"]
        for epsg_str in ["27700", "28992", "31467"]:
            params = results["helmert_parameters"][epsg_str]
            for field in numeric_fields:
                val = params[field]
                assert isinstance(val, (int, float)), (
                    f"Param {field} for EPSG:{epsg_str} is not numeric: {val}"
                )

    def test_helmert_translations_reasonable(self, results):
        """Translations for European datums should be in the hundreds of meters."""
        for epsg_str in ["27700", "28992", "31467"]:
            params = results["helmert_parameters"][epsg_str]
            for field in ["x", "y", "z"]:
                assert abs(params[field]) < 1000, (
                    f"Translation {field}={params[field]} for EPSG:{epsg_str} "
                    f"seems unreasonable (expected < 1000m)"
                )

    def test_helmert_translations_nonzero(self, results):
        """At least one translation must be significant (not a trivial/identity transform)."""
        for epsg_str in ["27700", "28992", "31467"]:
            params = results["helmert_parameters"][epsg_str]
            max_t = max(abs(params[f]) for f in ["x", "y", "z"])
            assert max_t > 10, (
                f"Translations for EPSG:{epsg_str} are suspiciously small "
                f"(max={max_t:.2f}m). Expected significant datum shift."
            )

    def test_helmert_convention_consistent_with_pipeline(self, results):
        """The convention declared in helmert_parameters must match the pipeline string."""
        for epsg_str in ["27700", "28992", "31467"]:
            params = results["helmert_parameters"][epsg_str]
            pipeline = results["pipelines"][f"{epsg_str}_to_4258"]
            declared_conv = params["convention"]
            assert f"+convention={declared_conv}" in pipeline, (
                f"Convention '{declared_conv}' for EPSG:{epsg_str} "
                f"does not appear in the pipeline string"
            )


class TestCoordinateAccuracy:
    """Verify transformed coordinates match independent reference computation."""

    def test_coordinate_values_are_lists(self, results):
        for pid, coords in results["etrs89_coordinates"].items():
            assert isinstance(coords, list) and len(coords) == 2, (
                f"{pid}: coordinates should be [lon, lat], got {coords}"
            )

    def test_coordinates_in_european_range(self, results):
        """Sanity check: all points should be in Europe."""
        for pid, coords in results["etrs89_coordinates"].items():
            lon, lat = coords[0], coords[1]
            assert -10 < lon < 25, (
                f"{pid}: longitude {lon} outside European range (-10 to 25). "
                f"Check [lon, lat] ordering."
            )
            assert 35 < lat < 60, (
                f"{pid}: latitude {lat} outside European range (35 to 60). "
                f"Check [lon, lat] ordering."
            )

    def test_pipeline_coordinate_consistency(self, results):
        """Agent's pipelines must produce coordinates matching their reported values."""
        geod = Geod(ellps="GRS80")
        for pid, (epsg, e, n) in SURVEY_POINTS.items():
            pipeline_key = f"{epsg}_to_4258"
            pipeline = results["pipelines"][pipeline_key]
            try:
                transformer = Transformer.from_pipeline(pipeline)
            except Exception as exc:
                pytest.fail(
                    f"Pipeline {pipeline_key} is not a valid PROJ pipeline: {exc}"
                )
            lon, lat = transformer.transform(e, n)
            agent_lon, agent_lat = results["etrs89_coordinates"][pid]
            _, _, dist = geod.inv(lon, lat, agent_lon, agent_lat)
            assert abs(dist) < 1.0, (
                f"{pid}: pipeline {pipeline_key} produces ({lon:.8f}, {lat:.8f}) "
                f"but reported ({agent_lon:.8f}, {agent_lat:.8f}), "
                f"off by {abs(dist):.4f}m"
            )

    def test_same_datum_accuracy(self, results, reference_coords):
        """Same-datum CRS should match within 0.5m."""
        geod = Geod(ellps="GRS80")
        checked = 0
        for pid, (epsg, e, n) in SURVEY_POINTS.items():
            if epsg not in SAME_DATUM_EPSG:
                continue
            if pid not in reference_coords:
                continue
            ref_lon, ref_lat = reference_coords[pid]
            agent_lon, agent_lat = results["etrs89_coordinates"][pid]
            _, _, dist = geod.inv(ref_lon, ref_lat, agent_lon, agent_lat)
            assert abs(dist) < 0.5, (
                f"{pid} (EPSG:{epsg}, same datum): off by {abs(dist):.4f}m "
                f"(tolerance 0.5m)"
            )
            checked += 1
        assert checked >= 3, f"Only {checked} same-datum points verified (expected >= 3)"

    def test_cross_datum_accuracy(self, results, reference_coords):
        """Cross-datum CRS: should be within 100m of reference.

        The reference is computed via pyproj EPSG-database transformation to WGS84
        (EPSG:4326). Different valid transformation operations may use different
        parameter sets causing differences — e.g. EPSG:1777 vs EPSG:1776 for DHDN
        can differ by ~50m. 100m accommodates any valid registered parameter set
        while still catching incorrect transforms (wrong datum or projection would
        produce km-level errors).
        """
        geod = Geod(ellps="GRS80")
        checked = 0
        for pid, (epsg, e, n) in SURVEY_POINTS.items():
            if epsg not in DATUM_TRANSFORM_EPSG:
                continue
            if pid not in reference_coords:
                continue
            ref_lon, ref_lat = reference_coords[pid]
            agent_lon, agent_lat = results["etrs89_coordinates"][pid]
            _, _, dist = geod.inv(ref_lon, ref_lat, agent_lon, agent_lat)
            assert abs(dist) < 100.0, (
                f"{pid} (EPSG:{epsg}, cross-datum): off by {abs(dist):.2f}m "
                f"from reference (tolerance 100m)"
            )
            checked += 1
        assert checked >= 3, (
            f"Only {checked} cross-datum points could be verified (expected >= 3)"
        )


class TestGeodesicDistances:
    """Verify geodesic distances are internally consistent with reported coordinates."""

    def test_distances_are_positive(self, results):
        for pair in DISTANCE_PAIRS:
            d = results["geodesic_distances"][pair]
            assert isinstance(d, (int, float)) and d > 0, (
                f"Distance {pair} should be a positive number, got {d}"
            )

    def test_distances_consistent_with_coordinates(self, results):
        """Recompute distances from agent's own coordinates; must match within 100m."""
        geod = Geod(ellps="GRS80")
        for pair in DISTANCE_PAIRS:
            p1, p2 = pair.split("_")
            lon1, lat1 = results["etrs89_coordinates"][p1]
            lon2, lat2 = results["etrs89_coordinates"][p2]
            _, _, expected_dist = geod.inv(lon1, lat1, lon2, lat2)
            agent_dist = results["geodesic_distances"][pair]
            diff = abs(agent_dist - abs(expected_dist))
            assert diff < 100.0, (
                f"Distance {pair}: agent={agent_dist:.2f}m, "
                f"computed from coords={abs(expected_dist):.2f}m, "
                f"diff={diff:.2f}m (tolerance 100m)"
            )

    def test_distances_plausible_range(self, results):
        """European inter-city distances should be 100km to 3000km."""
        for pair in DISTANCE_PAIRS:
            d = results["geodesic_distances"][pair]
            assert 100_000 < d < 3_000_000, (
                f"Distance {pair}={d:.0f}m seems implausible for European cities"
            )


class TestPolygonArea:
    """Verify geodesic polygon area is consistent with reported coordinates."""

    def test_area_is_positive(self, results):
        area = results["polygon_area_m2"]
        assert isinstance(area, (int, float)) and area > 0, (
            f"Polygon area should be positive, got {area}"
        )

    def test_area_consistent_with_coordinates(self, results):
        """Recompute area from agent's coordinates; must match within 1%."""
        geod = Geod(ellps="GRS80")
        lons = [results["etrs89_coordinates"][p][0] for p in POLYGON_VERTICES]
        lats = [results["etrs89_coordinates"][p][1] for p in POLYGON_VERTICES]
        ref_area, _ = geod.polygon_area_perimeter(lons, lats)
        ref_area = abs(ref_area)
        agent_area = results["polygon_area_m2"]
        rel_error = abs(agent_area - ref_area) / ref_area if ref_area > 0 else float("inf")
        assert rel_error < 0.01, (
            f"Polygon area relative error {rel_error:.4f} exceeds 1%. "
            f"Agent={agent_area:.0f}, computed={ref_area:.0f}"
        )

    def test_area_plausible_range(self, results):
        """Polygon covering parts of W. Europe should be 1e11 to 2e12 m^2."""
        area = results["polygon_area_m2"]
        assert 1e11 < area < 2e12, (
            f"Polygon area {area:.2e} m^2 seems implausible for W. European polygon"
        )


class TestUTMZone:
    """Verify the optimal UTM zone is correct."""

    def test_utm_zone_is_integer(self, results):
        zone = results["optimal_utm_zone"]
        assert isinstance(zone, int), f"UTM zone should be integer, got {type(zone)}"

    def test_utm_zone_in_range(self, results):
        zone = results["optimal_utm_zone"]
        assert 1 <= zone <= 60, f"UTM zone {zone} outside valid range 1-60"

    def test_utm_zone_correct(self, results, reference_coords):
        """UTM zone should match the zone containing the mean longitude."""
        avg_lon = sum(
            lon for lon, lat in reference_coords.values()
        ) / len(reference_coords)
        expected_zone = int((avg_lon + 180) / 6) + 1
        agent_zone = results["optimal_utm_zone"]
        assert agent_zone == expected_zone, (
            f"UTM zone {agent_zone} != expected {expected_zone} "
            f"(mean longitude ~{avg_lon:.2f} deg)"
        )
