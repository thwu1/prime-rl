"""
Tests for the dirty page write throttling controller.

Verifies controller function properties (unit), end-to-end simulation
behavior across three scenarios (integration), and required output
artifacts (gnuplot PNG, jq summary JSON).

"""

import json
import os
import subprocess
import sys
import importlib.util

import pytest


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SETPOINT = 0.40
LIMIT = 0.60

# Per-scenario total bandwidth
SCENARIO_BW = {"symmetric": 125.0, "bursty": 125.0, "asymmetric": 240.0}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def ctrl():
    """Import the controller module for direct unit testing."""
    spec = importlib.util.spec_from_file_location(
        "controller", "/app/controller.py")
    assert spec is not None and spec.loader is not None, \
        "Controller not found at /app/controller.py"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def all_metrics():
    """Run the full simulation framework and load all metrics."""
    r = subprocess.run(
        [sys.executable, "/app/framework.py"],
        capture_output=True, text=True, timeout=180,
    )
    assert r.returncode == 0, (
        f"Framework crashed:\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}")
    metrics = {}
    for name in ["symmetric", "bursty", "asymmetric"]:
        path = f"/app/output/{name}_metrics.json"
        assert os.path.exists(path), f"Missing output: {path}"
        with open(path) as f:
            metrics[name] = json.load(f)
    return metrics


# ---------------------------------------------------------------------------
# Unit tests — calc_pos_ratio
# ---------------------------------------------------------------------------

class TestCalcPosRatio:
    """Position ratio must satisfy boundary conditions and monotonicity."""

    SP = 40000
    LIM = 60000

    def test_at_setpoint(self, ctrl):
        r = ctrl.calc_pos_ratio(self.SP, self.SP, self.LIM)
        assert abs(r - 1.0) < 0.01, f"Ratio at setpoint: {r}"

    def test_at_limit(self, ctrl):
        r = ctrl.calc_pos_ratio(self.LIM, self.SP, self.LIM)
        assert r == 0.0, f"Ratio at limit: {r}"

    def test_above_limit(self, ctrl):
        r = ctrl.calc_pos_ratio(self.LIM + 1000, self.SP, self.LIM)
        assert r == 0.0, f"Ratio above limit: {r}"

    def test_at_zero(self, ctrl):
        r = ctrl.calc_pos_ratio(0, self.SP, self.LIM)
        assert abs(r - 2.0) < 0.01, f"Ratio at zero: {r}"

    def test_negative_feedback_above(self, ctrl):
        """Ratio < 1 when dirty exceeds setpoint."""
        r = ctrl.calc_pos_ratio(50000, self.SP, self.LIM)
        assert r < 1.0, f"Ratio above setpoint: {r}"

    def test_negative_feedback_below(self, ctrl):
        """Ratio > 1 when dirty is below setpoint."""
        r = ctrl.calc_pos_ratio(30000, self.SP, self.LIM)
        assert r > 1.0, f"Ratio below setpoint: {r}"

    def test_monotone_decreasing(self, ctrl):
        prev = ctrl.calc_pos_ratio(0, self.SP, self.LIM)
        for d in range(2000, self.LIM + 1, 2000):
            cur = ctrl.calc_pos_ratio(d, self.SP, self.LIM)
            assert cur <= prev + 0.001, (
                f"Monotonicity violated: {prev:.4f} -> {cur:.4f} at {d}")
            prev = cur

    def test_clamped_low(self, ctrl):
        """Ratio never negative."""
        for d in range(0, 80000, 5000):
            r = ctrl.calc_pos_ratio(d, self.SP, self.LIM)
            assert r >= 0.0, f"Negative ratio at dirty={d}: {r}"

    def test_clamped_high(self, ctrl):
        """Ratio never exceeds 2.0."""
        for d in range(0, 80000, 5000):
            r = ctrl.calc_pos_ratio(d, self.SP, self.LIM)
            assert r <= 2.0, f"Ratio > 2.0 at dirty={d}: {r}"


# ---------------------------------------------------------------------------
# Unit tests — bdi_pos_ratio
# ---------------------------------------------------------------------------

class TestBdiPosRatio:
    """BDI adjustment must respect fair-share deviation."""

    def test_fair_share_neutral(self, ctrl):
        """When BDI has its fair share, ratio ≈ base."""
        # BDI has 80% of dirty, 80% of bandwidth → fair
        r = ctrl.bdi_pos_ratio(1.0, 8000, 100.0, 10000, 125.0)
        assert abs(r - 1.0) < 0.05, f"Fair-share ratio: {r}"

    def test_under_represented_relaxed(self, ctrl):
        """Under-represented BDI gets higher ratio (relaxed)."""
        # BDI has 50% of dirty but 80% of bandwidth → under-represented
        r = ctrl.bdi_pos_ratio(1.0, 5000, 100.0, 10000, 125.0)
        assert r > 1.0, f"Under-represented ratio: {r}"

    def test_over_represented_tightened(self, ctrl):
        """Over-represented BDI gets lower ratio (tightened)."""
        # BDI has 95% of dirty but 80% of bandwidth → over-represented
        r = ctrl.bdi_pos_ratio(1.0, 9500, 100.0, 10000, 125.0)
        assert r < 1.0, f"Over-represented ratio: {r}"

    def test_zero_sys_dirty(self, ctrl):
        """Returns base_ratio when sys_dirty is zero."""
        r = ctrl.bdi_pos_ratio(1.5, 0, 100.0, 0, 125.0)
        assert abs(r - 1.5) < 0.01, f"Zero sys_dirty ratio: {r}"

    def test_clamped(self, ctrl):
        """Result always in [0, 2]."""
        r = ctrl.bdi_pos_ratio(2.0, 0, 200.0, 100, 200.0)
        assert 0.0 <= r <= 2.0, f"Unclamped ratio: {r}"


# ---------------------------------------------------------------------------
# Unit tests — compute_pause
# ---------------------------------------------------------------------------

class TestComputePause:
    """Pause must be proportional, bounded, and correct at edges."""

    def test_no_overshoot(self, ctrl):
        """No pause when want_rate <= allowed."""
        p = ctrl.compute_pause(20.0, 100.0, 1.0, 4, 10.0, 200.0)
        # allowed = 100/4 * 1.0 = 25 >= 20
        assert p == 0.0, f"Unexpected pause: {p}"

    def test_overshoot(self, ctrl):
        """Positive pause when want_rate > allowed."""
        p = ctrl.compute_pause(40.0, 100.0, 1.0, 4, 10.0, 200.0)
        # allowed = 25, overshoot = 15, pause = 10*15/40 = 3.75
        assert 3.0 < p < 5.0, f"Pause out of range: {p}"

    def test_full_stop(self, ctrl):
        """Max pause when allowed ≈ 0."""
        p = ctrl.compute_pause(40.0, 100.0, 0.0, 4, 10.0, 200.0)
        assert p == 200.0, f"Full stop pause: {p}"

    def test_clamped_at_max(self, ctrl):
        """Pause never exceeds max_pause_ms."""
        p = ctrl.compute_pause(1000.0, 1.0, 0.001, 10, 10.0, 200.0)
        assert p <= 200.0, f"Pause exceeds max: {p}"

    def test_non_negative(self, ctrl):
        """Pause is never negative."""
        for wr in [1.0, 10.0, 100.0]:
            for rl in [1.0, 50.0, 200.0]:
                for br in [0.0, 0.5, 1.0, 2.0]:
                    p = ctrl.compute_pause(wr, rl, br, 4, 10.0, 200.0)
                    assert p >= 0.0, (
                        f"Negative pause: {p} for wr={wr},rl={rl},br={br}")


# ---------------------------------------------------------------------------
# Unit tests — update_ratelimit
# ---------------------------------------------------------------------------

class TestUpdateRatelimit:
    """EWMA ratelimit must converge and stay non-negative."""

    def test_convergence(self, ctrl):
        """After many iterations, ratelimit converges to target."""
        val = 50.0
        target = 100.0
        for _ in range(200):
            val = ctrl.update_ratelimit(val, target, 0.125)
        assert abs(val - target) < 0.01, f"Did not converge: {val}"

    def test_no_smoothing(self, ctrl):
        """With smoothing=0, ratelimit unchanged."""
        r = ctrl.update_ratelimit(50.0, 100.0, 0.0)
        assert r == 50.0, f"Changed with smoothing=0: {r}"

    def test_full_smoothing(self, ctrl):
        """With smoothing=1, jumps immediately to target."""
        r = ctrl.update_ratelimit(50.0, 100.0, 1.0)
        assert abs(r - 100.0) < 0.01, f"Didn't jump: {r}"

    def test_non_negative(self, ctrl):
        """Result is always non-negative."""
        r = ctrl.update_ratelimit(1.0, -10.0, 0.5)
        assert r >= 0.0, f"Negative ratelimit: {r}"


# ---------------------------------------------------------------------------
# Integration — symmetric scenario
# ---------------------------------------------------------------------------

class TestSymmetric:
    """Steady-state convergence with SSD + HDD."""

    def test_convergence(self, all_metrics):
        avg = all_metrics["symmetric"]["avg_tail_dirty_ratio"]
        assert abs(avg - SETPOINT) < 0.10, (
            f"Avg dirty ratio {avg:.4f} not near setpoint {SETPOINT}")

    def test_below_limit(self, all_metrics):
        above = all_metrics["symmetric"]["ticks_above_limit"]
        assert above < 50, f"{above} ticks above limit"

    def test_stability(self, all_metrics):
        m = all_metrics["symmetric"]
        rng = m["max_tail_dirty_ratio"] - m["min_tail_dirty_ratio"]
        assert rng < 0.20, f"Tail range {rng:.4f} too wide"

    def test_max_pause(self, all_metrics):
        mp = all_metrics["symmetric"]["max_pause_ms"]
        assert mp <= 201.0, f"Max pause {mp:.2f} ms"

    def test_no_negative_pauses(self, all_metrics):
        assert all_metrics["symmetric"]["negative_pauses"] == 0

    def test_throughput(self, all_metrics):
        tp = all_metrics["symmetric"]["avg_tail_throughput"]
        assert tp > 75.0, f"Throughput {tp:.1f} too low"

    def test_ssd_share(self, all_metrics):
        share = all_metrics["symmetric"]["avg_tail_bdi_ssd_share"]
        assert share > 0.55, f"SSD share {share:.4f} too low"

    def test_hdd_share(self, all_metrics):
        share = all_metrics["symmetric"]["avg_tail_bdi_hdd_share"]
        assert share < 0.45, f"HDD share {share:.4f} too high"


# ---------------------------------------------------------------------------
# Integration — bursty scenario
# ---------------------------------------------------------------------------

class TestBursty:
    """Adaptation under time-varying workloads."""

    def test_convergence(self, all_metrics):
        avg = all_metrics["bursty"]["avg_tail_dirty_ratio"]
        assert abs(avg - SETPOINT) < 0.15, (
            f"Avg dirty ratio {avg:.4f} not near setpoint")

    def test_below_limit(self, all_metrics):
        above = all_metrics["bursty"]["ticks_above_limit"]
        assert above < 200, f"{above} ticks above limit"

    def test_max_pause(self, all_metrics):
        mp = all_metrics["bursty"]["max_pause_ms"]
        assert mp <= 201.0, f"Max pause {mp:.2f} ms"

    def test_no_negative_pauses(self, all_metrics):
        assert all_metrics["bursty"]["negative_pauses"] == 0

    def test_throughput(self, all_metrics):
        tp = all_metrics["bursty"]["avg_tail_throughput"]
        assert tp > 60.0, f"Throughput {tp:.1f} too low"


# ---------------------------------------------------------------------------
# Integration — asymmetric scenario
# ---------------------------------------------------------------------------

class TestAsymmetric:
    """BDI fairness with NVMe + SATA."""

    def test_convergence(self, all_metrics):
        avg = all_metrics["asymmetric"]["avg_tail_dirty_ratio"]
        assert abs(avg - SETPOINT) < 0.10, (
            f"Avg dirty ratio {avg:.4f} not near setpoint")

    def test_below_limit(self, all_metrics):
        above = all_metrics["asymmetric"]["ticks_above_limit"]
        assert above < 50, f"{above} ticks above limit"

    def test_max_pause(self, all_metrics):
        mp = all_metrics["asymmetric"]["max_pause_ms"]
        assert mp <= 201.0, f"Max pause {mp:.2f} ms"

    def test_no_negative_pauses(self, all_metrics):
        assert all_metrics["asymmetric"]["negative_pauses"] == 0

    def test_throughput(self, all_metrics):
        tp = all_metrics["asymmetric"]["avg_tail_throughput"]
        assert tp > 144.0, f"Throughput {tp:.1f} too low"

    def test_nvme_share(self, all_metrics):
        share = all_metrics["asymmetric"]["avg_tail_bdi_nvme_share"]
        assert share > 0.60, f"NVMe share {share:.4f} too low"

    def test_sata_share(self, all_metrics):
        share = all_metrics["asymmetric"]["avg_tail_bdi_sata_share"]
        assert share < 0.40, f"SATA share {share:.4f} too high"


# ---------------------------------------------------------------------------
# Output artifacts
# ---------------------------------------------------------------------------

class TestGnuplotOutput:
    """gnuplot convergence plot must exist and be a valid PNG."""

    def test_png_exists(self, all_metrics):
        assert os.path.exists("/app/output/convergence.png"), \
            "Missing /app/output/convergence.png"

    def test_png_valid(self, all_metrics):
        with open("/app/output/convergence.png", "rb") as f:
            header = f.read(8)
        assert header[:4] == b'\x89PNG', \
            "convergence.png is not a valid PNG file"

    def test_png_nontrivial(self, all_metrics):
        size = os.path.getsize("/app/output/convergence.png")
        assert size > 1000, f"PNG too small ({size} bytes)"


class TestSummaryJson:
    """jq-generated summary must have correct structure and values."""

    def test_exists(self, all_metrics):
        assert os.path.exists("/app/output/summary.json"), \
            "Missing /app/output/summary.json"

    def test_valid_json(self, all_metrics):
        with open("/app/output/summary.json") as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_structure(self, all_metrics):
        with open("/app/output/summary.json") as f:
            data = json.load(f)
        for scenario in ["symmetric", "bursty", "asymmetric"]:
            assert scenario in data, f"Missing scenario '{scenario}'"
            for key in ["avg_tail_dirty_ratio", "max_pause_ms",
                        "avg_tail_throughput"]:
                assert key in data[scenario], (
                    f"Missing '{key}' in '{scenario}'")
                assert isinstance(data[scenario][key], (int, float)), (
                    f"'{key}' in '{scenario}' is not numeric")

    def test_dirty_ratio_reasonable(self, all_metrics):
        with open("/app/output/summary.json") as f:
            data = json.load(f)
        for scenario in ["symmetric", "bursty", "asymmetric"]:
            dr = data[scenario]["avg_tail_dirty_ratio"]
            assert 0.0 < dr < 1.0, (
                f"Dirty ratio {dr} out of range in '{scenario}'")
