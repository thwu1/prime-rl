
import sys
import ast

sys.path.insert(0, "/app")

import numpy as np
import stim
from scipy.sparse import csc_matrix

from qec_pipeline import DemMatrices, dem_to_matrices, Decoder


def assert_csc_eq(sparse_mat, dense_list):
    """Assert a CSC sparse matrix equals the given dense 2D list."""
    dense = np.array(dense_list, dtype=np.uint8)
    diff = (sparse_mat != csc_matrix(dense, dtype=np.uint8)).nnz
    assert diff == 0, (
        f"Matrix mismatch:\nGot:\n{sparse_mat.toarray()}\nExpected:\n{dense}"
    )


# ── DEM-to-Matrices tests ─────────────────────────────────────────────


class TestDemToMatrices:
    def test_hyperedge_decomposition(self):
        """Hyperedges with ^ separator, probability merging, multiple observables."""
        dem = stim.DetectorErrorModel(
            "error(0.1) D0 D3 L0 L1 ^ D1 D2 L1\n"
            "error(0.15) D0 D3 L0 L1 ^ D1 D2 L1\n"
            "error(0.2) D0 D3 L0 L1\n"
            "error(0.3) D1 D2 L1\n"
            "error(0.4) D1 D2 L1"
        )
        mats = dem_to_matrices(dem)

        # 3 hyperedges: {0,1,2,3}, {0,3}, {1,2}
        assert_csc_eq(
            mats.check_matrix,
            [[1, 1, 0], [1, 0, 1], [1, 0, 1], [1, 1, 0]],
        )
        assert_csc_eq(
            mats.observables_matrix,
            [[1, 1, 0], [0, 1, 1]],
        )
        # 2 edges: {0,3}, {1,2}
        assert_csc_eq(
            mats.edge_check_matrix,
            [[1, 0], [0, 1], [0, 1], [1, 0]],
        )
        assert_csc_eq(
            mats.edge_observables_matrix,
            [[1, 0], [1, 1]],
        )
        assert_csc_eq(
            mats.hyperedge_to_edge_matrix,
            [[1, 1, 0], [1, 0, 1]],
        )
        # Priors: H0 = 0.1 merged with 0.15 -> 0.22,
        #         H1 = 0.2,
        #         H2 = 0.3 merged with 0.4 -> 0.46
        assert np.allclose(mats.priors, np.array([0.22, 0.2, 0.46]))

    def test_boundary_edges(self):
        """Edges with single detector (boundary) and no hyperedges."""
        dem = stim.DetectorErrorModel(
            "error(0.1) D0 D1\n"
            "error(0.2) D1 D2\n"
            "error(0.15) D0 L0\n"
            "error(0.25) D2 L0"
        )
        mats = dem_to_matrices(dem)

        # 4 hyperedges (all are edges): {0,1}, {1,2}, {0}, {2}
        assert_csc_eq(
            mats.check_matrix,
            [[1, 0, 1, 0], [1, 1, 0, 0], [0, 1, 0, 1]],
        )
        assert_csc_eq(mats.observables_matrix, [[0, 0, 1, 1]])

        # Edge matrices match (all hyperedges are edges)
        assert_csc_eq(
            mats.edge_check_matrix,
            [[1, 0, 1, 0], [1, 1, 0, 0], [0, 1, 0, 1]],
        )
        assert_csc_eq(mats.edge_observables_matrix, [[0, 0, 1, 1]])

        # Hyperedge-to-edge is identity
        np.testing.assert_array_equal(
            mats.hyperedge_to_edge_matrix.toarray(),
            np.eye(4, dtype=np.uint8),
        )
        assert np.allclose(mats.priors, [0.1, 0.2, 0.15, 0.25])

    def test_probability_merging(self):
        """Same hyperedge from multiple error instructions merges correctly."""
        dem = stim.DetectorErrorModel(
            "error(0.3) D0 D1 L0\n" "error(0.5) D0 D1 L0"
        )
        mats = dem_to_matrices(dem)

        # p = 0.3*(1-0.5) + 0.5*(1-0.3) = 0.15 + 0.35 = 0.5
        assert np.allclose(mats.priors, [0.5])
        assert_csc_eq(mats.check_matrix, [[1], [1]])
        assert_csc_eq(mats.observables_matrix, [[1]])

    def test_circuit_shapes(self):
        """Matrix shapes are consistent for a generated repetition code."""
        circuit = stim.Circuit.generated(
            "repetition_code:memory",
            rounds=3,
            distance=3,
            after_clifford_depolarization=0.01,
        )
        dem = circuit.detector_error_model(decompose_errors=True)
        mats = dem_to_matrices(dem)

        n_det = dem.num_detectors
        n_obs = dem.num_observables
        n_hyp = mats.check_matrix.shape[1]
        n_edge = mats.edge_check_matrix.shape[1]

        assert mats.check_matrix.shape == (n_det, n_hyp)
        assert mats.observables_matrix.shape == (n_obs, n_hyp)
        assert mats.edge_check_matrix.shape == (n_det, n_edge)
        assert mats.edge_observables_matrix.shape == (n_obs, n_edge)
        assert mats.hyperedge_to_edge_matrix.shape == (n_edge, n_hyp)
        assert mats.priors.shape == (n_hyp,)
        assert np.all(mats.priors >= 0) and np.all(mats.priors <= 1)
        assert np.all(
            (mats.check_matrix.toarray() == 0) | (mats.check_matrix.toarray() == 1)
        )


# ── Decoder tests ─────────────────────────────────────────────────────


def _rep_code_dem():
    """Distance-3 repetition code DEM with boundary edges."""
    return stim.DetectorErrorModel(
        "error(0.1) D0 D1\n"
        "error(0.2) D1 D2\n"
        "error(0.15) D0 L0\n"
        "error(0.25) D2 L0"
    )


class TestDecoder:
    def test_zero_syndrome(self):
        decoder = Decoder(_rep_code_dem())
        syndrome = np.zeros(3, dtype=np.uint8)
        prediction = decoder.decode(syndrome)
        assert prediction.shape == (1,)
        assert prediction[0] == 0

    def test_boundary_errors(self):
        """Single triggered detector matched to boundary flips observable."""
        decoder = Decoder(_rep_code_dem())

        # D0 triggered → matched to boundary via D0-L0 edge → L0 flipped
        pred = decoder.decode(np.array([1, 0, 0], dtype=np.uint8))
        assert pred[0] == 1

        # D2 triggered → matched to boundary via D2-L0 edge → L0 flipped
        pred = decoder.decode(np.array([0, 0, 1], dtype=np.uint8))
        assert pred[0] == 1

    def test_paired_detectors(self):
        """Two adjacent detectors matched together produce no observable flip."""
        decoder = Decoder(_rep_code_dem())

        # D0, D1 triggered → matched to each other → no obs flip
        pred = decoder.decode(np.array([1, 1, 0], dtype=np.uint8))
        assert pred[0] == 0

        # D1, D2 triggered → matched → no obs flip
        pred = decoder.decode(np.array([0, 1, 1], dtype=np.uint8))
        assert pred[0] == 0

    def test_all_detectors_triggered(self):
        """Odd number of triggered detectors routes one to boundary."""
        decoder = Decoder(_rep_code_dem())

        # D0, D1, D2 all triggered → odd → one matched to boundary
        pred = decoder.decode(np.array([1, 1, 1], dtype=np.uint8))
        assert pred[0] == 1

    def test_batch_decode(self):
        decoder = Decoder(_rep_code_dem())
        shots = np.array(
            [
                [0, 0, 0],
                [1, 0, 0],
                [1, 1, 0],
                [0, 0, 1],
                [0, 1, 1],
                [1, 1, 1],
            ],
            dtype=np.uint8,
        )
        predictions = decoder.decode_batch(shots)
        assert predictions.shape == (6, 1)
        assert predictions[0, 0] == 0  # zero syndrome
        assert predictions[1, 0] == 1  # boundary D0
        assert predictions[2, 0] == 0  # paired D0-D1
        assert predictions[3, 0] == 1  # boundary D2
        assert predictions[4, 0] == 0  # paired D1-D2
        assert predictions[5, 0] == 1  # all triggered

    def test_repetition_code_sampling(self):
        """End-to-end decoding of sampled repetition code data."""
        circuit = stim.Circuit.generated(
            "repetition_code:memory",
            rounds=5,
            distance=5,
            after_clifford_depolarization=0.05,
        )
        dem = circuit.detector_error_model(decompose_errors=True)
        decoder = Decoder(dem)

        sampler = circuit.compile_detector_sampler()
        shot_data = sampler.sample(
            2000, separate_observables=False, append_observables=True
        )

        shots = shot_data[:, : dem.num_detectors].astype(np.uint8)
        actual_obs = shot_data[:, dem.num_detectors :].astype(np.uint8)

        predictions = decoder.decode_batch(shots)

        num_errors = np.sum(np.any(predictions != actual_obs, axis=1))
        error_rate = num_errors / 2000
        assert error_rate < 0.05, f"Decoder error rate {error_rate:.4f} too high"

    def test_surface_code_sampling(self):
        """End-to-end decoding of sampled surface code data."""
        circuit = stim.Circuit.generated(
            "surface_code:rotated_memory_x",
            rounds=3,
            distance=3,
            before_round_data_depolarization=0.001,
            before_measure_flip_probability=0.001,
            after_reset_flip_probability=0.001,
            after_clifford_depolarization=0.001,
        )
        dem = circuit.detector_error_model(decompose_errors=True)
        decoder = Decoder(dem)

        sampler = circuit.compile_detector_sampler()
        shot_data = sampler.sample(
            500, separate_observables=False, append_observables=True
        )

        shots = shot_data[:, : dem.num_detectors].astype(np.uint8)
        actual_obs = shot_data[:, dem.num_detectors :].astype(np.uint8)

        predictions = decoder.decode_batch(shots)

        num_errors = np.sum(np.any(predictions != actual_obs, axis=1))
        error_rate = num_errors / 500
        assert error_rate < 0.05, f"Decoder error rate {error_rate:.4f} too high"


# ── Anti-cheat ────────────────────────────────────────────────────────


def test_no_forbidden_imports():
    """Implementation must not import existing QEC decoder packages."""
    with open("/app/qec_pipeline.py", "r") as f:
        tree = ast.parse(f.read())
    forbidden = {"pymatching", "beliefmatching", "stimbposd"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                assert top not in forbidden, f"Forbidden import: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                top = node.module.split(".")[0]
                assert top not in forbidden, f"Forbidden import from: {node.module}"
