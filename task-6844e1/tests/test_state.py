"""
Tests for the dirty page write throttling simulation.

Verifies behavioral properties of the throttling functions, simulation
convergence, per-BDI distribution, and required analysis artifacts.
"""


import json
import math
import os
import subprocess
import sys

import pytest

sys.path.insert(0, "/app")

RESULTS_FILE = "/app/results/simulation.json"


@pytest.fixture(scope="session", autouse=True)
def run_sim():
    """Run the simulation once before all tests."""
    result = subprocess.run(
        [sys.executable, "/app/run.py"],
        capture_output=True,
        text=True,
        cwd="/app",
    )
    assert result.returncode == 0, (
        f"Simulation failed to run.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert os.path.exists(RESULTS_FILE), "Simulation did not produce results file"


@pytest.fixture
def history():
    with open(RESULTS_FILE) as f:
        data = json.load(f)
    assert len(data) >= 200, f"Need at least 200 ticks, got {len(data)}"
    return data


# -- Behavioral tests for throttle functions ---------------------------------


class TestPosRatio:
    """Verify behavioral requirements of the position ratio function."""

    def test_at_setpoint_returns_one(self):
        from throttle import pos_ratio_polynom
        r = pos_ratio_polynom(2400, 2400, 4000)
        assert abs(r - 1.0) < 1e-6, f"At setpoint: expected 1.0, got {r}"

    def test_at_limit_returns_zero(self):
        from throttle import pos_ratio_polynom
        r = pos_ratio_polynom(2400, 4000, 4000)
        assert abs(r) < 1e-6, f"At limit: expected 0.0, got {r}"

    def test_above_limit_returns_zero(self):
        from throttle import pos_ratio_polynom
        r = pos_ratio_polynom(2400, 5000, 4000)
        assert r == 0.0, f"Above limit: expected 0.0, got {r}"

    def test_below_setpoint_greater_than_one(self):
        from throttle import pos_ratio_polynom
        r = pos_ratio_polynom(2400, 1200, 4000)
        assert r > 1.0, f"Below setpoint: expected > 1.0, got {r}"

    def test_above_setpoint_less_than_one(self):
        from throttle import pos_ratio_polynom
        r = pos_ratio_polynom(2400, 3200, 4000)
        assert 0 < r < 1.0, f"Above setpoint: expected (0, 1), got {r}"

    def test_monotonically_nonincreasing(self):
        """Throttle factor must not increase as dirty count grows."""
        from throttle import pos_ratio_polynom
        prev = pos_ratio_polynom(2400, 0, 4000)
        for dirty in range(100, 4500, 100):
            cur = pos_ratio_polynom(2400, dirty, 4000)
            assert cur <= prev + 1e-9, (
                f"Not monotonically non-increasing at dirty={dirty}: "
                f"prev={prev:.6f}, cur={cur:.6f}"
            )
            prev = cur

    def test_never_negative(self):
        from throttle import pos_ratio_polynom
        for dirty in range(0, 6000, 100):
            r = pos_ratio_polynom(2400, dirty, 4000)
            assert r >= 0.0, f"Negative ratio at dirty={dirty}: {r}"

    def test_smooth_not_step(self):
        """The function must not be a step function — values between 0 and 1
        must exist in the range (setpoint, limit)."""
        from throttle import pos_ratio_polynom
        values = [pos_ratio_polynom(2400, d, 4000) for d in range(2500, 3900, 50)]
        # Filter to values strictly between 0 and 1
        interior = [v for v in values if 0.01 < v < 0.99]
        assert len(interior) >= 5, (
            f"Function appears to be a step function — only {len(interior)} "
            f"values between 0.01 and 0.99 in range (setpoint, limit)"
        )


class TestPauseCalculation:
    """Verify pause time computation at boundary conditions."""

    def test_zero_pages_no_pause(self):
        from throttle import calc_task_pause_ms
        assert calc_task_pause_ms(0, 10.0, 100.0) == 0.0

    def test_at_ratelimit_no_pause(self):
        from throttle import calc_task_pause_ms
        pause = calc_task_pause_ms(10, 10.0, 100.0)
        assert pause == 0.0, f"At ratelimit: expected 0, got {pause}"

    def test_above_ratelimit_pauses(self):
        from throttle import calc_task_pause_ms
        pause = calc_task_pause_ms(20, 10.0, 100.0)
        assert 0 < pause <= 200, f"At 2x ratelimit: expected positive pause, got {pause}"

    def test_capped_at_max(self):
        from throttle import calc_task_pause_ms, MAX_PAUSE_MS
        pause = calc_task_pause_ms(1000, 1.0, 100.0)
        assert pause == MAX_PAUSE_MS, f"Expected MAX_PAUSE_MS={MAX_PAUSE_MS}, got {pause}"

    def test_tiny_ratelimit_caps(self):
        from throttle import calc_task_pause_ms, MAX_PAUSE_MS
        pause = calc_task_pause_ms(10, 0.0001, 100.0)
        assert pause == MAX_PAUSE_MS


class TestWriterEstimation:
    """Verify the active writer estimation converges correctly."""

    def test_stable_estimate(self):
        from throttle import estimate_bdi_writers
        # 3 writers each dirtying at ratelimit 10 => total 30, ratelimit 10 => 3 writers
        est = 1.0
        for _ in range(100):
            est = estimate_bdi_writers(30.0, 10.0, est)
        assert abs(est - 3.0) < 0.5, f"Expected ~3.0 writers, got {est}"

    def test_always_at_least_one(self):
        from throttle import estimate_bdi_writers
        est = estimate_bdi_writers(0.0, 10.0, 1.0)
        assert est >= 1.0, f"Estimate below 1.0: {est}"

    def test_tiny_ratelimit_preserves(self):
        from throttle import estimate_bdi_writers
        est = estimate_bdi_writers(50.0, 0.0, 5.0)
        assert est >= 1.0


# -- Integration tests on simulation results ---------------------------------


class TestConvergence:
    """System dirty count must converge to the setpoint."""

    def test_converges_within_tolerance(self, history):
        setpoint = history[0]["setpoint"]
        last_200 = history[-200:]
        avg_dirty = sum(h["nr_dirty"] for h in last_200) / len(last_200)
        deviation = abs(avg_dirty - setpoint) / setpoint
        assert deviation < 0.10, (
            f"System did not converge: avg_dirty={avg_dirty:.0f}, "
            f"setpoint={setpoint}, deviation={deviation:.1%}"
        )

    def test_dirty_count_bounded(self, history):
        limit = history[0]["limit"]
        for h in history:
            assert h["nr_dirty"] <= limit * 1.05, (
                f"Tick {h['tick']}: nr_dirty={h['nr_dirty']} exceeds "
                f"limit={limit} by more than 5%"
            )

    def test_steady_state_stability(self, history):
        """Coefficient of variation in last 200 ticks must be < 15%."""
        last_200 = history[-200:]
        values = [h["nr_dirty"] for h in last_200]
        mean = sum(values) / len(values)
        assert mean > 0, "Mean dirty count is zero -- no pages were dirtied"
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        cv = math.sqrt(variance) / mean
        assert cv < 0.15, (
            f"System unstable: mean={mean:.0f}, "
            f"std_dev={math.sqrt(variance):.0f}, CV={cv:.2%}"
        )


class TestBDIDistribution:
    """BDI dirty pages should be proportional to device bandwidth."""

    def test_proportional_to_bandwidth(self, history):
        last_100 = history[-100:]
        avg_ssd = sum(h["bdi"]["ssd"]["dirty"] for h in last_100) / len(last_100)
        avg_hdd = sum(h["bdi"]["hdd"]["dirty"] for h in last_100) / len(last_100)

        assert avg_hdd > 0, "HDD has zero dirty pages -- BDI balancing broken"
        ratio = avg_ssd / avg_hdd
        # SSD bandwidth / HDD bandwidth = 100/20 = 5.0
        # Accept 2.0 to 12.0 for simulation noise
        assert 2.0 <= ratio <= 12.0, (
            f"BDI distribution skewed: ssd_avg={avg_ssd:.0f}, "
            f"hdd_avg={avg_hdd:.0f}, ratio={ratio:.1f} (expected ~5.0)"
        )

    def test_both_bdis_have_dirty_pages(self, history):
        last_50 = history[-50:]
        for h in last_50:
            assert h["bdi"]["ssd"]["dirty"] > 0, (
                f"Tick {h['tick']}: SSD has 0 dirty pages"
            )
            assert h["bdi"]["hdd"]["dirty"] > 0, (
                f"Tick {h['tick']}: HDD has 0 dirty pages"
            )


class TestGlobalAccounting:
    """Global dirty count must equal sum of per-BDI counts."""

    def test_accounting_consistency(self, history):
        for h in history[-100:]:
            bdi_sum = sum(s["dirty"] for s in h["bdi"].values())
            diff = abs(h["nr_dirty"] - bdi_sum)
            assert diff < 1.0, (
                f"Tick {h['tick']}: nr_dirty={h['nr_dirty']:.1f} != "
                f"sum(bdi.dirty)={bdi_sum:.1f} (diff={diff:.1f}) -- accounting bug"
            )


class TestArtifacts:
    """Verify required analysis artifacts exist and are valid."""

    def test_convergence_plot_exists(self):
        plot_path = "/app/results/convergence.png"
        assert os.path.exists(plot_path), (
            "Convergence plot not found at /app/results/convergence.png"
        )
        size = os.path.getsize(plot_path)
        assert size > 1000, (
            f"Convergence plot file is too small ({size} bytes), likely empty or corrupt"
        )

    def test_analysis_json_valid(self):
        analysis_path = "/app/results/analysis.json"
        assert os.path.exists(analysis_path), (
            "Analysis JSON not found at /app/results/analysis.json"
        )
        with open(analysis_path) as f:
            data = json.load(f)

        required_keys = ["converged", "avg_dirty", "setpoint", "cv_pct", "bdi_ratio"]
        for key in required_keys:
            assert key in data, f"Missing key '{key}' in analysis.json"

        assert data["converged"] is True, "Analysis reports system did not converge"
        assert 2000 < data["avg_dirty"] < 2800, (
            f"avg_dirty={data['avg_dirty']} outside expected range (2000, 2800)"
        )
        assert data["setpoint"] == 2400, f"setpoint={data['setpoint']}, expected 2400"
        assert data["cv_pct"] < 15.0, f"cv_pct={data['cv_pct']}, expected < 15.0"
        assert 2.0 < data["bdi_ratio"] < 12.0, (
            f"bdi_ratio={data['bdi_ratio']}, expected between 2.0 and 12.0"
        )
