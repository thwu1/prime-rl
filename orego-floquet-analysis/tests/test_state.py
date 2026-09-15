
import pytest
import json
import os
import numpy as np
from scipy.integrate import solve_ivp, quad

# ---- Independent reference implementation of the ODE system ----
S = 77.27
Q = 8.375e-6
W = 0.161


def orego_rhs(t, y):
    y1, y2, y3 = y[0], y[1], y[2]
    return [
        S * (y2 + y1 * (1.0 - Q * y1 - y2)),
        (y3 - (1.0 + y1) * y2) / S,
        W * (y1 - y3),
    ]


def orego_jac(y):
    y1, y2, y3 = y[0], y[1], y[2]
    J = np.zeros((3, 3))
    J[0, 0] = S * (1.0 - 2.0 * Q * y1 - y2)
    J[0, 1] = S * (1.0 - y1)
    J[0, 2] = 0.0
    J[1, 0] = -y2 / S
    J[1, 1] = -(1.0 + y1) / S
    J[1, 2] = 1.0 / S
    J[2, 0] = W
    J[2, 1] = 0.0
    J[2, 2] = -W
    return J


# ---- Fixtures ----
@pytest.fixture
def period():
    with open("/app/period.txt") as f:
        return float(f.read().strip())


@pytest.fixture
def monodromy():
    with open("/app/monodromy_matrix.json") as f:
        return np.array(json.load(f))


@pytest.fixture
def multipliers():
    with open("/app/floquet_multipliers.json") as f:
        fm_list = json.load(f)
    return [complex(m["real"], m["imag"]) for m in fm_list]


@pytest.fixture
def trace_integral():
    with open("/app/trace_integral.txt") as f:
        return float(f.read().strip())


# ---- File existence and format ----
class TestOutputFiles:
    def test_period_file_exists(self):
        assert os.path.exists("/app/period.txt"), "period.txt not found"

    def test_monodromy_file_exists(self):
        assert os.path.exists("/app/monodromy_matrix.json"), "monodromy_matrix.json not found"

    def test_floquet_file_exists(self):
        assert os.path.exists("/app/floquet_multipliers.json"), "floquet_multipliers.json not found"

    def test_trace_integral_file_exists(self):
        assert os.path.exists("/app/trace_integral.txt"), "trace_integral.txt not found"


# ---- Period tests ----
class TestPeriod:
    def test_period_positive(self, period):
        assert period > 0, f"Period must be positive, got {period}"

    def test_period_in_range(self, period):
        assert 280.0 < period < 320.0, f"Period {period} outside expected range [280, 320]"

    def test_period_self_consistency(self, period):
        """Integrate ODE for one period from a limit-cycle point; must return close."""
        y0 = [1.0, 2.0, 3.0]
        sol = solve_ivp(orego_rhs, [0, 3000], y0, method="Radau",
                        rtol=1e-11, atol=1e-13, dense_output=True)
        y_lc = sol.sol(3000)

        sol2 = solve_ivp(orego_rhs, [0, period], y_lc, method="Radau",
                         rtol=1e-11, atol=1e-13)
        y_final = sol2.y[:, -1]

        rel_error = np.linalg.norm(y_final - y_lc) / np.linalg.norm(y_lc)
        assert rel_error < 1e-3, (
            f"Period self-consistency failed: y(T) drifted from y(0) with "
            f"relative error {rel_error:.2e}"
        )

    def test_independent_period_verification(self, period):
        """Verify period by detecting successive y1 maxima independently."""
        y0 = [1.0, 2.0, 3.0]
        sol = solve_ivp(orego_rhs, [0, 3000], y0, method="Radau",
                        rtol=1e-11, atol=1e-13, dense_output=True)

        def dy1_event(t, y):
            return S * (y[1] + y[0] * (1.0 - Q * y[0] - y[1]))

        dy1_event.direction = -1

        y_lc = sol.sol(3000)
        sol2 = solve_ivp(orego_rhs, [0, 1000], y_lc, method="Radau",
                         rtol=1e-11, atol=1e-13, events=dy1_event)

        maxima = sol2.t_events[0]
        assert len(maxima) >= 2, f"Could not detect enough y1 maxima: found {len(maxima)}"

        T_ref = maxima[1] - maxima[0]
        rel_error = abs(period - T_ref) / T_ref
        assert rel_error < 1e-3, (
            f"Period mismatch: submitted={period:.10f}, reference={T_ref:.10f}, "
            f"rel_err={rel_error:.2e}"
        )


# ---- Monodromy matrix tests ----
class TestMonodromyMatrix:
    def test_shape(self, monodromy):
        assert monodromy.shape == (3, 3), f"Expected (3,3), got {monodromy.shape}"

    def test_finite(self, monodromy):
        assert np.all(np.isfinite(monodromy)), "Monodromy matrix has non-finite entries"

    def test_not_identity(self, monodromy):
        diff = np.linalg.norm(monodromy - np.eye(3), "fro")
        assert diff > 0.01, (
            f"Monodromy matrix is too close to identity (Frobenius diff={diff:.4e}). "
            "This suggests the variational equations were not properly integrated."
        )

    def test_has_unit_eigenvalue(self, monodromy):
        """The monodromy matrix must have an eigenvalue equal to 1."""
        eigenvalues = np.linalg.eigvals(monodromy)
        distances = [abs(ev - 1.0) for ev in eigenvalues]
        assert min(distances) < 1e-2, (
            f"No eigenvalue of the monodromy matrix is close to 1. "
            f"Eigenvalues: {eigenvalues}"
        )


# ---- Floquet multiplier tests ----
class TestFloquetMultipliers:
    def test_count(self, multipliers):
        assert len(multipliers) == 3, f"Expected 3 multipliers, got {len(multipliers)}"

    def test_finite(self, multipliers):
        for m in multipliers:
            assert np.isfinite(m.real) and np.isfinite(m.imag), f"Non-finite multiplier {m}"

    def test_unit_multiplier_exists(self, multipliers):
        """One Floquet multiplier must be 1 (tangent direction of periodic orbit)."""
        distances = [abs(m - 1.0) for m in multipliers]
        min_dist = min(distances)
        assert min_dist < 1e-2, (
            f"No multiplier close to 1.0. Closest distance: {min_dist:.4e}. "
            f"Multipliers: {multipliers}"
        )

    def test_stable_orbit(self, multipliers):
        """Non-trivial multipliers must have |lambda| < 1 for a stable limit cycle."""
        distances = [abs(m - 1.0) for m in multipliers]
        non_trivial = [m for m, d in zip(multipliers, distances) if d > 0.05]
        for m in non_trivial:
            assert abs(m) < 1.0, (
                f"Non-trivial Floquet multiplier {m} has |lambda|={abs(m):.6f} >= 1, "
                "indicating an unstable orbit (incorrect computation)."
            )

    def test_strong_contraction(self, multipliers):
        """Non-trivial multipliers should be very small for this system."""
        distances = [abs(m - 1.0) for m in multipliers]
        non_trivial = [m for m, d in zip(multipliers, distances) if d > 0.05]
        for m in non_trivial:
            assert abs(m) < 1e-3, (
                f"Non-trivial multiplier {m} has |lambda|={abs(m):.6e}, "
                "expected < 1e-3 for this strongly contractive system."
            )

    def test_sorted_by_magnitude(self, multipliers):
        """Multipliers should be sorted by descending magnitude."""
        mags = [abs(m) for m in multipliers]
        for i in range(len(mags) - 1):
            assert mags[i] >= mags[i + 1] - 1e-10, (
                f"Multipliers not sorted by descending magnitude: {mags}"
            )


# ---- Trace integral tests ----
class TestTraceIntegral:
    def test_strongly_negative(self, trace_integral):
        """For a system with extreme contraction, trace integral must be very negative."""
        assert trace_integral < -1e5, (
            f"Trace integral should be strongly negative (< -1e5) for this "
            f"dissipative system, got {trace_integral}"
        )

    def test_independent_trace_verification(self, period, trace_integral):
        """Independently compute trace integral by quadrature and compare."""
        y0 = [1.0, 2.0, 3.0]
        sol = solve_ivp(orego_rhs, [0, 3000], y0, method="Radau",
                        rtol=1e-11, atol=1e-13, dense_output=True)
        y_lc = sol.sol(3000)

        sol_fwd = solve_ivp(orego_rhs, [0, period], y_lc, method="Radau",
                            rtol=1e-11, atol=1e-13, dense_output=True)

        def trace_func(t):
            y = sol_fwd.sol(t)
            return np.trace(orego_jac(y))

        ti_ref, _ = quad(trace_func, 0, period, limit=500,
                         epsabs=1e-4, epsrel=1e-4)

        rel_error = abs(trace_integral - ti_ref) / abs(ti_ref)
        assert rel_error < 0.01, (
            f"Trace integral mismatch: submitted={trace_integral:.6f}, "
            f"reference={ti_ref:.6f}, rel_err={rel_error:.4e}"
        )


# ---- Cross-validation ----
class TestCrossValidation:
    def test_monodromy_eigenvalues_match_multipliers(self, monodromy, multipliers):
        """Eigenvalues of submitted monodromy matrix must match submitted multipliers."""
        M_eigs = np.linalg.eigvals(monodromy)
        M_eigs_sorted = sorted(M_eigs, key=lambda x: -abs(x))
        mults_sorted = sorted(multipliers, key=lambda x: -abs(x))

        for me, ms in zip(M_eigs_sorted, mults_sorted):
            assert abs(abs(me) - abs(ms)) < 1e-3 * max(abs(me), abs(ms), 1e-15), (
                f"Monodromy eigenvalue magnitude {abs(me)} does not match "
                f"submitted multiplier magnitude {abs(ms)}"
            )

    def test_determinant_very_small(self, monodromy):
        """det(M) should be essentially zero due to extreme contraction."""
        det_M = abs(np.linalg.det(monodromy))
        assert det_M < 1e-5, (
            f"|det(M)| = {det_M:.4e}, expected essentially zero for this system."
        )
