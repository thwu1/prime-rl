"""
Tests for the fixed pipeline simulator.


Verifies that the pipeline:
  - Sheds load under sustained overload
  - Uses bounded queues
  - Recovers to low latency after overload subsides
  - Reports CO-corrected latency metrics
  - Maintains accurate request accounting
"""

import json
import os

import pytest

RESULTS = "/app/results.json"


@pytest.fixture(scope="module")
def results():
    assert os.path.exists(RESULTS), (
        "results.json not found — run the simulation first"
    )
    with open(RESULTS) as f:
        return json.load(f)


# ------------------------------------------------------------------ #
# Structure                                                           #
# ------------------------------------------------------------------ #

class TestStructure:
    """Results file has the required top-level and per-phase fields."""

    def test_top_level_fields(self, results):
        for key in [
            "total_arrived",
            "total_completed",
            "total_rejected",
            "in_flight_at_end",
            "max_queue_depths",
            "phases",
        ]:
            assert key in results, f"Missing top-level field: {key}"

    def test_phase_names(self, results):
        for phase in ["normal", "overload", "recovery"]:
            assert phase in results["phases"], f"Missing phase: {phase}"

    def test_phase_fields(self, results):
        required = ["arrived", "completed", "rejected", "p99_ms"]
        for pname in ["normal", "overload", "recovery"]:
            p = results["phases"][pname]
            for key in required:
                assert key in p, f"Missing field {key} in phase {pname}"

    def test_total_arrived_plausible(self, results):
        # 200*10 + 2000*10 + 200*10 = 24000
        assert 23000 <= results["total_arrived"] <= 25000


# ------------------------------------------------------------------ #
# Request accounting                                                  #
# ------------------------------------------------------------------ #

class TestAccounting:
    """Every request is accounted for: completed + rejected + in_flight."""

    def test_global_accounting(self, results):
        total = (
            results["total_completed"]
            + results["total_rejected"]
            + results["in_flight_at_end"]
        )
        assert total == results["total_arrived"], (
            f"Accounting mismatch: {results['total_completed']} completed "
            f"+ {results['total_rejected']} rejected "
            f"+ {results['in_flight_at_end']} in-flight "
            f"!= {results['total_arrived']} arrived"
        )

    def test_per_phase_accounting(self, results):
        for pname in ["normal", "overload", "recovery"]:
            p = results["phases"][pname]
            assert p["completed"] + p["rejected"] <= p["arrived"], (
                f"{pname}: completed ({p['completed']}) + rejected ({p['rejected']}) "
                f"> arrived ({p['arrived']})"
            )


# ------------------------------------------------------------------ #
# Load shedding                                                       #
# ------------------------------------------------------------------ #

class TestLoadShedding:
    """Excess requests must be explicitly rejected during overload."""

    def test_overall_rejections(self, results):
        assert results["total_rejected"] > 0, "No requests rejected — load shedding missing"

    def test_overload_rejections(self, results):
        ov = results["phases"]["overload"]
        assert ov["rejected"] > 0, "No rejections during overload phase"

    def test_normal_minimal_rejections(self, results):
        nm = results["phases"]["normal"]
        # Under normal load (well within capacity) rejections should be negligible
        threshold = max(2, int(nm["arrived"] * 0.01))
        assert nm["rejected"] <= threshold, (
            f"Normal phase had {nm['rejected']} rejections "
            f"(>{threshold}) — queue bounds too aggressive"
        )


# ------------------------------------------------------------------ #
# Bounded queues                                                      #
# ------------------------------------------------------------------ #

class TestBoundedQueues:
    """Queue depths must be bounded — not growing to 10,000+."""

    def test_queue_depths_bounded(self, results):
        for stage, depth in results["max_queue_depths"].items():
            assert depth <= 200, (
                f"Queue '{stage}' reached depth {depth} — "
                f"likely unbounded (expected <= 200)"
            )

    def test_queue_depths_positive(self, results):
        # At least one queue should have been non-empty at some point
        assert any(d > 0 for d in results["max_queue_depths"].values())


# ------------------------------------------------------------------ #
# Latency                                                             #
# ------------------------------------------------------------------ #

class TestLatency:
    """Tail latency must stay bounded in normal and recovery phases."""

    def test_normal_p99(self, results):
        p99 = results["phases"]["normal"]["p99_ms"]
        assert p99 < 50, f"Normal phase P99 = {p99:.1f} ms (expected < 50)"

    def test_recovery_p50(self, results):
        # P50 verifies that the majority of recovery-phase requests
        # complete at normal latency (the drain period affects only the
        # first few hundred ms of requests).
        p50 = results["phases"]["recovery"].get("p50_ms", 0)
        assert p50 < 30, f"Recovery phase P50 = {p50:.1f} ms (expected < 30)"

    def test_recovery_p99(self, results):
        # After overload the bounded queues need ~0.5-2 s to drain.
        # Requests arriving during the drain see elevated latency, so
        # we allow a generous P99 ceiling.  The important thing is that
        # the system *does* recover (tested separately by TestRecovery).
        p99 = results["phases"]["recovery"]["p99_ms"]
        assert p99 < 1000, f"Recovery phase P99 = {p99:.1f} ms (expected < 1000)"

    def test_overload_completed_bounded(self, results):
        # With load shedding, completed requests should not have
        # multi-second latencies like the broken system (16 000+ ms).
        p99 = results["phases"]["overload"]["p99_ms"]
        assert p99 < 1000, (
            f"Overload completed-request P99 = {p99:.1f} ms "
            f"(expected < 1000 with load shedding)"
        )

    def test_not_broken(self, results):
        # The broken system has overall P99 > 10 000 ms.
        # Any reasonable fix must bring it well below that.
        overall_p99 = results.get("overall_latency", {}).get("p99_ms", 0)
        assert overall_p99 < 5000, (
            f"Overall P99 = {overall_p99:.1f} ms — system likely still broken"
        )


# ------------------------------------------------------------------ #
# Recovery                                                            #
# ------------------------------------------------------------------ #

class TestRecovery:
    """System must drain its queues and return to normal after overload."""

    def test_in_flight_drains(self, results):
        assert results["in_flight_at_end"] <= 10, (
            f"{results['in_flight_at_end']} requests still in flight at t=30 s — "
            f"system did not recover"
        )

    def test_recovery_completions(self, results):
        rec = results["phases"]["recovery"]
        if rec["arrived"] > 0:
            ratio = rec["completed"] / rec["arrived"]
            assert ratio > 0.90, (
                f"Only {ratio:.0%} of recovery-phase requests completed "
                f"(expected > 90%)"
            )


# ------------------------------------------------------------------ #
# Coordinated-omission correction                                     #
# ------------------------------------------------------------------ #

class TestCOCorrection:
    """CO-corrected metrics must be present and mathematically sound."""

    def test_corrected_field_exists(self, results):
        for pname in ["normal", "overload", "recovery"]:
            assert "p99_corrected_ms" in results["phases"][pname], (
                f"Missing p99_corrected_ms in {pname} phase"
            )

    def test_corrected_is_numeric(self, results):
        for pname in ["normal", "overload", "recovery"]:
            val = results["phases"][pname]["p99_corrected_ms"]
            assert isinstance(val, (int, float)), (
                f"p99_corrected_ms in {pname} is {type(val).__name__}, not numeric"
            )
            assert val >= 0, f"p99_corrected_ms in {pname} is negative"

    def test_corrected_ge_naive(self, results):
        for pname in ["normal", "overload", "recovery"]:
            p = results["phases"][pname]
            # Corrected P99 should be >= naive P99 (within small tolerance
            # for index-shift effects when adding few low-latency in-flight
            # points to a large completed-request distribution)
            assert p["p99_corrected_ms"] >= p["p99_ms"] - 1.0, (
                f"{pname}: corrected P99 ({p['p99_corrected_ms']:.2f}) "
                f"significantly below naive P99 ({p['p99_ms']:.2f})"
            )
