"""
Tests for co-simulation convergence analysis task.
Independently verifies the agent's monolithic reference, co-simulation results,
convergence orders, and stability boundaries.
"""


import json
import csv
import os
import sys

import numpy as np
from scipy.integrate import solve_ivp
from scipy.interpolate import interp1d
import pytest

sys.path.insert(0, "/app")
from subsystems import PARAMS

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

Ra = PARAMS["Ra"]
La = PARAMS["La"]
ke = PARAMS["ke"]
ratio = PARAMS["ratio"]
J_eff = PARAMS["J_eff"]
k_PI = PARAMS["k_PI"]
T_PI = PARAMS["T_PI"]


def w_desired(t):
    return 10.0 if t >= 0.1 else 0.0


def tau_load(t):
    return 3.0 if t >= 0.5 else 0.0


def monolithic_rhs(t, x):
    i_a, w_load, x_i = x
    wd = w_desired(t)
    tl = tau_load(t)
    w = ratio * w_load
    e = wd - w
    V = k_PI * (e + x_i / T_PI)
    di_a = (V - Ra * i_a - ke * ratio * w_load) / La
    dw_load = (ke * ratio * i_a + tl) / J_eff
    dx_i = e
    return [di_a, dw_load, dx_i]


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ground_truth():
    """Compute an independent ground-truth reference solution."""
    x0 = [0.0, 0.0, 0.0]
    seg_bounds = [0.0, 0.1, 0.5, 1.0]
    state = x0
    t_all, y_all = [], []
    for i in range(len(seg_bounds) - 1):
        ts, te = seg_bounds[i], seg_bounds[i + 1]
        n_pts = int(round((te - ts) / 0.0001)) + 1
        t_eval = np.linspace(ts, te, n_pts)
        if t_all:
            t_eval = t_eval[1:]
        sol = solve_ivp(
            monolithic_rhs, (ts, te), state,
            method="RK45", t_eval=t_eval,
            rtol=1e-12, atol=1e-14, max_step=1e-4,
        )
        assert sol.success, f"Ground-truth integration failed: {sol.message}"
        t_all.extend(sol.t.tolist())
        y_all.append(sol.y)
        state = sol.y[:, -1].tolist()
    t_ref = np.array(t_all)
    w_ref = ratio * np.hstack(y_all)[1]
    return t_ref, w_ref


@pytest.fixture(scope="module")
def results():
    with open("/app/results.json", "r") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def reference_csv():
    t, w = [], []
    with open("/app/reference.csv", "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            t.append(float(row["time"]))
            w.append(float(row["w"]))
    return np.array(t), np.array(w)


# ---------------------------------------------------------------------------
# Tests: file existence and structure
# ---------------------------------------------------------------------------


class TestFilesExist:
    def test_reference_csv_exists(self):
        assert os.path.isfile("/app/reference.csv")

    def test_results_json_exists(self):
        assert os.path.isfile("/app/results.json")


class TestResultsStructure:
    def test_has_reference_w_final(self, results):
        assert "reference_w_final" in results
        assert isinstance(results["reference_w_final"], (int, float))

    def test_has_methods(self, results):
        for m in ("jacobi", "gauss_seidel"):
            assert m in results
            for key in ("errors", "convergence_order", "H_crit"):
                assert key in results[m], f"Missing {key} in {m}"

    def test_errors_have_required_keys(self, results):
        required = ["0.0001", "0.001", "0.01"]
        for m in ("jacobi", "gauss_seidel"):
            for h in required:
                assert h in results[m]["errors"], f"Missing H={h} in {m}"


# ---------------------------------------------------------------------------
# Tests: reference solution
# ---------------------------------------------------------------------------


class TestReferenceSolution:
    def test_reference_csv_length(self, reference_csv):
        t, _ = reference_csv
        assert len(t) == 10001, f"Expected 10001 rows, got {len(t)}"

    def test_reference_csv_endpoints(self, reference_csv):
        t, _ = reference_csv
        assert abs(t[0]) < 1e-9
        assert abs(t[-1] - 1.0) < 1e-9

    def test_reference_w_final_accuracy(self, results, ground_truth):
        _, w_gt = ground_truth
        expected = float(w_gt[-1])
        actual = results["reference_w_final"]
        assert abs(actual - expected) < 0.05, (
            f"reference_w_final={actual}, expected~{expected}"
        )

    def test_reference_csv_matches_ground_truth(self, reference_csv, ground_truth):
        _, w_csv = reference_csv
        _, w_gt = ground_truth
        for idx in [0, 1000, 5000, 8000, 10000]:
            assert abs(w_csv[idx] - w_gt[idx]) < 0.1, (
                f"Mismatch at index {idx}: csv={w_csv[idx]}, gt={w_gt[idx]}"
            )

    def test_reference_physical_behavior(self, reference_csv):
        t, w = reference_csv
        # Before step input, w ~ 0
        idx_009 = np.searchsorted(t, 0.09)
        assert abs(w[idx_009]) < 0.5, "w should be ~0 before t=0.1"
        # After transient settles, w should track w_desired=10
        idx_09 = np.searchsorted(t, 0.9)
        assert 5 < w[idx_09] < 15, "w should track ~10 near t=0.9"


# ---------------------------------------------------------------------------
# Tests: convergence properties
# ---------------------------------------------------------------------------


class TestConvergence:
    def test_jacobi_convergence_order(self, results):
        order = results["jacobi"]["convergence_order"]
        assert order is not None
        assert 0.5 <= order <= 2.5, f"Jacobi order {order} out of [0.5, 2.5]"

    def test_gs_convergence_order(self, results):
        order = results["gauss_seidel"]["convergence_order"]
        assert order is not None
        assert 0.5 <= order <= 2.5, f"GS order {order} out of [0.5, 2.5]"

    def test_gs_more_accurate_than_jacobi_small_h(self, results):
        """GS should be more accurate than Jacobi in the asymptotic regime."""
        gs_better = 0
        compared = 0
        for h_str in results["jacobi"]["errors"]:
            if float(h_str) > 0.002:
                continue  # only compare in asymptotic regime
            j = results["jacobi"]["errors"].get(h_str)
            g = results["gauss_seidel"]["errors"].get(h_str)
            if j is not None and g is not None:
                compared += 1
                if g <= j * 1.05:
                    gs_better += 1
        assert compared >= 2, "Need >=2 small-H points for comparison"
        assert gs_better >= compared * 0.5, (
            f"GS should be <= Jacobi for most small H ({gs_better}/{compared})"
        )

    def test_error_monotonicity_small_h(self, results):
        """In the asymptotic regime (small H), errors should increase with H."""
        for m in ("jacobi", "gauss_seidel"):
            pairs = sorted(
                [(float(h), e) for h, e in results[m]["errors"].items()
                 if e is not None and float(h) <= 0.002]
            )
            if len(pairs) < 3:
                continue
            # Check that each error is at least 50% of the next-smaller-H error
            for i in range(1, len(pairs)):
                assert pairs[i][1] >= pairs[i - 1][1] * 0.5, (
                    f"{m}: error at H={pairs[i][0]} ({pairs[i][1]:.4e}) should "
                    f"be >= 0.5 * error at H={pairs[i-1][0]} ({pairs[i-1][1]:.4e})"
                )


# ---------------------------------------------------------------------------
# Tests: stability boundaries
# ---------------------------------------------------------------------------


class TestStability:
    def test_h_crit_jacobi(self, results):
        hc = results["jacobi"]["H_crit"]
        assert hc is not None
        assert 0.0005 <= hc <= 0.1, f"Jacobi H_crit={hc} out of range"

    def test_h_crit_gs(self, results):
        hc = results["gauss_seidel"]["H_crit"]
        assert hc is not None
        assert 0.0005 <= hc <= 0.1, f"GS H_crit={hc} out of range"

    def test_gs_at_least_as_stable(self, results):
        """GS H_crit should be at least half of Jacobi H_crit."""
        hc_j = results["jacobi"]["H_crit"]
        hc_g = results["gauss_seidel"]["H_crit"]
        assert hc_g >= hc_j * 0.5, (
            f"GS H_crit ({hc_g}) should be >= 0.5 * Jacobi H_crit ({hc_j})"
        )


# ---------------------------------------------------------------------------
# Tests: small-step accuracy
# ---------------------------------------------------------------------------


class TestAccuracy:
    def test_jacobi_small_h_accurate(self, results):
        e = results["jacobi"]["errors"].get("0.0001")
        assert e is not None, "Jacobi at H=0.0001 is None"
        assert e < 1.0, f"Jacobi RMSE at H=0.0001 too large: {e}"

    def test_gs_small_h_accurate(self, results):
        e = results["gauss_seidel"]["errors"].get("0.0001")
        assert e is not None, "GS at H=0.0001 is None"
        assert e < 1.0, f"GS RMSE at H=0.0001 too large: {e}"


# ---------------------------------------------------------------------------
# Tests: independent cross-validation of GS at H=0.001
# ---------------------------------------------------------------------------


class TestIndependentVerification:
    def test_gs_h001(self, results, ground_truth):
        """Run an independent GS co-simulation at H=0.001 and compare."""
        t_gt, w_gt = ground_truth
        w_interp = interp1d(t_gt, w_gt, kind="cubic")

        H = 0.001
        N = 1000
        n_micro = 200
        h = H / n_micro

        x_i = 0.0
        i_a = 0.0
        w_load = 0.0
        w_val = 0.0

        t_out = [0.0]
        w_out = [0.0]

        for n in range(N):
            t_n = n * H
            wd = w_desired(t_n)
            tl = tau_load(t_n)

            # Controller first
            x_i += H * (wd - w_val)
            V = k_PI * ((wd - w_val) + x_i / T_PI)

            # Drive with RK4 micro-steps
            for _ in range(n_micro):
                d1a = (V - Ra * i_a - ke * ratio * w_load) / La
                d1w = (ke * ratio * i_a + tl) / J_eff

                ia2 = i_a + h / 2 * d1a
                wl2 = w_load + h / 2 * d1w
                d2a = (V - Ra * ia2 - ke * ratio * wl2) / La
                d2w = (ke * ratio * ia2 + tl) / J_eff

                ia3 = i_a + h / 2 * d2a
                wl3 = w_load + h / 2 * d2w
                d3a = (V - Ra * ia3 - ke * ratio * wl3) / La
                d3w = (ke * ratio * ia3 + tl) / J_eff

                ia4 = i_a + h * d3a
                wl4 = w_load + h * d3w
                d4a = (V - Ra * ia4 - ke * ratio * wl4) / La
                d4w = (ke * ratio * ia4 + tl) / J_eff

                i_a += h / 6 * (d1a + 2 * d2a + 2 * d3a + d4a)
                w_load += h / 6 * (d1w + 2 * d2w + 2 * d3w + d4w)

            w_val = ratio * w_load
            t_out.append(t_n + H)
            w_out.append(w_val)

        t_out = np.array(t_out)
        w_out = np.array(w_out)
        w_ref_c = w_interp(t_out)
        rmse_ind = float(np.sqrt(np.mean((w_out - w_ref_c) ** 2)))

        agent_rmse = results["gauss_seidel"]["errors"].get("0.001")
        assert agent_rmse is not None, "Agent GS RMSE at H=0.001 is None"

        rel = abs(agent_rmse - rmse_ind) / max(rmse_ind, 1e-12)
        assert rel < 0.5, (
            f"Agent GS RMSE={agent_rmse}, independent={rmse_ind}, "
            f"relative diff={rel:.1%}"
        )
