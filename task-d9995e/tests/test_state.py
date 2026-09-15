"""Verify urban morphometric characterization results against golden reference values."""


import json
import pytest


GOLDEN = {
    # Shape metrics (building footprints)
    "fractal_dimension_mean": 1.0284229071113,
    "circular_compactness_mean": 0.5690762180557374,
    "elongation_mean": 0.8046747233732038,
    "convexity_mean": 0.941622590878818,
    # Distribution metrics
    "orientation_mean": 20.983859394267952,
    "shared_walls_sum": 5310.17039728293,
    "building_adjacency_mean": 0.3784722222222222,
    "street_alignment_mean": 2.024707906317863,
    "mean_interbuilding_distance_mean": 13.018190603684694,
    # Diversity indices (tessellation areas, 3rd-order contiguity + self-weight)
    "shannon_mean": 0.8290031127861055,
    "simpson_mean": 0.5106343598245804,
    "gini_mean": 0.38686076469743697,
    "theil_mean": 0.3367193709036915,
    # Network analysis (global, radius=None)
    "meshedness": 0.1320754716981132,
    "cyclomatic": 7,
    "mean_node_degree": 2.413793103448276,
    # Elements & intensity
    "stroke_count": 10,
    "block_count": 8,
    "courtyard_mean": 0.6805555555555556,
}

INTEGER_KEYS = {"cyclomatic", "stroke_count", "block_count"}


@pytest.fixture(scope="module")
def results():
    with open("/app/results.json") as f:
        return json.load(f)


def test_results_file_exists(results):
    """Results file loads successfully."""
    assert isinstance(results, dict)


@pytest.mark.parametrize("key", sorted(GOLDEN.keys()))
def test_metric_present(results, key):
    """Each required metric key exists in the results."""
    assert key in results, f"Missing key: {key}"


@pytest.mark.parametrize("key,expected", sorted(GOLDEN.items()))
def test_metric_value(results, key, expected):
    """Each metric matches its golden reference value."""
    assert key in results, f"Missing key: {key}"
    actual = results[key]
    if key in INTEGER_KEYS:
        assert int(actual) == expected, (
            f"{key}: expected {expected}, got {actual}"
        )
    else:
        assert actual == pytest.approx(expected, rel=1e-3), (
            f"{key}: expected {expected}, got {actual}"
        )


def test_no_nan_values(results):
    """No NaN or null values in results."""
    import math

    for key, val in results.items():
        if key in GOLDEN:
            assert val is not None, f"{key} is None"
            if isinstance(val, float):
                assert not math.isnan(val), f"{key} is NaN"
