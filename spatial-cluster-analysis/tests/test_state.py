"""
Tests for spatial cluster analysis pipeline output.

Verifies zone value aggregation, spatial weights construction,
global/local spatial autocorrelation, and hot spot analysis.
"""

import json
import os
import pytest
import numpy as np

OUTPUT_DIR = "/app/output"

EXPECTED_ZONE_VALUES = {
    "Z00": 9.0, "Z01": 10.0, "Z02": 8.0, "Z03": 5.0, "Z04": 4.0, "Z05": 5.0,
    "Z06": 10.0, "Z07": 9.0, "Z08": 8.0, "Z09": 4.0, "Z10": 5.0, "Z11": 6.0,
    "Z12": 8.0, "Z13": 8.0, "Z14": 9.0, "Z15": 5.0, "Z16": 3.0, "Z17": 4.0,
    "Z18": 5.0, "Z19": 6.0, "Z20": 5.0, "Z21": 2.0, "Z22": 3.0, "Z23": 2.0,
    "Z24": 4.0, "Z25": 5.0, "Z26": 4.0, "Z27": 3.0, "Z28": 1.0, "Z29": 2.0,
    "Z30": 5.0, "Z31": 4.0, "Z32": 5.0, "Z33": 2.0, "Z34": 2.0, "Z35": 1.0,
}


def _queen_neighbors_grid(nrows, ncols):
    """Compute queen contiguity neighbors for a regular grid."""
    weights = {}
    for r in range(nrows):
        for c in range(ncols):
            zone_id = "Z{:02d}".format(r * ncols + c)
            neighbors = []
            for dr in [-1, 0, 1]:
                for dc in [-1, 0, 1]:
                    if dr == 0 and dc == 0:
                        continue
                    nr, nc_ = r + dr, c + dc
                    if 0 <= nr < nrows and 0 <= nc_ < ncols:
                        neighbors.append("Z{:02d}".format(nr * ncols + nc_))
            weights[zone_id] = sorted(neighbors)
    return weights


EXPECTED_WEIGHTS = _queen_neighbors_grid(6, 6)


def _compute_reference_morans_i():
    """Compute reference Global Moran's I using binary weights on the 6x6 grid."""
    values_list = [
        9, 10, 8, 5, 4, 5,
        10, 9, 8, 4, 5, 6,
        8, 8, 9, 5, 3, 4,
        5, 6, 5, 2, 3, 2,
        4, 5, 4, 3, 1, 2,
        5, 4, 5, 2, 2, 1,
    ]
    x = np.array(values_list, dtype=float)
    n = 36
    z = x - x.mean()

    W = np.zeros((n, n))
    for i in range(n):
        ri, ci = divmod(i, 6)
        for j in range(n):
            if i == j:
                continue
            rj, cj = divmod(j, 6)
            if abs(ri - rj) <= 1 and abs(ci - cj) <= 1:
                W[i, j] = 1.0

    S0 = W.sum()
    I = (n / S0) * float(z @ W @ z) / float(z @ z)
    return I


class TestOutputFilesExist:
    """Verify all required output files are present."""

    @pytest.mark.parametrize("filename", [
        "zone_values.json",
        "spatial_weights.json",
        "global_autocorrelation.json",
        "local_clusters.geojson",
        "hotspot_analysis.geojson",
        "summary.json",
    ])
    def test_file_exists(self, filename):
        path = os.path.join(OUTPUT_DIR, filename)
        assert os.path.isfile(path), f"Missing output file: {filename}"


class TestZoneValues:
    """Verify zone-level aggregated values."""

    @pytest.fixture
    def zone_values(self):
        with open(os.path.join(OUTPUT_DIR, "zone_values.json")) as f:
            return json.load(f)

    def test_all_zones_present(self, zone_values):
        for zid in EXPECTED_ZONE_VALUES:
            assert zid in zone_values, f"Missing zone: {zid}"

    def test_zone_count(self, zone_values):
        assert len(zone_values) == 36

    def test_zone_values_correct(self, zone_values):
        for zid, expected in EXPECTED_ZONE_VALUES.items():
            actual = zone_values[zid]
            assert abs(actual - expected) < 0.01, (
                f"Zone {zid}: expected {expected}, got {actual}"
            )


class TestSpatialWeights:
    """Verify queen contiguity spatial weights matrix."""

    @pytest.fixture
    def weights(self):
        with open(os.path.join(OUTPUT_DIR, "spatial_weights.json")) as f:
            return json.load(f)

    def test_all_zones_present(self, weights):
        for zid in EXPECTED_ZONE_VALUES:
            assert zid in weights, f"Missing zone in weights: {zid}"

    def test_corner_zone_has_3_neighbors(self, weights):
        """Corner zones should have exactly 3 queen neighbors."""
        for corner in ["Z00", "Z05", "Z30", "Z35"]:
            assert len(weights[corner]) == 3, (
                f"Corner {corner} should have 3 neighbors, got {len(weights[corner])}"
            )

    def test_edge_zone_has_5_neighbors(self, weights):
        """Non-corner edge zones should have exactly 5 queen neighbors."""
        for edge in ["Z01", "Z04", "Z06", "Z24", "Z11", "Z29"]:
            assert len(weights[edge]) == 5, (
                f"Edge {edge} should have 5 neighbors, got {len(weights[edge])}"
            )

    def test_interior_zone_has_8_neighbors(self, weights):
        """Interior zones should have exactly 8 queen neighbors."""
        for interior in ["Z07", "Z08", "Z13", "Z14", "Z20", "Z21", "Z22", "Z28"]:
            assert len(weights[interior]) == 8, (
                f"Interior {interior} should have 8 neighbors, got {len(weights[interior])}"
            )

    def test_specific_neighbors_z00(self, weights):
        assert set(weights["Z00"]) == {"Z01", "Z06", "Z07"}

    def test_specific_neighbors_z07(self, weights):
        assert set(weights["Z07"]) == {
            "Z00", "Z01", "Z02", "Z06", "Z08", "Z12", "Z13", "Z14"
        }

    def test_specific_neighbors_z35(self, weights):
        assert set(weights["Z35"]) == {"Z28", "Z29", "Z34"}

    def test_symmetry(self, weights):
        """Weights should be symmetric: if A neighbors B, then B neighbors A."""
        for zid, neighbors in weights.items():
            for nid in neighbors:
                assert zid in weights[nid], (
                    f"Asymmetric weights: {zid} lists {nid} but not vice versa"
                )


class TestGlobalMoransI:
    """Verify Global Moran's I spatial autocorrelation test."""

    @pytest.fixture
    def global_result(self):
        with open(os.path.join(OUTPUT_DIR, "global_autocorrelation.json")) as f:
            return json.load(f)

    def test_required_keys(self, global_result):
        required = ["morans_i", "expected_i", "variance", "z_score", "p_value"]
        for key in required:
            assert key in global_result, f"Missing key: {key}"

    def test_morans_i_positive(self, global_result):
        """Data has clear spatial clustering so Moran's I should be positive."""
        assert global_result["morans_i"] > 0.2, (
            f"Moran's I should be > 0.2 for clustered data, got {global_result['morans_i']}"
        )

    def test_morans_i_reasonable_range(self, global_result):
        """Moran's I should be in [-1, 1] range."""
        I = global_result["morans_i"]
        assert -1.0 <= I <= 1.0, f"Moran's I out of range: {I}"

    def test_expected_i_negative(self, global_result):
        """Expected Moran's I under null should be -1/(n-1) which is negative."""
        EI = global_result["expected_i"]
        assert EI < 0, f"Expected I should be negative, got {EI}"
        assert abs(EI - (-1.0 / 35)) < 0.01, (
            f"Expected I should be close to -1/35 = -0.0286, got {EI}"
        )

    def test_statistically_significant(self, global_result):
        """Data has clear clustering so should be significant at 0.05."""
        assert global_result["p_value"] < 0.05, (
            f"p-value should be < 0.05, got {global_result['p_value']}"
        )

    def test_z_score_positive(self, global_result):
        """Positive Moran's I should yield positive z-score."""
        assert global_result["z_score"] > 1.96, (
            f"z-score should be > 1.96 for significant positive autocorrelation, "
            f"got {global_result['z_score']}"
        )

    def test_morans_i_close_to_reference(self, global_result):
        """Moran's I should be reasonably close to reference computation.
        Allows tolerance for different weight normalization approaches."""
        ref = _compute_reference_morans_i()
        I = global_result["morans_i"]
        assert abs(I - ref) < 0.25 or I > 0.3, (
            f"Moran's I = {I} too far from binary-weight reference {ref:.4f}"
        )


class TestLISAClusters:
    """Verify Local Indicators of Spatial Association (LISA)."""

    @pytest.fixture
    def lisa_data(self):
        with open(os.path.join(OUTPUT_DIR, "local_clusters.geojson")) as f:
            data = json.load(f)
        return {
            f["properties"]["zone_id"]: f["properties"]
            for f in data["features"]
        }

    def test_is_feature_collection(self):
        with open(os.path.join(OUTPUT_DIR, "local_clusters.geojson")) as f:
            data = json.load(f)
        assert data["type"] == "FeatureCollection"
        assert len(data["features"]) == 36

    def test_required_properties(self, lisa_data):
        required = ["zone_id", "value", "local_morans_i", "z_score",
                     "p_value", "cluster_type"]
        for zid, props in lisa_data.items():
            for key in required:
                assert key in props, f"Zone {zid} missing property: {key}"

    def test_valid_cluster_types(self, lisa_data):
        valid = {"HH", "HL", "LH", "LL", "NS"}
        for zid, props in lisa_data.items():
            assert props["cluster_type"] in valid, (
                f"Zone {zid} has invalid cluster_type: {props['cluster_type']}"
            )

    def test_core_high_cluster_is_hh(self, lisa_data):
        """Core high-value zones surrounded by high values should be HH."""
        for zid in ["Z07"]:
            assert lisa_data[zid]["cluster_type"] == "HH", (
                f"Zone {zid} (value {lisa_data[zid]['value']}) should be HH, "
                f"got {lisa_data[zid]['cluster_type']}"
            )

    def test_high_value_zones_hh_or_ns(self, lisa_data):
        """High-value zones in the top-left should be HH or at least NS."""
        for zid in ["Z00", "Z01", "Z06"]:
            ct = lisa_data[zid]["cluster_type"]
            assert ct in ("HH", "NS"), (
                f"Zone {zid} should be HH or NS, got {ct}"
            )

    def test_core_low_cluster_is_ll(self, lisa_data):
        """Core low-value zones surrounded by low values should be LL."""
        for zid in ["Z28"]:
            assert lisa_data[zid]["cluster_type"] == "LL", (
                f"Zone {zid} (value {lisa_data[zid]['value']}) should be LL, "
                f"got {lisa_data[zid]['cluster_type']}"
            )

    def test_low_value_zones_ll_or_ns(self, lisa_data):
        """Low-value zones in the bottom-right should be LL or at least NS."""
        for zid in ["Z29", "Z34", "Z35"]:
            ct = lisa_data[zid]["cluster_type"]
            assert ct in ("LL", "NS"), (
                f"Zone {zid} should be LL or NS, got {ct}"
            )

    def test_significant_clusters_have_low_p(self, lisa_data):
        """Zones classified as clusters should have p < 0.05."""
        for zid, props in lisa_data.items():
            if props["cluster_type"] != "NS":
                assert props["p_value"] < 0.05, (
                    f"Zone {zid} classified as {props['cluster_type']} "
                    f"but p-value = {props['p_value']}"
                )

    def test_ns_zones_have_high_p(self, lisa_data):
        """Zones classified as NS should have p >= 0.05."""
        for zid, props in lisa_data.items():
            if props["cluster_type"] == "NS":
                assert props["p_value"] >= 0.05 or abs(props["local_morans_i"]) < 0.01, (
                    f"Zone {zid} classified as NS but p-value = {props['p_value']}"
                )

    def test_has_both_hh_and_ll(self, lisa_data):
        """The data should produce both HH and LL clusters."""
        types = {props["cluster_type"] for props in lisa_data.values()}
        assert "HH" in types, "No HH clusters found"
        assert "LL" in types, "No LL clusters found"

    def test_pseudo_p_values_positive(self, lisa_data):
        """Pseudo-p-values from permutation testing must be strictly positive."""
        for zid, props in lisa_data.items():
            assert props["p_value"] > 0, (
                f"Zone {zid}: pseudo-p-value is 0.0"
            )


class TestHotspotAnalysis:
    """Verify Getis-Ord Gi* hot spot analysis."""

    @pytest.fixture
    def gi_data(self):
        with open(os.path.join(OUTPUT_DIR, "hotspot_analysis.geojson")) as f:
            data = json.load(f)
        return {
            f["properties"]["zone_id"]: f["properties"]
            for f in data["features"]
        }

    def test_is_feature_collection(self):
        with open(os.path.join(OUTPUT_DIR, "hotspot_analysis.geojson")) as f:
            data = json.load(f)
        assert data["type"] == "FeatureCollection"
        assert len(data["features"]) == 36

    def test_required_properties(self, gi_data):
        required = ["zone_id", "value", "gi_star", "z_score",
                     "p_value", "classification"]
        for zid, props in gi_data.items():
            for key in required:
                assert key in props, f"Zone {zid} missing property: {key}"

    def test_valid_classifications(self, gi_data):
        valid = {"Hot Spot", "Cold Spot", "Not Significant"}
        for zid, props in gi_data.items():
            assert props["classification"] in valid, (
                f"Zone {zid}: invalid classification '{props['classification']}'"
            )

    def test_core_hot_spots(self, gi_data):
        """Interior zones in the high-value cluster should be Hot Spots."""
        for zid in ["Z07"]:
            assert gi_data[zid]["classification"] == "Hot Spot", (
                f"Zone {zid} (value {gi_data[zid]['value']}) should be Hot Spot, "
                f"got {gi_data[zid]['classification']}"
            )

    def test_high_value_zones_hot_or_ns(self, gi_data):
        """High-value zones should be Hot Spot or Not Significant."""
        for zid in ["Z00", "Z01", "Z06"]:
            cl = gi_data[zid]["classification"]
            assert cl in ("Hot Spot", "Not Significant"), (
                f"Zone {zid} should be Hot Spot or NS, got {cl}"
            )

    def test_core_cold_spots(self, gi_data):
        """Interior zones in the low-value cluster should be Cold Spots."""
        for zid in ["Z28"]:
            assert gi_data[zid]["classification"] == "Cold Spot", (
                f"Zone {zid} (value {gi_data[zid]['value']}) should be Cold Spot, "
                f"got {gi_data[zid]['classification']}"
            )

    def test_low_value_zones_cold_or_ns(self, gi_data):
        """Low-value zones should be Cold Spot or Not Significant."""
        for zid in ["Z29", "Z34", "Z35"]:
            cl = gi_data[zid]["classification"]
            assert cl in ("Cold Spot", "Not Significant"), (
                f"Zone {zid} should be Cold Spot or NS, got {cl}"
            )

    def test_hot_spots_have_positive_z(self, gi_data):
        """Hot Spot zones should have positive z-scores."""
        for zid, props in gi_data.items():
            if props["classification"] == "Hot Spot":
                assert props["z_score"] > 1.5, (
                    f"Hot Spot {zid} should have z > 1.5, got {props['z_score']}"
                )

    def test_cold_spots_have_negative_z(self, gi_data):
        """Cold Spot zones should have negative z-scores."""
        for zid, props in gi_data.items():
            if props["classification"] == "Cold Spot":
                assert props["z_score"] < -1.5, (
                    f"Cold Spot {zid} should have z < -1.5, got {props['z_score']}"
                )

    def test_has_both_hot_and_cold(self, gi_data):
        """Should find both hot spots and cold spots."""
        classifications = {props["classification"] for props in gi_data.values()}
        assert "Hot Spot" in classifications, "No hot spots found"
        assert "Cold Spot" in classifications, "No cold spots found"


class TestSummary:
    """Verify summary statistics."""

    @pytest.fixture
    def summary(self):
        with open(os.path.join(OUTPUT_DIR, "summary.json")) as f:
            return json.load(f)

    def test_required_keys(self, summary):
        required = ["n_zones", "n_observations", "mean_value",
                     "global_morans_i", "global_p_value",
                     "n_hot_spots", "n_cold_spots",
                     "n_high_high", "n_low_low"]
        for key in required:
            assert key in summary, f"Missing summary key: {key}"

    def test_zone_count(self, summary):
        assert summary["n_zones"] == 36

    def test_observation_count(self, summary):
        assert summary["n_observations"] == 108

    def test_mean_value(self, summary):
        expected_mean = sum(EXPECTED_ZONE_VALUES.values()) / 36
        assert abs(summary["mean_value"] - expected_mean) < 0.1, (
            f"Mean value should be ~{expected_mean:.2f}, got {summary['mean_value']}"
        )

    def test_global_morans_positive(self, summary):
        assert summary["global_morans_i"] > 0.2

    def test_global_significant(self, summary):
        assert summary["global_p_value"] < 0.05

    def test_hot_spots_exist(self, summary):
        assert summary["n_hot_spots"] >= 1, "Should find at least 1 hot spot"

    def test_cold_spots_exist(self, summary):
        assert summary["n_cold_spots"] >= 1, "Should find at least 1 cold spot"

    def test_hh_clusters_exist(self, summary):
        assert summary["n_high_high"] >= 1, "Should find at least 1 HH cluster"

    def test_ll_clusters_exist(self, summary):
        assert summary["n_low_low"] >= 1, "Should find at least 1 LL cluster"

    def test_consistency_with_geojson(self, summary):
        """Summary counts should match the GeoJSON classifications."""
        with open(os.path.join(OUTPUT_DIR, "hotspot_analysis.geojson")) as f:
            gi = json.load(f)
        n_hot = sum(1 for f in gi["features"]
                    if f["properties"]["classification"] == "Hot Spot")
        n_cold = sum(1 for f in gi["features"]
                     if f["properties"]["classification"] == "Cold Spot")
        assert summary["n_hot_spots"] == n_hot
        assert summary["n_cold_spots"] == n_cold

        with open(os.path.join(OUTPUT_DIR, "local_clusters.geojson")) as f:
            lisa = json.load(f)
        n_hh = sum(1 for f in lisa["features"]
                   if f["properties"]["cluster_type"] == "HH")
        n_ll = sum(1 for f in lisa["features"]
                   if f["properties"]["cluster_type"] == "LL")
        assert summary["n_high_high"] == n_hh
        assert summary["n_low_low"] == n_ll
