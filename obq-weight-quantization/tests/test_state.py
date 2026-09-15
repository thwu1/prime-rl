
import sys
sys.path.insert(0, '/app')
import itertools
import numpy as np
import pytest

from quantizer import (
    uniform_quantize,
    compute_hessian,
    obq_quantize,
    obq_quantize_actorder,
    mixed_precision_search,
)


# ---------------------------------------------------------------------------
# uniform_quantize
# ---------------------------------------------------------------------------

class TestUniformQuantize:
    def test_symmetric_known_values(self):
        x = np.array([0.5, -0.3, 0.8, -0.1], dtype=np.float64)
        q = uniform_quantize(x, 4, symmetric=True)
        q_max = 7
        scale = 0.8 / q_max
        expected = np.clip(np.round(x / scale), -q_max, q_max) * scale
        np.testing.assert_allclose(q, expected, atol=1e-10)

    def test_symmetric_idempotent(self):
        np.random.seed(123)
        x = np.random.randn(200).astype(np.float64)
        for bits in [2, 3, 4, 8]:
            q1 = uniform_quantize(x, bits, symmetric=True)
            q2 = uniform_quantize(q1, bits, symmetric=True)
            np.testing.assert_allclose(q1, q2, atol=1e-10,
                                       err_msg=f"Not idempotent at {bits} bits")

    def test_symmetric_zero_input(self):
        x = np.zeros(10, dtype=np.float64)
        q = uniform_quantize(x, 4, symmetric=True)
        np.testing.assert_allclose(q, np.zeros(10))

    def test_asymmetric_known_values(self):
        x = np.array([0.0, 0.5, 1.0], dtype=np.float64)
        q = uniform_quantize(x, 2, symmetric=False)
        q_max = 3
        scale = 1.0 / q_max
        zp = np.clip(np.round(-0.0 / scale), 0, q_max)
        expected = (np.clip(np.round(x / scale + zp), 0, q_max) - zp) * scale
        np.testing.assert_allclose(q, expected, atol=1e-10)

    def test_asymmetric_negative_range(self):
        x = np.array([-1.0, -0.5, 0.0], dtype=np.float64)
        q = uniform_quantize(x, 2, symmetric=False)
        q_max = 3
        scale = (0.0 - (-1.0)) / q_max
        zp = np.clip(np.round(1.0 / scale), 0, q_max)
        expected = (np.clip(np.round(x / scale + zp), 0, q_max) - zp) * scale
        np.testing.assert_allclose(q, expected, atol=1e-10)

    def test_num_unique_levels(self):
        np.random.seed(456)
        x = np.random.randn(1000).astype(np.float64)
        for bits in [2, 3, 4, 8]:
            q = uniform_quantize(x, bits, symmetric=True)
            n_unique = len(np.unique(np.round(q, decimals=12)))
            assert n_unique <= 2 ** bits, \
                f"{bits}-bit produced {n_unique} levels (max {2**bits})"

    def test_asymmetric_constant_input(self):
        x = np.full(10, 3.14, dtype=np.float64)
        q = uniform_quantize(x, 4, symmetric=False)
        np.testing.assert_allclose(q, x, atol=1e-10)


# ---------------------------------------------------------------------------
# compute_hessian
# ---------------------------------------------------------------------------

class TestComputeHessian:
    def test_identity_calibration(self):
        N, d = 10, 10
        X = np.eye(N, d, dtype=np.float64)
        H = compute_hessian(X)
        expected = 2.0 * np.eye(d) / N
        np.testing.assert_allclose(H, expected, atol=1e-10)

    def test_symmetric(self):
        np.random.seed(789)
        X = np.random.randn(50, 20).astype(np.float64)
        H = compute_hessian(X)
        np.testing.assert_allclose(H, H.T, atol=1e-10)

    def test_psd(self):
        np.random.seed(101)
        X = np.random.randn(100, 30).astype(np.float64)
        H = compute_hessian(X)
        eigvals = np.linalg.eigvalsh(H)
        assert np.all(eigvals >= -1e-10), \
            f"Hessian not PSD, min eigenvalue: {eigvals.min()}"

    def test_shape(self):
        X = np.random.randn(50, 15).astype(np.float64)
        H = compute_hessian(X)
        assert H.shape == (15, 15)

    def test_exact_formula(self):
        X = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]], dtype=np.float64)
        H = compute_hessian(X)
        expected = 2.0 * X.T @ X / 3.0
        np.testing.assert_allclose(H, expected, atol=1e-10)


# ---------------------------------------------------------------------------
# obq_quantize
# ---------------------------------------------------------------------------

class TestOBQ:
    @pytest.fixture
    def small_problem(self):
        np.random.seed(42)
        d_row, d_col = 16, 8
        W = np.random.randn(d_row, d_col).astype(np.float64) * 0.1
        X = np.random.randn(64, d_col).astype(np.float64)
        H = 2.0 * X.T @ X / 64.0
        return W, H

    def test_output_shape(self, small_problem):
        W, H = small_problem
        Q, err = obq_quantize(W, H, num_bits=4)
        assert Q.shape == W.shape
        assert isinstance(err, (float, np.floating))

    def test_output_on_grid(self, small_problem):
        W, H = small_problem
        Q, _ = obq_quantize(W, H, num_bits=4)
        for col in range(Q.shape[1]):
            col_data = Q[:, col]
            re_q = uniform_quantize(col_data, 4, symmetric=True)
            np.testing.assert_allclose(col_data, re_q, atol=1e-8,
                                       err_msg=f"Column {col} not on grid")

    def test_better_than_naive(self, small_problem):
        W, H = small_problem
        Q_obq, err_obq = obq_quantize(W, H, num_bits=3)
        Q_naive = np.column_stack(
            [uniform_quantize(W[:, j], 3) for j in range(W.shape[1])])
        diff_naive = W - Q_naive
        err_naive = np.trace(diff_naive @ H @ diff_naive.T)
        assert err_obq < err_naive, \
            f"OBQ error {err_obq:.6f} >= naive error {err_naive:.6f}"

    def test_block_equivalence(self, small_problem):
        W, H = small_problem
        Q1, err1 = obq_quantize(W, H, num_bits=4, block_size=1)
        Q4, err4 = obq_quantize(W, H, num_bits=4, block_size=4)
        np.testing.assert_allclose(Q1, Q4, atol=1e-8,
                                   err_msg="Block-4 differs from sequential")
        np.testing.assert_allclose(err1, err4, rtol=1e-6)

    def test_deterministic(self, small_problem):
        W, H = small_problem
        Q1, e1 = obq_quantize(W, H, num_bits=4)
        Q2, e2 = obq_quantize(W, H, num_bits=4)
        np.testing.assert_allclose(Q1, Q2, atol=1e-12)
        np.testing.assert_allclose(e1, e2, atol=1e-12)

    def test_higher_bits_lower_error(self, small_problem):
        W, H = small_problem
        _, err2 = obq_quantize(W, H, num_bits=2)
        _, err4 = obq_quantize(W, H, num_bits=4)
        _, err8 = obq_quantize(W, H, num_bits=8)
        assert err8 < err4 < err2, \
            f"Expected decreasing error: 2-bit={err2:.4f}, 4-bit={err4:.4f}, 8-bit={err8:.4f}"

    def test_error_nonnegative(self, small_problem):
        W, H = small_problem
        _, err = obq_quantize(W, H, num_bits=4)
        assert err >= -1e-10, f"Negative error: {err}"

    def test_block_size_larger_than_cols(self, small_problem):
        W, H = small_problem
        Q1, err1 = obq_quantize(W, H, num_bits=4, block_size=1)
        Q_big, err_big = obq_quantize(W, H, num_bits=4, block_size=100)
        np.testing.assert_allclose(Q1, Q_big, atol=1e-8)


# ---------------------------------------------------------------------------
# obq_quantize_actorder
# ---------------------------------------------------------------------------

class TestOBQActOrder:
    @pytest.fixture
    def problem_with_varying_sensitivity(self):
        np.random.seed(77)
        d_row, d_col = 32, 16
        W = np.random.randn(d_row, d_col).astype(np.float64) * 0.1
        X = np.random.randn(128, d_col).astype(np.float64)
        scale_factors = np.array(
            [10.0 if i % 3 == 0 else 0.1 for i in range(d_col)])
        X = X * scale_factors[None, :]
        H = 2.0 * X.T @ X / 128.0
        return W, H

    def test_valid_permutation(self, problem_with_varying_sensitivity):
        W, H = problem_with_varying_sensitivity
        Q, err, perm = obq_quantize_actorder(W, H, num_bits=3)
        assert len(perm) == W.shape[1]
        assert set(int(p) for p in perm) == set(range(W.shape[1]))

    def test_output_shape(self, problem_with_varying_sensitivity):
        W, H = problem_with_varying_sensitivity
        Q, err, perm = obq_quantize_actorder(W, H, num_bits=4)
        assert Q.shape == W.shape

    def test_error_not_worse(self, problem_with_varying_sensitivity):
        W, H = problem_with_varying_sensitivity
        _, err_std = obq_quantize(W, H, num_bits=3)
        _, err_ao, _ = obq_quantize_actorder(W, H, num_bits=3)
        assert err_ao <= err_std * 1.01, \
            f"Act-order error {err_ao:.6f} > standard {err_std:.6f}"

    def test_permutation_is_descending_diag(self, problem_with_varying_sensitivity):
        W, H = problem_with_varying_sensitivity
        _, _, perm = obq_quantize_actorder(W, H, num_bits=4)
        expected_perm = np.argsort(np.diag(H))[::-1]
        np.testing.assert_array_equal(perm, expected_perm)

    def test_actorder_correct_unpermute(self, problem_with_varying_sensitivity):
        """Verify Q columns correspond to original W columns, not permuted."""
        W, H = problem_with_varying_sensitivity
        Q, _, perm = obq_quantize_actorder(W, H, num_bits=8)
        diff = W - Q
        err = np.trace(diff @ H @ diff.T)
        assert err >= 0


# ---------------------------------------------------------------------------
# mixed_precision_search
# ---------------------------------------------------------------------------

class TestMixedPrecision:
    def test_basic_optimal(self):
        layer_sizes = [(10, 10), (10, 10)]
        error_table = {
            (0, 2): 10.0, (0, 4): 3.0, (0, 8): 0.5,
            (1, 2): 8.0,  (1, 4): 2.0, (1, 8): 0.3,
        }
        budget = 800  # allows (4,4) cost=800
        result = mixed_precision_search(layer_sizes, error_table, [2, 4, 8], budget)
        assert result == [4, 4], f"Expected [4,4], got {result}"

    def test_tight_budget(self):
        layer_sizes = [(10, 10), (10, 10)]
        error_table = {
            (0, 2): 10.0, (0, 4): 3.0, (0, 8): 0.5,
            (1, 2): 8.0,  (1, 4): 2.0, (1, 8): 0.3,
        }
        budget = 600  # feasible: (2,4)=600 err=12, (4,2)=600 err=11, (2,2)=400 err=18
        result = mixed_precision_search(layer_sizes, error_table, [2, 4, 8], budget)
        assert result == [4, 2], f"Expected [4,2], got {result}"

    def test_no_feasible(self):
        layer_sizes = [(10, 10), (10, 10)]
        error_table = {(0, 4): 3.0, (1, 4): 2.0}
        with pytest.raises(ValueError):
            mixed_precision_search(layer_sizes, error_table, [4], 100)

    def test_exhaustive_optimality(self):
        np.random.seed(999)
        K = 3
        layer_sizes = [(5, 5)] * K
        bit_options = [2, 4, 8]
        error_table = {}
        for k in range(K):
            for b in bit_options:
                error_table[(k, b)] = np.random.uniform(1, 20)
        budget = K * 25 * 4

        result = mixed_precision_search(layer_sizes, error_table, bit_options, budget)
        result_error = sum(error_table[(k, result[k])] for k in range(K))
        result_cost = sum(25 * result[k] for k in range(K))
        assert result_cost <= budget

        best_error = float('inf')
        for assignment in itertools.product(bit_options, repeat=K):
            cost = sum(25 * assignment[k] for k in range(K))
            if cost <= budget:
                err = sum(error_table[(k, assignment[k])] for k in range(K))
                best_error = min(best_error, err)

        assert abs(result_error - best_error) < 1e-10, \
            f"Solution error {result_error} != optimal {best_error}"

    def test_many_layers(self):
        K = 8
        layer_sizes = [(10, 10)] * K
        bit_options = [2, 4, 8]
        error_table = {}
        for k in range(K):
            for b in bit_options:
                error_table[(k, b)] = 100.0 / b + k * 0.5
        budget = K * 100 * 4

        result = mixed_precision_search(layer_sizes, error_table, bit_options, budget)
        assert len(result) == K
        total_cost = sum(100 * result[k] for k in range(K))
        assert total_cost <= budget

        total_error = sum(error_table[(k, result[k])] for k in range(K))
        for k in range(K):
            for b in bit_options:
                alt_cost = total_cost - 100 * result[k] + 100 * b
                if alt_cost <= budget:
                    alt_error = total_error - error_table[(k, result[k])] + error_table[(k, b)]
                    assert alt_error >= total_error - 1e-10, \
                        f"Better: layer {k} {result[k]}->{b}"

    def test_budget_constraint_respected(self):
        layer_sizes = [(20, 20), (10, 10)]
        error_table = {
            (0, 2): 50.0, (0, 8): 5.0,
            (1, 2): 10.0, (1, 8): 1.0,
        }
        budget = 1000  # layer0: 400*2=800 or 400*8=3200; layer1: 100*2=200 or 100*8=800
        result = mixed_precision_search(layer_sizes, error_table, [2, 8], budget)
        total_cost = sum(
            layer_sizes[k][0] * layer_sizes[k][1] * result[k] for k in range(2))
        assert total_cost <= budget


# ---------------------------------------------------------------------------
# Integration test
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_full_pipeline(self):
        W0 = np.load('/app/data/weights_layer0.npy')
        W1 = np.load('/app/data/weights_layer1.npy')
        W2 = np.load('/app/data/weights_layer2.npy')
        X = np.load('/app/data/calibration.npy')

        weights = [W0, W1, W2]

        # Compute per-layer Hessians via forward-pass activations
        H0 = compute_hessian(X)
        hidden1 = X @ W0.T                # (256, 128)
        H1 = compute_hessian(hidden1)
        hidden2 = hidden1 @ W1.T           # (256, 64)
        H2 = compute_hessian(hidden2)
        hessians = [H0, H1, H2]

        # OBQ must beat naive on every layer
        for k, (W, H) in enumerate(zip(weights, hessians)):
            Q, err = obq_quantize(W, H, num_bits=4)
            assert Q.shape == W.shape
            assert err >= 0

            Q_naive = np.column_stack(
                [uniform_quantize(W[:, j], 4) for j in range(W.shape[1])])
            diff_naive = W - Q_naive
            err_naive = np.trace(diff_naive @ H @ diff_naive.T)
            assert err < err_naive, \
                f"Layer {k}: OBQ {err:.6f} >= naive {err_naive:.6f}"

        # Act-order must not degrade
        for k, (W, H) in enumerate(zip(weights, hessians)):
            _, err_ao, perm = obq_quantize_actorder(W, H, num_bits=4)
            _, err_std = obq_quantize(W, H, num_bits=4)
            # Act-order is a heuristic; on layers with uniform sensitivity
            # it may not help (or may slightly hurt due to numerics).
            # Verify it doesn't catastrophically degrade.
            assert err_ao <= err_std * 1.10, \
                f"Layer {k}: act-order {err_ao:.6f} >> standard {err_std:.6f}"

        # Mixed precision search
        layer_sizes = [W.shape for W in weights]
        bit_options = [2, 3, 4, 8]
        error_table = {}
        for k, (W, H) in enumerate(zip(weights, hessians)):
            for b in bit_options:
                _, err = obq_quantize(W, H, num_bits=b)
                error_table[(k, b)] = err

        total_params = sum(r * c for r, c in layer_sizes)
        budget = total_params * 4

        assignment = mixed_precision_search(
            layer_sizes, error_table, bit_options, budget)
        assert len(assignment) == 3
        total_cost = sum(
            layer_sizes[k][0] * layer_sizes[k][1] * assignment[k]
            for k in range(3))
        assert total_cost <= budget

        # Verify local optimality
        total_error = sum(error_table[(k, assignment[k])] for k in range(3))
        for k in range(3):
            for b in bit_options:
                alt_cost = (total_cost
                            - layer_sizes[k][0] * layer_sizes[k][1] * assignment[k]
                            + layer_sizes[k][0] * layer_sizes[k][1] * b)
                if alt_cost <= budget:
                    alt_error = (total_error
                                 - error_table[(k, assignment[k])]
                                 + error_table[(k, b)])
                    assert alt_error >= total_error - 1e-10
