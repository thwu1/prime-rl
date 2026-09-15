"""Verify the morphometric profile JSON against golden values from the bubenec dataset."""


import json
import os

import pytest


@pytest.fixture(scope="module")
def profile():
    path = "/app/morphometric_profile.json"
    assert os.path.exists(path), f"Output file not found: {path}"
    with open(path) as f:
        data = json.load(f)
    return data


class TestCounts:
    def test_building_count(self, profile):
        assert profile["counts"]["buildings"] == 144

    def test_street_count(self, profile):
        assert profile["counts"]["streets"] == 35

    def test_tessellation_count(self, profile):
        assert profile["counts"]["tessellation_cells"] == 144


class TestShapeMetrics:
    def test_fractal_dimension(self, profile):
        assert profile["shape"]["fractal_dimension_mean"] == pytest.approx(
            1.0284229071113, rel=1e-4
        )

    def test_circular_compactness(self, profile):
        assert profile["shape"]["circular_compactness_mean"] == pytest.approx(
            0.5690762180557374, rel=1e-4
        )

    def test_square_compactness(self, profile):
        assert profile["shape"]["square_compactness_mean"] == pytest.approx(
            0.8486134470818577, rel=1e-4
        )

    def test_convexity(self, profile):
        assert profile["shape"]["convexity_mean"] == pytest.approx(
            0.941622590878818, rel=1e-4
        )

    def test_rectangularity(self, profile):
        assert profile["shape"]["rectangularity_mean"] == pytest.approx(
            0.8867686143851342, rel=1e-3
        )

    def test_elongation(self, profile):
        assert profile["shape"]["elongation_mean"] == pytest.approx(
            0.8046747233732038, rel=1e-3
        )

    def test_equivalent_rectangular_index(self, profile):
        assert profile["shape"]["equivalent_rectangular_index_mean"] == pytest.approx(
            0.9307591166031689, rel=1e-4
        )

    def test_corners_sum(self, profile):
        assert profile["shape"]["corners_sum"] == 1485

    def test_squareness(self, profile):
        assert profile["shape"]["squareness_mean"] == pytest.approx(
            5.229888125861968, rel=1e-4
        )


class TestDimensionMetrics:
    def test_courtyard_area_sum(self, profile):
        assert profile["dimension"]["courtyard_area_sum"] == pytest.approx(
            353.33274206543274, rel=1e-4
        )

    def test_form_factor_mean(self, profile):
        assert profile["dimension"]["form_factor_mean"] == pytest.approx(
            5.4486362624193, rel=1e-4
        )


class TestDistributionMetrics:
    def test_orientation_buildings(self, profile):
        assert profile["distribution"]["orientation_buildings_mean"] == pytest.approx(
            20.983859394267952, rel=1e-4
        )

    def test_orientation_streets(self, profile):
        assert profile["distribution"]["orientation_streets_mean"] == pytest.approx(
            21.176405050561755, rel=1e-4
        )

    def test_shared_walls(self, profile):
        assert profile["distribution"]["shared_walls_mean"] == pytest.approx(
            36.87618331446485, rel=1e-4
        )

    def test_alignment(self, profile):
        assert profile["distribution"]["alignment_mean"] == pytest.approx(
            2.90842367974375, rel=1e-4
        )

    def test_neighbor_distance(self, profile):
        assert profile["distribution"]["neighbor_distance_mean"] == pytest.approx(
            14.254601392635818, rel=1e-4
        )

    def test_building_adjacency(self, profile):
        assert profile["distribution"]["building_adjacency_mean"] == pytest.approx(
            0.3784722222222222, rel=1e-4
        )

    def test_street_alignment(self, profile):
        assert profile["distribution"]["street_alignment_mean"] == pytest.approx(
            2.024707906317863, rel=1e-3
        )

    def test_linearity(self, profile):
        assert profile["distribution"]["linearity_mean"] == pytest.approx(
            0.9976310491404173, rel=1e-4
        )


class TestDiversityMetrics:
    def test_shannon(self, profile):
        assert profile["diversity"]["shannon_mean"] == pytest.approx(
            0.8290031127861055, rel=1e-4
        )

    def test_simpson(self, profile):
        assert profile["diversity"]["simpson_mean"] == pytest.approx(
            0.5106343598245804, rel=1e-4
        )

    def test_gini(self, profile):
        assert profile["diversity"]["gini_mean"] == pytest.approx(
            0.38686076469743697, rel=1e-4
        )

    def test_theil(self, profile):
        assert profile["diversity"]["theil_mean"] == pytest.approx(
            0.3367193709036915, rel=1e-4
        )


class TestCOINS:
    def test_stroke_count(self, profile):
        assert profile["coins"]["stroke_count"] == 10

    def test_n_segments(self, profile):
        assert profile["coins"]["n_segments"] == [8, 19, 17, 13, 5, 14, 2, 3, 3, 5]
