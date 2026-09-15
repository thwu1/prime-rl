"""Tests for the cross-field decomposition pipeline.

"""

import sys
sys.path.insert(0, '/app')

import os
import subprocess
import pytest
import numpy as np

from cross_decomp import (
    load_fields,
    fractional_matrix_power,
    whiten,
    cpcca,
    squared_covariance_fraction,
    homogeneous_patterns,
    heterogeneous_patterns,
    promax_rotation,
    bootstrap_significance,
)


@pytest.fixture
def data():
    return load_fields()


@pytest.fixture
def symmetric_psd():
    rng = np.random.RandomState(123)
    A = rng.randn(10, 10)
    return A.T @ A + 0.1 * np.eye(10)


# ============================================================
# Data loading tests
# ============================================================

class TestDataLoading:
    def test_shapes(self):
        """Loaded data should have expected shapes."""
        X, Y = load_fields()
        assert X.shape == (200, 50)
        assert Y.shape == (200, 30)

    def test_centered(self):
        """Loaded data must be centered (zero column means)."""
        X, Y = load_fields()
        np.testing.assert_allclose(X.mean(axis=0), 0.0, atol=1e-10)
        np.testing.assert_allclose(Y.mean(axis=0), 0.0, atol=1e-10)


# ============================================================
# fractional_matrix_power tests
# ============================================================

class TestFractionalMatrixPower:
    def test_identity_power(self, symmetric_psd):
        """C^0 should be the identity matrix."""
        C = symmetric_psd
        result = fractional_matrix_power(C, 0.0)
        np.testing.assert_allclose(result, np.eye(C.shape[0]), atol=1e-10)

    def test_first_power(self, symmetric_psd):
        """C^1 should equal C."""
        C = symmetric_psd
        result = fractional_matrix_power(C, 1.0)
        np.testing.assert_allclose(result, C, atol=1e-10)

    def test_sqrt_composed(self, symmetric_psd):
        """C^0.5 @ C^0.5 should equal C."""
        C = symmetric_psd
        sqrt_C = fractional_matrix_power(C, 0.5)
        np.testing.assert_allclose(sqrt_C @ sqrt_C, C, atol=1e-8)

    def test_inverse(self, symmetric_psd):
        """C^(-1) should be the matrix inverse of C."""
        C = symmetric_psd
        C_inv = fractional_matrix_power(C, -1.0)
        np.testing.assert_allclose(C @ C_inv, np.eye(C.shape[0]), atol=1e-8)

    def test_output_symmetric(self, symmetric_psd):
        """Result should be symmetric for any real alpha."""
        C = symmetric_psd
        result = fractional_matrix_power(C, 0.37)
        np.testing.assert_allclose(result, result.T, atol=1e-10)

    def test_additive_exponents(self, symmetric_psd):
        """C^a @ C^b should equal C^(a+b)."""
        C = symmetric_psd
        Ca = fractional_matrix_power(C, 0.3)
        Cb = fractional_matrix_power(C, 0.7)
        Cab = fractional_matrix_power(C, 1.0)
        np.testing.assert_allclose(Ca @ Cb, Cab, atol=1e-8)


# ============================================================
# whiten tests
# ============================================================

class TestWhiten:
    def test_no_whitening_alpha1(self, data):
        """alpha=1 should return data unchanged and W=I."""
        X, _ = data
        X_w, W = whiten(X, 1.0)
        np.testing.assert_allclose(X_w, X, atol=1e-10)
        np.testing.assert_allclose(W, np.eye(X.shape[1]), atol=1e-10)

    def test_full_whitening_identity_cov(self, data):
        """alpha=0 should produce data with identity covariance."""
        X, _ = data
        X_w, W = whiten(X, 0.0)
        n = X_w.shape[0]
        C_w = X_w.T @ X_w / (n - 1)
        np.testing.assert_allclose(C_w, np.eye(X_w.shape[1]), atol=1e-6)

    def test_partial_whitening_reduces_condition(self, data):
        """Partial whitening (alpha=0.5) should reduce the condition number."""
        X, _ = data
        n = X.shape[0]
        C_orig = X.T @ X / (n - 1)
        X_w, _ = whiten(X, 0.5)
        C_w = X_w.T @ X_w / (n - 1)
        assert np.linalg.cond(C_w) < np.linalg.cond(C_orig)

    def test_whitening_matrix_symmetric(self, data):
        """The whitening matrix W should be symmetric."""
        X, _ = data
        _, W = whiten(X, 0.3)
        np.testing.assert_allclose(W, W.T, atol=1e-10)


# ============================================================
# cpcca tests
# ============================================================

class TestCPCCA:
    def test_mca_matches_direct_svd(self, data):
        """With no whitening, singular values should match SVD of cross-covariance."""
        X, Y = data
        n = X.shape[0]
        n_modes = 5
        result = cpcca(X, Y, n_modes, alpha_x=1.0, alpha_y=1.0)

        C_xy = X.T @ Y / (n - 1)
        _, s_direct, _ = np.linalg.svd(C_xy, full_matrices=False)
        np.testing.assert_allclose(
            np.abs(result['singular_values']),
            s_direct[:n_modes],
            rtol=1e-6,
        )

    def test_cca_correlations_bounded(self, data):
        """Full whitening should produce singular values <= 1."""
        X, Y = data
        result = cpcca(X, Y, 5, alpha_x=0.0, alpha_y=0.0)
        assert np.all(result['singular_values'] <= 1.0 + 1e-10)
        assert np.all(result['singular_values'] >= -1e-10)

    def test_cca_x_scores_uncorrelated(self, data):
        """Full whitening X-scores should be mutually uncorrelated."""
        X, Y = data
        result = cpcca(X, Y, 5, alpha_x=0.0, alpha_y=0.0)
        Rx = result['Rx']
        Rx_centered = Rx - Rx.mean(axis=0)
        Rx_std = Rx_centered / Rx_centered.std(axis=0)
        corr = Rx_std.T @ Rx_std / (Rx.shape[0] - 1)
        off_diag = corr - np.diag(np.diag(corr))
        np.testing.assert_allclose(off_diag, 0.0, atol=0.05)

    def test_rda_x_scores_uncorrelated(self, data):
        """Asymmetric whitening X-scores should be uncorrelated."""
        X, Y = data
        result = cpcca(X, Y, 5, alpha_x=0.0, alpha_y=1.0)
        Rx = result['Rx']
        Rx_centered = Rx - Rx.mean(axis=0)
        Rx_std = Rx_centered / Rx_centered.std(axis=0)
        corr = Rx_std.T @ Rx_std / (Rx.shape[0] - 1)
        off_diag = corr - np.diag(np.diag(corr))
        np.testing.assert_allclose(off_diag, 0.0, atol=0.05)

    def test_singular_values_descending(self, data):
        """Singular values should be in descending order."""
        X, Y = data
        result = cpcca(X, Y, 5, alpha_x=0.5, alpha_y=0.5)
        sv = result['singular_values']
        for i in range(len(sv) - 1):
            assert sv[i] >= sv[i + 1] - 1e-10

    def test_scores_shapes(self, data):
        """Scores should have shape (n_samples, n_modes)."""
        X, Y = data
        n_modes = 4
        result = cpcca(X, Y, n_modes, alpha_x=0.5, alpha_y=0.5)
        assert result['Rx'].shape == (X.shape[0], n_modes)
        assert result['Ry'].shape == (Y.shape[0], n_modes)

    def test_components_shapes(self, data):
        """Components should have correct shapes."""
        X, Y = data
        n_modes = 4
        result = cpcca(X, Y, n_modes, alpha_x=0.5, alpha_y=0.5)
        assert result['Qx'].shape == (X.shape[1], n_modes)
        assert result['Qy'].shape == (Y.shape[1], n_modes)
        assert result['Px'].shape == (X.shape[1], n_modes)
        assert result['Py'].shape == (Y.shape[1], n_modes)

    def test_original_space_components(self, data):
        """Original-space components should equal whitening matrix times whitened components."""
        X, Y = data
        n_modes = 4
        result_full = cpcca(X, Y, n_modes, alpha_x=0.3, alpha_y=0.7)
        _, Wx = whiten(X, 0.3)
        _, Wy = whiten(Y, 0.7)
        np.testing.assert_allclose(
            result_full['Px'], Wx @ result_full['Qx'], atol=1e-8
        )
        np.testing.assert_allclose(
            result_full['Py'], Wy @ result_full['Qy'], atol=1e-8
        )

    def test_reconstruction_captures_cross_covariance(self, data):
        """Reconstruction with many modes should capture the cross-covariance."""
        X, Y = data
        n_modes = 30
        result = cpcca(X, Y, n_modes, alpha_x=1.0, alpha_y=1.0)
        n = X.shape[0]
        Xrec = result['Rx'] @ result['Qx'].T
        C_xy_rec = Xrec.T @ Y / (n - 1)
        C_xy = X.T @ Y / (n - 1)
        ratio = np.linalg.norm(C_xy_rec) / np.linalg.norm(C_xy)
        assert ratio > 0.99


# ============================================================
# squared_covariance_fraction tests
# ============================================================

class TestSCF:
    def test_sums_to_one(self, data):
        """SCF should sum to 1 when all modes are included."""
        X, Y = data
        n_modes = min(X.shape[1], Y.shape[1])
        result = cpcca(X, Y, n_modes, alpha_x=1.0, alpha_y=1.0)
        scf = squared_covariance_fraction(result['singular_values'])
        np.testing.assert_allclose(scf.sum(), 1.0, atol=1e-10)

    def test_nonnegative(self, data):
        """SCF values should be non-negative."""
        X, Y = data
        result = cpcca(X, Y, 5, alpha_x=1.0, alpha_y=1.0)
        scf = squared_covariance_fraction(result['singular_values'])
        assert np.all(scf >= -1e-15)

    def test_decreasing(self, data):
        """SCF values should be in decreasing order."""
        X, Y = data
        result = cpcca(X, Y, 5, alpha_x=1.0, alpha_y=1.0)
        scf = squared_covariance_fraction(result['singular_values'])
        for i in range(len(scf) - 1):
            assert scf[i] >= scf[i + 1] - 1e-10


# ============================================================
# homogeneous/heterogeneous patterns tests
# ============================================================

class TestPatterns:
    def test_homogeneous_shape(self, data):
        """Homogeneous patterns shape should be (n_features, n_modes)."""
        X, Y = data
        n_modes = 4
        result = cpcca(X, Y, n_modes, alpha_x=1.0, alpha_y=1.0)
        hp = homogeneous_patterns(X, result['Rx'])
        assert hp.shape == (X.shape[1], n_modes)

    def test_heterogeneous_shape(self, data):
        """Heterogeneous patterns shape should be (n_features, n_modes)."""
        X, Y = data
        n_modes = 4
        result = cpcca(X, Y, n_modes, alpha_x=1.0, alpha_y=1.0)
        het = heterogeneous_patterns(X, result['Ry'])
        assert het.shape == (X.shape[1], n_modes)

    def test_correlation_bounded(self, data):
        """Correlation patterns should be in [-1, 1]."""
        X, Y = data
        n_modes = 4
        result = cpcca(X, Y, n_modes, alpha_x=1.0, alpha_y=1.0)
        hp = homogeneous_patterns(X, result['Rx'])
        assert np.all(hp >= -1.0 - 1e-10)
        assert np.all(hp <= 1.0 + 1e-10)

    def test_homogeneous_matches_corrcoef(self, data):
        """Homogeneous pattern should match np.corrcoef for a single pair."""
        X, Y = data
        n_modes = 3
        result = cpcca(X, Y, n_modes, alpha_x=1.0, alpha_y=1.0)
        hp = homogeneous_patterns(X, result['Rx'])
        expected = np.corrcoef(X[:, 0], result['Rx'][:, 0])[0, 1]
        np.testing.assert_allclose(hp[0, 0], expected, atol=1e-10)

    def test_heterogeneous_matches_corrcoef(self, data):
        """Heterogeneous pattern should match np.corrcoef for a single pair."""
        X, Y = data
        n_modes = 3
        result = cpcca(X, Y, n_modes, alpha_x=1.0, alpha_y=1.0)
        het = heterogeneous_patterns(X, result['Ry'])
        expected = np.corrcoef(X[:, 0], result['Ry'][:, 0])[0, 1]
        np.testing.assert_allclose(het[0, 0], expected, atol=1e-10)


# ============================================================
# promax_rotation tests
# ============================================================

class TestPromaxRotation:
    def test_varimax_orthogonal(self, data):
        """Orthogonal rotation matrix should satisfy R^T R = I."""
        X, Y = data
        n_modes = 4
        result = cpcca(X, Y, n_modes, alpha_x=1.0, alpha_y=1.0)
        rot = promax_rotation(
            result['Qx'], result['Qy'], result['singular_values'], power=1
        )
        R = rot['rotation_matrix']
        np.testing.assert_allclose(R.T @ R, np.eye(n_modes), atol=1e-6)

    def test_subspace_preservation(self, data):
        """Rotated components should span the same column space as originals."""
        X, Y = data
        n_modes = 4
        result = cpcca(X, Y, n_modes, alpha_x=1.0, alpha_y=1.0)
        rot = promax_rotation(
            result['Qx'], result['Qy'], result['singular_values'], power=1
        )
        P_orig = result['Qx'] @ np.linalg.pinv(result['Qx'])
        P_rot = rot['Qx_rot'] @ np.linalg.pinv(rot['Qx_rot'])
        np.testing.assert_allclose(P_orig, P_rot, atol=1e-5)

    def test_varimax_preserves_total_variance(self, data):
        """Orthogonal rotation should preserve Frobenius norm of stacked loadings."""
        X, Y = data
        n_modes = 4
        result = cpcca(X, Y, n_modes, alpha_x=1.0, alpha_y=1.0)
        rot = promax_rotation(
            result['Qx'], result['Qy'], result['singular_values'], power=1
        )
        sqrt_s = np.sqrt(result['singular_values'])
        Lx_orig = result['Qx'] * sqrt_s
        Ly_orig = result['Qy'] * sqrt_s
        L_orig = np.vstack([Lx_orig, Ly_orig])
        original_total = np.sum(np.linalg.norm(L_orig, axis=0) ** 2)
        rotated_total = np.sum(rot['singular_values_rot'] ** 2)
        np.testing.assert_allclose(original_total, rotated_total, rtol=1e-6)

    def test_rotated_sv_descending(self, data):
        """Rotated singular values should be in descending order."""
        X, Y = data
        n_modes = 4
        result = cpcca(X, Y, n_modes, alpha_x=1.0, alpha_y=1.0)
        rot = promax_rotation(
            result['Qx'], result['Qy'], result['singular_values'], power=2
        )
        sv = rot['singular_values_rot']
        for i in range(len(sv) - 1):
            assert sv[i] >= sv[i + 1] - 1e-10

    def test_rotation_matrix_shape(self, data):
        """Rotation matrix should be square (k x k)."""
        X, Y = data
        n_modes = 3
        result = cpcca(X, Y, n_modes, alpha_x=1.0, alpha_y=1.0)
        rot = promax_rotation(
            result['Qx'], result['Qy'], result['singular_values'], power=2
        )
        assert rot['rotation_matrix'].shape == (n_modes, n_modes)
        assert rot['Qx_rot'].shape == result['Qx'].shape
        assert rot['Qy_rot'].shape == result['Qy'].shape


# ============================================================
# bootstrap_significance tests
# ============================================================

class TestBootstrapSignificance:
    def test_detects_strong_mode(self, data):
        """The dominant coupled mode should be detected as significant."""
        X, Y = data
        result = bootstrap_significance(
            X, Y, n_modes=3, alpha_x=1.0, alpha_y=1.0,
            n_bootstraps=50, confidence=0.95, seed=42,
        )
        assert result['significant'][0] is True or result['significant'][0] == True

    def test_pvalues_bounded(self, data):
        """p-values should be in [0, 1]."""
        X, Y = data
        result = bootstrap_significance(
            X, Y, n_modes=3, alpha_x=1.0, alpha_y=1.0,
            n_bootstraps=50, confidence=0.95, seed=42,
        )
        assert np.all(result['pvalues'] >= 0.0)
        assert np.all(result['pvalues'] <= 1.0)

    def test_pvalue_first_mode_smallest(self, data):
        """First mode should have the smallest (or tied smallest) p-value."""
        X, Y = data
        result = bootstrap_significance(
            X, Y, n_modes=3, alpha_x=1.0, alpha_y=1.0,
            n_bootstraps=100, confidence=0.95, seed=42,
        )
        assert result['pvalues'][0] <= result['pvalues'][-1] + 1e-10

    def test_null_data_not_significant(self):
        """Pure noise (uncoupled) data should produce no significant modes."""
        rng = np.random.RandomState(99)
        X_noise = rng.randn(100, 20)
        Y_noise = rng.randn(100, 15)
        X_noise -= X_noise.mean(axis=0)
        Y_noise -= Y_noise.mean(axis=0)
        result = bootstrap_significance(
            X_noise, Y_noise, n_modes=3, alpha_x=1.0, alpha_y=1.0,
            n_bootstraps=50, confidence=0.95, seed=42,
        )
        assert np.sum(result['significant']) <= 1

    def test_output_shapes(self, data):
        """Output arrays should have correct sizes."""
        X, Y = data
        n_modes = 4
        result = bootstrap_significance(
            X, Y, n_modes=n_modes, alpha_x=1.0, alpha_y=1.0,
            n_bootstraps=30, confidence=0.95, seed=42,
        )
        assert result['significant'].shape == (n_modes,)
        assert result['pvalues'].shape == (n_modes,)


# ============================================================
# Pipeline integration tests
# ============================================================

class TestPipeline:
    def test_make_all_succeeds(self):
        """make all should complete without errors."""
        subprocess.run(['make', '-C', '/app', 'clean'],
                       capture_output=True, timeout=30)
        result = subprocess.run(
            ['make', '-C', '/app', 'all'],
            capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, \
            f"make all failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"

    def test_output_at_expected_path(self):
        """Decomposition output should exist at results/decomposition.npz."""
        subprocess.run(['make', '-C', '/app', 'clean'],
                       capture_output=True, timeout=30)
        subprocess.run(['make', '-C', '/app', 'all'],
                       capture_output=True, timeout=120)
        assert os.path.exists('/app/results/decomposition.npz'), \
            "Expected output at /app/results/decomposition.npz"
