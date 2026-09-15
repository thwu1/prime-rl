"""

Verification tests for the system identification and forecasting task.
Checks both JSON and HDF5 outputs against ground-truth dynamics
regenerated from the same random seed used during data generation.
"""
import numpy as np
import json
import os
import h5py
import pytest


# ── ground truth regeneration ───────────────────────────────────────────

def regenerate_true_system():
    """
    Reproduce the exact ground-truth dynamical system that generated the
    training data.  Uses the same seed and parameter sequence as
    generate_data.py.
    """
    np.random.seed(12345)

    n = 10
    r_true = 4
    m = 200
    n_pred = 50

    H = np.random.randn(n, n)
    Q, _ = np.linalg.qr(H)

    Lambda = np.zeros((n, n))
    Lambda[0, 0] = 0.995
    Lambda[1, 1] = 0.92;  Lambda[1, 2] = -0.15
    Lambda[2, 1] = 0.15;  Lambda[2, 2] = 0.92
    Lambda[3, 3] = 0.98

    A = Q @ Lambda @ Q.T

    coeffs = np.array([2.0, 1.5, -1.0, 0.8])
    x0 = Q[:, :r_true] @ coeffs

    total_steps = m + 1 + n_pred
    X_full = np.zeros((n, total_steps))
    X_full[:, 0] = x0
    for t in range(total_steps - 1):
        X_full[:, t + 1] = A @ X_full[:, t]

    # consume noise RNG draws (sync with generate_data.py)
    _ = 0.01 * np.random.randn(n, m + 1)

    complex_mag = np.sqrt(0.92**2 + 0.15**2)
    true_eig_magnitudes = sorted(
        [0.995, complex_mag, complex_mag, 0.98], reverse=True
    )

    return {
        'n': n,
        'r_true': r_true,
        'm': m,
        'n_pred': n_pred,
        'true_eig_magnitudes': true_eig_magnitudes,
        'X_future': X_full[:, m + 1:m + 1 + n_pred],
        'X_train_clean': X_full[:, :m + 1],
    }


def parse_eigenvalues(raw):
    """Parse eigenvalues from JSON — accepts [real, imag] pairs, floats, or strings."""
    parsed = []
    for e in raw:
        if isinstance(e, (list, tuple)) and len(e) >= 2:
            parsed.append(complex(float(e[0]), float(e[1])))
        elif isinstance(e, (int, float)):
            parsed.append(complex(float(e), 0.0))
        elif isinstance(e, str):
            parsed.append(complex(e))
        else:
            raise ValueError(f"Cannot parse eigenvalue entry: {e}")
    return np.array(parsed)


# ── fixtures ────────────────────────────────────────────────────────────

@pytest.fixture(scope='module')
def true_system():
    return regenerate_true_system()


@pytest.fixture(scope='module')
def json_results():
    path = '/app/results.json'
    assert os.path.exists(path), "results.json not found at /app/results.json"
    with open(path, 'r') as f:
        data = json.load(f)
    assert isinstance(data, dict), "results.json must be a JSON object"
    return data


@pytest.fixture(scope='module')
def hdf5_results():
    path = '/app/results.h5'
    assert os.path.exists(path), "results.h5 not found at /app/results.h5"
    return h5py.File(path, 'r')


# ── JSON output format tests ───────────────────────────────────────────

class TestJSONFormat:
    REQUIRED_FIELDS = ['optimal_rank', 'eigenvalues',
                       'eigenvalue_magnitudes', 'predictions',
                       'reconstruction_rmse']

    def test_required_fields_present(self, json_results):
        for field in self.REQUIRED_FIELDS:
            assert field in json_results, f"Missing JSON field: '{field}'"

    def test_optimal_rank_is_int(self, json_results):
        assert isinstance(json_results['optimal_rank'], int)

    def test_eigenvalues_is_list(self, json_results):
        assert isinstance(json_results['eigenvalues'], list)

    def test_eigenvalue_magnitudes_is_list(self, json_results):
        assert isinstance(json_results['eigenvalue_magnitudes'], list)

    def test_predictions_is_nested_list(self, json_results):
        preds = json_results['predictions']
        assert isinstance(preds, list) and len(preds) > 0
        assert isinstance(preds[0], list)


# ── HDF5 output structure tests ────────────────────────────────────────

class TestHDF5Structure:
    """Verify that the HDF5 output has the group hierarchy
    specified in the XML output_spec.xml."""

    def test_rank_group_exists(self, hdf5_results):
        assert 'analysis/rank' in hdf5_results, \
            "HDF5 missing group /analysis/rank"

    def test_rank_dataset(self, hdf5_results):
        grp = hdf5_results['analysis/rank']
        assert 'optimal_rank' in grp, \
            "HDF5 /analysis/rank missing 'optimal_rank' dataset"

    def test_spectral_group_exists(self, hdf5_results):
        assert 'analysis/spectral' in hdf5_results, \
            "HDF5 missing group /analysis/spectral"

    def test_spectral_eigenvalues(self, hdf5_results):
        grp = hdf5_results['analysis/spectral']
        assert 'eigenvalues' in grp, \
            "HDF5 /analysis/spectral missing 'eigenvalues'"

    def test_spectral_magnitudes(self, hdf5_results):
        grp = hdf5_results['analysis/spectral']
        assert 'eigenvalue_magnitudes' in grp, \
            "HDF5 /analysis/spectral missing 'eigenvalue_magnitudes'"

    def test_forecasting_group_exists(self, hdf5_results):
        assert 'analysis/forecasting' in hdf5_results, \
            "HDF5 missing group /analysis/forecasting"

    def test_forecasting_predictions(self, hdf5_results):
        grp = hdf5_results['analysis/forecasting']
        assert 'predictions' in grp, \
            "HDF5 /analysis/forecasting missing 'predictions'"

    def test_quality_group_exists(self, hdf5_results):
        assert 'analysis/quality' in hdf5_results, \
            "HDF5 missing group /analysis/quality"

    def test_quality_rmse(self, hdf5_results):
        grp = hdf5_results['analysis/quality']
        assert 'reconstruction_rmse' in grp, \
            "HDF5 /analysis/quality missing 'reconstruction_rmse'"


# ── rank tests ──────────────────────────────────────────────────────────

class TestOptimalRank:
    def test_json_rank(self, json_results, true_system):
        assert json_results['optimal_rank'] == true_system['r_true'], (
            f"JSON optimal_rank: expected {true_system['r_true']}, "
            f"got {json_results['optimal_rank']}"
        )

    def test_hdf5_rank(self, hdf5_results, true_system):
        val = int(hdf5_results['analysis/rank/optimal_rank'][()])
        assert val == true_system['r_true'], (
            f"HDF5 optimal_rank: expected {true_system['r_true']}, got {val}"
        )

    def test_json_hdf5_rank_consistent(self, json_results, hdf5_results):
        j = json_results['optimal_rank']
        h = int(hdf5_results['analysis/rank/optimal_rank'][()])
        assert j == h, f"Rank mismatch: JSON={j}, HDF5={h}"


# ── eigenvalue tests ────────────────────────────────────────────────────

class TestEigenvalues:
    def test_eigenvalue_count(self, json_results, true_system):
        eigs = json_results['eigenvalues']
        assert len(eigs) == true_system['r_true'], (
            f"Expected {true_system['r_true']} eigenvalues, got {len(eigs)}"
        )

    def test_eigenvalue_magnitudes(self, json_results, true_system):
        eigs = parse_eigenvalues(json_results['eigenvalues'])
        computed_mags = sorted(np.abs(eigs), reverse=True)
        true_mags = true_system['true_eig_magnitudes']
        for i, (comp, true) in enumerate(zip(computed_mags, true_mags)):
            assert abs(comp - true) < 0.03, (
                f"Eigenvalue magnitude {i}: expected {true:.4f}, got {comp:.4f}"
            )

    def test_complex_conjugate_pair(self, json_results):
        eigs = parse_eigenvalues(json_results['eigenvalues'])
        complex_eigs = [e for e in eigs if abs(e.imag) > 0.01]
        assert len(complex_eigs) == 2, (
            f"Expected 2 complex eigenvalues, got {len(complex_eigs)}"
        )
        e1, e2 = complex_eigs
        assert abs(e1.real - e2.real) < 0.03
        assert abs(e1.imag + e2.imag) < 0.03

    def test_magnitude_list(self, json_results, true_system):
        mags = json_results['eigenvalue_magnitudes']
        assert len(mags) == true_system['r_true']
        true_mags = true_system['true_eig_magnitudes']
        for i, (comp, true) in enumerate(zip(sorted(mags, reverse=True),
                                              true_mags)):
            assert abs(comp - true) < 0.03, (
                f"Magnitude {i}: expected {true:.4f}, got {comp:.4f}"
            )

    def test_hdf5_eigenvalue_magnitudes(self, hdf5_results, true_system):
        mags = np.array(hdf5_results['analysis/spectral/eigenvalue_magnitudes'])
        true_mags = true_system['true_eig_magnitudes']
        computed_sorted = sorted(mags, reverse=True)
        for i, (comp, true) in enumerate(zip(computed_sorted, true_mags)):
            assert abs(comp - true) < 0.03


# ── prediction tests ───────────────────────────────────────────────────

class TestPredictions:
    def test_prediction_shape(self, json_results, true_system):
        preds = np.array(json_results['predictions'])
        expected = (true_system['n_pred'], true_system['n'])
        assert preds.shape == expected, (
            f"Expected shape {expected}, got {preds.shape}"
        )

    def test_prediction_rmse(self, json_results, true_system):
        preds = np.array(json_results['predictions'], dtype=float)
        X_future = true_system['X_future'].T
        rmse = np.sqrt(np.mean((preds - X_future) ** 2))
        assert rmse < 0.05, f"Prediction RMSE too high: {rmse:.6f}"

    def test_first_step(self, json_results, true_system):
        preds = np.array(json_results['predictions'], dtype=float)
        X_future = true_system['X_future'].T
        max_err = np.max(np.abs(preds[0] - X_future[0]))
        assert max_err < 0.03, f"First step max error: {max_err:.6f}"

    def test_last_step(self, json_results, true_system):
        preds = np.array(json_results['predictions'], dtype=float)
        X_future = true_system['X_future'].T
        max_err = np.max(np.abs(preds[-1] - X_future[-1]))
        assert max_err < 0.1, f"Last step max error: {max_err:.6f}"

    def test_hdf5_prediction_shape(self, hdf5_results, true_system):
        preds = np.array(hdf5_results['analysis/forecasting/predictions'])
        expected = (true_system['n_pred'], true_system['n'])
        assert preds.shape == expected

    def test_hdf5_prediction_rmse(self, hdf5_results, true_system):
        preds = np.array(hdf5_results['analysis/forecasting/predictions'])
        X_future = true_system['X_future'].T
        rmse = np.sqrt(np.mean((preds - X_future) ** 2))
        assert rmse < 0.05


# ── reconstruction tests ───────────────────────────────────────────────

class TestReconstruction:
    def test_json_rmse_plausible(self, json_results):
        rmse = json_results['reconstruction_rmse']
        assert rmse < 0.02, f"Reconstruction RMSE too high: {rmse:.6f}"
        assert rmse > 0.001, f"Reconstruction RMSE suspiciously low: {rmse:.6f}"

    def test_hdf5_rmse_plausible(self, hdf5_results):
        rmse = float(hdf5_results['analysis/quality/reconstruction_rmse'][()])
        assert rmse < 0.02
        assert rmse > 0.001

    def test_json_hdf5_rmse_consistent(self, json_results, hdf5_results):
        j = json_results['reconstruction_rmse']
        h = float(hdf5_results['analysis/quality/reconstruction_rmse'][()])
        assert abs(j - h) < 1e-10, f"RMSE mismatch: JSON={j}, HDF5={h}"


# ── cross-format consistency tests ─────────────────────────────────────

class TestCrossFormatConsistency:
    def test_predictions_match(self, json_results, hdf5_results):
        j = np.array(json_results['predictions'], dtype=float)
        h = np.array(hdf5_results['analysis/forecasting/predictions'])
        assert np.allclose(j, h, atol=1e-10), \
            "JSON and HDF5 predictions differ"

    def test_magnitudes_match(self, json_results, hdf5_results):
        j = sorted(json_results['eigenvalue_magnitudes'], reverse=True)
        h = sorted(
            np.array(hdf5_results['analysis/spectral/eigenvalue_magnitudes']),
            reverse=True
        )
        for jv, hv in zip(j, h):
            assert abs(jv - hv) < 1e-10
