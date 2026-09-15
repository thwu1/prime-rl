"""Tests for TDA point cloud classification task.

Verifies structure, topological correctness, and mathematical
properties of the results produced by the agent.
"""

import json
import numpy as np
import pytest
import os

RESULTS_PATH = "/app/results.json"
TRUE_LABELS = [0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2]


@pytest.fixture
def results():
    assert os.path.exists(RESULTS_PATH), f"{RESULTS_PATH} does not exist"
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return data


class TestResultsStructure:
    """Verify the results JSON has the correct structure and dimensions."""

    def test_required_keys(self, results):
        required = [
            "persistence_entropies",
            "significant_features",
            "bottleneck_amplitudes",
            "shape_labels",
            "distance_matrix_h1",
            "most_similar_pair",
            "most_dissimilar_pair",
            "stability_scores",
        ]
        for key in required:
            assert key in results, f"Missing key: {key}"

    def test_persistence_entropies_shape(self, results):
        pe = np.array(results["persistence_entropies"])
        assert pe.shape == (12, 3), f"Expected shape (12, 3), got {pe.shape}"

    def test_significant_features_shape(self, results):
        sf = np.array(results["significant_features"])
        assert sf.shape == (12, 3), f"Expected shape (12, 3), got {sf.shape}"

    def test_bottleneck_amplitudes_shape(self, results):
        ba = np.array(results["bottleneck_amplitudes"])
        assert ba.shape == (12, 3), f"Expected shape (12, 3), got {ba.shape}"

    def test_shape_labels_length(self, results):
        labels = results["shape_labels"]
        assert len(labels) == 12, f"Expected 12 labels, got {len(labels)}"
        for label in labels:
            assert label in [0, 1, 2], f"Invalid label: {label}"

    def test_distance_matrix_shape(self, results):
        dm = np.array(results["distance_matrix_h1"])
        assert dm.shape == (12, 12), f"Expected shape (12, 12), got {dm.shape}"

    def test_similar_pair_format(self, results):
        pair = results["most_similar_pair"]
        assert len(pair) == 2
        assert 0 <= pair[0] < pair[1] < 12

    def test_dissimilar_pair_format(self, results):
        pair = results["most_dissimilar_pair"]
        assert len(pair) == 2
        assert 0 <= pair[0] < pair[1] < 12

    def test_stability_scores_length(self, results):
        ss = results["stability_scores"]
        assert len(ss) == 12, f"Expected 12 stability scores, got {len(ss)}"


class TestClassification:
    """Verify shape classification accuracy."""

    def test_classification_accuracy(self, results):
        predicted = np.array(results["shape_labels"])
        true = np.array(TRUE_LABELS)
        accuracy = np.mean(predicted == true)
        assert accuracy >= 10 / 12, (
            f"Classification accuracy {accuracy:.3f} is below threshold "
            f"(10/12 = {10/12:.3f}). Predicted: {predicted.tolist()}, "
            f"True: {true.tolist()}"
        )


class TestTopologicalSignatures:
    """Verify that the Betti number signatures match expected topology."""

    def test_circles_have_h1_features(self, results):
        sf = np.array(results["significant_features"])
        # Circles (indices 0-3): should have at least 1 significant H1 feature
        for i in range(4):
            assert sf[i, 1] >= 1, (
                f"Circle {i}: expected >= 1 significant H1 feature, "
                f"got {sf[i, 1]}"
            )

    def test_circles_h2_amplitude_negligible(self, results):
        ba = np.array(results["bottleneck_amplitudes"])
        # Circles (indices 0-3): H2 amplitude should be much smaller than H1
        # because circles have no 2-dimensional void — any H2 features are noise
        for i in range(4):
            assert ba[i, 2] < ba[i, 1], (
                f"Circle {i}: H2 amplitude ({ba[i, 2]:.4f}) should be less "
                f"than H1 amplitude ({ba[i, 1]:.4f})"
            )

    def test_spheres_have_h2_features(self, results):
        sf = np.array(results["significant_features"])
        ba = np.array(results["bottleneck_amplitudes"])
        # Spheres (indices 4-7): at least some should have H2 features
        # Low-noise spheres (index 4, 5) should reliably show H2
        h2_count = sum(1 for i in range(4, 8) if sf[i, 2] >= 1)
        assert h2_count >= 2, (
            f"Expected at least 2 spheres with significant H2, got {h2_count}. "
            f"H2 significant features: {sf[4:8, 2].tolist()}"
        )

    def test_tori_have_multiple_h1_features(self, results):
        sf = np.array(results["significant_features"])
        # Tori (indices 8-11): should have >= 2 significant H1 features
        # At least the low-noise ones should show this
        multi_h1_count = sum(1 for i in range(8, 12) if sf[i, 1] >= 2)
        assert multi_h1_count >= 2, (
            f"Expected at least 2 tori with >= 2 significant H1 features, "
            f"got {multi_h1_count}. H1 significant: {sf[8:12, 1].tolist()}"
        )


class TestDistanceMatrix:
    """Verify mathematical properties of the H1 bottleneck distance matrix."""

    def test_symmetry(self, results):
        dm = np.array(results["distance_matrix_h1"])
        assert np.allclose(dm, dm.T, atol=1e-6), "Distance matrix is not symmetric"

    def test_zero_diagonal(self, results):
        dm = np.array(results["distance_matrix_h1"])
        assert np.allclose(np.diag(dm), 0, atol=1e-6), (
            f"Diagonal is not zero: {np.diag(dm).tolist()}"
        )

    def test_non_negative(self, results):
        dm = np.array(results["distance_matrix_h1"])
        assert np.all(dm >= -1e-6), "Distance matrix has negative entries"

    def test_all_values_finite(self, results):
        dm = np.array(results["distance_matrix_h1"])
        assert np.all(np.isfinite(dm)), "Distance matrix has non-finite entries"

    def test_intra_vs_inter_class_distances(self, results):
        dm = np.array(results["distance_matrix_h1"])
        # Compute average intra-class and inter-class distances
        intra_dists = []
        inter_dists = []
        for i in range(12):
            for j in range(i + 1, 12):
                if TRUE_LABELS[i] == TRUE_LABELS[j]:
                    intra_dists.append(dm[i, j])
                else:
                    inter_dists.append(dm[i, j])
        avg_intra = np.mean(intra_dists) if intra_dists else 0.0
        avg_inter = np.mean(inter_dists) if inter_dists else 0.0
        # Intra-class distances should generally be smaller
        assert avg_intra < avg_inter, (
            f"Average intra-class distance ({avg_intra:.4f}) should be less "
            f"than average inter-class distance ({avg_inter:.4f})"
        )

    def test_most_similar_distance_less_than_dissimilar(self, results):
        dm = np.array(results["distance_matrix_h1"])
        sim = results["most_similar_pair"]
        dis = results["most_dissimilar_pair"]
        d_sim = dm[sim[0], sim[1]]
        d_dis = dm[dis[0], dis[1]]
        assert d_sim <= d_dis, (
            f"Most similar pair distance ({d_sim:.4f}) should be <= "
            f"most dissimilar pair distance ({d_dis:.4f})"
        )


class TestNumericalProperties:
    """Verify numerical properties of extracted features."""

    def test_entropies_non_negative(self, results):
        pe = np.array(results["persistence_entropies"])
        assert np.all(pe >= -1e-6), (
            f"Persistence entropies should be non-negative, "
            f"min value: {pe.min():.6f}"
        )

    def test_entropies_finite(self, results):
        pe = np.array(results["persistence_entropies"])
        assert np.all(np.isfinite(pe)), "Persistence entropies have non-finite values"

    def test_significant_features_non_negative_integers(self, results):
        sf = np.array(results["significant_features"])
        assert np.all(sf >= 0), "Significant feature counts should be non-negative"
        assert np.all(sf == sf.astype(int)), "Significant feature counts should be integers"

    def test_bottleneck_amplitudes_non_negative(self, results):
        ba = np.array(results["bottleneck_amplitudes"])
        assert np.all(ba >= -1e-6), "Bottleneck amplitudes should be non-negative"

    def test_stability_scores_in_range(self, results):
        ss = np.array(results["stability_scores"])
        assert np.all(ss > 0), f"Stability scores should be positive, min: {ss.min()}"
        assert np.all(ss <= 1.0 + 1e-6), (
            f"Stability scores should be <= 1.0, max: {ss.max()}"
        )

    def test_stability_scores_finite(self, results):
        ss = np.array(results["stability_scores"])
        assert np.all(np.isfinite(ss)), "Stability scores have non-finite values"

    def test_h0_features_all_clouds(self, results):
        """Every point cloud should have at least one significant H0 feature."""
        sf = np.array(results["significant_features"])
        for i in range(12):
            assert sf[i, 0] >= 1, (
                f"Cloud {i}: expected at least 1 significant H0 feature, "
                f"got {sf[i, 0]}"
            )
