"""
Tests for symplectic integrator convergence benchmark.

"""

import json
import os
import pytest


RESULTS_PATH = "/app/results.json"


@pytest.fixture
def results():
    assert os.path.exists(RESULTS_PATH), (
        f"Results file not found at {RESULTS_PATH}. "
        "Run the benchmark first."
    )
    with open(RESULTS_PATH) as f:
        return json.load(f)


# ───────────────────────────────────────────────────────────
#  Structural checks
# ───────────────────────────────────────────────────────────

class TestStructure:
    def test_results_file_exists(self):
        assert os.path.exists(RESULTS_PATH)

    def test_required_keys(self, results):
        for key in [
            "velocity_verlet_order",
            "forest_ruth_order",
            "pefrl_order",
            "velocity_verlet_errors",
            "forest_ruth_errors",
            "pefrl_errors",
            "pefrl_to_fr_error_ratio",
            "fr_force_evals",
            "pefrl_force_evals",
        ]:
            assert key in results, f"Missing required key: {key}"

    def test_orders_are_numeric(self, results):
        for name in ["velocity_verlet", "forest_ruth", "pefrl"]:
            val = results[f"{name}_order"]
            assert isinstance(val, (int, float)), (
                f"{name}_order must be numeric, got {type(val)}"
            )

    def test_errors_dicts_nonempty(self, results):
        for name in ["velocity_verlet", "forest_ruth", "pefrl"]:
            errs = results[f"{name}_errors"]
            assert isinstance(errs, dict), f"{name}_errors must be a dict"
            assert len(errs) >= 3, (
                f"{name}_errors should have at least 3 timestep entries"
            )


# ───────────────────────────────────────────────────────────
#  Convergence-order checks
# ───────────────────────────────────────────────────────────

class TestConvergenceOrders:
    def test_velocity_verlet_order(self, results):
        order = results["velocity_verlet_order"]
        assert 1.8 <= order <= 2.2, (
            f"Velocity Verlet should be 2nd order, got {order:.4f}"
        )

    def test_forest_ruth_order(self, results):
        order = results["forest_ruth_order"]
        assert 3.6 <= order <= 4.4, (
            f"Forest-Ruth should be 4th order, got {order:.4f}"
        )

    def test_pefrl_order(self, results):
        order = results["pefrl_order"]
        assert 3.6 <= order <= 4.4, (
            f"PEFRL should be 4th order, got {order:.4f}"
        )

    def test_4th_order_exceeds_2nd_order(self, results):
        vv = results["velocity_verlet_order"]
        fr = results["forest_ruth_order"]
        pe = results["pefrl_order"]
        assert fr > vv + 1.0, (
            f"Forest-Ruth order ({fr:.2f}) should be well above "
            f"Velocity Verlet ({vv:.2f})"
        )
        assert pe > vv + 1.0, (
            f"PEFRL order ({pe:.2f}) should be well above "
            f"Velocity Verlet ({vv:.2f})"
        )


# ───────────────────────────────────────────────────────────
#  Error-value checks
# ───────────────────────────────────────────────────────────

class TestErrorValues:
    def test_errors_are_positive(self, results):
        for name in ["velocity_verlet", "forest_ruth", "pefrl"]:
            for dt_str, err in results[f"{name}_errors"].items():
                assert err > 0, (
                    f"{name} at dt={dt_str}: error must be positive"
                )

    def test_errors_decrease_with_smaller_dt(self, results):
        """Errors should decrease monotonically as dt shrinks."""
        for name in ["velocity_verlet", "forest_ruth", "pefrl"]:
            errs = results[f"{name}_errors"]
            sorted_items = sorted(errs.items(), key=lambda kv: float(kv[0]))
            for i in range(len(sorted_items) - 1):
                dt_small, err_small = sorted_items[i]
                dt_large, err_large = sorted_items[i + 1]
                assert err_small < err_large, (
                    f"{name}: error at dt={dt_small} ({err_small:.4e}) "
                    f"should be < error at dt={dt_large} ({err_large:.4e})"
                )

    def test_4th_order_small_dt_accuracy(self, results):
        """At the smallest timestep, 4th-order methods must conserve
        energy to within 0.1% relative error."""
        for name in ["forest_ruth", "pefrl"]:
            errs = results[f"{name}_errors"]
            smallest_dt = min(errs.keys(), key=float)
            err = errs[smallest_dt]
            assert err < 1e-3, (
                f"{name} at dt={smallest_dt}: error {err:.4e} exceeds 1e-3"
            )

    def test_pefrl_more_accurate_than_forest_ruth(self, results):
        ratio = results["pefrl_to_fr_error_ratio"]
        assert 0 < ratio < 0.5, (
            f"PEFRL should have < 50% of Forest-Ruth's error, "
            f"got ratio = {ratio:.4f}"
        )


# ───────────────────────────────────────────────────────────
#  Force-evaluation counts
# ───────────────────────────────────────────────────────────

class TestForceEvals:
    def test_fr_force_evals(self, results):
        assert results["fr_force_evals"] == 3, (
            "Forest-Ruth requires exactly 3 force evaluations per step"
        )

    def test_pefrl_force_evals(self, results):
        assert results["pefrl_force_evals"] == 4, (
            "PEFRL requires exactly 4 force evaluations per step"
        )


# ───────────────────────────────────────────────────────────
#  Cross-consistency checks
# ───────────────────────────────────────────────────────────

class TestCrossConsistency:
    def test_fr_errors_larger_than_pefrl(self, results):
        """At every common timestep, PEFRL error < Forest-Ruth error."""
        fr = results["forest_ruth_errors"]
        pe = results["pefrl_errors"]
        common = set(fr.keys()) & set(pe.keys())
        assert len(common) >= 2, "Need at least 2 common timesteps"
        for dt_str in common:
            assert pe[dt_str] < fr[dt_str], (
                f"At dt={dt_str}: PEFRL error ({pe[dt_str]:.4e}) should be "
                f"less than Forest-Ruth error ({fr[dt_str]:.4e})"
            )

    def test_vv_errors_larger_than_4th_order(self, results):
        """At every common timestep, VV error > 4th-order errors."""
        vv = results["velocity_verlet_errors"]
        for name in ["forest_ruth", "pefrl"]:
            other = results[f"{name}_errors"]
            common = set(vv.keys()) & set(other.keys())
            for dt_str in common:
                assert vv[dt_str] > other[dt_str], (
                    f"VV error at dt={dt_str} ({vv[dt_str]:.4e}) should "
                    f"exceed {name} error ({other[dt_str]:.4e})"
                )
