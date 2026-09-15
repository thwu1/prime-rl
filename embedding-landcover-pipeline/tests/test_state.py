"""Tests for the geospatial embedding classification pipeline.

"""

import json
import os

import numpy as np
import pytest
import rasterio
from scipy.optimize import linear_sum_assignment


# ---------------------------------------------------------------------------
# Helper: deterministically regenerate ground truth (no secrets in the image)
# ---------------------------------------------------------------------------

def _ground_truth():
    """Reproduce the ground-truth class map and nodata mask from the data
    generation script's deterministic logic."""
    H, W = 100, 100
    seeds = [(20, 25), (75, 20), (15, 75), (80, 80), (50, 50)]
    class_map = np.zeros((H, W), dtype=np.int32)
    for i in range(H):
        for j in range(W):
            dists = [np.sqrt((i - si) ** 2 + (j - sj) ** 2) for si, sj in seeds]
            class_map[i, j] = int(np.argmin(dists))
    nodata_rng = np.random.RandomState(99)
    nodata_mask = nodata_rng.random((H, W)) < 0.03
    return class_map, nodata_mask


# ===================================================================
# 1. Output file existence
# ===================================================================

class TestOutputFiles:
    def test_report_exists(self):
        assert os.path.exists("/app/output/report.json"), "report.json not found"

    def test_classified_map_exists(self):
        assert os.path.exists("/app/output/classified_map.tif"), (
            "classified_map.tif not found"
        )

    def test_confidence_map_exists(self):
        assert os.path.exists("/app/output/confidence_map.tif"), (
            "confidence_map.tif not found"
        )


# ===================================================================
# 2. Report structure
# ===================================================================

class TestReportStructure:
    @pytest.fixture(autouse=True)
    def load_report(self):
        with open("/app/output/report.json") as f:
            self.report = json.load(f)

    def test_required_fields(self):
        required = [
            "optimal_n_components",
            "explained_variance_ratios",
            "optimal_k",
            "silhouette_scores",
            "classification_accuracy",
            "per_class_f1",
            "confusion_matrix",
        ]
        for field in required:
            assert field in self.report, f"Missing required field: {field}"

    def test_explained_variance_is_list(self):
        evr = self.report["explained_variance_ratios"]
        assert isinstance(evr, list) and len(evr) > 0

    def test_silhouette_scores_coverage(self):
        scores = self.report["silhouette_scores"]
        if isinstance(scores, dict):
            ks = {int(k) for k in scores.keys()}
        else:
            ks = set(range(2, 2 + len(scores)))
        assert set(range(2, 11)).issubset(ks), "Must report silhouette for K=2..10"

    def test_confusion_matrix_shape(self):
        cm = self.report["confusion_matrix"]
        assert isinstance(cm, list) and len(cm) >= 5
        assert all(len(row) >= 5 for row in cm)


# ===================================================================
# 3. Dimensionality reduction results
# ===================================================================

class TestDimensionalityReduction:
    @pytest.fixture(autouse=True)
    def load_report(self):
        with open("/app/output/report.json") as f:
            self.report = json.load(f)

    def test_optimal_n_components(self):
        n = self.report["optimal_n_components"]
        assert n == 4, f"Expected 4 informative dimensions, got {n}"

    def test_variance_sum_exceeds_threshold(self):
        evr = self.report["explained_variance_ratios"]
        total = sum(evr)
        assert total >= 0.95, f"Cumulative EVR {total:.4f} < 0.95"

    def test_each_component_nontrivial(self):
        evr = self.report["explained_variance_ratios"]
        assert all(v > 0.05 for v in evr), (
            f"Each retained component should explain >5%: {evr}"
        )


# ===================================================================
# 4. Clustering results
# ===================================================================

class TestClusteringResults:
    @pytest.fixture(autouse=True)
    def load_report(self):
        with open("/app/output/report.json") as f:
            self.report = json.load(f)

    def test_optimal_k(self):
        k = self.report["optimal_k"]
        assert k == 5, f"Expected optimal K=5, got {k}"

    def test_silhouette_at_optimal_k(self):
        scores = self.report["silhouette_scores"]
        if isinstance(scores, dict):
            score_5 = scores.get("5", scores.get(5))
        else:
            score_5 = scores[3]  # K=5 is index 3 when K starts at 2
        assert score_5 is not None, "No silhouette score for K=5"
        assert score_5 > 0.5, f"Silhouette(K=5) = {score_5} <= 0.5"


# ===================================================================
# 5. Classification metrics
# ===================================================================

class TestClassification:
    @pytest.fixture(autouse=True)
    def load_report(self):
        with open("/app/output/report.json") as f:
            self.report = json.load(f)

    def test_accuracy_threshold(self):
        acc = self.report["classification_accuracy"]
        assert acc > 0.85, f"Accuracy {acc:.4f} < 0.85"

    def test_per_class_f1_all_above_threshold(self):
        f1 = self.report["per_class_f1"]
        values = list(f1.values()) if isinstance(f1, dict) else f1
        assert all(v > 0.70 for v in values), (
            f"All per-class F1 should exceed 0.70: {f1}"
        )


# ===================================================================
# 6. Classified map raster checks
# ===================================================================

class TestClassifiedMap:
    @pytest.fixture(autouse=True)
    def load_ground_truth(self):
        self.gt_classes, self.nodata_mask = _ground_truth()

    def test_raster_dimensions(self):
        with rasterio.open("/app/output/classified_map.tif") as src:
            assert src.height == 100 and src.width == 100
            assert src.count == 1

    def test_crs_preserved(self):
        with rasterio.open("/app/output/classified_map.tif") as out:
            with rasterio.open("/app/data/embeddings.tif") as ref:
                assert out.crs == ref.crs, f"CRS mismatch: {out.crs} vs {ref.crs}"

    def test_transform_preserved(self):
        with rasterio.open("/app/output/classified_map.tif") as out:
            with rasterio.open("/app/data/embeddings.tif") as ref:
                assert out.transform == ref.transform, "Affine transform mismatch"

    def test_class_values_in_range(self):
        with rasterio.open("/app/output/classified_map.tif") as src:
            data = src.read(1)
        unique = set(np.unique(data))
        assert len(unique) >= 5, f"Expected >= 5 unique values, got {unique}"
        assert unique.issubset({0, 1, 2, 3, 4, 5}), f"Values outside 0-5: {unique}"

    def test_nodata_pixels_masked(self):
        with rasterio.open("/app/output/classified_map.tif") as src:
            data = src.read(1)
        nodata_vals = data[self.nodata_mask]
        assert np.all(nodata_vals == 0), "NaN-embedding pixels must be 0 in output"

    def test_spatial_accuracy(self):
        """Classified map should match ground truth (allowing arbitrary class IDs)."""
        with rasterio.open("/app/output/classified_map.tif") as src:
            data = src.read(1)

        valid = ~self.nodata_mask
        pred = data[valid]
        truth = self.gt_classes[valid]

        pred_classes = sorted(set(pred) - {0})
        true_classes = sorted(set(truth))

        n = max(len(pred_classes), len(true_classes))
        cost = np.zeros((n, n))
        for i, pc in enumerate(pred_classes):
            for j, tc in enumerate(true_classes):
                cost[i, j] = -np.sum((pred == pc) & (truth == tc))

        row_ind, col_ind = linear_sum_assignment(cost)
        mapping = {}
        for r, c in zip(row_ind, col_ind):
            if r < len(pred_classes) and c < len(true_classes):
                mapping[pred_classes[r]] = true_classes[c]

        mapped = np.array([mapping.get(p, -1) for p in pred])
        accuracy = np.mean(mapped == truth)
        assert accuracy > 0.80, f"Spatial accuracy {accuracy:.4f} < 0.80"


# ===================================================================
# 7. Confidence map checks
# ===================================================================

class TestConfidenceMap:
    @pytest.fixture(autouse=True)
    def load_ground_truth(self):
        self.gt_classes, self.nodata_mask = _ground_truth()

    def test_confidence_dimensions(self):
        with rasterio.open("/app/output/confidence_map.tif") as src:
            assert src.height == 100 and src.width == 100
            assert src.count == 1

    def test_confidence_dtype(self):
        with rasterio.open("/app/output/confidence_map.tif") as src:
            assert src.dtypes[0] == "float32", (
                f"Expected float32, got {src.dtypes[0]}"
            )

    def test_confidence_range(self):
        with rasterio.open("/app/output/confidence_map.tif") as src:
            data = src.read(1)
        valid = ~self.nodata_mask
        valid_data = data[valid]
        assert np.all(valid_data >= 0.0), "Confidence values below 0"
        assert np.all(valid_data <= 1.0), "Confidence values above 1"

    def test_confidence_nodata_zero(self):
        with rasterio.open("/app/output/confidence_map.tif") as src:
            data = src.read(1)
        nodata_vals = data[self.nodata_mask]
        assert np.all(nodata_vals == 0.0), (
            "NaN-embedding pixels must have confidence 0.0"
        )

    def test_confidence_crs_preserved(self):
        with rasterio.open("/app/output/confidence_map.tif") as out:
            with rasterio.open("/app/data/embeddings.tif") as ref:
                assert out.crs == ref.crs, "Confidence map CRS mismatch"

    def test_confidence_transform_preserved(self):
        with rasterio.open("/app/output/confidence_map.tif") as out:
            with rasterio.open("/app/data/embeddings.tif") as ref:
                assert out.transform == ref.transform, (
                    "Confidence map transform mismatch"
                )

    def test_mean_confidence_reasonable(self):
        with rasterio.open("/app/output/confidence_map.tif") as src:
            data = src.read(1)
        valid = ~self.nodata_mask
        mean_conf = float(np.mean(data[valid]))
        assert mean_conf > 0.3, (
            f"Mean confidence {mean_conf:.4f} unreasonably low"
        )

    def test_confidence_variance_nonzero(self):
        """Confidence should vary across pixels, not be a constant."""
        with rasterio.open("/app/output/confidence_map.tif") as src:
            data = src.read(1)
        valid = ~self.nodata_mask
        std = float(np.std(data[valid]))
        assert std > 0.01, (
            f"Confidence std {std:.6f} near zero — values should vary"
        )
