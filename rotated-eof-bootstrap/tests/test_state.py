
"""Tests for corrected EOF analysis results."""

import pytest
import numpy as np
import json
import xarray as xr
import os

RESULTS_PATH = '/app/results/eof_results.json'
DATA_PATH = '/app/data/sst_anomaly.nc'


@pytest.fixture
def results():
    assert os.path.exists(RESULTS_PATH), f"Results file not found: {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        return json.load(f)


@pytest.fixture
def reference_eigenvalues():
    """Independently compute reference eigenvalue ratios."""
    ds = xr.open_dataset(DATA_PATH)
    sst = ds['sst_anomaly'].values
    lat = ds['lat'].values
    ntime, nlat, nlon = sst.shape

    ocean_mask = ~np.isnan(sst[0])
    X = sst[:, ocean_mask]
    X = X - X.mean(axis=0)

    lat_grid = np.broadcast_to(lat[:, None], (nlat, nlon))
    lat_ocean = lat_grid[ocean_mask]
    weights = np.sqrt(np.clip(np.cos(np.deg2rad(lat_ocean)), 0, 1))
    X = X * weights[None, :]

    _, s, _ = np.linalg.svd(X, full_matrices=False)
    eigenvalues = s[:10] ** 2 / (ntime - 1)
    total_var = float(np.sum(np.var(X, axis=0, ddof=1)))

    return eigenvalues / total_var


class TestOutputStructure:
    def test_required_fields_exist(self, results):
        required = [
            'n_modes_computed', 'explained_variance_ratios', 'cumulative_variance',
            'n_modes_rotated', 'rotation_matrix', 'rotated_explained_variance_ratios',
            'n_significant_modes', 'bootstrap_eigenvalue_ci'
        ]
        for field in required:
            assert field in results, f"Missing required field: {field}"

    def test_field_types(self, results):
        assert isinstance(results['n_modes_computed'], int)
        assert isinstance(results['explained_variance_ratios'], list)
        assert isinstance(results['cumulative_variance'], list)
        assert isinstance(results['n_modes_rotated'], int)
        assert isinstance(results['rotation_matrix'], list)
        assert isinstance(results['rotated_explained_variance_ratios'], list)
        assert isinstance(results['n_significant_modes'], int)
        assert isinstance(results['bootstrap_eigenvalue_ci'], list)

    def test_dimensions(self, results):
        n = results['n_modes_computed']
        nr = results['n_modes_rotated']
        assert n == 10, f"Expected 10 modes, got {n}"
        assert nr == 5, f"Expected 5 rotated modes, got {nr}"
        assert len(results['explained_variance_ratios']) == n
        assert len(results['cumulative_variance']) == n
        assert len(results['rotation_matrix']) == nr
        assert all(len(row) == nr for row in results['rotation_matrix'])
        assert len(results['rotated_explained_variance_ratios']) == nr
        assert len(results['bootstrap_eigenvalue_ci']) == n
        assert all(len(ci) == 2 for ci in results['bootstrap_eigenvalue_ci'])


class TestEigenvalues:
    def test_eigenvalues_match_reference(self, results, reference_eigenvalues):
        """Eigenvalue ratios must match independently computed reference."""
        agent_ratios = np.array(results['explained_variance_ratios'])
        np.testing.assert_allclose(
            agent_ratios, reference_eigenvalues, rtol=1e-4,
            err_msg="Eigenvalue ratios don't match reference computation."
        )

    def test_eigenvalues_descending(self, results):
        ratios = results['explained_variance_ratios']
        for i in range(len(ratios) - 1):
            assert ratios[i] >= ratios[i + 1] - 1e-10, \
                f"Eigenvalues not in descending order at index {i}: {ratios[i]} < {ratios[i+1]}"

    def test_eigenvalues_nonnegative(self, results):
        for i, r in enumerate(results['explained_variance_ratios']):
            assert r >= -1e-10, f"Negative eigenvalue ratio at mode {i}: {r}"

    def test_eigenvalues_sum_leq_one(self, results):
        total = sum(results['explained_variance_ratios'])
        assert total <= 1.0 + 1e-6, f"Sum of variance ratios {total} exceeds 1.0"

    def test_cumulative_variance_consistent(self, results):
        ratios = np.array(results['explained_variance_ratios'])
        expected = np.cumsum(ratios)
        actual = np.array(results['cumulative_variance'])
        np.testing.assert_allclose(actual, expected, rtol=1e-6)

    def test_first_three_modes_dominant(self, results):
        """Dataset has 3 embedded signals; first 3 modes should explain substantial variance."""
        ratios = results['explained_variance_ratios']
        top3 = sum(ratios[:3])
        assert top3 > 0.15, \
            f"First 3 modes explain only {top3:.4f} of variance; expected >0.15"

    def test_clear_gap_after_third_mode(self, results):
        """There should be a clear eigenvalue gap between mode 3 and mode 4."""
        ratios = results['explained_variance_ratios']
        assert ratios[2] > ratios[3] * 1.3, \
            f"No clear gap: mode3={ratios[2]:.6f}, mode4={ratios[3]:.6f}"


class TestVarimaxRotation:
    def test_rotation_matrix_orthogonal(self, results):
        R = np.array(results['rotation_matrix'])
        RtR = R.T @ R
        np.testing.assert_allclose(
            RtR, np.eye(R.shape[1]), atol=1e-6,
            err_msg="Rotation matrix is not orthogonal (R^T R != I)"
        )

    def test_rotation_matrix_det_pm_one(self, results):
        R = np.array(results['rotation_matrix'])
        det = np.linalg.det(R)
        assert abs(abs(det) - 1.0) < 1e-6, \
            f"Rotation matrix determinant {det} is not +/-1"

    def test_variance_preserved_under_rotation(self, results):
        n_rot = results['n_modes_rotated']
        unrotated_sum = sum(results['explained_variance_ratios'][:n_rot])
        rotated_sum = sum(results['rotated_explained_variance_ratios'])
        np.testing.assert_allclose(
            rotated_sum, unrotated_sum, rtol=1e-4,
            err_msg=f"Variance not preserved: unrotated sum={unrotated_sum:.6f}, "
                     f"rotated sum={rotated_sum:.6f}"
        )

    def test_rotated_variance_nonnegative(self, results):
        for i, r in enumerate(results['rotated_explained_variance_ratios']):
            assert r >= -1e-10, f"Negative rotated variance ratio at mode {i}: {r}"

    def test_rotated_variance_sorted_descending(self, results):
        ratios = results['rotated_explained_variance_ratios']
        for i in range(len(ratios) - 1):
            assert ratios[i] >= ratios[i + 1] - 1e-10, \
                f"Rotated ratios not descending at index {i}"


class TestBootstrapSignificance:
    def test_n_significant_modes(self, results):
        """With 3 embedded signals well above noise, exactly 3 modes should be significant."""
        assert results['n_significant_modes'] == 3, \
            f"Expected 3 significant modes, got {results['n_significant_modes']}"

    def test_ci_lower_leq_upper(self, results):
        for k, ci in enumerate(results['bootstrap_eigenvalue_ci']):
            assert ci[0] <= ci[1] + 1e-10, \
                f"Mode {k}: CI lower ({ci[0]}) > upper ({ci[1]})"

    def test_ci_positive(self, results):
        for k, ci in enumerate(results['bootstrap_eigenvalue_ci']):
            assert ci[0] > 0, f"Mode {k}: lower CI bound is non-positive ({ci[0]})"
            assert ci[1] > 0, f"Mode {k}: upper CI bound is non-positive ({ci[1]})"

    def test_ci_first_mode_largest(self, results):
        cis = results['bootstrap_eigenvalue_ci']
        for k in range(1, len(cis)):
            assert cis[0][1] > cis[k][0], \
                f"Mode 0 upper CI ({cis[0][1]}) not larger than mode {k} lower CI ({cis[k][0]})"

    def test_ci_monotonically_decreasing_midpoints(self, results):
        """CI midpoints should roughly decrease with mode number."""
        cis = results['bootstrap_eigenvalue_ci']
        midpoints = [(ci[0] + ci[1]) / 2 for ci in cis]
        for i in range(len(midpoints) - 1):
            assert midpoints[i] >= midpoints[i + 1] - midpoints[i] * 0.1, \
                f"CI midpoints not roughly decreasing: mode {i}={midpoints[i]:.4f}, " \
                f"mode {i+1}={midpoints[i+1]:.4f}"

    def test_significant_modes_separated(self, results):
        """For each significant mode, verify the CI non-overlap condition."""
        n_sig = results['n_significant_modes']
        cis = results['bootstrap_eigenvalue_ci']
        for k in range(n_sig):
            ci_lower_k = cis[k][0]
            ci_upper_next = cis[k + 1][1]
            assert ci_lower_k > ci_upper_next, \
                f"Significant mode {k}: ci_lower ({ci_lower_k:.4f}) <= " \
                f"ci_upper of mode {k+1} ({ci_upper_next:.4f})"
