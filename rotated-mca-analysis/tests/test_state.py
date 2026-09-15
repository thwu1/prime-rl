"""Tests for MCA significance testing pipeline.

"""
import json
import numpy as np
import pytest
import xarray as xr


# ---------------------------------------------------------------------------
# Reference helpers — independent reimplementation for verification
# ---------------------------------------------------------------------------

def _preprocess(path):
    """Reference preprocessing: center, sqrt(coslat)-weight, flatten, drop NaN."""
    ds = xr.open_dataset(path, engine='scipy')
    data = ds['data'].values
    lat = ds['lat'].values
    ds.close()
    nt, nlat, nlon = data.shape
    w = np.sqrt(np.cos(np.radians(lat)))[:, None] * np.ones((1, nlon))
    d = (data - np.nanmean(data, axis=0)) * w[None, :, :]
    d2 = d.reshape(nt, -1)
    mask = ~np.any(np.isnan(d2), axis=0)
    return d2[:, mask], int(mask.sum())


def _varimax(A, maxiter=1000, tol=1e-8):
    """Reference Varimax via pairwise Jacobi rotations (Kaiser 1958)."""
    p, k = A.shape
    R = np.eye(k)
    L = A.copy()
    for _ in range(maxiter):
        oL = L.copy()
        for i in range(k - 1):
            for j in range(i + 1, k):
                u = L[:, i] ** 2 - L[:, j] ** 2
                v = 2 * L[:, i] * L[:, j]
                a, b = u.sum(), v.sum()
                c, d = (u ** 2 - v ** 2).sum(), (2 * u * v).sum()
                th = 0.25 * np.arctan2(d - 2 * a * b / p,
                                       c - (a * a - b * b) / p)
                ct, st = np.cos(th), np.sin(th)
                li, lj = L[:, i].copy(), L[:, j].copy()
                L[:, i] = ct * li + st * lj
                L[:, j] = -st * li + ct * lj
                ri, rj = R[:, i].copy(), R[:, j].copy()
                R[:, i] = ct * ri + st * rj
                R[:, j] = -st * ri + ct * rj
        if np.max(np.abs(L - oL)) < tol:
            break
    return L, R


def _permutation_test(X, Y, observed_sv, n_perm=500, seed=2024, n_modes=6):
    """Reference Monte Carlo permutation test using squared singular values."""
    rng = np.random.default_rng(seed)
    nt = X.shape[0]
    observed_sq = observed_sv[:n_modes] ** 2
    null_sq = np.zeros((n_perm, n_modes))
    for i in range(n_perm):
        perm_idx = rng.permutation(nt)
        Y_perm = Y[perm_idx, :]
        C_perm = X.T @ Y_perm / (nt - 1)
        _, s_perm, _ = np.linalg.svd(C_perm, full_matrices=False)
        null_sq[i, :] = s_perm[:n_modes] ** 2
    p_values = np.zeros(n_modes)
    for k in range(n_modes):
        count = np.sum(null_sq[:, k] >= observed_sq[k])
        p_values[k] = (count + 1) / (n_perm + 1)
    return p_values


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def results():
    with open('/app/results.json') as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def ref():
    """Independently compute all reference values from raw data."""
    X, nfx = _preprocess('/app/data/field_x.nc')
    Y, nfy = _preprocess('/app/data/field_y.nc')
    nt = X.shape[0]

    # Cross-covariance SVD
    C = X.T @ Y / (nt - 1)
    U, S, Vt = np.linalg.svd(C, full_matrices=False)
    U6, S6, V6 = U[:, :6], S[:6], Vt[:6, :].T
    frob2 = np.sum(S ** 2)
    scf = S6 ** 2 / frob2

    # Varimax rotation of concatenated loadings
    sqS = np.sqrt(S6)
    L = np.vstack([U6 * sqS, V6 * sqS])
    Lr, R = _varimax(L)
    Ar, Br = Lr[:nfx, :], Lr[nfx:, :]
    rv = np.sum(Lr ** 2, axis=0)
    rvf = rv / rv.sum()
    si = np.argsort(-rv)

    # Cross-correlations of expansion coefficients
    Ar_s, Br_s = Ar[:, si], Br[:, si]
    an = np.linalg.norm(Ar_s, axis=0)
    bn = np.linalg.norm(Br_s, axis=0)
    sx = X @ (Ar_s / an)
    sy = Y @ (Br_s / bn)
    cc = [float(np.corrcoef(sx[:, i], sy[:, i])[0, 1]) for i in range(6)]

    # Permutation significance test (uses squared singular values, not SCF)
    p_values = _permutation_test(X, Y, S, n_perm=500, seed=2024, n_modes=6)
    significant = [bool(p < 0.05) for p in p_values]
    n_sig = sum(significant)

    return dict(nt=nt, nfx=nfx, nfy=nfy, sv=S6, scf=scf,
                rvf=rvf[si], cc=cc, p_values=p_values,
                significant=significant, n_sig=n_sig)


# ---------------------------------------------------------------------------
# Structure tests — verify all required fields and dimensions
# ---------------------------------------------------------------------------

class TestStructure:
    def test_file_loads(self, results):
        assert results is not None

    def test_all_required_keys(self, results):
        required = ('n_samples', 'n_features_x', 'n_features_y',
                     'singular_values', 'scf', 'rotation_matrix',
                     'rotated_variance_fraction', 'cross_correlations',
                     'permutation_p_values', 'n_significant_modes',
                     'significant_modes')
        for k in required:
            assert k in results, f"Missing required key: {k}"

    def test_sv_length(self, results):
        assert len(results['singular_values']) == 6

    def test_scf_length(self, results):
        assert len(results['scf']) == 6

    def test_rotation_shape(self, results):
        R = results['rotation_matrix']
        assert len(R) == 6 and all(len(row) == 6 for row in R)

    def test_rvf_length(self, results):
        assert len(results['rotated_variance_fraction']) == 6

    def test_cc_length(self, results):
        assert len(results['cross_correlations']) == 6

    def test_p_values_length(self, results):
        assert len(results['permutation_p_values']) == 6

    def test_significant_modes_length(self, results):
        assert len(results['significant_modes']) == 6

    def test_significant_modes_are_booleans(self, results):
        for v in results['significant_modes']:
            assert isinstance(v, bool), f"significant_modes entries must be booleans, got {type(v)}"


# ---------------------------------------------------------------------------
# Decomposition tests — preprocessing and SVD correctness
# ---------------------------------------------------------------------------

class TestDecomposition:
    def test_n_samples(self, results, ref):
        assert results['n_samples'] == ref['nt']

    def test_n_features_x(self, results, ref):
        assert results['n_features_x'] == ref['nfx']

    def test_n_features_y(self, results, ref):
        assert results['n_features_y'] == ref['nfy']

    def test_singular_values(self, results, ref):
        np.testing.assert_allclose(
            results['singular_values'], ref['sv'], rtol=1e-4,
            err_msg="Singular values do not match reference")

    def test_singular_values_descending(self, results):
        sv = results['singular_values']
        for i in range(len(sv) - 1):
            assert sv[i] >= sv[i + 1] - 1e-12

    def test_scf_values(self, results, ref):
        np.testing.assert_allclose(
            results['scf'], ref['scf'], rtol=1e-4,
            err_msg="Squared covariance fractions do not match reference")

    def test_scf_positive(self, results):
        assert all(s > 0 for s in results['scf'])

    def test_scf_sum_bounded(self, results):
        assert sum(results['scf']) <= 1.0 + 1e-9, \
            "Sum of 6 SCF values must not exceed 1.0"


# ---------------------------------------------------------------------------
# Rotation tests — Varimax correctness and properties
# ---------------------------------------------------------------------------

class TestRotation:
    def test_orthogonal(self, results):
        R = np.array(results['rotation_matrix'])
        np.testing.assert_allclose(
            R.T @ R, np.eye(6), atol=1e-5,
            err_msg="Rotation matrix is not orthogonal")

    def test_det_positive(self, results):
        R = np.array(results['rotation_matrix'])
        assert np.linalg.det(R) > 0, "Rotation matrix should have positive determinant"

    def test_rvf_sum_to_one(self, results):
        rvf = np.array(results['rotated_variance_fraction'])
        np.testing.assert_allclose(
            rvf.sum(), 1.0, atol=1e-5,
            err_msg="Rotated variance fractions must sum to 1")

    def test_rvf_positive(self, results):
        assert all(v > 0 for v in results['rotated_variance_fraction'])

    def test_rvf_descending(self, results):
        rvf = results['rotated_variance_fraction']
        for i in range(len(rvf) - 1):
            assert rvf[i] >= rvf[i + 1] - 1e-9, \
                f"Rotated variance fractions must be in descending order"

    def test_rvf_values(self, results, ref):
        rvf = np.sort(results['rotated_variance_fraction'])[::-1]
        ref_rvf = np.sort(ref['rvf'])[::-1]
        np.testing.assert_allclose(
            rvf, ref_rvf, atol=2e-3,
            err_msg="Rotated variance fractions do not match reference")

    def test_varimax_applied(self, results):
        """Rotation matrix should differ substantially from identity."""
        R = np.array(results['rotation_matrix'])
        assert np.max(np.abs(R - np.eye(6))) > 0.01, \
            "Rotation matrix too close to identity — rotation not applied"


# ---------------------------------------------------------------------------
# Cross-correlation tests
# ---------------------------------------------------------------------------

class TestCrossCorrelations:
    def test_range(self, results):
        for c in results['cross_correlations']:
            assert -1.0 - 1e-9 <= c <= 1.0 + 1e-9

    def test_values(self, results, ref):
        cc = np.sort(np.abs(results['cross_correlations']))[::-1]
        ref_cc = np.sort(np.abs(ref['cc']))[::-1]
        np.testing.assert_allclose(
            cc, ref_cc, atol=0.03,
            err_msg="Cross-correlation magnitudes do not match reference")


# ---------------------------------------------------------------------------
# Significance tests — permutation test correctness
# ---------------------------------------------------------------------------

class TestSignificance:
    def test_p_values_in_valid_range(self, results):
        for p in results['permutation_p_values']:
            assert 0.0 < p <= 1.0, f"p-value {p} out of valid range (0, 1]"

    def test_p_values_resolution(self, results):
        """p-values from 501-denominator test must be multiples of 1/501."""
        for p in results['permutation_p_values']:
            remainder = (p * 501) % 1.0
            assert remainder < 0.01 or remainder > 0.99, \
                f"p-value {p} is not consistent with 500-permutation test"

    def test_p_values_accuracy(self, results, ref):
        np.testing.assert_allclose(
            results['permutation_p_values'], ref['p_values'], atol=0.015,
            err_msg="Permutation p-values do not match reference")

    def test_n_significant_modes(self, results, ref):
        assert results['n_significant_modes'] == ref['n_sig'], \
            f"Expected {ref['n_sig']} significant modes, got {results['n_significant_modes']}"

    def test_significant_modes_consistency(self, results):
        """significant_modes must be consistent with p_values and n_significant."""
        p_vals = results['permutation_p_values']
        sig = results['significant_modes']
        for k in range(6):
            expected = p_vals[k] < 0.05
            assert sig[k] == expected, \
                f"Mode {k}: p={p_vals[k]}, significant_modes={sig[k]}, expected {expected}"

    def test_significant_modes_match_ref(self, results, ref):
        assert results['significant_modes'] == ref['significant'], \
            f"Significance determinations do not match reference"

    def test_leading_modes_significant(self, results):
        """Leading 2 modes should be significant given strong planted signal."""
        p_vals = results['permutation_p_values']
        assert p_vals[0] < 0.05, "Leading mode should be significant"
        assert p_vals[1] < 0.05, "Second mode should be significant"

    def test_trailing_modes_not_significant(self, results):
        """Last 2 modes should not be significant (noise only)."""
        p_vals = results['permutation_p_values']
        assert p_vals[-1] >= 0.05, "Last mode should not be significant"
        assert p_vals[-2] >= 0.05, "5th mode should not be significant"
