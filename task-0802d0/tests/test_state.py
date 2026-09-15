"""
Tests for SDC convergence and stability analysis.

"""

import json
import numpy as np
import pytest


def load_results():
    with open('/app/results.json', 'r') as f:
        return json.load(f)


def compute_Q_via_vandermonde(nodes):
    """Independent Q computation via Vandermonde system.

    Given M nodes, Q is the unique MxM matrix satisfying
    Q @ [f(tau_1),...,f(tau_M)]^T = [int_0^{tau_1} f(s) ds,...,int_0^{tau_M} f(s) ds]^T
    for all polynomials f of degree < M.

    We solve Q V = G where V_{ij} = tau_j^i and G_{ij} = tau_i^{j+1}/(j+1).
    """
    M = len(nodes)
    V = np.vander(nodes, M, increasing=True)
    G = np.zeros((M, M))
    for k in range(M):
        G[:, k] = nodes ** (k + 1) / (k + 1)
    return G @ np.linalg.inv(V)


def compute_R_reference(z, M=3, K=3):
    """Independent reference computation of SDC stability function.

    Uses analytically known M=3 Radau IIa nodes and Vandermonde-based Q.
    """
    sqrt6 = np.sqrt(6.0)
    nodes = np.array([(4 - sqrt6) / 10.0, (4 + sqrt6) / 10.0, 1.0])
    Q = compute_Q_via_vandermonde(nodes)

    deltas = np.diff(np.concatenate(([0.0], nodes)))
    Q_delta = np.zeros((M, M))
    for i in range(M):
        for j in range(i + 1):
            Q_delta[i, j] = deltas[j]

    I_mat = np.eye(M)
    ones = np.ones(M)

    # Predictor
    U = np.linalg.solve(I_mat - z * Q_delta, ones)

    # K correction sweeps
    for _ in range(K):
        rhs = ones + z * (Q - Q_delta) @ U
        U = np.linalg.solve(I_mat - z * Q_delta, rhs)

    return U[-1]


# ---------- Node tests ----------

class TestNodesM3:
    def test_count(self):
        nodes = load_results()['nodes_M3']
        assert len(nodes) == 3

    def test_analytical_values(self):
        nodes = np.array(load_results()['nodes_M3'])
        sqrt6 = np.sqrt(6.0)
        expected = np.array([(4 - sqrt6) / 10.0, (4 + sqrt6) / 10.0, 1.0])
        np.testing.assert_allclose(nodes, expected, atol=1e-12)

    def test_sorted(self):
        nodes = load_results()['nodes_M3']
        for i in range(len(nodes) - 1):
            assert nodes[i] < nodes[i + 1]

    def test_right_endpoint(self):
        nodes = load_results()['nodes_M3']
        assert abs(nodes[-1] - 1.0) < 1e-14

    def test_positive(self):
        nodes = load_results()['nodes_M3']
        assert all(n > 0 for n in nodes)


class TestNodesM5:
    def test_count(self):
        nodes = load_results()['nodes_M5']
        assert len(nodes) == 5

    def test_sorted_and_positive(self):
        nodes = load_results()['nodes_M5']
        assert all(n > 0 for n in nodes)
        for i in range(len(nodes) - 1):
            assert nodes[i] < nodes[i + 1]

    def test_right_endpoint(self):
        nodes = load_results()['nodes_M5']
        assert abs(nodes[-1] - 1.0) < 1e-14

    def test_legendre_polynomial_roots(self):
        """M=5 nodes must be roots of P_5(2t-1) - P_4(2t-1) = 0."""
        nodes = np.array(load_results()['nodes_M5'])
        from numpy.polynomial.legendre import legval
        for t in nodes:
            x = 2.0 * t - 1.0
            P5 = legval(x, [0, 0, 0, 0, 0, 1])
            P4 = legval(x, [0, 0, 0, 0, 1])
            assert abs(P5 - P4) < 1e-10, f"Node t={t} not a root of P5-P4"

    def test_quadrature_exactness(self):
        """Radau IIa with M=5 integrates polynomials up to degree 2*5-2=8 exactly."""
        nodes = np.array(load_results()['nodes_M5'])
        Q = compute_Q_via_vandermonde(nodes)
        weights = Q[-1, :]  # last row = integral from 0 to 1

        for k in range(9):  # degrees 0 through 8
            exact = 1.0 / (k + 1)
            approx = np.dot(weights, nodes ** k)
            assert abs(approx - exact) < 1e-10, f"Quadrature fails for degree {k}"

    def test_quadrature_not_exact_degree9(self):
        """Degree 9 should NOT be exactly integrated (Radau, not Gauss-Legendre)."""
        nodes = np.array(load_results()['nodes_M5'])
        Q = compute_Q_via_vandermonde(nodes)
        weights = Q[-1, :]
        exact = 1.0 / 10.0
        approx = np.dot(weights, nodes ** 9)
        assert abs(approx - exact) > 1e-8, "Degree 9 should not be exact for M=5 Radau IIa"


# ---------- Q matrix tests ----------

class TestQMatrix:
    def test_shape(self):
        Q = np.array(load_results()['Q_M3'])
        assert Q.shape == (3, 3)

    def test_row_sums_equal_nodes(self):
        """Row sums of Q must equal nodes (integral of constant 1 from 0 to tau_i)."""
        r = load_results()
        Q = np.array(r['Q_M3'])
        nodes = np.array(r['nodes_M3'])
        np.testing.assert_allclose(Q.sum(axis=1), nodes, atol=1e-12)

    def test_integrate_linear(self):
        """Q @ [tau_j] = [tau_i^2 / 2]."""
        r = load_results()
        Q = np.array(r['Q_M3'])
        nodes = np.array(r['nodes_M3'])
        np.testing.assert_allclose(Q @ nodes, nodes ** 2 / 2.0, atol=1e-12)

    def test_integrate_quadratic(self):
        """Q @ [tau_j^2] = [tau_i^3 / 3]."""
        r = load_results()
        Q = np.array(r['Q_M3'])
        nodes = np.array(r['nodes_M3'])
        np.testing.assert_allclose(Q @ nodes ** 2, nodes ** 3 / 3.0, atol=1e-12)

    def test_integrate_degree4_quadrature(self):
        """Last row of Q (integral to tau_M=1) is exact for degree 4 (Radau IIa property).
        The full quadrature rule integrates polynomials up to degree 2M-2=4 exactly,
        but partial integrals (other rows) are only exact up to degree M-1=2."""
        r = load_results()
        Q = np.array(r['Q_M3'])
        nodes = np.array(r['nodes_M3'])
        # Only the quadrature weights (last row) integrate degree 4 exactly
        actual = Q[-1, :] @ nodes ** 4
        expected = 1.0 / 5.0  # integral of t^4 from 0 to 1
        assert abs(actual - expected) < 1e-10, \
            f"Quadrature for t^4: expected {expected}, got {actual}"

    def test_matches_vandermonde_computation(self):
        """Q must match independently computed Vandermonde-based Q."""
        r = load_results()
        Q = np.array(r['Q_M3'])
        nodes = np.array(r['nodes_M3'])
        Q_ref = compute_Q_via_vandermonde(nodes)
        np.testing.assert_allclose(Q, Q_ref, atol=1e-11)


# ---------- Convergence order tests ----------

class TestConvergence:
    """SDC with M=3 Radau IIa and backward-Euler predictor + K corrections
    should achieve order min(K+1, 2M-1) = min(K+1, 5)."""

    def test_K1_order_2(self):
        order = load_results()['convergence_orders']['1']
        assert abs(order - 2.0) < 0.5, f"K=1: expected ~2, got {order}"

    def test_K2_order_3(self):
        order = load_results()['convergence_orders']['2']
        assert abs(order - 3.0) < 0.5, f"K=2: expected ~3, got {order}"

    def test_K3_order_4(self):
        order = load_results()['convergence_orders']['3']
        assert abs(order - 4.0) < 0.5, f"K=3: expected ~4, got {order}"

    def test_K4_order_5(self):
        order = load_results()['convergence_orders']['4']
        assert abs(order - 5.0) < 0.5, f"K=4: expected ~5, got {order}"

    def test_K5_saturated_order_5(self):
        order = load_results()['convergence_orders']['5']
        assert abs(order - 5.0) < 0.5, f"K=5: expected ~5 (saturated), got {order}"

    def test_orders_increase_with_K(self):
        """Orders must increase with K until saturation."""
        orders = load_results()['convergence_orders']
        vals = [orders[str(k)] for k in range(1, 6)]
        for i in range(3):  # K=1..4 should be strictly increasing
            assert vals[i + 1] > vals[i] - 0.3, \
                f"Order should increase: K={i + 1}->{vals[i]:.2f}, K={i + 2}->{vals[i + 1]:.2f}"


# ---------- Stability function tests ----------

class TestStability:
    def test_values_match_reference(self):
        """R(z) must match independent reference computation."""
        R_vals = load_results()['stability_R']
        for z in [-0.5, -1.0, -2.0, -5.0, -10.0]:
            ref = compute_R_reference(z)
            actual = R_vals[str(z)]
            assert abs(actual - ref) < 1e-10, \
                f"R({z}): expected {ref:.12e}, got {actual:.12e}"

    def test_bounded_on_negative_real(self):
        """|R(z)| < 1 for z on negative real axis (stable SDC)."""
        R_vals = load_results()['stability_R']
        for z_str, R in R_vals.items():
            assert abs(R) < 1.01, f"|R({z_str})| = {abs(R):.6f} >= 1"

    def test_small_z_approximates_exp(self):
        """R(-0.5) should closely approximate exp(-0.5) for this order-4 method."""
        R = load_results()['stability_R']['-0.5']
        # Order 4 means R(z) = exp(z) + O(z^5); at z=-0.5 the error is tiny
        assert abs(R - np.exp(-0.5)) < 0.01, \
            f"R(-0.5)={R:.8f}, exp(-0.5)={np.exp(-0.5):.8f}"

    def test_all_keys_present(self):
        R_vals = load_results()['stability_R']
        for z in ['-0.5', '-1.0', '-2.0', '-5.0', '-10.0']:
            assert z in R_vals, f"Missing key {z} in stability_R"


# ---------- Optimal diagonal preconditioner tests ----------

class TestOptimalDiagonal:
    def test_entries_positive(self):
        d = load_results()['optimal_diag_entries']
        assert len(d) == 3
        assert all(di > 0 for di in d), "Diagonal entries must be positive"

    def test_spectral_radius_in_range(self):
        rho = load_results()['optimal_spectral_radius']
        assert 0 < rho < 1.0, f"Spectral radius {rho} must be in (0, 1)"

    def test_spectral_radius_sufficiently_small(self):
        """For M=3 Radau IIa, optimal diagonal achieves rho < 0.5."""
        rho = load_results()['optimal_spectral_radius']
        assert rho < 0.5, f"Optimal spectral radius {rho} should be < 0.5"

    def test_better_than_diagonal_of_Q(self):
        """Optimal diagonal must improve upon using the diagonal of Q itself."""
        r = load_results()
        Q = np.array(r['Q_M3'])
        diag_Q = np.diag(Q)
        D_Q_inv = np.diag(1.0 / diag_Q)
        rho_diag = max(abs(np.linalg.eigvals(np.eye(3) - D_Q_inv @ Q)))
        rho_opt = r['optimal_spectral_radius']
        assert rho_opt <= rho_diag + 1e-8, \
            f"Optimal {rho_opt:.6f} should be <= diagonal-of-Q {rho_diag:.6f}"

    def test_self_consistency(self):
        """Reported spectral radius must match computation from reported d values."""
        r = load_results()
        Q = np.array(r['Q_M3'])
        d = np.array(r['optimal_diag_entries'])
        D_inv = np.diag(1.0 / d)
        M_mat = np.eye(3) - D_inv @ Q
        rho_computed = max(abs(np.linalg.eigvals(M_mat)))
        rho_reported = r['optimal_spectral_radius']
        assert abs(rho_computed - rho_reported) < 1e-4, \
            f"Reported rho={rho_reported:.6f}, computed rho={rho_computed:.6f}"
