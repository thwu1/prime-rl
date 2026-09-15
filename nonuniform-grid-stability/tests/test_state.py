
"""
Verification tests for non-uniform grid finite difference stability analysis.
Independently computes reference values and compares against agent's results.
"""

import json
import os
import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Reference implementations
# ---------------------------------------------------------------------------

def fornberg_weights(x0, x, m):
    """Fornberg's algorithm for finite difference weights."""
    n = len(x) - 1
    c = np.zeros((n + 1, m + 1))
    c1 = 1.0
    c4 = x[0] - x0
    c[0, 0] = 1.0
    for i in range(1, n + 1):
        mn = min(i, m)
        c2 = 1.0
        c5 = c4
        c4 = x[i] - x0
        for j in range(i):
            c3 = x[i] - x[j]
            c2 *= c3
            if j == i - 1:
                for k in range(mn, 0, -1):
                    c[i, k] = c1 * (k * c[i - 1, k - 1] - c5 * c[i - 1, k]) / c2
                c[i, 0] = -c1 * c5 * c[i - 1, 0] / c2
            for k in range(mn, 0, -1):
                c[j, k] = (c4 * c[j, k] - k * c[j, k - 1]) / c3
            c[j, 0] = c4 * c[j, 0] / c3
        c1 = c2
    return c[:, m]


def generate_grid(N, alpha, L=2 * np.pi):
    """Generate non-uniform periodic grid."""
    j = np.arange(N)
    return L * (j / N + alpha / (2 * np.pi) * np.sin(2 * np.pi * j / N))


def build_operator(x, a, nu, hw=2):
    """Build spatial operator matrix L = -a*D1 + nu*D2 with periodic BC."""
    N = len(x)
    L_period = 2 * np.pi
    D1 = np.zeros((N, N))
    D2 = np.zeros((N, N))

    for i in range(N):
        indices = [(i + k) % N for k in range(-hw, hw + 1)]
        x_stencil = np.array([x[idx] for idx in indices])
        for k in range(len(x_stencil)):
            diff = x_stencil[k] - x[i]
            if diff > L_period / 2:
                x_stencil[k] -= L_period
            elif diff < -L_period / 2:
                x_stencil[k] += L_period

        w1 = fornberg_weights(x[i], x_stencil, 1)
        w2 = fornberg_weights(x[i], x_stencil, 2)

        for k_idx, j in enumerate(indices):
            D1[i, j] += w1[k_idx]
            D2[i, j] += w2[k_idx]

    return -a * D1 + nu * D2


def rk4_stability_function(z):
    """RK4 stability polynomial."""
    return 1 + z + z ** 2 / 2 + z ** 3 / 6 + z ** 4 / 24


def compute_fe_dt_max(eigenvalues):
    """Maximum stable dt for Forward Euler."""
    dt_max = float('inf')
    for lam in eigenvalues:
        re = lam.real
        if abs(lam) < 1e-14:
            continue
        if re >= 0:
            return 0.0
        dt_j = -2 * re / (re ** 2 + lam.imag ** 2)
        dt_max = min(dt_max, dt_j)
    return dt_max


def compute_rk4_dt_max(eigenvalues, tol=1e-12):
    """Maximum stable dt for RK4 via binary search."""
    dt_low = 0.0
    dt_high = 0.1
    for _ in range(100):
        z = eigenvalues * dt_high
        if np.max(np.abs(rk4_stability_function(z))) > 1.0:
            break
        dt_high *= 2
    for _ in range(200):
        dt_mid = (dt_low + dt_high) / 2
        z = eigenvalues * dt_mid
        if np.max(np.abs(rk4_stability_function(z))) <= 1.0:
            dt_low = dt_mid
        else:
            dt_high = dt_mid
        if dt_high - dt_low < tol:
            break
    return dt_low


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def config():
    with open('/app/config.json', 'r') as f:
        return json.load(f)


@pytest.fixture(scope="module")
def results():
    assert os.path.exists('/app/results.json'), "results.json not found at /app/results.json"
    with open('/app/results.json', 'r') as f:
        return json.load(f)


@pytest.fixture(scope="module")
def reference(config):
    """Compute all reference values independently."""
    N = config['grid']['N']
    alpha = config['grid']['stretching_alpha']
    a = config['pde']['advection_speed']
    nu = config['pde']['diffusion_coeff']

    x = generate_grid(N, alpha)
    L_op = build_operator(x, a, nu, hw=config['discretization']['stencil_half_width'])
    eigenvalues = np.linalg.eigvals(L_op)

    # Sanity-check the reference on a uniform grid
    x_uni = np.array([-2.0, -1.0, 0.0, 1.0, 2.0])
    w1_uni = fornberg_weights(0.0, x_uni, 1)
    expected_w1 = np.array([1.0 / 12, -2.0 / 3, 0.0, 2.0 / 3, -1.0 / 12])
    assert np.allclose(w1_uni, expected_w1, atol=1e-13), \
        "Reference sanity check failed for 1st derivative"
    w2_uni = fornberg_weights(0.0, x_uni, 2)
    expected_w2 = np.array([-1.0 / 12, 4.0 / 3, -5.0 / 2, 4.0 / 3, -1.0 / 12])
    assert np.allclose(w2_uni, expected_w2, atol=1e-13), \
        "Reference sanity check failed for 2nd derivative"

    return {
        'x': x,
        'L_op': L_op,
        'eigenvalues': eigenvalues,
        'spectral_radius': float(np.max(np.abs(eigenvalues))),
        'dt_fe': compute_fe_dt_max(eigenvalues),
        'dt_rk4': compute_rk4_dt_max(eigenvalues),
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestResultsStructure:
    def test_results_file_exists(self):
        assert os.path.exists('/app/results.json'), "results.json not produced"

    def test_required_keys(self, results):
        required = [
            'spectral_radius', 'dt_max_forward_euler', 'dt_max_rk4',
            'rk4_simulation_l2_error', 'eigenvalues_real', 'eigenvalues_imag',
            'fd_weights_d1_at_j32', 'fd_weights_d2_at_j32',
        ]
        for key in required:
            assert key in results, f"Missing required key: {key}"

    def test_eigenvalue_count(self, results, config):
        N = config['grid']['N']
        assert len(results['eigenvalues_real']) == N, \
            f"Expected {N} eigenvalues, got {len(results['eigenvalues_real'])}"
        assert len(results['eigenvalues_imag']) == N

    def test_fd_weights_length(self, results):
        assert len(results['fd_weights_d1_at_j32']) == 5, "Expected 5 weights for d1"
        assert len(results['fd_weights_d2_at_j32']) == 5, "Expected 5 weights for d2"


class TestFDWeights:
    def test_polynomial_exactness_d1(self, results, config):
        """Weights for 1st derivative must exactly differentiate polynomials up to degree 4."""
        N = config['grid']['N']
        alpha = config['grid']['stretching_alpha']
        x = generate_grid(N, alpha)

        i0 = 32
        hw = config['discretization']['stencil_half_width']
        indices = [(i0 + k) % N for k in range(-hw, hw + 1)]
        x_s = np.array([x[idx] for idx in indices])
        x0 = x[i0]
        w = np.array(results['fd_weights_d1_at_j32'])

        for p in range(5):
            vals = x_s ** p
            got = np.dot(w, vals)
            if p == 0:
                expected = 0.0
            else:
                expected = p * x0 ** (p - 1)
            assert abs(got - expected) < 1e-8, \
                f"d1 polynomial exactness failed for x^{p}: got {got}, expected {expected}"

    def test_polynomial_exactness_d2(self, results, config):
        """Weights for 2nd derivative must exactly differentiate polynomials up to degree 4."""
        N = config['grid']['N']
        alpha = config['grid']['stretching_alpha']
        x = generate_grid(N, alpha)

        i0 = 32
        hw = config['discretization']['stencil_half_width']
        indices = [(i0 + k) % N for k in range(-hw, hw + 1)]
        x_s = np.array([x[idx] for idx in indices])
        x0 = x[i0]
        w = np.array(results['fd_weights_d2_at_j32'])

        for p in range(5):
            vals = x_s ** p
            got = np.dot(w, vals)
            if p < 2:
                expected = 0.0
            else:
                expected = p * (p - 1) * x0 ** (p - 2)
            assert abs(got - expected) < 1e-7, \
                f"d2 polynomial exactness failed for x^{p}: got {got}, expected {expected}"

    def test_weights_match_reference(self, results, config):
        """Weights must match independently computed reference."""
        N = config['grid']['N']
        alpha = config['grid']['stretching_alpha']
        x = generate_grid(N, alpha)

        i0 = 32
        hw = config['discretization']['stencil_half_width']
        indices = [(i0 + k) % N for k in range(-hw, hw + 1)]
        x_s = np.array([x[idx] for idx in indices])
        L_period = 2 * np.pi
        for k in range(len(x_s)):
            diff = x_s[k] - x[i0]
            if diff > L_period / 2:
                x_s[k] -= L_period
            elif diff < -L_period / 2:
                x_s[k] += L_period

        w1_ref = fornberg_weights(x[i0], x_s, 1)
        w2_ref = fornberg_weights(x[i0], x_s, 2)

        w1_rep = np.array(results['fd_weights_d1_at_j32'])
        w2_rep = np.array(results['fd_weights_d2_at_j32'])

        assert np.allclose(w1_rep, w1_ref, atol=1e-8), \
            f"d1 weights mismatch: ref={w1_ref}, reported={w1_rep}"
        assert np.allclose(w2_rep, w2_ref, atol=1e-8), \
            f"d2 weights mismatch: ref={w2_ref}, reported={w2_rep}"


class TestEigenvalues:
    def test_negative_real_parts(self, results):
        """All eigenvalues of the advection-diffusion operator must have non-positive real parts."""
        eig_real = np.array(results['eigenvalues_real'])
        assert np.all(eig_real <= 1e-10), \
            f"Found eigenvalue with positive real part: max Re = {np.max(eig_real)}"

    def test_spectral_radius_self_consistent(self, results):
        """Reported spectral radius must equal max magnitude of reported eigenvalues."""
        eig = np.array(results['eigenvalues_real']) + 1j * np.array(results['eigenvalues_imag'])
        rho_from_eig = np.max(np.abs(eig))
        rho_reported = results['spectral_radius']
        rel_err = abs(rho_from_eig - rho_reported) / max(rho_from_eig, 1e-14)
        assert rel_err < 1e-6, \
            f"Spectral radius inconsistent: from eigenvalues {rho_from_eig}, reported {rho_reported}"

    def test_spectral_radius_reference(self, results, reference):
        """Spectral radius must match independent reference."""
        rho_ref = reference['spectral_radius']
        rho_rep = results['spectral_radius']
        rel_err = abs(rho_ref - rho_rep) / max(rho_ref, 1e-14)
        assert rel_err < 1e-3, \
            f"Spectral radius: ref={rho_ref:.6f}, reported={rho_rep:.6f}, rel_err={rel_err:.2e}"

    def test_eigenvalues_match_reference(self, results, reference):
        """Eigenvalues must match independently computed reference (matched by nearest)."""
        eig_rep = np.array(results['eigenvalues_real']) + 1j * np.array(results['eigenvalues_imag'])
        eig_ref = reference['eigenvalues']

        key_fn = lambda z: (round(abs(z), 10), round(np.angle(z), 10))
        eig_rep_sorted = np.array(sorted(eig_rep, key=key_fn))
        eig_ref_sorted = np.array(sorted(eig_ref, key=key_fn))

        mismatches = 0
        for i in range(len(eig_ref_sorted)):
            diff = abs(eig_rep_sorted[i] - eig_ref_sorted[i])
            scale = max(abs(eig_ref_sorted[i]), 1.0)
            if diff / scale > 1e-3:
                mismatches += 1
        assert mismatches == 0, f"{mismatches} eigenvalues do not match reference (tol=1e-3)"


class TestStability:
    def test_forward_euler_dt(self, results, reference):
        """Forward Euler stability limit must match reference."""
        dt_ref = reference['dt_fe']
        dt_rep = results['dt_max_forward_euler']
        rel_err = abs(dt_ref - dt_rep) / max(dt_ref, 1e-14)
        assert rel_err < 0.02, \
            f"FE dt_max: ref={dt_ref:.6e}, reported={dt_rep:.6e}, rel_err={rel_err:.2e}"

    def test_rk4_dt(self, results, reference):
        """RK4 stability limit must match reference."""
        dt_ref = reference['dt_rk4']
        dt_rep = results['dt_max_rk4']
        rel_err = abs(dt_ref - dt_rep) / max(dt_ref, 1e-14)
        assert rel_err < 0.02, \
            f"RK4 dt_max: ref={dt_ref:.6e}, reported={dt_rep:.6e}, rel_err={rel_err:.2e}"

    def test_rk4_larger_than_forward_euler(self, results):
        """RK4 stability limit should be larger than Forward Euler's."""
        assert results['dt_max_rk4'] > results['dt_max_forward_euler'], \
            f"RK4 dt_max ({results['dt_max_rk4']}) should exceed FE dt_max ({results['dt_max_forward_euler']})"

    def test_stability_limits_positive(self, results):
        """Both stability limits must be positive."""
        assert results['dt_max_forward_euler'] > 0, "FE dt_max must be positive"
        assert results['dt_max_rk4'] > 0, "RK4 dt_max must be positive"


class TestSimulation:
    def test_rms_error_small(self, results):
        """RK4 simulation RMS error must be below threshold."""
        err = results['rk4_simulation_l2_error']
        assert err < 5e-3, f"Simulation RMS error too large: {err}"

    def test_rms_error_positive(self, results):
        """RMS error must be positive (not trivially zero)."""
        err = results['rk4_simulation_l2_error']
        assert err > 0, "RMS error is zero - likely incorrect"

    def test_simulation_error_plausible(self, results):
        """For 4th-order FD + RK4 on N=64 grid, error should be in a reasonable range."""
        err = results['rk4_simulation_l2_error']
        assert err < 1e-2, f"Error suspiciously large for 4th-order method: {err}"
        assert err > 1e-10, f"Error suspiciously small: {err}"
