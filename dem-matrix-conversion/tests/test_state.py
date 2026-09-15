"""
Tests for the DEM-to-matrices conversion module.
"""
import sys
sys.path.insert(0, "/app")

import numpy as np
import pytest
from scipy.sparse import csc_matrix
import stim

from dem_converter import DemMatrices, detector_error_model_to_check_matrices


def assert_csc_eq(sparse_mat, dense_list):
    """Assert that a CSC sparse matrix equals a dense list-of-lists."""
    expected = csc_matrix(np.array(dense_list, dtype=np.uint8))
    diff = sparse_mat != expected
    assert diff.nnz == 0, (
        f"Matrix mismatch.\n"
        f"Got:\n{sparse_mat.toarray()}\n"
        f"Expected:\n{np.array(dense_list, dtype=np.uint8)}"
    )


class TestSimpleEdges:
    """Test basic edge-only DEM with no hyperedges or separators."""

    def test_matrices(self):
        dem = stim.DetectorErrorModel(
            "error(0.1) D0 D1\n"
            "error(0.2) D1 D2 L0\n"
            "error(0.05) D0 L1"
        )
        mats = detector_error_model_to_check_matrices(dem)

        # 3 detectors, 2 observables, 3 hyperedges (all are edges)
        assert_csc_eq(mats.check_matrix, [
            [1, 0, 1],
            [1, 1, 0],
            [0, 1, 0],
        ])
        assert_csc_eq(mats.observables_matrix, [
            [0, 1, 0],
            [0, 0, 1],
        ])
        # Edge matrices equal hyperedge matrices when all are simple edges
        assert_csc_eq(mats.edge_check_matrix, [
            [1, 0, 1],
            [1, 1, 0],
            [0, 1, 0],
        ])
        assert_csc_eq(mats.edge_observables_matrix, [
            [0, 1, 0],
            [0, 0, 1],
        ])
        # h2e is identity
        assert_csc_eq(mats.hyperedge_to_edge_matrix, [
            [1, 0, 0],
            [0, 1, 0],
            [0, 0, 1],
        ])
        assert np.allclose(mats.priors, [0.1, 0.2, 0.05])


class TestHyperedgeDecomposition:
    """Test DEM with hyperedges decomposed via ^ separators."""

    def test_matrices(self):
        dem = stim.DetectorErrorModel(
            "error(0.1) D0 D3 L0 L1 ^ D1 D2 L1\n"
            "error(0.15) D0 D3 L0 L1 ^ D1 D2 L1\n"
            "error(0.2) D0 D3 L0 L1\n"
            "error(0.3) D1 D2 L1\n"
            "error(0.4) D1 D2 L1"
        )
        mats = detector_error_model_to_check_matrices(dem)

        # 3 hyperedges: {0,1,2,3}, {0,3}, {1,2}
        assert_csc_eq(mats.check_matrix, [
            [1, 1, 0],
            [1, 0, 1],
            [1, 0, 1],
            [1, 1, 0],
        ])
        # obs for h0: symm_diff({0,1},{1}) = {0}
        # obs for h1: {0,1}
        # obs for h2: {1}
        assert_csc_eq(mats.observables_matrix, [
            [1, 1, 0],
            [0, 1, 1],
        ])

        # 2 edges: {0,3}, {1,2}
        assert_csc_eq(mats.edge_check_matrix, [
            [1, 0],
            [0, 1],
            [0, 1],
            [1, 0],
        ])
        assert_csc_eq(mats.edge_observables_matrix, [
            [1, 0],
            [1, 1],
        ])
        assert_csc_eq(mats.hyperedge_to_edge_matrix, [
            [1, 1, 0],
            [1, 0, 1],
        ])

        # Prior accumulation:
        # h0 ({0,1,2,3}): 0.1*(1-0.15) + 0.15*(1-0.1) = 0.22
        # h1 ({0,3}): 0.2
        # h2 ({1,2}): 0.3*(1-0.4) + 0.4*(1-0.3) = 0.46
        assert np.allclose(mats.priors, [0.22, 0.2, 0.46])


class TestPriorAccumulation:
    """Test that duplicate error mechanisms combine priors correctly."""

    def test_gf2_probability_combination(self):
        dem = stim.DetectorErrorModel(
            "error(0.1) D0 D1 L0\n"
            "error(0.2) D0 D1 L0\n"
            "error(0.3) D1 D2"
        )
        mats = detector_error_model_to_check_matrices(dem)

        assert_csc_eq(mats.check_matrix, [
            [1, 0],
            [1, 1],
            [0, 1],
        ])
        assert_csc_eq(mats.observables_matrix, [[1, 0]])

        # p = 0.1*(1-0.2) + 0.2*(1-0.1) = 0.08 + 0.18 = 0.26
        assert np.allclose(mats.priors, [0.26, 0.3])

    def test_triple_accumulation(self):
        dem = stim.DetectorErrorModel(
            "error(0.1) D0 D1\n"
            "error(0.1) D0 D1\n"
            "error(0.1) D0 D1"
        )
        mats = detector_error_model_to_check_matrices(dem)

        # Three independent p=0.1 events:
        # After 2: 0.1*(1-0.1) + 0.1*(1-0.1) = 0.18
        # After 3: 0.18*(1-0.1) + 0.1*(1-0.18) = 0.162 + 0.082 = 0.244
        assert np.allclose(mats.priors, [0.244])
        assert mats.check_matrix.shape == (2, 1)


class TestBoundaryError:
    """Test error mechanisms with empty or single-detector support."""

    def test_observable_only_error(self):
        dem = stim.DetectorErrorModel(
            "error(0.05) L0\n"
            "error(0.1) D0 D1\n"
            "error(0.2) D0 L0"
        )
        mats = detector_error_model_to_check_matrices(dem)

        # Hyperedge 0: {} (no detectors, only L0)
        # Hyperedge 1: {0,1}
        # Hyperedge 2: {0}
        assert_csc_eq(mats.check_matrix, [
            [0, 1, 1],
            [0, 1, 0],
        ])
        assert_csc_eq(mats.observables_matrix, [[1, 0, 1]])
        assert np.allclose(mats.priors, [0.05, 0.1, 0.2])

        # All are edges (≤2 detectors each, including 0-detector boundary)
        assert_csc_eq(mats.edge_check_matrix, [
            [0, 1, 1],
            [0, 1, 0],
        ])
        assert_csc_eq(mats.hyperedge_to_edge_matrix, [
            [1, 0, 0],
            [0, 1, 0],
            [0, 0, 1],
        ])


class TestUndecomposedHyperedge:
    """Test handling of >2-detector components."""

    def test_allowed(self):
        dem = stim.DetectorErrorModel("error(0.1) D0 D1 D2 L0")
        mats = detector_error_model_to_check_matrices(
            dem, allow_undecomposed_hyperedges=True
        )

        assert_csc_eq(mats.check_matrix, [[1], [1], [1]])
        assert_csc_eq(mats.observables_matrix, [[1]])
        assert np.allclose(mats.priors, [0.1])

        # No edges created (the 3-detector component is skipped)
        assert mats.edge_check_matrix.shape == (3, 0)
        assert mats.edge_observables_matrix.shape == (1, 0)
        assert mats.hyperedge_to_edge_matrix.shape == (0, 1)

    def test_raises_when_disallowed(self):
        dem = stim.DetectorErrorModel("error(0.1) D0 D1 D2 L0")
        with pytest.raises(ValueError):
            detector_error_model_to_check_matrices(
                dem, allow_undecomposed_hyperedges=False
            )


class TestMultiComponentDecomposition:
    """Test a 3-component hyperedge decomposition."""

    def test_matrices(self):
        dem = stim.DetectorErrorModel(
            "error(0.05) D0 D1 L0 ^ D2 D3 L1 ^ D4 D5\n"
            "error(0.1) D0 D1 L0\n"
            "error(0.15) D2 D3 L1"
        )
        mats = detector_error_model_to_check_matrices(dem)

        # Hyperedge 0: {0,1,2,3,4,5} (symm diff of all 3 components)
        # Hyperedge 1: {0,1}
        # Hyperedge 2: {2,3}
        assert_csc_eq(mats.check_matrix, [
            [1, 1, 0],
            [1, 1, 0],
            [1, 0, 1],
            [1, 0, 1],
            [1, 0, 0],
            [1, 0, 0],
        ])

        # obs for h0: symm_diff({0},{1},{}) = {0,1}
        # obs for h1: {0}
        # obs for h2: {1}
        assert_csc_eq(mats.observables_matrix, [
            [1, 1, 0],
            [1, 0, 1],
        ])

        # 3 edges: {0,1}, {2,3}, {4,5}
        assert_csc_eq(mats.edge_check_matrix, [
            [1, 0, 0],
            [1, 0, 0],
            [0, 1, 0],
            [0, 1, 0],
            [0, 0, 1],
            [0, 0, 1],
        ])
        assert_csc_eq(mats.edge_observables_matrix, [
            [1, 0, 0],
            [0, 1, 0],
        ])

        # h0 decomposes into all 3 edges; h1->edge0; h2->edge1
        assert_csc_eq(mats.hyperedge_to_edge_matrix, [
            [1, 1, 0],
            [1, 0, 1],
            [1, 0, 0],
        ])

        assert np.allclose(mats.priors, [0.05, 0.1, 0.15])


class TestRepetitionCodeCircuit:
    """Integration test with a stim-generated repetition code circuit."""

    def test_shapes_and_properties(self):
        circuit = stim.Circuit.generated(
            "repetition_code:memory",
            rounds=3,
            distance=5,
            after_clifford_depolarization=0.01,
        )
        dem = circuit.detector_error_model(decompose_errors=True)
        mats = detector_error_model_to_check_matrices(dem)

        # Check matrix shapes are consistent
        num_hyperedges = mats.check_matrix.shape[1]
        assert mats.check_matrix.shape[0] == dem.num_detectors
        assert mats.observables_matrix.shape[0] == dem.num_observables
        assert mats.observables_matrix.shape[1] == num_hyperedges
        assert len(mats.priors) == num_hyperedges

        num_edges = mats.edge_check_matrix.shape[1]
        assert mats.edge_check_matrix.shape[0] == dem.num_detectors
        assert mats.edge_observables_matrix.shape[0] == dem.num_observables
        assert mats.edge_observables_matrix.shape[1] == num_edges

        assert mats.hyperedge_to_edge_matrix.shape == (num_edges, num_hyperedges)

        # Priors are valid probabilities
        assert np.all(mats.priors >= 0)
        assert np.all(mats.priors <= 1)

        # Matrices have binary entries
        assert np.all(mats.check_matrix.data == 1)
        if mats.observables_matrix.nnz > 0:
            assert np.all(mats.observables_matrix.data == 1)


class TestSurfaceCodeCircuit:
    """Integration test with a stim-generated surface code circuit."""

    def test_shapes_and_consistency(self):
        circuit = stim.Circuit.generated(
            "surface_code:rotated_memory_x",
            rounds=3,
            distance=3,
            after_clifford_depolarization=0.005,
        )
        dem = circuit.detector_error_model(decompose_errors=True)
        mats = detector_error_model_to_check_matrices(dem)

        num_h = mats.check_matrix.shape[1]
        num_e = mats.edge_check_matrix.shape[1]

        assert mats.check_matrix.shape[0] == dem.num_detectors
        assert mats.observables_matrix.shape == (dem.num_observables, num_h)
        assert mats.edge_check_matrix.shape[0] == dem.num_detectors
        assert mats.edge_observables_matrix.shape == (dem.num_observables, num_e)
        assert mats.hyperedge_to_edge_matrix.shape == (num_e, num_h)
        assert len(mats.priors) == num_h

        assert np.all(mats.priors >= 0)
        assert np.all(mats.priors <= 1)
        assert np.all(mats.check_matrix.data == 1)
        assert np.all(mats.edge_check_matrix.data == 1)

        # Verify check_matrix = edge_check_matrix @ h2e (mod 2)
        # for the columns where h2e has nonzero entries
        product = mats.edge_check_matrix @ mats.hyperedge_to_edge_matrix
        reconstructed = product.toarray() % 2
        original = mats.check_matrix.toarray()
        # Only check columns where the hyperedge has an edge decomposition
        for j in range(num_h):
            h2e_col = mats.hyperedge_to_edge_matrix[:, j]
            if h2e_col.nnz > 0:
                np.testing.assert_array_equal(
                    reconstructed[:, j], original[:, j],
                    err_msg=f"check_matrix column {j} != edge_check_matrix @ h2e column {j} mod 2"
                )
