"""Tests for the QUIC Multipath CUBIC Congestion Control Simulator."""
import json
import math
import os
import subprocess
import sys
import pytest

sys.path.insert(0, '/app')


def run_scenario(scenario, base_path):
    """Run a scenario through the simulator CLI and return parsed output."""
    os.makedirs(base_path, exist_ok=True)
    scenario_path = os.path.join(str(base_path), "scenario.json")
    output_path = os.path.join(str(base_path), "output.json")
    with open(scenario_path, 'w') as f:
        json.dump(scenario, f)
    result = subprocess.run(
        ['python3', '/app/simulator.py', '--scenario', scenario_path, '--output', output_path],
        capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, f"Simulator failed with stderr: {result.stderr}"
    assert os.path.exists(output_path), "Output file not created"
    with open(output_path) as f:
        return json.load(f)


STANDARD_PARAMS = {
    "mss_bytes": 1200,
    "cubic_C": 0.4,
    "cubic_beta": 0.7,
    "ecn_beta": 0.85,
    "initial_cwnd_mss": 10
}


class TestCLIInterface:
    """Test the command-line interface and output format."""

    def test_basic_scenario_produces_output(self, tmp_path):
        """Simulator should run and produce valid JSON output."""
        scenario = {
            "params": STANDARD_PARAMS,
            "paths": [{"id": 0, "rtt_ms": 100}],
            "events": [{"time_ms": 500, "type": "loss", "path_id": 0}],
            "duration_ms": 5000
        }
        output = run_scenario(scenario, tmp_path)
        assert "paths" in output
        assert "0" in output["paths"]
        assert "total_bytes_delivered" in output

    def test_output_has_required_fields(self, tmp_path):
        """Output must contain all required per-path fields."""
        scenario = {
            "params": STANDARD_PARAMS,
            "paths": [{"id": 0, "rtt_ms": 50}],
            "events": [
                {"time_ms": 200, "type": "loss", "path_id": 0},
                {"time_ms": 1000, "type": "ecn", "path_id": 0}
            ],
            "duration_ms": 3000
        }
        output = run_scenario(scenario, tmp_path)
        path_data = output["paths"]["0"]
        for field in ["final_cwnd_bytes", "loss_events", "ecn_events",
                      "spurious_recoveries", "bytes_delivered", "cwnd_at_events"]:
            assert field in path_data, f"Missing required field: {field}"

    def test_cwnd_at_events_has_fields(self, tmp_path):
        """Each cwnd_at_events entry must have time, cwnd, and event_type."""
        scenario = {
            "params": STANDARD_PARAMS,
            "paths": [{"id": 0, "rtt_ms": 50}],
            "events": [{"time_ms": 100, "type": "loss", "path_id": 0}],
            "duration_ms": 1000
        }
        output = run_scenario(scenario, tmp_path)
        events = output["paths"]["0"]["cwnd_at_events"]
        assert len(events) >= 1
        ev = events[0]
        assert "time_ms" in ev
        assert "cwnd_after_bytes" in ev
        assert "event_type" in ev


class TestSlowStart:
    """Test slow start behavior."""

    def test_exponential_growth_before_loss(self, tmp_path):
        """In slow start, cwnd should approximately double each RTT."""
        # RTT=100ms, loss at 300ms = 3 RTTs. cwnd should be ~10 * 2^3 = 80 MSS
        scenario = {
            "params": STANDARD_PARAMS,
            "paths": [{"id": 0, "rtt_ms": 100}],
            "events": [{"time_ms": 300, "type": "loss", "path_id": 0}],
            "duration_ms": 500
        }
        output = run_scenario(scenario, tmp_path)
        loss_cwnd = output["paths"]["0"]["cwnd_at_events"][0]["cwnd_after_bytes"]
        # Pre-loss cwnd = 10 * 2^3 * 1200 = 96000
        # Post-loss = 96000 * 0.7 = 67200
        expected_post_loss = 10 * (2 ** 3) * 1200 * 0.7
        assert abs(loss_cwnd - expected_post_loss) / expected_post_loss < 0.05, \
            f"Post-loss cwnd {loss_cwnd} not close to expected {expected_post_loss}"

    def test_loss_exits_slow_start(self, tmp_path):
        """After a loss, the controller should not be in slow start."""
        scenario = {
            "params": STANDARD_PARAMS,
            "paths": [{"id": 0, "rtt_ms": 50}],
            "events": [{"time_ms": 100, "type": "loss", "path_id": 0}],
            "duration_ms": 5000
        }
        output = run_scenario(scenario, tmp_path)
        # After loss at 100ms, cwnd should grow via CUBIC, not exponentially
        # At 5000ms, if still in slow start, cwnd would be astronomical
        # With CUBIC recovery from ~28 MSS, cwnd should be much smaller
        final_cwnd = output["paths"]["0"]["final_cwnd_bytes"]
        # In slow start for 5000ms at rtt=50: 10 * 2^100 = enormous
        # In CUBIC: reasonable (hundreds of MSS)
        assert final_cwnd < 1e9, "cwnd too large; slow start may not have exited"


class TestLossHandling:
    """Test loss-based congestion events."""

    def test_loss_reduces_cwnd_by_beta(self, tmp_path):
        """Loss should reduce cwnd by cubic_beta factor."""
        # RTT=50, loss at 100ms = 2 RTTs
        scenario = {
            "params": STANDARD_PARAMS,
            "paths": [{"id": 0, "rtt_ms": 50}],
            "events": [{"time_ms": 100, "type": "loss", "path_id": 0}],
            "duration_ms": 200
        }
        output = run_scenario(scenario, tmp_path)
        loss_cwnd = output["paths"]["0"]["cwnd_at_events"][0]["cwnd_after_bytes"]
        # Pre-loss: 10 * 2^2 * 1200 = 48000
        # Post-loss: 48000 * 0.7 = 33600
        expected = 10 * (2 ** 2) * 1200 * 0.7
        assert abs(loss_cwnd - expected) / expected < 0.05

    def test_cwnd_never_below_one_mss(self, tmp_path):
        """cwnd must never drop below 1 MSS regardless of repeated losses."""
        scenario = {
            "params": STANDARD_PARAMS,
            "paths": [{"id": 0, "rtt_ms": 50}],
            "events": [{"time_ms": 100 + i * 100, "type": "loss", "path_id": 0}
                       for i in range(10)],
            "duration_ms": 1500
        }
        output = run_scenario(scenario, tmp_path)
        for ev in output["paths"]["0"]["cwnd_at_events"]:
            assert ev["cwnd_after_bytes"] >= 1200, \
                f"cwnd {ev['cwnd_after_bytes']} dropped below MSS at t={ev['time_ms']}"
        assert output["paths"]["0"]["final_cwnd_bytes"] >= 1200

    def test_loss_count(self, tmp_path):
        """loss_events counter should match number of loss events."""
        scenario = {
            "params": STANDARD_PARAMS,
            "paths": [{"id": 0, "rtt_ms": 50}],
            "events": [
                {"time_ms": 100, "type": "loss", "path_id": 0},
                {"time_ms": 1000, "type": "loss", "path_id": 0},
                {"time_ms": 3000, "type": "loss", "path_id": 0}
            ],
            "duration_ms": 5000
        }
        output = run_scenario(scenario, tmp_path)
        assert output["paths"]["0"]["loss_events"] == 3


class TestECNBackoff:
    """Test ECN alternative backoff."""

    def test_ecn_reduces_cwnd_by_ecn_beta(self, tmp_path):
        """ECN should reduce cwnd by ecn_beta (0.85)."""
        # RTT=50, ECN at 100ms = 2 RTTs
        scenario = {
            "params": STANDARD_PARAMS,
            "paths": [{"id": 0, "rtt_ms": 50}],
            "events": [{"time_ms": 100, "type": "ecn", "path_id": 0}],
            "duration_ms": 200
        }
        output = run_scenario(scenario, tmp_path)
        ecn_cwnd = output["paths"]["0"]["cwnd_at_events"][0]["cwnd_after_bytes"]
        # Pre-ECN: 10 * 2^2 * 1200 = 48000
        # Post-ECN: 48000 * 0.85 = 40800
        expected = 10 * (2 ** 2) * 1200 * 0.85
        assert abs(ecn_cwnd - expected) / expected < 0.05

    def test_ecn_lighter_than_loss(self, tmp_path):
        """ECN reduction (beta=0.85) should be lighter than loss (beta=0.7)."""
        base = {
            "params": STANDARD_PARAMS,
            "paths": [{"id": 0, "rtt_ms": 50}],
            "duration_ms": 1000
        }
        loss_scenario = {**base, "events": [{"time_ms": 100, "type": "loss", "path_id": 0}]}
        ecn_scenario = {**base, "events": [{"time_ms": 100, "type": "ecn", "path_id": 0}]}

        loss_dir = tmp_path / "loss"
        ecn_dir = tmp_path / "ecn"

        loss_output = run_scenario(loss_scenario, loss_dir)
        ecn_output = run_scenario(ecn_scenario, ecn_dir)

        loss_cwnd = loss_output["paths"]["0"]["cwnd_at_events"][0]["cwnd_after_bytes"]
        ecn_cwnd = ecn_output["paths"]["0"]["cwnd_at_events"][0]["cwnd_after_bytes"]
        assert ecn_cwnd > loss_cwnd, \
            f"ECN cwnd ({ecn_cwnd}) should be > loss cwnd ({loss_cwnd})"

    def test_ecn_count(self, tmp_path):
        """ecn_events counter should match number of ECN events."""
        scenario = {
            "params": STANDARD_PARAMS,
            "paths": [{"id": 0, "rtt_ms": 50}],
            "events": [
                {"time_ms": 100, "type": "ecn", "path_id": 0},
                {"time_ms": 1000, "type": "ecn", "path_id": 0}
            ],
            "duration_ms": 3000
        }
        output = run_scenario(scenario, tmp_path)
        assert output["paths"]["0"]["ecn_events"] == 2


class TestSpuriousRecovery:
    """Test spurious congestion event detection and recovery."""

    def test_recovery_restores_cwnd(self, tmp_path):
        """After spurious recovery, cwnd should return to pre-loss value."""
        # RTT=50, loss at 100ms (2 RTTs), recovery at 110ms
        scenario = {
            "params": STANDARD_PARAMS,
            "paths": [{"id": 0, "rtt_ms": 50}],
            "events": [
                {"time_ms": 100, "type": "loss", "path_id": 0},
                {"time_ms": 110, "type": "spurious_recovery", "path_id": 0}
            ],
            "duration_ms": 1000
        }
        output = run_scenario(scenario, tmp_path)
        events = output["paths"]["0"]["cwnd_at_events"]
        assert len(events) >= 2

        loss_ev = events[0]
        recovery_ev = events[1]
        assert recovery_ev["event_type"] == "spurious_recovery"

        # Pre-loss cwnd = 10 * 2^2 * 1200 = 48000
        pre_loss_cwnd = 10 * (2 ** 2) * 1200
        assert abs(recovery_ev["cwnd_after_bytes"] - pre_loss_cwnd) / pre_loss_cwnd < 0.05, \
            f"Recovered cwnd {recovery_ev['cwnd_after_bytes']} not close to pre-loss {pre_loss_cwnd}"

    def test_recovery_undoes_performance_degradation(self, tmp_path):
        """Spurious recovery should restore throughput close to no-loss scenario."""
        base = {
            "params": STANDARD_PARAMS,
            "paths": [{"id": 0, "rtt_ms": 50}],
            "duration_ms": 2000
        }
        no_loss = {**base, "events": []}
        with_recovery = {**base, "events": [
            {"time_ms": 100, "type": "loss", "path_id": 0},
            {"time_ms": 110, "type": "spurious_recovery", "path_id": 0}
        ]}

        nl_dir = tmp_path / "no_loss"
        wr_dir = tmp_path / "with_recovery"

        nl_output = run_scenario(no_loss, nl_dir)
        wr_output = run_scenario(with_recovery, wr_dir)

        nl_bytes = nl_output["total_bytes_delivered"]
        wr_bytes = wr_output["total_bytes_delivered"]

        # With quick spurious recovery, bytes delivered should be close to no-loss
        # At least 70% of no-loss throughput
        assert wr_bytes > nl_bytes * 0.70, \
            f"Recovered throughput ({wr_bytes}) too low vs no-loss ({nl_bytes})"

    def test_spurious_recovery_count(self, tmp_path):
        """spurious_recoveries counter should track recoveries independently."""
        scenario = {
            "params": STANDARD_PARAMS,
            "paths": [{"id": 0, "rtt_ms": 50}],
            "events": [
                {"time_ms": 100, "type": "loss", "path_id": 0},
                {"time_ms": 110, "type": "spurious_recovery", "path_id": 0},
                {"time_ms": 500, "type": "loss", "path_id": 0},
                {"time_ms": 1000, "type": "ecn", "path_id": 0},
                {"time_ms": 2000, "type": "loss", "path_id": 0},
                {"time_ms": 2010, "type": "spurious_recovery", "path_id": 0},
                {"time_ms": 3000, "type": "ecn", "path_id": 0}
            ],
            "duration_ms": 5000
        }
        output = run_scenario(scenario, tmp_path)
        path = output["paths"]["0"]
        assert path["spurious_recoveries"] == 2
        assert path["ecn_events"] == 2
        # 3 loss events triggered (independent of spurious recoveries)
        assert path["loss_events"] == 3


class TestCUBICRecovery:
    """Test CUBIC function correctness during recovery."""

    def test_cubic_recovers_past_wmax(self, tmp_path):
        """Given enough time, CUBIC recovery should exceed W_max."""
        scenario = {
            "params": STANDARD_PARAMS,
            "paths": [{"id": 0, "rtt_ms": 100}],
            "events": [{"time_ms": 200, "type": "loss", "path_id": 0}],
            "duration_ms": 60000
        }
        output = run_scenario(scenario, tmp_path)
        final_cwnd = output["paths"]["0"]["final_cwnd_bytes"]
        # W_max = 40 MSS = 48000 bytes. After 60s of CUBIC, cwnd >> W_max
        W_max_bytes = 10 * (2 ** 2) * 1200  # 48000
        assert final_cwnd > W_max_bytes, \
            f"After 60s recovery, cwnd ({final_cwnd}) should exceed W_max ({W_max_bytes})"

    def test_second_loss_has_lower_cwnd_than_first_recovery(self, tmp_path):
        """A second loss shortly after the first should produce a lower post-loss cwnd."""
        scenario = {
            "params": STANDARD_PARAMS,
            "paths": [{"id": 0, "rtt_ms": 100}],
            "events": [
                {"time_ms": 300, "type": "loss", "path_id": 0},
                {"time_ms": 600, "type": "loss", "path_id": 0}
            ],
            "duration_ms": 1000
        }
        output = run_scenario(scenario, tmp_path)
        events = output["paths"]["0"]["cwnd_at_events"]
        assert len(events) >= 2
        assert events[1]["cwnd_after_bytes"] < events[0]["cwnd_after_bytes"], \
            "Second consecutive loss should yield lower post-loss cwnd"


class TestFastConvergence:
    """Test CUBIC fast convergence (RFC 9438 Section 4.8)."""

    def test_rapid_consecutive_losses_progressively_reduce_cwnd(self, tmp_path):
        """Rapid consecutive losses should produce strictly decreasing post-loss cwnd.

        Fast convergence causes W_max to be reduced when cwnd at loss is below
        the previous W_max, which combined with the beta reduction means each
        successive rapid loss produces a strictly lower post-loss cwnd.
        """
        scenario = {
            "params": STANDARD_PARAMS,
            "paths": [{"id": 0, "rtt_ms": 100}],
            "events": [
                {"time_ms": 300, "type": "loss", "path_id": 0},
                {"time_ms": 310, "type": "loss", "path_id": 0},
                {"time_ms": 320, "type": "loss", "path_id": 0}
            ],
            "duration_ms": 500
        }
        output = run_scenario(scenario, tmp_path)
        events = output["paths"]["0"]["cwnd_at_events"]

        assert len(events) == 3
        for i in range(1, len(events)):
            assert events[i]["cwnd_after_bytes"] < events[i - 1]["cwnd_after_bytes"], \
                f"Loss {i+1} cwnd ({events[i]['cwnd_after_bytes']}) should be < " \
                f"loss {i} cwnd ({events[i-1]['cwnd_after_bytes']})"


class TestMultipath:
    """Test multipath scheduling and per-path independence."""

    def test_both_paths_get_decisions(self, tmp_path):
        """Both paths should receive scheduling decisions when one has losses."""
        scenario = {
            "params": STANDARD_PARAMS,
            "paths": [
                {"id": 0, "rtt_ms": 50},
                {"id": 1, "rtt_ms": 50}
            ],
            "events": [
                {"time_ms": 200, "type": "loss", "path_id": 0},
                {"time_ms": 1000, "type": "loss", "path_id": 0},
                {"time_ms": 2000, "type": "loss", "path_id": 0}
            ],
            "duration_ms": 5000
        }
        output = run_scenario(scenario, tmp_path)
        schedule = output["multipath_schedule"]
        assert int(schedule.get("0", schedule.get(0, 0))) > 0, "Path 0 should have decisions"
        assert int(schedule.get("1", schedule.get(1, 0))) > 0, "Path 1 should have decisions"

    def test_lower_rtt_path_preferred(self, tmp_path):
        """Path with lower RTT should be preferred by the scheduler."""
        scenario = {
            "params": STANDARD_PARAMS,
            "paths": [
                {"id": 0, "rtt_ms": 20},
                {"id": 1, "rtt_ms": 200}
            ],
            "events": [],
            "duration_ms": 10000
        }
        output = run_scenario(scenario, tmp_path)
        schedule = output["multipath_schedule"]
        p0 = int(schedule.get("0", schedule.get(0, 0)))
        p1 = int(schedule.get("1", schedule.get(1, 0)))
        assert p0 > p1, f"Lower-RTT path should be preferred: path0={p0}, path1={p1}"

    def test_paths_have_independent_congestion_state(self, tmp_path):
        """Loss on one path must not affect the other path's cwnd."""
        scenario = {
            "params": STANDARD_PARAMS,
            "paths": [
                {"id": 0, "rtt_ms": 50},
                {"id": 1, "rtt_ms": 50}
            ],
            "events": [
                {"time_ms": 100, "type": "loss", "path_id": 0},
                {"time_ms": 200, "type": "loss", "path_id": 0},
                {"time_ms": 300, "type": "loss", "path_id": 0}
            ],
            "duration_ms": 2000
        }
        output = run_scenario(scenario, tmp_path)
        path0 = output["paths"]["0"]
        path1 = output["paths"]["1"]
        assert path1["loss_events"] == 0, "Path 1 should have no losses"
        assert path1["final_cwnd_bytes"] > path0["final_cwnd_bytes"], \
            "Unaffected path should have higher final cwnd"

    def test_total_bytes_equals_sum_of_paths(self, tmp_path):
        """total_bytes_delivered should equal sum of per-path bytes."""
        scenario = {
            "params": STANDARD_PARAMS,
            "paths": [
                {"id": 0, "rtt_ms": 50},
                {"id": 1, "rtt_ms": 100}
            ],
            "events": [{"time_ms": 500, "type": "loss", "path_id": 0}],
            "duration_ms": 5000
        }
        output = run_scenario(scenario, tmp_path)
        path_sum = sum(p["bytes_delivered"] for p in output["paths"].values())
        total = output["total_bytes_delivered"]
        assert abs(path_sum - total) / max(total, 1) < 0.01, \
            f"Total ({total}) should equal sum of paths ({path_sum})"


class TestBytesDelivered:
    """Test bytes delivered calculation."""

    def test_positive_bytes(self, tmp_path):
        """Any simulation with positive duration should deliver bytes."""
        scenario = {
            "params": STANDARD_PARAMS,
            "paths": [{"id": 0, "rtt_ms": 50}],
            "events": [],
            "duration_ms": 1000
        }
        output = run_scenario(scenario, tmp_path)
        assert output["total_bytes_delivered"] > 0

    def test_longer_sim_delivers_more(self, tmp_path):
        """Longer simulation should deliver more bytes."""
        base = {
            "params": STANDARD_PARAMS,
            "paths": [{"id": 0, "rtt_ms": 50}],
            "events": []
        }
        short_out = run_scenario({**base, "duration_ms": 1000}, tmp_path / "short")
        long_out = run_scenario({**base, "duration_ms": 5000}, tmp_path / "long")
        assert long_out["total_bytes_delivered"] > short_out["total_bytes_delivered"]


class TestDirectImport:
    """Test that the simulator can be imported directly."""

    def test_run_simulation_is_callable(self):
        """run_simulation function should be importable."""
        from simulator import run_simulation
        assert callable(run_simulation)

    def test_run_simulation_returns_valid_dict(self):
        """run_simulation should return a dict with correct structure."""
        from simulator import run_simulation
        scenario = {
            "params": STANDARD_PARAMS,
            "paths": [{"id": 0, "rtt_ms": 50}],
            "events": [{"time_ms": 100, "type": "loss", "path_id": 0}],
            "duration_ms": 1000
        }
        result = run_simulation(scenario)
        assert isinstance(result, dict)
        assert "paths" in result
        assert "0" in result["paths"]
        assert "total_bytes_delivered" in result
        assert result["paths"]["0"]["loss_events"] == 1
