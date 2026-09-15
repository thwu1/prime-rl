
import sys
import ast

sys.path.insert(0, "/app")

import numpy as np
import pytest
import stim
from scipy.sparse import csc_matrix


def assert_csc_eq(sparse_mat, dense_list):
    """Assert that a sparse CSC matrix equals a given dense matrix."""
    expected = csc_matrix(dense_list, dtype=np.uint8)
    diff = sparse_mat != expected
    assert diff.nnz == 0, (
        f"Matrix mismatch.\nGot:\n{sparse_mat.toarray()}\nExpected:\n{expected.toarray()}"
    )


# ---------------------------------------------------------------------------
# Matrix construction tests — verify DEM-to-matrices conversion
# ---------------------------------------------------------------------------


class TestBasicDem:
    """Hyperedge decomposition, probability accumulation, all six matrices."""

    DEM = stim.DetectorErrorModel(
        "error(0.1) D0 D3 L0 L1 ^ D1 D2 L1\n"
        "error(0.15) D0 D3 L0 L1 ^ D1 D2 L1\n"
        "error(0.2) D0 D3 L0 L1\n"
        "error(0.3) D1 D2 L1\n"
        "error(0.4) D1 D2 L1"
    )

    def _get_mats(self):
        from qec_decoder import detector_error_model_to_check_matrices

        return detector_error_model_to_check_matrices(self.DEM)

    def test_check_matrix(self):
        mats = self._get_mats()
        # 3 hyperedges: h0={0,1,2,3}, h1={0,3}, h2={1,2}
        assert_csc_eq(
            mats.check_matrix, [[1, 1, 0], [1, 0, 1], [1, 0, 1], [1, 1, 0]]
        )

    def test_observables_matrix(self):
        mats = self._get_mats()
        # h0: obs XOR = {0,1} XOR {1} = {0}
        # h1: obs = {0,1}, h2: obs = {1}
        assert_csc_eq(mats.observables_matrix, [[1, 1, 0], [0, 1, 1]])

    def test_edge_check_matrix(self):
        mats = self._get_mats()
        # 2 edges: e0={0,3}, e1={1,2}
        assert_csc_eq(mats.edge_check_matrix, [[1, 0], [0, 1], [0, 1], [1, 0]])

    def test_edge_observables_matrix(self):
        mats = self._get_mats()
        # e0: obs={0,1}, e1: obs={1}
        assert_csc_eq(mats.edge_observables_matrix, [[1, 0], [1, 1]])

    def test_hyperedge_to_edge_matrix(self):
        mats = self._get_mats()
        # h0->{e0,e1}, h1->{e0}, h2->{e1}
        assert_csc_eq(mats.hyperedge_to_edge_matrix, [[1, 1, 0], [1, 0, 1]])

    def test_priors(self):
        mats = self._get_mats()
        # h0: 0.1 then 0.15 => 0.1*0.85 + 0.15*0.9 = 0.22
        # h1: 0.2
        # h2: 0.3 then 0.4 => 0.3*0.6 + 0.4*0.7 = 0.46
        assert np.allclose(mats.priors, np.array([0.22, 0.2, 0.46]))

    def test_shapes(self):
        mats = self._get_mats()
        assert mats.check_matrix.shape == (4, 3)
        assert mats.observables_matrix.shape == (2, 3)
        assert mats.edge_check_matrix.shape == (4, 2)
        assert mats.edge_observables_matrix.shape == (2, 2)
        assert mats.hyperedge_to_edge_matrix.shape == (2, 3)
        assert mats.priors.shape == (3,)


class TestThreeComponentHyperedge:
    """Three-component hyperedge with XOR cancellation in observables."""

    DEM = stim.DetectorErrorModel(
        "error(0.05) D0 L0 ^ D1 L1 ^ D2 L0 L1\n"
        "error(0.08) D0 D2\n"
        "error(0.12) D1 L1"
    )

    def _get_mats(self):
        from qec_decoder import detector_error_model_to_check_matrices

        return detector_error_model_to_check_matrices(self.DEM)

    def test_shapes(self):
        mats = self._get_mats()
        assert mats.check_matrix.shape == (3, 3)
        assert mats.observables_matrix.shape == (2, 3)
        assert mats.edge_check_matrix.shape == (3, 4)
        assert mats.edge_observables_matrix.shape == (2, 4)
        assert mats.hyperedge_to_edge_matrix.shape == (4, 3)
        assert mats.priors.shape == (3,)

    def test_check_matrix(self):
        mats = self._get_mats()
        # h0: dets = {0} XOR {1} XOR {2} = {0,1,2}
        # h1: dets = {0,2}
        # h2: dets = {1}
        assert_csc_eq(mats.check_matrix, [[1, 1, 0], [1, 0, 1], [1, 1, 0]])

    def test_xor_cancellation_in_observables(self):
        """Three-component XOR: {0} XOR {1} XOR {0,1} = {}"""
        mats = self._get_mats()
        # h0 obs = {} (all cancel), h1 obs = {}, h2 obs = {1}
        assert_csc_eq(mats.observables_matrix, [[0, 0, 0], [0, 0, 1]])

    def test_edge_check_matrix(self):
        mats = self._get_mats()
        # e0={0}, e1={1}, e2={2}, e3={0,2}
        assert_csc_eq(
            mats.edge_check_matrix,
            [[1, 0, 0, 1], [0, 1, 0, 0], [0, 0, 1, 1]],
        )

    def test_edge_observables_matrix(self):
        mats = self._get_mats()
        # e0: obs={0}, e1: obs={1}, e2: obs={0,1}, e3: obs={}
        assert_csc_eq(
            mats.edge_observables_matrix,
            [[1, 0, 1, 0], [0, 1, 1, 0]],
        )

    def test_hyperedge_to_edge_matrix(self):
        mats = self._get_mats()
        # h0->{e0,e1,e2}, h1->{e3}, h2->{e1}
        assert_csc_eq(
            mats.hyperedge_to_edge_matrix,
            [[1, 0, 0], [1, 0, 1], [1, 0, 0], [0, 1, 0]],
        )

    def test_priors(self):
        mats = self._get_mats()
        assert np.allclose(mats.priors, [0.05, 0.08, 0.12])


class TestRepeatBlock:
    """Repeat block flattening with probability accumulation via stim."""

    DEM = stim.DetectorErrorModel(
        "repeat 2 {\n"
        "    error(0.05) D0 D1 L0 ^ D2 D3\n"
        "}\n"
        "error(0.1) D0 D1 L0\n"
        "error(0.15) D2 D3"
    )

    def _get_mats(self):
        from qec_decoder import detector_error_model_to_check_matrices

        return detector_error_model_to_check_matrices(self.DEM)

    def test_shapes(self):
        mats = self._get_mats()
        assert mats.check_matrix.shape == (4, 3)
        assert mats.observables_matrix.shape == (1, 3)
        assert mats.priors.shape == (3,)

    def test_check_matrix(self):
        mats = self._get_mats()
        assert_csc_eq(
            mats.check_matrix,
            [[1, 1, 0], [1, 1, 0], [1, 0, 1], [1, 0, 1]],
        )

    def test_observables_matrix(self):
        mats = self._get_mats()
        assert_csc_eq(mats.observables_matrix, [[1, 1, 0]])

    def test_probability_accumulation(self):
        mats = self._get_mats()
        # h0 (compound): two applications of error(0.05)
        # After 2nd: p=0.05*(1-0.05) + 0.05*(1-0.05) = 0.095
        assert np.isclose(mats.priors[0], 0.095)
        assert np.isclose(mats.priors[1], 0.1)
        assert np.isclose(mats.priors[2], 0.15)

    def test_hyperedge_to_edge_matrix(self):
        mats = self._get_mats()
        assert_csc_eq(
            mats.hyperedge_to_edge_matrix,
            [[1, 1, 0], [1, 0, 1]],
        )


class TestBoundaryEdges:
    """Weight-0 (boundary) and weight-1 edges."""

    DEM = stim.DetectorErrorModel(
        "error(0.05) D0 L0\n"
        "error(0.1) D0 D1\n"
        "error(0.2) L0"
    )

    def _get_mats(self):
        from qec_decoder import detector_error_model_to_check_matrices

        return detector_error_model_to_check_matrices(self.DEM)

    def test_shapes(self):
        mats = self._get_mats()
        assert mats.check_matrix.shape == (2, 3)
        assert mats.observables_matrix.shape == (1, 3)
        assert mats.priors.shape == (3,)

    def test_check_matrix(self):
        mats = self._get_mats()
        # h0: {0}, h1: {0,1}, h2: {} (boundary)
        assert_csc_eq(mats.check_matrix, [[1, 1, 0], [0, 1, 0]])

    def test_observables_matrix(self):
        mats = self._get_mats()
        # h0: {0}, h1: {}, h2: {0}
        assert_csc_eq(mats.observables_matrix, [[1, 0, 1]])

    def test_boundary_hyperedge_has_no_detectors(self):
        """error(0.2) L0 produces a hyperedge with empty detector set."""
        mats = self._get_mats()
        col2 = mats.check_matrix[:, 2].toarray().flatten()
        assert np.all(col2 == 0)

    def test_boundary_hyperedge_has_observable(self):
        mats = self._get_mats()
        obs_col2 = mats.observables_matrix[:, 2].toarray().flatten()
        assert obs_col2[0] == 1

    def test_priors(self):
        mats = self._get_mats()
        assert np.allclose(mats.priors, [0.05, 0.1, 0.2])


# ---------------------------------------------------------------------------
# Decoder construction and batch decoding tests
# ---------------------------------------------------------------------------


class TestDecoderAndBatchDecoding:
    """Verify build_decoder creates a working decoder and decode_batch works."""

    DEM = stim.DetectorErrorModel(
        "error(0.1) D0 D1 L0\n"
        "error(0.2) D1 D2\n"
        "error(0.05) D2 D3 L0\n"
        "error(0.08) D3 D4\n"
        "error(0.03) D4 D5"
    )

    def _get_mats(self):
        from qec_decoder import detector_error_model_to_check_matrices

        return detector_error_model_to_check_matrices(self.DEM)

    def test_decoder_has_decode_method(self):
        from qec_decoder import build_decoder

        mats = self._get_mats()
        decoder = build_decoder(mats)
        assert hasattr(decoder, "decode"), "Decoder must have a .decode() method"

    def test_zero_syndrome_batch(self):
        """Zero syndromes should produce zero predicted observable flips."""
        from qec_decoder import build_decoder, decode_batch

        mats = self._get_mats()
        decoder = build_decoder(mats)
        n_det = mats.check_matrix.shape[0]
        zero_events = np.zeros((10, n_det), dtype=np.uint8)
        predictions = decode_batch(decoder, mats, zero_events)
        assert predictions.shape == (10, mats.observables_matrix.shape[0])
        assert np.all(predictions == 0), "Zero syndrome must predict zero observable flips"

    def test_output_is_binary(self):
        """Predictions must be binary (0 or 1)."""
        from qec_decoder import build_decoder, decode_batch

        mats = self._get_mats()
        decoder = build_decoder(mats)
        n_det = mats.check_matrix.shape[0]
        # Create some non-trivial syndromes
        events = np.zeros((5, n_det), dtype=np.uint8)
        events[1, 0] = 1
        events[1, 1] = 1
        events[2, 2] = 1
        events[2, 3] = 1
        predictions = decode_batch(decoder, mats, events)
        assert set(np.unique(predictions)).issubset({0, 1}), "Predictions must be binary"


# ---------------------------------------------------------------------------
# End-to-end pipeline tests on stim-generated circuits
# ---------------------------------------------------------------------------


class TestEndToEndDecoding:
    """Full pipeline: stim circuit -> DEM -> matrices -> decoder -> predictions."""

    def test_repetition_code(self):
        """Repetition code at very low noise should decode near-perfectly."""
        from qec_decoder import (
            detector_error_model_to_check_matrices,
            build_decoder,
            decode_batch,
        )

        circuit = stim.Circuit.generated(
            "repetition_code:memory",
            distance=5,
            rounds=3,
            after_clifford_depolarization=0.001,
        )
        dem = circuit.detector_error_model(decompose_errors=True)
        matrices = detector_error_model_to_check_matrices(dem)
        decoder = build_decoder(matrices)

        sampler = circuit.compile_detector_sampler(seed=42)
        det_events, obs_flips = sampler.sample(1000, separate_observables=True)

        predictions = decode_batch(decoder, matrices, det_events)
        errors = np.any(predictions != obs_flips, axis=1)
        error_rate = errors.mean()

        assert error_rate < 0.05, (
            f"Repetition code d=5 at p=0.001: logical error rate {error_rate:.4f} "
            f"exceeds threshold 0.05"
        )

    def test_surface_code(self):
        """Surface code at moderate noise should decode far better than random."""
        from qec_decoder import (
            detector_error_model_to_check_matrices,
            build_decoder,
            decode_batch,
        )

        circuit = stim.Circuit.generated(
            "surface_code:rotated_memory_z",
            distance=3,
            rounds=3,
            after_clifford_depolarization=0.005,
        )
        dem = circuit.detector_error_model(decompose_errors=True)
        matrices = detector_error_model_to_check_matrices(dem)
        decoder = build_decoder(matrices)

        sampler = circuit.compile_detector_sampler(seed=42)
        det_events, obs_flips = sampler.sample(500, separate_observables=True)

        predictions = decode_batch(decoder, matrices, det_events)
        errors = np.any(predictions != obs_flips, axis=1)
        error_rate = errors.mean()

        assert error_rate < 0.25, (
            f"Surface code d=3 at p=0.005: logical error rate {error_rate:.4f} "
            f"exceeds threshold 0.25 (random guessing gives 0.50)"
        )

    def test_prediction_shape_matches_observables(self):
        """Output shape must match (num_shots, num_observables)."""
        from qec_decoder import (
            detector_error_model_to_check_matrices,
            build_decoder,
            decode_batch,
        )

        circuit = stim.Circuit.generated(
            "repetition_code:memory",
            distance=3,
            rounds=2,
            after_clifford_depolarization=0.01,
        )
        dem = circuit.detector_error_model(decompose_errors=True)
        matrices = detector_error_model_to_check_matrices(dem)
        decoder = build_decoder(matrices)

        sampler = circuit.compile_detector_sampler(seed=99)
        det_events, obs_flips = sampler.sample(50, separate_observables=True)

        predictions = decode_batch(decoder, matrices, det_events)
        assert predictions.shape == obs_flips.shape, (
            f"Shape mismatch: predictions {predictions.shape} vs "
            f"observables {obs_flips.shape}"
        )


# ---------------------------------------------------------------------------
# ML decoding validation — verify matrices enable correct maximum-likelihood
# decoding on a degenerate code
# ---------------------------------------------------------------------------


class TestMLDecodingValidation:
    """Verify matrices produce correct ML predictions on a small degenerate code
    where each syndrome admits both l=0 and l=1 configurations."""

    DEM = stim.DetectorErrorModel(
        "error(0.3) D0 L0\n"
        "error(0.15) D0 D1\n"
        "error(0.2) D1"
    )

    def _get_mats(self):
        from qec_decoder import detector_error_model_to_check_matrices

        return detector_error_model_to_check_matrices(self.DEM)

    def test_ml_predictions(self):
        """Enumerate all 2^3 error configs and verify ML decoding per syndrome."""
        mats = self._get_mats()
        n = mats.priors.shape[0]
        check = mats.check_matrix.toarray()
        obs = mats.observables_matrix.toarray()
        priors = mats.priors

        expected_ml = {
            (0, 0): (0,),
            (1, 0): (1,),
            (0, 1): (0,),
            (1, 1): (0,),
        }

        for syndrome_tuple, expected_l in expected_ml.items():
            logical_probs = {}
            for config_int in range(2**n):
                config = np.array(
                    [(config_int >> i) & 1 for i in range(n)], dtype=int
                )
                computed_syndrome = tuple(int(x) for x in (check @ config) % 2)
                if computed_syndrome != syndrome_tuple:
                    continue
                prob = 1.0
                for i in range(n):
                    prob *= priors[i] if config[i] else (1 - priors[i])
                logical = tuple(int(x) for x in (obs @ config) % 2)
                logical_probs[logical] = logical_probs.get(logical, 0.0) + prob

            best_l = max(logical_probs, key=logical_probs.get)
            assert best_l == expected_l, (
                f"Syndrome {syndrome_tuple}: expected ML={expected_l}, got "
                f"{best_l}. Probs: {logical_probs}"
            )


# ---------------------------------------------------------------------------
# Anti-cheat: forbidden imports
# ---------------------------------------------------------------------------


class TestNoForbiddenImports:
    """Ensure the implementation does not use QEC library shortcuts."""

    def test_no_forbidden_imports(self):
        source = open("/app/qec_decoder.py").read()
        tree = ast.parse(source)
        forbidden = {"stimbposd", "beliefmatching", "pymatching"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    assert top not in forbidden, (
                        f"Forbidden import: {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    top = node.module.split(".")[0]
                    assert top not in forbidden, (
                        f"Forbidden import from: {node.module}"
                    )
