"""Tests for the multi-queue fair queuing rate limiter.

"""

import pytest
import json
import subprocess
import sys
import os
import re

sys.path.insert(0, '/app')


class TestMaxMinFairRates:
    """Test the analytical max-min fair rate computation."""

    def test_equal_weights_unlimited(self):
        from scheduler import compute_max_min_fair_rates
        rates = compute_max_min_fair_rates(
            global_rate=100.0,
            flow_weights={0: 1.0, 1: 1.0, 2: 1.0, 3: 1.0},
            flow_demands=None
        )
        for fid in range(4):
            assert abs(rates[fid] - 25.0) < 0.01, \
                f"Flow {fid}: expected 25.0, got {rates[fid]}"

    def test_weighted_unlimited(self):
        from scheduler import compute_max_min_fair_rates
        rates = compute_max_min_fair_rates(
            global_rate=80.0,
            flow_weights={0: 1.0, 1: 3.0, 2: 2.0, 3: 2.0},
            flow_demands=None
        )
        expected = {0: 10.0, 1: 30.0, 2: 20.0, 3: 20.0}
        for fid, exp in expected.items():
            assert abs(rates[fid] - exp) < 0.01, \
                f"Flow {fid}: expected {exp}, got {rates[fid]}"

    def test_single_demand_limited(self):
        from scheduler import compute_max_min_fair_rates
        rates = compute_max_min_fair_rates(
            global_rate=100.0,
            flow_weights={0: 1.0, 1: 1.0, 2: 1.0, 3: 1.0},
            flow_demands={0: 10.0, 1: None, 2: None, 3: None}
        )
        assert abs(rates[0] - 10.0) < 0.01
        for fid in [1, 2, 3]:
            assert abs(rates[fid] - 30.0) < 0.01, \
                f"Flow {fid}: expected 30.0, got {rates[fid]}"

    def test_multiple_demand_limited(self):
        from scheduler import compute_max_min_fair_rates
        rates = compute_max_min_fair_rates(
            global_rate=100.0,
            flow_weights={0: 1.0, 1: 1.0, 2: 1.0},
            flow_demands={0: 10.0, 1: 20.0, 2: None}
        )
        assert abs(rates[0] - 10.0) < 0.01
        assert abs(rates[1] - 20.0) < 0.01
        assert abs(rates[2] - 70.0) < 0.01

    def test_weighted_demand_limited(self):
        from scheduler import compute_max_min_fair_rates
        rates = compute_max_min_fair_rates(
            global_rate=100.0,
            flow_weights={0: 2.0, 1: 1.0},
            flow_demands={0: 30.0, 1: None}
        )
        assert abs(rates[0] - 30.0) < 0.01
        assert abs(rates[1] - 70.0) < 0.01

    def test_all_demand_limited(self):
        from scheduler import compute_max_min_fair_rates
        rates = compute_max_min_fair_rates(
            global_rate=100.0,
            flow_weights={0: 1.0, 1: 1.0},
            flow_demands={0: 20.0, 1: 30.0}
        )
        assert abs(rates[0] - 20.0) < 0.01
        assert abs(rates[1] - 30.0) < 0.01

    def test_cascade_demands(self):
        from scheduler import compute_max_min_fair_rates
        rates = compute_max_min_fair_rates(
            global_rate=12500000.0,
            flow_weights={0: 1.0, 1: 1.0, 2: 2.0, 3: 1.0, 4: 1.0},
            flow_demands={0: 625000.0, 1: 1875000.0, 2: 3125000.0, 3: None, 4: None}
        )
        assert abs(rates[0] - 625000.0) < 100, \
            f"Flow 0: expected 625000, got {rates[0]}"
        assert abs(rates[1] - 1875000.0) < 100, \
            f"Flow 1: expected 1875000, got {rates[1]}"
        assert abs(rates[2] - 3125000.0) < 100, \
            f"Flow 2: expected 3125000, got {rates[2]}"
        assert abs(rates[3] - 3437500.0) < 100, \
            f"Flow 3: expected 3437500, got {rates[3]}"
        assert abs(rates[4] - 3437500.0) < 100, \
            f"Flow 4: expected 3437500, got {rates[4]}"


class TestTokenBucket:
    """Test the token bucket implementation."""

    def test_initial_full(self):
        from scheduler import TokenBucket
        tb = TokenBucket(rate=1000.0, burst=500.0)
        consumed = tb.consume(500.0)
        assert consumed == 500.0

    def test_refill_after_drain(self):
        from scheduler import TokenBucket
        tb = TokenBucket(rate=1000.0, burst=1000.0)
        tb.consume(1000.0)  # Empty it
        tb.refill(0.5)      # 0.5s at 1000/s = 500 tokens
        consumed = tb.consume(500.0)
        assert consumed == 500.0

    def test_burst_cap(self):
        from scheduler import TokenBucket
        tb = TokenBucket(rate=1000.0, burst=500.0)
        tb.refill(10.0)     # Long time, but capped at burst
        consumed = tb.consume(600.0)
        assert consumed == 500.0  # Cannot exceed burst

    def test_partial_consume(self):
        from scheduler import TokenBucket
        tb = TokenBucket(rate=1000.0, burst=100.0)
        consumed = tb.consume(200.0)
        assert consumed == 100.0  # Only had 100 tokens


class TestSimulationScenarios:
    """Test full simulation scenarios end-to-end."""

    def _run_scenario(self, name):
        result = subprocess.run(
            [sys.executable, '/app/main.py',
             f'/app/scenarios/{name}.json',
             f'/app/results/{name}.json'],
            capture_output=True, text=True, cwd='/app'
        )
        assert result.returncode == 0, \
            f"Scenario {name} failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        with open(f'/app/results/{name}.json') as f:
            return json.load(f)

    def test_uniform_fairness(self):
        results = self._run_scenario('uniform')
        assert results['jains_fairness_index'] >= 0.99, \
            f"JFI too low: {results['jains_fairness_index']}"

    def test_uniform_utilization(self):
        results = self._run_scenario('uniform')
        assert results['utilization'] >= 0.98, \
            f"Utilization too low: {results['utilization']}"

    def test_skewed_fairness(self):
        results = self._run_scenario('skewed')
        assert results['jains_fairness_index'] >= 0.99, \
            f"JFI too low: {results['jains_fairness_index']}"

    def test_skewed_utilization(self):
        results = self._run_scenario('skewed')
        assert results['utilization'] >= 0.98, \
            f"Utilization too low: {results['utilization']}"

    def test_weighted_fairness(self):
        results = self._run_scenario('weighted')
        assert results['jains_fairness_index'] >= 0.99, \
            f"JFI too low: {results['jains_fairness_index']}"

    def test_weighted_rate_ratios(self):
        results = self._run_scenario('weighted')
        tp = results['throughputs']
        # Flow 1 (weight 3) should get ~3x flow 0 (weight 1)
        ratio = float(tp['1']) / float(tp['0'])
        assert 2.8 <= ratio <= 3.2, \
            f"Weight ratio wrong: {ratio} (expected ~3.0)"

    def test_demand_limited_cap(self):
        results = self._run_scenario('demand_limited')
        tp = results['throughputs']
        # Flow 0 limited to 10 Mbps = 1,250,000 bytes/sec
        flow0_mbps = float(tp['0']) * 8 / 1e6
        assert flow0_mbps <= 11.0, \
            f"Flow 0 exceeded demand cap: {flow0_mbps:.2f} Mbps"

    def test_demand_limited_redistribution(self):
        results = self._run_scenario('demand_limited')
        tp = results['throughputs']
        # Unconstrained flows should get ~30 Mbps each (excess redistributed)
        for fid in ['1', '2', '3']:
            fmbps = float(tp[fid]) * 8 / 1e6
            assert fmbps >= 28.0, \
                f"Flow {fid} too low: {fmbps:.2f} Mbps (expected ~30)"

    def test_demand_limited_utilization(self):
        results = self._run_scenario('demand_limited')
        assert results['utilization'] >= 0.98, \
            f"Utilization too low: {results['utilization']}"

    def test_dynamic_utilization(self):
        results = self._run_scenario('dynamic')
        assert results['utilization'] >= 0.95, \
            f"Utilization too low: {results['utilization']}"

    def test_dynamic_new_flows_receive_bandwidth(self):
        results = self._run_scenario('dynamic')
        tp = results['throughputs']
        # Flows 4 and 5 (start at t=1) must have received bandwidth
        assert float(tp['4']) > 0, "Flow 4 received no bandwidth"
        assert float(tp['5']) > 0, "Flow 5 received no bandwidth"

    def test_dynamic_original_flows_balanced(self):
        results = self._run_scenario('dynamic')
        tp = results['throughputs']
        # Flows 0-3 (active full duration) should be roughly equal
        bytes_0_3 = [float(tp[str(i)]) for i in range(4)]
        ratio = max(bytes_0_3) / min(bytes_0_3)
        assert ratio < 1.05, \
            f"Flows 0-3 imbalanced: max/min ratio = {ratio:.4f}"

    def test_dynamic_late_flows_balanced(self):
        results = self._run_scenario('dynamic')
        tp = results['throughputs']
        # Flows 4 and 5 (both start at t=1) should be roughly equal
        f4 = float(tp['4'])
        f5 = float(tp['5'])
        diff = abs(f4 - f5) / max(f4, f5)
        assert diff < 0.05, \
            f"Late flows imbalanced: {diff:.4f}"

    def test_dynamic_duration_proportionality(self):
        results = self._run_scenario('dynamic')
        tp = results['throughputs']
        # Flow 0 (3s active) vs flow 4 (2s active): byte ratio ~ 1.75
        ratio = float(tp['0']) / float(tp['4'])
        assert 1.6 <= ratio <= 1.9, \
            f"Duration proportionality wrong: ratio = {ratio:.4f} (expected ~1.75)"

    def test_cascade_caps_respected(self):
        results = self._run_scenario('cascade')
        tp = results['throughputs']
        # Flow 0 capped at 5 Mbps
        flow0_mbps = float(tp['0']) * 8 / 1e6
        assert flow0_mbps <= 6.0, \
            f"Flow 0 exceeded 5 Mbps cap: {flow0_mbps:.2f} Mbps"
        # Flow 1 capped at 15 Mbps
        flow1_mbps = float(tp['1']) * 8 / 1e6
        assert flow1_mbps <= 16.0, \
            f"Flow 1 exceeded 15 Mbps cap: {flow1_mbps:.2f} Mbps"
        # Flow 2 capped at 25 Mbps
        flow2_mbps = float(tp['2']) * 8 / 1e6
        assert flow2_mbps <= 26.0, \
            f"Flow 2 exceeded 25 Mbps cap: {flow2_mbps:.2f} Mbps"

    def test_cascade_uncapped_flows(self):
        results = self._run_scenario('cascade')
        tp = results['throughputs']
        for fid in ['3', '4']:
            fmbps = float(tp[fid]) * 8 / 1e6
            assert fmbps >= 26.0, \
                f"Flow {fid} too low: {fmbps:.2f} Mbps (expected ~27.5)"

    def test_cascade_utilization(self):
        results = self._run_scenario('cascade')
        assert results['utilization'] >= 0.98, \
            f"Utilization too low: {results['utilization']}"


class TestTcConfiguration:
    """Test the Linux tc traffic control configuration script."""

    def test_tc_config_exists(self):
        assert os.path.isfile('/app/tc_config.sh'), \
            "tc_config.sh not found at /app/tc_config.sh"
        assert os.access('/app/tc_config.sh', os.X_OK), \
            "tc_config.sh must be executable"

    def test_tc_config_creates_interface(self):
        content = open('/app/tc_config.sh').read()
        assert 'mqsim0' in content, \
            "Script must reference dummy interface mqsim0"
        assert 'ip link' in content or 'ip -' in content, \
            "Script must use ip link to manage the interface"

    def test_tc_config_has_classful_qdisc(self):
        content = open('/app/tc_config.sh').read()
        assert 'tc qdisc' in content, "Script must configure a qdisc"
        content_lower = content.lower()
        assert any(qd in content_lower for qd in ['htb', 'hfsc', 'drr', 'qfq', 'cbq']), \
            "Script must use a classful qdisc (htb, hfsc, drr, qfq, or cbq)"

    def test_tc_config_global_rate(self):
        content = open('/app/tc_config.sh').read()
        has_rate = bool(re.search(r'80\s*[mM]bit', content)) or \
                   bool(re.search(r'80000\s*[kK]bit', content))
        assert has_rate, \
            "Root class must enforce 80 Mbps global rate (e.g., rate 80mbit)"

    def test_tc_config_has_flow_classes(self):
        content = open('/app/tc_config.sh').read()
        class_adds = [l for l in content.split('\n') if 'tc class add' in l]
        assert len(class_adds) >= 4, \
            f"Expected at least 4 tc class add commands (one per flow), found {len(class_adds)}"

    def test_tc_config_weight_proportionality(self):
        content = open('/app/tc_config.sh').read()
        # Extract rate values, normalize to mbit
        rates = []
        for val, unit in re.findall(r'rate\s+(\d+)\s*([mkMK]?[bB]it)', content):
            v = int(val)
            u = unit.lower()
            if u.startswith('k'):
                rates.append(v / 1000)
            else:
                rates.append(v)
        # Weighted scenario: weights 1,3,2,2 → rates ~10,30,20,20 mbit
        has_w1 = any(8 <= r <= 12 for r in rates)
        has_w2 = any(18 <= r <= 22 for r in rates)
        has_w3 = any(28 <= r <= 32 for r in rates)
        assert has_w1, \
            f"Expected rate ~10mbit for weight-1 flow, found rates: {rates}"
        assert has_w2, \
            f"Expected rate ~20mbit for weight-2 flows, found rates: {rates}"
        assert has_w3, \
            f"Expected rate ~30mbit for weight-3 flow, found rates: {rates}"

    def test_tc_config_has_filters(self):
        content = open('/app/tc_config.sh').read()
        assert 'tc filter' in content, \
            "Script must include tc filter commands for flow classification"


class TestAggregatedReport:
    """Test the jq-based aggregated report."""

    def test_aggregate_script_exists(self):
        assert os.path.isfile('/app/aggregate.sh'), \
            "aggregate.sh not found at /app/aggregate.sh"
        assert os.access('/app/aggregate.sh', os.X_OK), \
            "aggregate.sh must be executable"

    def test_aggregate_uses_jq(self):
        content = open('/app/aggregate.sh').read()
        assert 'jq' in content, \
            "aggregate.sh must use jq for JSON merging"

    def test_summary_exists(self):
        assert os.path.isfile('/app/results/summary.json'), \
            "summary.json not found at /app/results/summary.json"

    def test_summary_schema(self):
        with open('/app/results/summary.json') as f:
            data = json.load(f)
        expected_scenarios = ['uniform', 'skewed', 'weighted',
                              'demand_limited', 'dynamic', 'cascade']
        for scenario in expected_scenarios:
            assert scenario in data, \
                f"Missing scenario '{scenario}' in summary.json"
            entry = data[scenario]
            for key in ['jfi', 'utilization', 'num_flows', 'total_throughput_bps']:
                assert key in entry, \
                    f"Missing key '{key}' in summary['{scenario}']"
            assert isinstance(entry['num_flows'], int), \
                f"num_flows should be int, got {type(entry['num_flows'])}"

    def test_summary_values_consistent(self):
        with open('/app/results/summary.json') as f:
            summary = json.load(f)
        for name in ['uniform', 'skewed', 'weighted',
                     'demand_limited', 'dynamic', 'cascade']:
            with open(f'/app/results/{name}.json') as f:
                individual = json.load(f)
            assert abs(summary[name]['jfi'] - individual['jains_fairness_index']) < 0.001, \
                f"JFI mismatch for {name}"
            assert abs(summary[name]['utilization'] - individual['utilization']) < 0.001, \
                f"Utilization mismatch for {name}"
