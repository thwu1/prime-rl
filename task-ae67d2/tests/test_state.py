
import sys
sys.path.insert(0, "/app")

import json
import pytest
import numpy as np
import stim
import pymatching
from scipy.sparse import csc_matrix

from dem_to_matrices import detector_error_model_to_check_matrices, DemMatrices
from decoder import SyndromeDecoder


def assert_csc_eq(sparse_mat, dense_mat):
    """Assert a sparse matrix equals a given dense matrix."""
    assert (sparse_mat != csc_matrix(dense_mat)).nnz == 0


class TestDemToMatrices:
    """Test the DEM-to-matrices conversion on a known reference DEM."""

    def test_returns_dem_matrices_dataclass(self):
        dem = stim.DetectorErrorModel(
            "error(0.1) D0 D3 L0 L1 ^ D1 D2 L1\n"
            "error(0.15) D0 D3 L0 L1 ^ D1 D2 L1\n"
            "error(0.2) D0 D3 L0 L1\n"
            "error(0.3) D1 D2 L1\n"
            "error(0.4) D1 D2 L1\n"
        )
        mats = detector_error_model_to_check_matrices(dem)
        assert isinstance(mats, DemMatrices)
        assert isinstance(mats.check_matrix, csc_matrix)
        assert isinstance(mats.observables_matrix, csc_matrix)
        assert isinstance(mats.edge_check_matrix, csc_matrix)
        assert isinstance(mats.edge_observables_matrix, csc_matrix)
        assert isinstance(mats.hyperedge_to_edge_matrix, csc_matrix)
        assert isinstance(mats.priors, np.ndarray)

    def test_check_matrix_shape_and_values(self):
        dem = stim.DetectorErrorModel(
            "error(0.1) D0 D3 L0 L1 ^ D1 D2 L1\n"
            "error(0.15) D0 D3 L0 L1 ^ D1 D2 L1\n"
            "error(0.2) D0 D3 L0 L1\n"
            "error(0.3) D1 D2 L1\n"
            "error(0.4) D1 D2 L1\n"
        )
        mats = detector_error_model_to_check_matrices(dem)
        assert mats.check_matrix.shape == (4, 3)
        assert_csc_eq(mats.check_matrix, [
            [1, 1, 0],
            [1, 0, 1],
            [1, 0, 1],
            [1, 1, 0],
        ])

    def test_observables_matrix(self):
        dem = stim.DetectorErrorModel(
            "error(0.1) D0 D3 L0 L1 ^ D1 D2 L1\n"
            "error(0.15) D0 D3 L0 L1 ^ D1 D2 L1\n"
            "error(0.2) D0 D3 L0 L1\n"
            "error(0.3) D1 D2 L1\n"
            "error(0.4) D1 D2 L1\n"
        )
        mats = detector_error_model_to_check_matrices(dem)
        assert mats.observables_matrix.shape == (2, 3)
        assert_csc_eq(mats.observables_matrix, [
            [1, 1, 0],
            [0, 1, 1],
        ])

    def test_edge_check_matrix(self):
        dem = stim.DetectorErrorModel(
            "error(0.1) D0 D3 L0 L1 ^ D1 D2 L1\n"
            "error(0.15) D0 D3 L0 L1 ^ D1 D2 L1\n"
            "error(0.2) D0 D3 L0 L1\n"
            "error(0.3) D1 D2 L1\n"
            "error(0.4) D1 D2 L1\n"
        )
        mats = detector_error_model_to_check_matrices(dem)
        assert mats.edge_check_matrix.shape == (4, 2)
        assert_csc_eq(mats.edge_check_matrix, [
            [1, 0],
            [0, 1],
            [0, 1],
            [1, 0],
        ])

    def test_edge_observables_matrix(self):
        dem = stim.DetectorErrorModel(
            "error(0.1) D0 D3 L0 L1 ^ D1 D2 L1\n"
            "error(0.15) D0 D3 L0 L1 ^ D1 D2 L1\n"
            "error(0.2) D0 D3 L0 L1\n"
            "error(0.3) D1 D2 L1\n"
            "error(0.4) D1 D2 L1\n"
        )
        mats = detector_error_model_to_check_matrices(dem)
        assert mats.edge_observables_matrix.shape == (2, 2)
        assert_csc_eq(mats.edge_observables_matrix, [
            [1, 0],
            [1, 1],
        ])

    def test_hyperedge_to_edge_matrix(self):
        dem = stim.DetectorErrorModel(
            "error(0.1) D0 D3 L0 L1 ^ D1 D2 L1\n"
            "error(0.15) D0 D3 L0 L1 ^ D1 D2 L1\n"
            "error(0.2) D0 D3 L0 L1\n"
            "error(0.3) D1 D2 L1\n"
            "error(0.4) D1 D2 L1\n"
        )
        mats = detector_error_model_to_check_matrices(dem)
        assert mats.hyperedge_to_edge_matrix.shape == (2, 3)
        assert_csc_eq(mats.hyperedge_to_edge_matrix, [
            [1, 1, 0],
            [1, 0, 1],
        ])

    def test_priors_merging(self):
        dem = stim.DetectorErrorModel(
            "error(0.1) D0 D3 L0 L1 ^ D1 D2 L1\n"
            "error(0.15) D0 D3 L0 L1 ^ D1 D2 L1\n"
            "error(0.2) D0 D3 L0 L1\n"
            "error(0.3) D1 D2 L1\n"
            "error(0.4) D1 D2 L1\n"
        )
        mats = detector_error_model_to_check_matrices(dem)
        assert mats.priors.shape == (3,)
        assert np.allclose(mats.priors, np.array([0.22, 0.2, 0.46]))

    def test_surface_code_dem_consistency(self):
        """Test matrix dimension consistency on the real surface code DEM."""
        dem = stim.DetectorErrorModel.from_file("/app/surface_code.dem")
        with open("/app/config.json") as f:
            config = json.load(f)

        mats = detector_error_model_to_check_matrices(dem)

        assert mats.check_matrix.shape[0] == config["num_detectors"]
        assert mats.edge_check_matrix.shape[0] == config["num_detectors"]
        assert mats.observables_matrix.shape[0] == config["num_observables"]
        assert mats.edge_observables_matrix.shape[0] == config["num_observables"]

        n_hyperedges = mats.check_matrix.shape[1]
        n_edges = mats.edge_check_matrix.shape[1]
        assert mats.observables_matrix.shape[1] == n_hyperedges
        assert mats.edge_observables_matrix.shape[1] == n_edges
        assert mats.hyperedge_to_edge_matrix.shape == (n_edges, n_hyperedges)
        assert mats.priors.shape == (n_hyperedges,)
        assert np.all(mats.priors >= 0)
        assert np.all(mats.priors <= 1)


class TestSyndromeDecoder:
    """Test the syndrome decoder."""

    def test_instantiation(self):
        dem = stim.DetectorErrorModel.from_file("/app/surface_code.dem")
        decoder = SyndromeDecoder(dem)
        assert decoder is not None

    def test_decode_zero_syndrome(self):
        dem = stim.DetectorErrorModel.from_file("/app/surface_code.dem")
        with open("/app/config.json") as f:
            config = json.load(f)
        decoder = SyndromeDecoder(dem)
        syndrome = np.zeros(config["num_detectors"], dtype=np.uint8)
        prediction = decoder.decode(syndrome)
        assert prediction.shape == (config["num_observables"],)
        assert np.all(prediction == 0)

    def test_decode_batch_shape(self):
        dem = stim.DetectorErrorModel.from_file("/app/surface_code.dem")
        with open("/app/config.json") as f:
            config = json.load(f)
        decoder = SyndromeDecoder(dem)
        shots = np.zeros((10, config["num_detectors"]), dtype=np.uint8)
        predictions = decoder.decode_batch(shots)
        assert predictions.shape == (10, config["num_observables"])
        assert np.all((predictions == 0) | (predictions == 1))

    def test_outperforms_mwpm(self):
        """Decoder must achieve <= errors compared to plain MWPM."""
        dem = stim.DetectorErrorModel.from_file("/app/surface_code.dem")
        with open("/app/config.json") as f:
            config = json.load(f)

        shot_data = stim.read_shot_data_file(
            path="/app/shots.b8",
            format="b8",
            num_detectors=config["num_detectors"],
            num_observables=config["num_observables"],
        )
        shots = shot_data[:, :config["num_detectors"]]
        observables = shot_data[:, config["num_detectors"]:]

        # MWPM baseline
        matching = pymatching.Matching.from_detector_error_model(dem)
        mwpm_preds = matching.decode_batch(shots)
        mwpm_errors = int(np.sum(np.any(mwpm_preds != observables, axis=1)))

        # Syndrome decoder
        sd = SyndromeDecoder(dem)
        sd_preds = sd.decode_batch(shots)
        sd_errors = int(np.sum(np.any(sd_preds != observables, axis=1)))

        # Data should be non-trivial
        assert mwpm_errors > 0, "Shot data has no MWPM errors; data is trivial"

        # Decoder should match or beat MWPM
        assert sd_errors <= mwpm_errors, (
            f"Decoder ({sd_errors} errors) must not exceed "
            f"MWPM ({mwpm_errors} errors)"
        )

        # Sanity: not worse than random guessing
        assert sd_errors < config["num_shots"] // 2
