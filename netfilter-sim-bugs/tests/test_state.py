#!/usr/bin/env python3
"""
Tests for the netfilter simulator debugging, strategy evaluation, and DDoS mitigation task.

Verifies:
  1. All five built-in scenarios produce correct results (simulator bugs fixed)
  2. Strategy evaluation metrics are correct (evaluate.py fixed, classification accurate)
  3. DDoS mitigation rules achieve required effectiveness metrics
"""

import json
import os
import sys
from ipaddress import ip_address, ip_network

sys.path.insert(0, "/app")

import pytest


# ---------------------------------------------------------------------------
# Ground truth for mitigation test (independent of solver's classification)
# ---------------------------------------------------------------------------

KNOWN_RESOLVERS = {"8.8.8.8", "8.8.4.4", "1.1.1.1", "1.0.0.1"}


def is_attack_packet(pkt):
    """Classify a packet as attack or legitimate using ground truth patterns."""
    proto = pkt["protocol"]
    src_ip = pkt["src_ip"]
    src_port = pkt.get("src_port", 0)
    dst_port = pkt.get("dst_port", 0)

    # SYN flood: TCP to port 80 from 198.18.0.0/15
    if proto == "TCP" and dst_port == 80:
        if ip_address(src_ip) in ip_network("198.18.0.0/15", strict=False):
            return True

    # Port scan: TCP from 192.168.100.0/24
    if proto == "TCP":
        if ip_address(src_ip) in ip_network("192.168.100.0/24", strict=False):
            return True

    # DNS amplification: UDP from port 53, not from known resolvers
    if proto == "UDP" and src_port == 53:
        if src_ip not in KNOWN_RESOLVERS:
            return True

    return False


# ---------------------------------------------------------------------------
# Scenario tests: verify simulator bugs are fixed
# ---------------------------------------------------------------------------

def _load_and_run_scenario(filename):
    """Load a scenario, run it through the simulator, return (actual, expected)."""
    from netfilter_sim import run_scenario, load_scenario
    path = os.path.join("/app/scenarios", filename)
    scenario = load_scenario(path)
    actual = run_scenario(scenario)
    expected = scenario["expected"]
    return actual, expected


class TestScenario01:
    """Conntrack entry lifecycle with filter DROP."""

    def test_packet_results(self):
        actual, expected = _load_and_run_scenario("scenario_01.json")
        assert actual["packet_results"] == expected["packet_results"], \
            "Packet dispositions incorrect"

    def test_conntrack_entries(self):
        actual, expected = _load_and_run_scenario("scenario_01.json")
        assert actual["conntrack_entries"] == expected["conntrack_entries"], \
            "conntrack_entries: expected {}, got {}".format(
                expected["conntrack_entries"], actual["conntrack_entries"])

    def test_no_conntrack_drops(self):
        actual, expected = _load_and_run_scenario("scenario_01.json")
        assert actual["conntrack_drops"] == expected["conntrack_drops"], \
            "conntrack_drops: expected {}, got {}".format(
                expected["conntrack_drops"], actual["conntrack_drops"])

    def test_counters(self):
        actual, expected = _load_and_run_scenario("scenario_01.json")
        for key, exp_val in expected["counters"].items():
            act_val = actual["counters"].get(key, 0)
            assert act_val == exp_val, \
                "counter {}: expected {}, got {}".format(key, exp_val, act_val)


class TestScenario02:
    """NOTRACK bypass under constrained conntrack."""

    def test_packet_results(self):
        actual, expected = _load_and_run_scenario("scenario_02.json")
        assert actual["packet_results"] == expected["packet_results"]

    def test_conntrack_entries(self):
        actual, expected = _load_and_run_scenario("scenario_02.json")
        assert actual["conntrack_entries"] == expected["conntrack_entries"]

    def test_totals(self):
        actual, expected = _load_and_run_scenario("scenario_02.json")
        assert actual["total_accepted"] == expected["total_accepted"]
        assert actual["total_dropped"] == expected["total_dropped"]
        assert actual["conntrack_drops"] == expected["conntrack_drops"]


class TestScenario03:
    """NOTRACK as non-terminating target."""

    def test_packet_results(self):
        actual, expected = _load_and_run_scenario("scenario_03.json")
        assert actual["packet_results"] == expected["packet_results"], \
            "Expected {}, got {}".format(
                expected["packet_results"], actual["packet_results"])

    def test_counters(self):
        actual, expected = _load_and_run_scenario("scenario_03.json")
        for key, exp_val in expected["counters"].items():
            act_val = actual["counters"].get(key, 0)
            assert act_val == exp_val, \
                "counter {}: expected {}, got {}".format(key, exp_val, act_val)

    def test_totals(self):
        actual, expected = _load_and_run_scenario("scenario_03.json")
        assert actual["total_accepted"] == expected["total_accepted"]
        assert actual["total_dropped"] == expected["total_dropped"]
        assert actual["conntrack_entries"] == expected["conntrack_entries"]


class TestScenario04:
    """Combined conntrack lifecycle under load."""

    def test_packet_results(self):
        actual, expected = _load_and_run_scenario("scenario_04.json")
        assert actual["packet_results"] == expected["packet_results"]

    def test_conntrack_entries(self):
        actual, expected = _load_and_run_scenario("scenario_04.json")
        assert actual["conntrack_entries"] == expected["conntrack_entries"], \
            "conntrack_entries: expected {}, got {}".format(
                expected["conntrack_entries"], actual["conntrack_entries"])

    def test_no_conntrack_drops(self):
        actual, expected = _load_and_run_scenario("scenario_04.json")
        assert actual["conntrack_drops"] == expected["conntrack_drops"]

    def test_counters(self):
        actual, expected = _load_and_run_scenario("scenario_04.json")
        for key, exp_val in expected["counters"].items():
            act_val = actual["counters"].get(key, 0)
            assert act_val == exp_val, \
                "counter {}: expected {}, got {}".format(key, exp_val, act_val)


class TestScenario05:
    """CIDR-based filtering with full pipeline."""

    def test_packet_results(self):
        actual, expected = _load_and_run_scenario("scenario_05.json")
        assert actual["packet_results"] == expected["packet_results"]

    def test_conntrack_entries(self):
        actual, expected = _load_and_run_scenario("scenario_05.json")
        assert actual["conntrack_entries"] == expected["conntrack_entries"], \
            "conntrack_entries: expected {}, got {}".format(
                expected["conntrack_entries"], actual["conntrack_entries"])

    def test_totals(self):
        actual, expected = _load_and_run_scenario("scenario_05.json")
        assert actual["total_accepted"] == expected["total_accepted"]
        assert actual["total_dropped"] == expected["total_dropped"]
        assert actual["conntrack_drops"] == expected["conntrack_drops"]


# ---------------------------------------------------------------------------
# Strategy evaluation tests
# ---------------------------------------------------------------------------

class TestStrategyEvaluation:
    """Verify the strategy evaluation report is correct."""

    def _load_eval(self):
        with open("/app/output/evaluation.json") as f:
            return json.load(f)

    def test_evaluation_file_exists(self):
        assert os.path.exists("/app/output/evaluation.json"), \
            "evaluation.json not found in /app/output/"

    def test_all_strategies_present(self):
        data = self._load_eval()
        expected_names = {
            "subnet_block", "dns_src_block", "udp_block_all",
            "combined_basic", "dns_payload_filter"
        }
        actual_names = set(data["strategies"].keys())
        assert expected_names == actual_names, \
            "Missing strategies: {}".format(expected_names - actual_names)

    def test_best_strategy_identified(self):
        data = self._load_eval()
        assert data["best_strategy"] == "combined_basic", \
            "Best strategy should be combined_basic, got {}".format(
                data["best_strategy"])

    def test_combined_basic_catches_most(self):
        """combined_basic should have highest tp among strategies."""
        data = self._load_eval()
        m = data["strategies"]["combined_basic"]
        assert m["tp"] == 600, \
            "combined_basic tp: expected 600, got {}".format(m["tp"])
        assert m["fn"] == 40, \
            "combined_basic fn: expected 40, got {}".format(m["fn"])

    def test_combined_basic_has_false_positives(self):
        """combined_basic drops legitimate DNS responses."""
        data = self._load_eval()
        m = data["strategies"]["combined_basic"]
        assert m["fp"] == 30, \
            "combined_basic fp: expected 30, got {}".format(m["fp"])
        assert m["tn"] == 100, \
            "combined_basic tn: expected 100, got {}".format(m["tn"])

    def test_subnet_block_no_false_positives(self):
        """subnet_block has perfect precision but low recall."""
        data = self._load_eval()
        m = data["strategies"]["subnet_block"]
        assert m["fp"] == 0, \
            "subnet_block fp: expected 0, got {}".format(m["fp"])
        assert m["tp"] == 400, \
            "subnet_block tp: expected 400, got {}".format(m["tp"])

    def test_dns_payload_filter_precision(self):
        """dns_payload_filter should have zero false positives."""
        data = self._load_eval()
        m = data["strategies"]["dns_payload_filter"]
        assert m["fp"] == 0, \
            "dns_payload_filter fp: expected 0, got {}".format(m["fp"])
        assert m["tp"] == 200, \
            "dns_payload_filter tp: expected 200, got {}".format(m["tp"])

    def test_deficiency_count(self):
        """Best strategy misses 40 port scan packets."""
        data = self._load_eval()
        assert data["deficiency_count"] == 40, \
            "deficiency_count: expected 40, got {}".format(
                data["deficiency_count"])

    def test_f1_ordering(self):
        """combined_basic should have highest f1 score."""
        data = self._load_eval()
        strategies = data["strategies"]
        best_f1 = strategies["combined_basic"]["f1"]
        for name, metrics in strategies.items():
            assert metrics["f1"] <= best_f1 + 1e-6, \
                "{} has f1={} > combined_basic f1={}".format(
                    name, metrics["f1"], best_f1)


# ---------------------------------------------------------------------------
# Mitigation design tests
# ---------------------------------------------------------------------------

class TestMitigationDesign:
    """Verify the DDoS mitigation rules meet all requirements."""

    def _run_mitigation(self):
        """Load rules and traffic, run through fixed simulator."""
        from netfilter_sim import NetfilterSimulator, Rule, Packet

        with open("/app/traffic_mix.json") as f:
            traffic_data = json.load(f)

        rules_path = "/app/output/rules.json"
        with open(rules_path) as f:
            rules_list = json.load(f)

        rules = [Rule.from_dict(r) for r in rules_list]
        packets = [Packet.from_dict(p) for p in traffic_data["packets"]]
        conntrack_max = traffic_data["conntrack_max"]

        sim = NetfilterSimulator(
            rules=rules,
            conntrack_max=conntrack_max,
        )

        results = sim.process_packet_sequence(packets)
        return results, traffic_data["packets"]

    def test_rules_file_exists(self):
        assert os.path.exists("/app/output/rules.json"), \
            "rules.json not found in /app/output/"

    def test_rules_valid_json(self):
        with open("/app/output/rules.json") as f:
            rules = json.load(f)
        assert isinstance(rules, list), "rules.json must be a JSON array"
        assert len(rules) >= 1, "Must have at least one rule"

    def test_all_attacks_dropped(self):
        results, packets = self._run_mitigation()
        packet_results = results["packet_results"]

        for i, pkt in enumerate(packets):
            if is_attack_packet(pkt):
                assert packet_results[i].startswith("dropped"), \
                    "Attack packet {} ({} {}:{} -> :{}) not dropped: {}".format(
                        i, pkt["protocol"], pkt["src_ip"],
                        pkt["src_port"], pkt["dst_port"],
                        packet_results[i])

    def test_all_legitimate_accepted(self):
        results, packets = self._run_mitigation()
        packet_results = results["packet_results"]

        for i, pkt in enumerate(packets):
            if not is_attack_packet(pkt):
                assert packet_results[i] == "accepted", \
                    "Legitimate packet {} ({} {}:{} -> :{}) not accepted: {}".format(
                        i, pkt["protocol"], pkt["src_ip"],
                        pkt["src_port"], pkt["dst_port"],
                        packet_results[i])

    def test_conntrack_within_limit(self):
        results, _ = self._run_mitigation()
        assert results["conntrack_entries"] <= 120, \
            "conntrack_entries={} exceeds limit of 120".format(
                results["conntrack_entries"])

    def test_raw_drop_efficiency(self):
        results, _ = self._run_mitigation()
        packet_results = results["packet_results"]

        raw_drops = sum(1 for r in packet_results
                        if r == "dropped:raw_prerouting")
        total_drops = sum(1 for r in packet_results
                          if r.startswith("dropped"))

        assert total_drops > 0, "No packets were dropped"
        ratio = raw_drops / total_drops
        assert ratio >= 0.60, \
            "Raw drop ratio {:.2%} ({}/{}) below 60% threshold".format(
                ratio, raw_drops, total_drops)

    def test_no_conntrack_overflow(self):
        results, _ = self._run_mitigation()
        assert results["conntrack_drops"] == 0, \
            "conntrack_drops={} -- table overflowed".format(
                results["conntrack_drops"])
