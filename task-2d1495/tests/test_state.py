
import numpy as np
import h5py
import json
import os
import pytest

RESULTS_PATH = "/app/results.json"

# Ground truth specs: (rows, cols, dtype, format)
MATRIX_SPECS = {
    'mat_alpha':   (500, 200, 'float64', 'hdf5'),
    'mat_beta':    (300, 300, 'float64', 'hdf5'),
    'mat_gamma':   (400, 150, 'float32', 'raw'),
    'mat_delta':   (250, 250, 'float64', 'raw'),
    'mat_epsilon': (200, 400, 'float64', 'raw'),
}

TOLERANCE = 0.01
BUDGET = 60


@pytest.fixture(scope="module")
def ground_truth():
    """Compute all reference answers from the raw data files."""
    data_dir = '/app/pipeline/data'

    matrices = {}
    svds = {}
    for name, (rows, cols, dtype, fmt) in MATRIX_SPECS.items():
        if fmt == 'hdf5':
            with h5py.File(
                os.path.join(data_dir, '{}.h5'.format(name)), 'r'
            ) as f:
                A = f['matrix'][:].astype(np.float64)
        else:
            data = np.fromfile(
                os.path.join(data_dir, '{}.dat'.format(name)),
                dtype=np.dtype(dtype)
            )
            A = data.reshape(rows, cols).astype(np.float64)
        matrices[name] = A
        U, s, Vt = np.linalg.svd(A, full_matrices=False)
        svds[name] = (U, s, Vt)

    # Optimal rank allocation: pool all SVs, sort descending, take top BUDGET
    pool = []
    for name in sorted(MATRIX_SPECS.keys()):
        _, s, _ = svds[name]
        for j in range(len(s)):
            pool.append((float(s[j]), name))
    pool.sort(key=lambda x: -x[0])

    allocation = {name: 0 for name in MATRIX_SPECS}
    for _, name in pool[:BUDGET]:
        allocation[name] += 1

    # Per-matrix reference values
    ref = {}
    total_sq_err = 0.0
    for name in sorted(MATRIX_SPECS.keys()):
        rows, cols, dtype, fmt = MATRIX_SPECS[name]
        A = matrices[name]
        U, s, Vt = svds[name]
        fnorm = float(np.linalg.norm(A, 'fro'))
        nrank = int(np.sum(s > TOLERANCE * s[0]))
        arank = allocation[name]

        # SVD approximation error at allocated rank
        if arank >= len(s):
            svd_abs = 0.0
        else:
            svd_abs = float(np.sqrt(np.sum(s[arank:] ** 2)))
        svd_rel = svd_abs / fnorm
        total_sq_err += svd_abs ** 2

        # CUR skeleton approximation error at allocated rank
        r = min(arank, len(s))
        if r == 0:
            cur_abs = fnorm
        else:
            V_r = Vt[:r, :].T  # (n, r)
            col_lev = np.sum(V_r ** 2, axis=1)
            U_r = U[:, :r]  # (m, r)
            row_lev = np.sum(U_r ** 2, axis=1)

            J = np.sort(np.argsort(col_lev)[::-1][:r])
            I = np.sort(np.argsort(row_lev)[::-1][:r])

            C = A[:, J]
            R = A[I, :]
            W = A[np.ix_(I, J)]
            CUR = C @ np.linalg.pinv(W) @ R
            cur_abs = float(np.linalg.norm(A - CUR, 'fro'))
        cur_rel = cur_abs / fnorm

        ref[name] = {
            'shape': [rows, cols],
            'dtype': dtype,
            'frobenius_norm': fnorm,
            'numerical_rank': nrank,
            'allocated_rank': arank,
            'svd_relative_error': svd_rel,
            'cur_relative_error': cur_rel,
            'top_5_singular_values': s[:min(5, len(s))].tolist(),
        }

    ref['_allocation'] = {
        'budget': BUDGET,
        'total_allocated': sum(allocation.values()),
        'total_squared_svd_error': total_sq_err,
    }

    return ref


@pytest.fixture(scope="module")
def results():
    """Load the agent's results."""
    assert os.path.exists(RESULTS_PATH), \
        "Results file not found at {}".format(RESULTS_PATH)
    with open(RESULTS_PATH) as f:
        return json.load(f)


MATRIX_NAMES = sorted(MATRIX_SPECS.keys())


class TestMatrixDiscovery:
    """Verify all matrices were found and loaded correctly."""

    def test_all_matrices_present(self, results):
        assert "matrices" in results, "results.json must contain 'matrices' key"
        for name in MATRIX_NAMES:
            assert name in results["matrices"], "Missing matrix: {}".format(name)

    def test_no_phantom_matrices(self, results):
        """mat_zeta should NOT appear in results (no backing file)."""
        assert "mat_zeta" not in results.get("matrices", {}), \
            "mat_zeta should not be in results — its data file does not exist"

    @pytest.mark.parametrize("name", MATRIX_NAMES)
    def test_shape(self, name, results, ground_truth):
        expected = ground_truth[name]['shape']
        actual = results["matrices"][name]["shape"]
        assert actual == expected, \
            "{}: expected shape {}, got {}".format(name, expected, actual)

    @pytest.mark.parametrize("name", MATRIX_NAMES)
    def test_dtype(self, name, results, ground_truth):
        expected = ground_truth[name]['dtype']
        actual = results["matrices"][name]["dtype"]
        assert actual == expected, \
            "{}: expected dtype {}, got {}".format(name, expected, actual)


class TestSpectralProperties:
    """Verify spectral analysis results."""

    @pytest.mark.parametrize("name", MATRIX_NAMES)
    def test_frobenius_norm(self, name, results, ground_truth):
        expected = ground_truth[name]['frobenius_norm']
        actual = results["matrices"][name]["frobenius_norm"]
        assert abs(actual - expected) / expected < 1e-6, \
            "{}: frobenius_norm expected {}, got {}".format(name, expected, actual)

    @pytest.mark.parametrize("name", MATRIX_NAMES)
    def test_numerical_rank(self, name, results, ground_truth):
        expected = ground_truth[name]['numerical_rank']
        actual = results["matrices"][name]["numerical_rank"]
        assert actual == expected, \
            "{}: numerical_rank expected {}, got {}".format(name, expected, actual)

    @pytest.mark.parametrize("name", MATRIX_NAMES)
    def test_top_5_singular_values(self, name, results, ground_truth):
        expected = np.array(ground_truth[name]['top_5_singular_values'])
        actual = np.array(results["matrices"][name]["top_5_singular_values"])
        np.testing.assert_allclose(actual, expected, rtol=1e-6,
            err_msg="{}: top 5 singular values mismatch".format(name))


class TestRankAllocation:
    """Verify optimal rank allocation solution."""

    def test_budget_field(self, results):
        assert results["rank_allocation"]["budget"] == BUDGET

    def test_budget_respected(self, results):
        assert results["rank_allocation"]["total_allocated"] <= BUDGET, \
            "Total allocated {} exceeds budget {}".format(
                results["rank_allocation"]["total_allocated"], BUDGET)

    def test_total_allocated(self, results, ground_truth):
        expected = ground_truth['_allocation']['total_allocated']
        actual = results["rank_allocation"]["total_allocated"]
        assert actual == expected, \
            "total_allocated: expected {}, got {}".format(expected, actual)

    @pytest.mark.parametrize("name", MATRIX_NAMES)
    def test_allocated_rank(self, name, results, ground_truth):
        expected = ground_truth[name]['allocated_rank']
        actual = results["matrices"][name]["allocated_rank"]
        assert actual == expected, \
            "{}: allocated_rank expected {}, got {}".format(name, expected, actual)

    def test_total_squared_error(self, results, ground_truth):
        expected = ground_truth['_allocation']['total_squared_svd_error']
        actual = results["rank_allocation"]["total_squared_svd_error"]
        if expected < 1e-12:
            assert actual < 1e-10
        else:
            assert abs(actual - expected) / expected < 1e-6, \
                "total_squared_svd_error: expected {}, got {}".format(
                    expected, actual)

    def test_allocation_consistency(self, results):
        """Sum of per-matrix allocated_rank must equal total_allocated."""
        total = sum(
            results["matrices"][name]["allocated_rank"]
            for name in MATRIX_NAMES
            if name in results.get("matrices", {})
        )
        assert total == results["rank_allocation"]["total_allocated"], \
            "Sum of allocated_rank ({}) != total_allocated ({})".format(
                total, results["rank_allocation"]["total_allocated"])


class TestApproximationErrors:
    """Verify SVD and CUR approximation error calculations."""

    @pytest.mark.parametrize("name", MATRIX_NAMES)
    def test_svd_relative_error(self, name, results, ground_truth):
        expected = ground_truth[name]['svd_relative_error']
        actual = results["matrices"][name]["svd_relative_error"]
        if expected < 1e-12:
            assert actual < 1e-10, \
                "{}: svd_relative_error should be near zero".format(name)
        else:
            assert abs(actual - expected) / expected < 1e-4, \
                "{}: svd_relative_error expected {}, got {}".format(
                    name, expected, actual)

    @pytest.mark.parametrize("name", MATRIX_NAMES)
    def test_cur_relative_error(self, name, results, ground_truth):
        expected = ground_truth[name]['cur_relative_error']
        actual = results["matrices"][name]["cur_relative_error"]
        if expected < 1e-12:
            assert actual < 1e-10, \
                "{}: cur_relative_error should be near zero".format(name)
        else:
            assert abs(actual - expected) / expected < 1e-2, \
                "{}: cur_relative_error expected {}, got {}".format(
                    name, expected, actual)

    @pytest.mark.parametrize("name", MATRIX_NAMES)
    def test_cur_geq_svd(self, name, results):
        """CUR error should be >= SVD error (SVD is optimal)."""
        svd_err = results["matrices"][name]["svd_relative_error"]
        cur_err = results["matrices"][name]["cur_relative_error"]
        assert cur_err >= svd_err - 1e-10, \
            "{}: CUR error ({}) should not be less than SVD error ({})".format(
                name, cur_err, svd_err)
